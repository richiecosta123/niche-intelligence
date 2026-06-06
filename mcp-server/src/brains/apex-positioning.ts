import type { Pool } from 'pg';

// ─── Data gathering ───────────────────────────────────────────────────────────

async function gatherSources(pool: Pool) {
  const [apexRes, agencyRes, authorityRes, assocRes] = await Promise.all([
    pool.query(
      `SELECT id, source_type, source_url, title, content, collected_at
       FROM raw_source_data
       WHERE source_url ILIKE '%apexexoticmarketing.com%'
       ORDER BY collected_at DESC NULLS LAST
       LIMIT 20`
    ),
    pool.query(
      `SELECT id, agency_name, tier, website, headline_positioning, outcome_language,
              proprietary_frameworks, pricing_signals, case_study_format, meta_ads, notes
       FROM agency_benchmarks
       ORDER BY created_at DESC`
    ),
    pool.query(
      `SELECT id, firm_name, content_hubs, report_structure, tone_style,
              visual_design, frameworks, paid_amplification, luxury_content, raw_notes
       FROM authority_sources
       ORDER BY created_at DESC`
    ),
    pool.query(
      `SELECT id, name, acronym, website, geo_focus, vertical,
              citation_tier, public_publications, citation_use, notes
       FROM association_intelligence
       ORDER BY citation_tier ASC NULLS LAST, created_at DESC`
    ),
  ]);

  return {
    apexPages:        apexRes.rows,
    agencyBenchmarks: agencyRes.rows,
    authoritySources: authorityRes.rows,
    associations:     assocRes.rows,
  };
}

// ─── Main export ──────────────────────────────────────────────────────────────

export async function runApexPositioningBrain(pool: Pool) {
  const sources = await gatherSources(pool);

  return {
    status: 'ready_to_analyze',
    apex_current: {
      page_count: sources.apexPages.length,
      pages: sources.apexPages,
    },
    agency_benchmarks: {
      count: sources.agencyBenchmarks.length,
      records: sources.agencyBenchmarks,
    },
    authority_sources: {
      count: sources.authoritySources.length,
      records: sources.authoritySources,
    },
    associations: {
      count: sources.associations.length,
      records: sources.associations,
    },
    instruction:
      'Analyze Apex\'s current positioning against the agency benchmarks and consulting firm formats. ' +
      'Identify strengths, gaps, and opportunities. Then produce a positioning brief and style guide. ' +
      'Save result via save_apex_positioning_brief tool.',
    saveSchema: {
      tool:  'save_apex_positioning_brief',
      table: 'apex_positioning_briefs',
      required: ['current_positioning'],
      columns: {
        version:                      'string — e.g. "v1.0" or date-stamped label',
        current_positioning:          'string — narrative summary of Apex\'s current positioning',
        positioning_gaps:             'object — areas where Apex is weaker than benchmarks',
        positioning_strengths:        'object — areas where Apex already leads or differentiates',
        positioning_opportunities:    'object — specific moves Apex should make',
        agency_comparisons:           'object — side-by-side benchmark analysis per agency',
        consulting_firm_comparisons:  'object — comparison against authority/consulting firm formats',
        methodology_recommendations:  'string — recommended proprietary methodology to develop',
        pricing_recommendations:      'string — packaging and pricing tier guidance',
        packaging_recommendations:    'string — how to structure service packages',
        proposal_language:            'object — recommended language patterns for proposals',
        citation_recommendations:     'object — which associations/sources to cite and how',
        report_format:                'string — recommended report structure and section order',
        tone_guidelines:              'string — voice, tone, and style directives',
        citation_style:               'string — citation formatting standard to adopt',
        framework_naming:             'object — proprietary framework names and descriptions',
        visual_guidelines:            'string — visual design and branding directives',
        raw_analysis:                 'string — full unstructured analysis text',
      },
    },
  };
}
