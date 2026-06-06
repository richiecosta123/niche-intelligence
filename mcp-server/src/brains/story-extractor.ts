import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import type { Pool } from 'pg';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SYSTEM_PROMPT = readFileSync(
  path.join(__dirname, 'prompts/story-extractor.md'),
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
  const [adsRes, postsRes, insightsRes, existingRes] = await Promise.all([
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
      `SELECT id, insight_type, title, summary, body
       FROM insights
       WHERE niche_id = $1
       ORDER BY confidence_score DESC NULLS LAST
       LIMIT $2`,
      [nicheId, LIMITS.insights]
    ),
    // Existing story titles for deduplication awareness
    pool.query(
      `SELECT LOWER(TRIM(title)) AS t FROM stories_library WHERE niche_id = $1`,
      [nicheId]
    ),
  ]);

  return {
    competitorAds:       adsRes.rows,
    rawPosts:            postsRes.rows,
    insights:            insightsRes.rows,
    existingStoryTitles: existingRes.rows.map((r: { t: string }) => r.t),
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

function buildSourcePayload(sources: Omit<Awaited<ReturnType<typeof gatherSources>>, 'existingStoryTitles'>): string {
  const sections: string[] = [];

  if (sources.rawPosts.length) {
    const formatted = sources.rawPosts.map(formatPost);
    sections.push(`=== CUSTOMER POSTS — Reddit / YouTube / Reviews (${formatted.length}) ===\n${formatted.join('\n\n')}`);
  }

  if (sources.competitorAds.length) {
    const lines = sources.competitorAds.map((ad) =>
      `[AD id=${ad.id}] ${ad.competitor_name ?? 'Unknown'} | ` +
      `Headline: "${ad.headline ?? ''}" | ` +
      `Body: "${(ad.body_text ?? '').slice(0, 300)}" | ` +
      `CTA: "${ad.cta ?? ''}" | ` +
      `URL: ${ad.landing_page_url ?? 'n/a'}`
    );
    sections.push(`=== COMPETITOR ADS — may contain testimonials (${lines.length}) ===\n${lines.join('\n')}`);
  }

  if (sources.insights.length) {
    const lines = sources.insights.map((ins) =>
      `[INSIGHT id=${ins.id} type=${ins.insight_type}] "${ins.title}"\n` +
      `Summary: ${ins.summary ?? ''}\n` +
      `Body: ${(ins.body ?? '').slice(0, 500)}`
    );
    sections.push(`=== MARKET INSIGHTS — may surface success stories (${lines.length}) ===\n${lines.join('\n\n')}`);
  }

  if (!sections.length) return 'No source data available for this niche yet.';

  return sections.join('\n\n' + '─'.repeat(60) + '\n\n');
}

// ─── Main export ──────────────────────────────────────────────────────────────

export async function runStoryExtractor(pool: Pool, nicheId: number) {
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
  });

  return {
    status:     'ready_to_extract',
    niche_id:   nicheId,
    systemPrompt: SYSTEM_PROMPT,
    sourceData,
    sourceCounts: {
      raw_posts:     sources.rawPosts.length,
      competitor_ads: sources.competitorAds.length,
      insights:      sources.insights.length,
    },
    existingStoryTitles: sources.existingStoryTitles,
    sourceUrlMap,
    instruction:
      'Read the systemPrompt for extraction rules. Analyze sourceData to identify transformation ' +
      'narratives, success stories, testimonials, and case studies. ' +
      'Skip any story whose normalized title already appears in existingStoryTitles. ' +
      'Use sourceUrlMap[source_id] to resolve source_url when missing from a result. ' +
      'Save each qualifying story via save_success_story with all available fields. ' +
      'Set verified=false on every story — human review required before use.',
    saveSchema: {
      tool: 'save_success_story',
      required: ['niche_id', 'story_title', 'summary', 'method', 'credibility_score', 'source_url'],
      columns: {
        niche_id:            'number',
        story_type:          'string — success_story | transformation_narrative | testimonial | case_study',
        story_title:         'string — compelling outcome-first headline',
        summary:             'string — one-sentence brief',
        source_type:         'string — reddit | youtube | review | competitor_ad | news',
        source_url:          'string — use sourceUrlMap[source_id] if not in source data',
        protagonist_profile: 'object — { occupation, location, experience_level, context }',
        before_state:        'string — situation before the story began',
        after_state:         'string — situation after, with numbers when possible',
        transformation:      'string — what specifically changed',
        key_mechanism:       'string — how they got from before to after (= method field)',
        quantified_results:  'object — { revenue, timeframe, cars, platform, ... }',
        emotional_arc:       'object — { start, journey, end, original_quote }',
        usable_hooks:        'string[] — 2–5 hook-worthy phrases from this story',
        credibility_score:   'number 0.0–1.0 — how credible/specific this story is',
        verified:            'false — always false on extraction',
      },
    },
  };
}
