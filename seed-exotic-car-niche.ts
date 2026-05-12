import 'dotenv/config';
import { Pool } from 'pg';

const pool = new Pool({ connectionString: process.env.NEON_DB_URL });

const NICHE = {
  name: 'Exotic Car Rental',
  slug: 'exotic-car-rental',
  description:
    'High-end exotic and luxury vehicle rental market — targeting affluent consumers, event planners, and content creators seeking Lamborghinis, Ferraris, McLarens and similar vehicles.',
  status: 'active',
  data_sources: {
    reddit: [
      'r/exoticcars',
      'r/luxurycars',
      'r/carporn',
      'r/supercars',
      'r/Entrepreneur',
    ],
    youtube: [
      'exotic car rental reviews',
      'rent lamborghini experience',
      'supercar rental vlog',
      'luxury car rental business',
    ],
    google_trends: [
      'exotic car rental',
      'rent a ferrari',
      'rent a lamborghini',
      'supercar rental near me',
      'luxury car rental for a day',
    ],
  },
  research_frequency: {
    daily: ['trend_data', 'raw_source_data'],
    weekly: ['insights', 'opportunities', 'customer_avatars'],
    monthly: ['disruption_reports', 'quarterly_industry_reports'],
  },
  metadata: {
    avg_rental_price_per_day: 1500,
    top_vehicles: ['Lamborghini Huracán', 'Ferrari 488', 'McLaren 570S', 'Rolls-Royce Wraith', 'Bentley Continental GT'],
    primary_markets: ['Miami', 'Las Vegas', 'Los Angeles', 'New York', 'Dubai'],
    market_size_usd_billions: 4.2,
    yoy_growth_percent: 8.5,
  },
};

const BRAIN_DEPENDENCIES = [
  {
    brain_name: 'research_analyst',
    brain_type: 'data_collection',
    display_name: 'Research Analyst Brain',
    description: 'Collects and normalizes raw data from Reddit, YouTube, and Google Trends.',
    depends_on: [],
    schedule: '0 6 * * *',
    config: { max_posts_per_subreddit: 100, lookback_days: 7 },
  },
  {
    brain_name: 'persona_architect',
    brain_type: 'intelligence',
    display_name: 'Persona Architect Brain',
    description: 'Synthesizes customer avatars from raw conversation data and buying signals.',
    depends_on: ['research_analyst'],
    schedule: '0 8 * * 1',
    config: { min_data_points: 50, avatar_depth: 'deep' },
  },
  {
    brain_name: 'insight_extractor',
    brain_type: 'intelligence',
    display_name: 'Insight Extractor Brain',
    description: 'Identifies actionable market insights, pain points, and desire patterns.',
    depends_on: ['research_analyst'],
    schedule: '0 9 * * *',
    config: { confidence_threshold: 0.75, max_insights_per_run: 20 },
  },
  {
    brain_name: 'offer_spy',
    brain_type: 'competitive_intelligence',
    display_name: 'Offer Spy Brain',
    description: 'Monitors competitor offers, pricing, and conversion elements across platforms.',
    depends_on: ['research_analyst'],
    schedule: '0 10 * * 2',
    config: { platforms: ['facebook_ads', 'google_ads', 'instagram'], depth: 'full' },
  },
  {
    brain_name: 'copy_alchemist',
    brain_type: 'content_generation',
    display_name: 'Copy Alchemist Brain',
    description: 'Generates high-converting marketing copy informed by avatars and insights.',
    depends_on: ['persona_architect', 'insight_extractor'],
    schedule: '0 11 * * 3',
    config: { copy_types: ['headline', 'hook', 'email_subject', 'ad_body', 'cta'], variants_per_type: 5 },
  },
  {
    brain_name: 'opportunity_hunter',
    brain_type: 'strategic_intelligence',
    display_name: 'Opportunity Hunter Brain',
    description: 'Identifies underserved segments, market gaps, and monetization opportunities.',
    depends_on: ['insight_extractor', 'offer_spy'],
    schedule: '0 7 * * 4',
    config: { min_opportunity_score: 0.6, focus: ['gaps', 'segments', 'pricing'] },
  },
  {
    brain_name: 'disruption_sentinel',
    brain_type: 'strategic_intelligence',
    display_name: 'Disruption Sentinel Brain',
    description: 'Monitors macro signals: regulatory changes, tech shifts, and competitive moves.',
    depends_on: ['research_analyst', 'offer_spy'],
    schedule: '0 8 1 * *',
    config: { signal_categories: ['regulatory', 'technology', 'consumer_behavior', 'competitive'] },
  },
  {
    brain_name: 'report_synthesizer',
    brain_type: 'reporting',
    display_name: 'Report Synthesizer Brain',
    description: 'Compiles quarterly industry reports from all intelligence brain outputs.',
    depends_on: ['insight_extractor', 'opportunity_hunter', 'disruption_sentinel'],
    schedule: '0 9 1 1,4,7,10 *',
    config: { report_sections: ['market_overview', 'trends', 'opportunities', 'competitive', 'recommendations'] },
  },
];

async function seed() {
  const client = await pool.connect();
  try {
    console.log('🌱 Seeding Exotic Car Rental niche...\n');

    // Upsert niche
    const { rows: [niche] } = await client.query(
      `INSERT INTO niches (name, slug, description, status, data_sources, research_frequency, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (slug) DO UPDATE SET
         name = EXCLUDED.name,
         description = EXCLUDED.description,
         status = EXCLUDED.status,
         data_sources = EXCLUDED.data_sources,
         research_frequency = EXCLUDED.research_frequency,
         metadata = EXCLUDED.metadata,
         updated_at = NOW()
       RETURNING id, name, slug`,
      [
        NICHE.name,
        NICHE.slug,
        NICHE.description,
        NICHE.status,
        JSON.stringify(NICHE.data_sources),
        JSON.stringify(NICHE.research_frequency),
        JSON.stringify(NICHE.metadata),
      ]
    );

    console.log(`✅ Niche upserted → id=${niche.id}, slug="${niche.slug}"`);
    console.log(`   📡 Data sources: ${Object.keys(NICHE.data_sources).join(', ')}`);
    console.log(`   🔄 Research schedule: ${Object.keys(NICHE.research_frequency).join(', ')}\n`);

    // Delete existing brain dependencies for this niche (clean re-seed)
    await client.query('DELETE FROM brain_dependencies WHERE niche_id = $1', [niche.id]);

    // Insert brain dependencies
    console.log('🧠 Seeding brain dependencies...');
    for (const brain of BRAIN_DEPENDENCIES) {
      const { rows: [bd] } = await client.query(
        `INSERT INTO brain_dependencies
           (niche_id, brain_name, brain_type, display_name, description, depends_on, schedule, config)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
         RETURNING id, brain_name`,
        [
          niche.id,
          brain.brain_name,
          brain.brain_type,
          brain.display_name,
          brain.description,
          JSON.stringify(brain.depends_on),
          brain.schedule,
          JSON.stringify(brain.config),
        ]
      );
      const depsLabel = brain.depends_on.length
        ? `depends on: [${brain.depends_on.join(', ')}]`
        : 'no dependencies';
      console.log(`   ✅ ${bd.brain_name} (id=${bd.id}) — ${depsLabel}`);
    }

    console.log(`\n✨ Seed complete!`);
    console.log(`   Niche: "${NICHE.name}" (id=${niche.id})`);
    console.log(`   Brains: ${BRAIN_DEPENDENCIES.length} registered`);

    // Quick summary query
    const { rows: summary } = await client.query(
      `SELECT brain_type, COUNT(*) as count
       FROM brain_dependencies
       WHERE niche_id = $1
       GROUP BY brain_type
       ORDER BY brain_type`,
      [niche.id]
    );
    console.log('\n   Brain breakdown by type:');
    for (const row of summary) {
      console.log(`     ${row.brain_type}: ${row.count}`);
    }
  } catch (err) {
    console.error('❌ Seed failed:', err);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

seed();
