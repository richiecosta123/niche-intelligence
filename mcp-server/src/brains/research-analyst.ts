import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import { Pool } from 'pg';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SYSTEM_PROMPT = readFileSync(
  path.join(__dirname, 'prompts/research-analyst.md'),
  'utf-8'
);

const RAW_POST_LIMIT = 100;

// Raw customer-voice source types this brain analyzes — excludes landing pages,
// ad data, and other non-voice-of-customer rows in raw_source_data.
const CUSTOMER_VOICE_SOURCE_TYPES = ['reddit', 'youtube', 'trustpilot', 'yelp', 'newsletter'];

// ─── Data gathering ───────────────────────────────────────────────────────────

async function gatherUnprocessedPosts(pool: Pool, nicheId: number) {
  // Same stateful-progress pattern as query_raw_posts: the highest id any
  // completed research_jobs row has already marked as processed for this
  // niche. Falls back to 0 (process everything) if research_jobs is empty
  // or unavailable — absence of a cursor is never treated as "nothing to do."
  let sinceId = 0;
  try {
    const { rows } = await pool.query<{ max_id: number }>(
      `SELECT COALESCE(MAX((result->>'max_id_processed')::int), 0) AS max_id
       FROM research_jobs WHERE niche_id = $1 AND status = 'completed'`,
      [nicheId]
    );
    sinceId = rows[0]?.max_id ?? 0;
  } catch {
    // research_jobs unavailable — scan all posts for this niche instead
  }

  // Oldest-unprocessed-first: this batch's max id is the next correct cursor
  // value, so ordering DESC would let a backlog skip over older posts forever.
  const { rows } = await pool.query(
    `SELECT id, source_type, source_url, title, content, author, score, collected_at
     FROM raw_source_data
     WHERE niche_id = $1
       AND id > $2
       AND (source_type = ANY($3::text[]) OR source_type LIKE 'forum_%')
     ORDER BY id ASC
     LIMIT $4`,
    [nicheId, sinceId, CUSTOMER_VOICE_SOURCE_TYPES, RAW_POST_LIMIT]
  );
  return { posts: rows, sinceId };
}

// ─── Prompt builder ───────────────────────────────────────────────────────────

type RawPost = {
  id: number;
  source_type: string;
  source_url?: string;
  title?: string;
  content?: string;
  author?: string;
  score?: number;
  collected_at?: string;
};

function formatPost(p: RawPost): string {
  const lines = [
    `[POST id=${p.id} source=${p.source_type}]`,
    `Title: "${p.title ?? ''}"`,
    `Content: "${(p.content ?? '').slice(0, 1000)}"`,
  ];
  if (p.author) lines.push(`Author: ${p.author}`);
  if (p.score != null) lines.push(`Score: ${p.score}`);
  lines.push(`URL: ${p.source_url ?? 'n/a'}`);
  return lines.join('\n');
}

function buildSourcePayload(posts: RawPost[]): string {
  if (!posts.length) return 'No unprocessed customer-voice posts available for this niche yet.';
  return posts.map(formatPost).join('\n\n' + '─'.repeat(60) + '\n\n');
}

function tallyBySourceType(posts: RawPost[]): Record<string, number> {
  const tally: Record<string, number> = {};
  for (const p of posts) {
    tally[p.source_type] = (tally[p.source_type] ?? 0) + 1;
  }
  return tally;
}

// ─── Main export ──────────────────────────────────────────────────────────────

export async function runResearchAnalystBrain(pool: Pool, nicheId: number) {
  const { posts, sinceId } = await gatherUnprocessedPosts(pool, nicheId);

  const sourceUrlMap: Record<number, string> = {};
  for (const p of posts) {
    if (p.source_url) sourceUrlMap[p.id] = p.source_url;
  }

  return {
    status: 'ready_to_analyze',
    niche_id: nicheId,
    systemPrompt: SYSTEM_PROMPT,
    sourceData: buildSourcePayload(posts),
    sourceCounts: {
      raw_posts: posts.length,
      by_source_type: tallyBySourceType(posts),
    },
    progress: {
      since_id: sinceId,
      max_id_in_batch: posts.length ? Math.max(...posts.map((p) => p.id)) : sinceId,
    },
    sourceUrlMap,
    instruction:
      'Read the systemPrompt for the 6 extraction categories and critical rules. Analyze sourceData ' +
      '(raw customer-voice posts not yet processed) and extract evidence-based insights — every insight ' +
      'needs 2+ real quotes from the data, specific (not generic) language, a noted frequency, and a ' +
      'concrete action. Use sourceUrlMap[source_id] to resolve source_url when needed. ' +
      'Save each qualifying insight via save_insight with: niche_id, insight_type, title, summary, body, ' +
      'confidence_score, source_ids, tags, is_actionable.',
    saveSchema: {
      tool: 'save_insight',
      required: ['niche_id', 'insight_type', 'title', 'body', 'confidence_score'],
      columns: {
        niche_id:         'number',
        insight_type:     'string — pain_point | buying_trigger | objection | language_pattern | competitor_gap | market_timing',
        title:            'string — short, specific (max 200 chars)',
        summary:          'string — one-sentence summary',
        body:             'string — full analysis ending in a concrete action to take',
        confidence_score: 'number — 0.0-1.0, evidence strength (see systemPrompt)',
        source_ids:       'number[] — real raw_source_data ids backing this insight (2+ required)',
        tags:             'string[] | null — keyword tags',
        is_actionable:    'boolean — default true',
      },
    },
  };
}

// ─── Backward-compat shim for run.ts ───────────────────────────────────────────
//
// run.ts's tiny standalone CLI calls brains as `{ execute({ nicheId }) }` with
// no pool of its own, so this brain manages a short-lived connection only when
// invoked that way. The MCP server (index.ts) calls runResearchAnalystBrain
// directly with its own shared pool instead — this shim is not used there.

export interface BrainInput {
  nicheId: number;
}

export interface Brain {
  execute(input: BrainInput): Promise<unknown>;
}

export const researchAnalystBrain: Brain = {
  async execute({ nicheId }) {
    const localPool = new Pool({ connectionString: process.env.NEON_DB_URL });
    try {
      return await runResearchAnalystBrain(localPool, nicheId);
    } finally {
      await localPool.end();
    }
  },
};
