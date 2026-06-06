import type { Pool } from 'pg';

const LIMITS = {
  insights:        100,
  personas:         10,
  stories:          30,
  hooks:            50,
  offers:           20,
  googleTrends:     20,
  competitorAds:    50,
  disruptionReports: 3,
};

// ─── Data gathering ───────────────────────────────────────────────────────────

async function gatherSources(pool: Pool, nicheId: number) {
  const [
    styleGuideRes,
    insightsRes,
    personasRes,
    storiesRes,
    hooksRes,
    offersRes,
    trendsRes,
    adsRes,
    reportsRes,
  ] = await Promise.all([
    pool.query(
      `SELECT id, version, current_positioning, positioning_gaps, positioning_strengths,
              positioning_opportunities, methodology_recommendations, pricing_recommendations,
              packaging_recommendations, proposal_language, citation_recommendations,
              report_format, tone_guidelines, citation_style, framework_naming,
              visual_guidelines, created_at
       FROM apex_positioning_briefs
       ORDER BY created_at DESC
       LIMIT 1`
    ),
    pool.query(
      `SELECT id, insight_type, title, summary, body, confidence_score, tags
       FROM insights
       WHERE niche_id = $1
       ORDER BY confidence_score DESC NULLS LAST
       LIMIT $2`,
      [nicheId, LIMITS.insights]
    ),
    pool.query(
      `SELECT id, name, avatar_type, age_range, income_range,
              psychographics, pain_points, desires, objections, buying_triggers
       FROM customer_avatars
       WHERE niche_id = $1
       ORDER BY is_primary DESC, created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.personas]
    ),
    pool.query(
      `SELECT id, story_type, title, key_mechanism, quantified_results, usable_hooks,
              before_state, after_state, transformation
       FROM stories_library
       WHERE niche_id = $1
       ORDER BY created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.stories]
    ),
    pool.query(
      `SELECT id, hook_text, hook_type, usage_context, tags
       FROM hooks_library
       WHERE niche_id = $1
       ORDER BY created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.hooks]
    ),
    pool.query(
      `SELECT id, offer_name, offer_type, price_point, pricing_model,
              core_promise, unique_mechanism
       FROM offer_intelligence
       WHERE niche_id = $1
       ORDER BY created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.offers]
    ),
    pool.query(
      `SELECT id, title, content, collected_at
       FROM raw_source_data
       WHERE niche_id = $1
         AND source_type = 'google_trends'
       ORDER BY collected_at DESC NULLS LAST
       LIMIT $2`,
      [nicheId, LIMITS.googleTrends]
    ),
    pool.query(
      `SELECT id, competitor_name, headline, body_text, cta, landing_page_url,
              estimated_spend, running_since, last_seen_at
       FROM competitor_ad_data
       WHERE niche_id = $1
       ORDER BY last_seen_at DESC NULLS LAST
       LIMIT $2`,
      [nicheId, LIMITS.competitorAds]
    ),
    pool.query(
      `SELECT id, report_title, report_period, executive_summary,
              disruption_signals, recommended_actions, created_at
       FROM disruption_reports
       WHERE niche_id = $1
       ORDER BY created_at DESC
       LIMIT $2`,
      [nicheId, LIMITS.disruptionReports]
    ),
  ]);

  return {
    styleGuide:        styleGuideRes.rows[0] ?? null,
    insights:          insightsRes.rows,
    personas:          personasRes.rows,
    stories:           storiesRes.rows,
    hooks:             hooksRes.rows,
    offers:            offersRes.rows,
    googleTrends:      trendsRes.rows,
    competitorAds:     adsRes.rows,
    disruptionReports: reportsRes.rows,
  };
}

// ─── Main export ──────────────────────────────────────────────────────────────

export async function runClientIntelligenceBrain(
  pool: Pool,
  nicheId: number,
  clientName?: string,
  city?: string,
  reportType: string = 'state_of_market',
) {
  const sources = await gatherSources(pool, nicheId);

  return {
    status: 'ready_to_synthesize',
    style_guide: sources.styleGuide,
    niche_intelligence: {
      insights:          { count: sources.insights.length,          records: sources.insights },
      personas:          { count: sources.personas.length,          records: sources.personas },
      stories:           { count: sources.stories.length,           records: sources.stories },
      hooks:             { count: sources.hooks.length,             records: sources.hooks },
      offers:            { count: sources.offers.length,            records: sources.offers },
      google_trends:     { count: sources.googleTrends.length,      records: sources.googleTrends },
      competitor_ads:    { count: sources.competitorAds.length,     records: sources.competitorAds },
      disruption_reports:{ count: sources.disruptionReports.length, records: sources.disruptionReports },
    },
    client_context: {
      client_name: clientName ?? null,
      city:        city ?? null,
      report_type: reportType,
    },
    instruction:
      'Using the style_guide as your format standard, synthesize the niche_intelligence into a ' +
      'client intelligence report. Save result via save_client_intelligence_report tool.',
    saveSchema: {
      tool:  'save_client_intelligence_report',
      table: 'client_intelligence_reports',
      required: ['niche_id', 'report_type'],
      columns: {
        niche_id:                'number',
        client_name:             'string | null — name of the specific client',
        city:                    'string | null — city/market this report targets',
        report_type:             'string — state_of_market | opportunity_brief | competitive_landscape',
        report_period:           'string | null — e.g. "Q2_2026"',
        positioning_brief_id:    'number | null — ID of apex_positioning_briefs row used',
        executive_summary:       'string — 2-3 paragraph executive summary',
        market_overview:         'string — narrative market analysis',
        uhnw_persona_profiles:   'object — persona breakdowns relevant to this client',
        seasonality_data:        'object — seasonal patterns and timing opportunities',
        competitor_ad_intelligence: 'object — curated competitor ad insights',
        hooks_and_offers:        'object — recommended hooks and offer structures',
        citations:               'object — data citations per section',
        recommendations:         'object — prioritized action items',
        full_report:             'string — complete formatted report text',
      },
    },
  };
}
