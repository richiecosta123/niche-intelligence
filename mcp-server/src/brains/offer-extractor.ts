import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import type { Pool } from 'pg';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SYSTEM_PROMPT = readFileSync(
  path.join(__dirname, 'prompts/offer-extractor.md'),
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
      `SELECT id, insight_type, title, summary, body
       FROM insights
       WHERE niche_id = $1
         AND insight_type IN ('competitor_gap', 'market_timing', 'buying_trigger', 'pain_point')
       ORDER BY confidence_score DESC NULLS LAST
       LIMIT $2`,
      [nicheId, LIMITS.insights]
    ),
    pool.query(
      `SELECT id, title, key_mechanism, quantified_results, source_url
       FROM stories_library
       WHERE niche_id = $1
         AND story_type IN ('success_story', 'case_study')
       ORDER BY created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.stories]
    ),
    // Existing offer names for deduplication awareness
    pool.query(
      `SELECT LOWER(TRIM(offer_name)) AS n FROM offer_intelligence WHERE niche_id = $1`,
      [nicheId]
    ),
  ]);

  return {
    competitorAds:     adsRes.rows,
    rawPosts:          postsRes.rows,
    insights:          insightsRes.rows,
    stories:           storiesRes.rows,
    existingOfferNames: existingRes.rows.map((r: { n: string }) => r.n),
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

function buildSourcePayload(sources: Omit<Awaited<ReturnType<typeof gatherSources>>, 'existingOfferNames'>): string {
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
    sections.push(`=== CUSTOMER POSTS — Reddit / YouTube / Reviews (${formatted.length}) ===\n${formatted.join('\n\n')}`);
  }

  if (sources.insights.length) {
    const lines = sources.insights.map((ins) =>
      `[INSIGHT id=${ins.id} type=${ins.insight_type}] "${ins.title}"\n` +
      `Summary: ${ins.summary ?? ''}\n` +
      `Body: ${(ins.body ?? '').slice(0, 400)}`
    );
    sections.push(`=== MARKET INSIGHTS — competitor gaps & timing signals (${lines.length}) ===\n${lines.join('\n\n')}`);
  }

  if (sources.stories.length) {
    const lines = sources.stories.map((s) => {
      const results = s.quantified_results ? JSON.stringify(s.quantified_results) : '';
      return (
        `[STORY id=${s.id}] "${s.title}"\n` +
        `Mechanism: ${s.key_mechanism ?? ''}\n` +
        `Results: ${results}\n` +
        `URL: ${s.source_url ?? 'n/a'}`
      );
    });
    sections.push(`=== SUCCESS STORIES — business models & pricing (${lines.length}) ===\n${lines.join('\n\n')}`);
  }

  if (!sections.length) return 'No source data available for this niche yet.';

  return sections.join('\n\n' + '─'.repeat(60) + '\n\n');
}

// ─── Main export ──────────────────────────────────────────────────────────────

export async function runOfferExtractor(pool: Pool, nicheId: number) {
  const sources = await gatherSources(pool, nicheId);

  // Source URL fallback map: id → url (for Claude to resolve source_url accurately)
  const sourceUrlMap: Record<number, string> = {};
  for (const p of sources.rawPosts) {
    if (p.source_url) sourceUrlMap[p.id] = p.source_url;
  }
  for (const ad of sources.competitorAds) {
    if (ad.landing_page_url) sourceUrlMap[ad.id] = ad.landing_page_url;
  }
  for (const s of sources.stories) {
    if (s.source_url) sourceUrlMap[s.id] = s.source_url;
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
      competitor_ads: sources.competitorAds.length,
      raw_posts:      sources.rawPosts.length,
      insights:       sources.insights.length,
      stories:        sources.stories.length,
    },
    existingOfferNames: sources.existingOfferNames,
    sourceUrlMap,
    instruction:
      'Read the systemPrompt for extraction rules. Analyze sourceData to identify product/service offers ' +
      'with pricing, positioning, and value propositions. ' +
      'Skip any offer whose normalized name already appears in existingOfferNames. ' +
      'Use sourceUrlMap[source_id] to resolve source_url when missing from a result. ' +
      'Save each qualifying offer via save_offer with all available fields.',
    saveSchema: {
      tool: 'save_offer',
      required: ['niche_id', 'offer_name', 'problem_solved', 'unique_value'],
      columns: {
        niche_id:         'number',
        offer_name:       'string — specific enough to be unique (include brand/model if relevant)',
        offer_type:       'string — product | service | saas | marketplace | bundle | membership',
        competitor_name:  'string | null — named competitor if this is their offer',
        problem_solved:   'string — core_promise: what transformation does this deliver?',
        unique_value:     'string — unique_mechanism: what makes it different?',
        pricing: {
          suggestedPrice:              'string — primary price (e.g. "1400", "89", "10000")',
          priceRationale:              'string — pricing_model: daily | monthly | one_time | tiered | custom',
          competitorPricing:           'string | null — comparison if known',
          willingness_to_pay_signals:  'string[] — evidence of price acceptance',
        },
        market_timing: {
          urgencyFactors:      'string[] — why now?',
          seasonality:         'string | null',
          competitorWeakness:  'string | null',
        },
        anticipated_objections: 'object[] — [{ objection, response }]',
      },
    },
  };
}
