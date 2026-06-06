import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import type { Pool } from 'pg';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SYSTEM_PROMPT = readFileSync(
  path.join(__dirname, 'prompts/hook-extractor.md'),
  'utf-8'
);

const LIMITS = {
  competitorAds: 60,
  rawPosts:      120,
  insights:      100,
  stories:       50,
};

// ─── Data gathering ───────────────────────────────────────────────────────────

async function gatherSources(pool: Pool, nicheId: number) {
  const [adsRes, postsRes, insightsRes, storiesRes, existingRes] = await Promise.all([
    pool.query(
      `SELECT id, competitor_name, headline, body_text, cta, landing_page_url
       FROM competitor_ad_data
       WHERE niche_id = $1
         AND (headline IS NOT NULL OR body_text IS NOT NULL)
       ORDER BY last_seen_at DESC NULLS LAST, created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.competitorAds]
    ),
    pool.query(
      `SELECT id, source_type, source_url, title, content, raw_data
       FROM raw_source_data
       WHERE niche_id = $1
         AND source_type IN ('reddit', 'youtube', 'google_news', 'trustpilot', 'forum')
       ORDER BY score DESC NULLS LAST, id DESC
       LIMIT $2`,
      [nicheId, LIMITS.rawPosts]
    ),
    pool.query(
      `SELECT id, title, summary, body
       FROM insights
       WHERE niche_id = $1
         AND insight_type = 'language_pattern'
       ORDER BY confidence_score DESC NULLS LAST
       LIMIT $2`,
      [nicheId, LIMITS.insights]
    ),
    pool.query(
      `SELECT id, title, usable_hooks, before_state, after_state,
              transformation, quantified_results, emotional_arc
       FROM stories_library
       WHERE niche_id = $1
       ORDER BY created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.stories]
    ),
    // Existing hook texts for deduplication awareness
    pool.query(
      `SELECT LOWER(TRIM(hook_text)) AS t FROM hooks_library WHERE niche_id = $1`,
      [nicheId]
    ),
  ]);

  return {
    competitorAds:      adsRes.rows,
    rawPosts:           postsRes.rows,
    insights:           insightsRes.rows,
    stories:            storiesRes.rows,
    existingHookTexts:  existingRes.rows.map((r: { t: string }) => r.t),
  };
}

// ─── Prompt builder ───────────────────────────────────────────────────────────

type Comment = { author?: string; body?: string; score?: number };

function formatPost(p: { id: number; source_type: string; source_url?: string; title?: string; content?: string; raw_data?: unknown }): string {
  const raw = p.raw_data
    ? (typeof p.raw_data === 'string' ? JSON.parse(p.raw_data) : p.raw_data) as Record<string, unknown>
    : {};
  const comments = (Array.isArray(raw.comments) ? raw.comments as Comment[] : []).slice(0, 10);

  const lines = [
    `[POST id=${p.id} source=${p.source_type}]`,
    `Title: "${p.title ?? ''}"`,
    `Post: "${(p.content ?? '').slice(0, 400)}"`,
  ];
  if (comments.length) {
    lines.push('[COMMENTS - customer voice, high value]');
    for (const c of comments) {
      lines.push(`u/${c.author ?? 'unknown'} (↑${c.score ?? 0}): "${(c.body ?? '').slice(0, 300)}"`);
    }
  }
  lines.push(`URL: ${p.source_url ?? 'n/a'}`);
  return lines.join('\n');
}

function buildSourcePayload(sources: Omit<Awaited<ReturnType<typeof gatherSources>>, 'existingHookTexts'>): string {
  const sections: string[] = [];

  if (sources.competitorAds.length) {
    const lines = sources.competitorAds.map((ad) =>
      `[AD id=${ad.id}] ${ad.competitor_name ?? 'Unknown'} | ` +
      `Headline: "${ad.headline ?? ''}" | ` +
      `Body: "${(ad.body_text ?? '').slice(0, 300)}" | ` +
      `CTA: "${ad.cta ?? ''}" | ` +
      `URL: ${ad.landing_page_url ?? 'n/a'}`
    );
    sections.push(`=== COMPETITOR ADS (${lines.length}) ===\n${lines.join('\n')}`);
  }

  if (sources.rawPosts.length) {
    const formatted = sources.rawPosts.map(formatPost);
    sections.push(`=== CUSTOMER POSTS (${formatted.length}) ===\n${formatted.join('\n\n')}`);
  }

  if (sources.insights.length) {
    const lines = sources.insights.map((ins) =>
      `[INSIGHT id=${ins.id}] "${ins.title}"\n` +
      `Summary: ${ins.summary ?? ''}\n` +
      `Body: ${(ins.body ?? '').slice(0, 600)}`
    );
    sections.push(`=== LANGUAGE PATTERN INSIGHTS (${lines.length}) ===\n${lines.join('\n\n')}`);
  }

  if (sources.stories.length) {
    const lines = sources.stories.map((s) => {
      const hooks = Array.isArray(s.usable_hooks) ? s.usable_hooks.join(' | ') : '';
      const results = s.quantified_results ? JSON.stringify(s.quantified_results) : '';
      return (
        `[STORY id=${s.id}] "${s.title}"\n` +
        `Before: ${s.before_state ?? ''} | After: ${s.after_state ?? ''}\n` +
        `Transformation: ${s.transformation ?? ''}\n` +
        `Results: ${results}\n` +
        `Usable hooks: ${hooks}`
      );
    });
    sections.push(`=== SUCCESS STORY HOOKS (${lines.length}) ===\n${lines.join('\n\n')}`);
  }

  if (!sections.length) return 'No source data available for this niche yet.';

  return sections.join('\n\n' + '─'.repeat(60) + '\n\n');
}

// ─── Main export ──────────────────────────────────────────────────────────────

export async function runHookExtractor(pool: Pool, nicheId: number) {
  const sources = await gatherSources(pool, nicheId);

  // Source URL fallback map: id → url (for Claude to resolve source_url accurately)
  const sourceUrlMap: Record<number, string> = {};
  for (const p of sources.rawPosts) {
    if (p.source_url) sourceUrlMap[p.id] = p.source_url;
  }
  for (const ad of sources.competitorAds) {
    if (ad.landing_page_url) sourceUrlMap[ad.id] = ad.landing_page_url;
  }

  const sourceData = buildSourcePayload({
    competitorAds: sources.competitorAds,
    rawPosts:      sources.rawPosts,
    insights:      sources.insights,
    stories:       sources.stories,
  });

  return {
    status:     'ready_to_extract',
    niche_id:   nicheId,
    systemPrompt: SYSTEM_PROMPT,
    sourceData,
    sourceCounts: {
      competitor_ads:     sources.competitorAds.length,
      raw_posts:          sources.rawPosts.length,
      language_insights:  sources.insights.length,
      stories:            sources.stories.length,
    },
    existingHookTexts: sources.existingHookTexts,
    sourceUrlMap,
    instruction:
      'Read the systemPrompt for extraction rules. Analyze sourceData to identify hook-worthy language. ' +
      'Skip any hook whose normalized text already appears in existingHookTexts. ' +
      'Use sourceUrlMap[source_id] to resolve source_url when it is missing from a result. ' +
      'Save each qualifying hook via save_hook with: niche_id, hook_text, hook_type, ' +
      'customer_language_quote (if applicable), source_insight_ids, ai_generated=false, approved=false.',
    saveSchema: {
      tool: 'save_hook',
      required: ['niche_id', 'hook_text', 'hook_type'],
      columns: {
        niche_id:                'number',
        hook_text:               'string — the hook line itself',
        hook_type:               'string — curiosity | fear | desire | social_proof | urgency | pattern_interrupt',
        customer_language_quote: 'string | null — verbatim quote if hook came from customer language',
        source_insight_ids:      'number[] — insight IDs if sourced from insights table',
        usage_context:           'string | null — ad | email_subject | landing_page | social_post | vsl_opener',
        ai_generated:            'false — these are extracted, not generated',
        approved:                'false — needs human review',
        tags:                    'string[] | null — keyword tags',
      },
    },
  };
}
