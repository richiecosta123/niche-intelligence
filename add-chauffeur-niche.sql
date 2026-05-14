-- Add Chauffeur Services niche (#2) to the niches table
-- and register its brain dependencies

-- Upsert the niche
INSERT INTO niches (name, slug, description, status, data_sources, research_frequency, metadata)
VALUES (
  'Chauffeur Services',
  'chauffeur-services',
  'Executive and luxury chauffeur transportation market — targeting corporate accounts, event planners, and high-net-worth individuals seeking reliable professional drivers for airport transfers, corporate events, and special occasions.',
  'active',
  '{
    "reddit": ["r/entrepreneur", "r/smallbusiness", "r/Entrepreneurship", "r/startups", "r/luxurylife"],
    "youtube": ["chauffeur service business", "black car service startup", "executive transportation business", "limousine service review"],
    "google_trends": ["chauffeur service", "black car service", "executive car service", "corporate transportation", "luxury car service near me"]
  }'::json,
  '{
    "daily": ["trend_data", "raw_source_data"],
    "weekly": ["insights", "opportunities", "customer_avatars"],
    "monthly": ["disruption_reports", "quarterly_industry_reports"]
  }'::json,
  '{
    "avg_trip_price_usd": 150,
    "primary_segments": ["corporate", "airport_transfers", "special_events", "roadshows"],
    "primary_markets": ["New York", "Los Angeles", "Chicago", "San Francisco", "London"],
    "market_size_usd_billions": 6.8,
    "yoy_growth_percent": 7.2,
    "key_platforms": ["Blacklane", "Carey", "GroundLink", "Uber Black", "Lyft Lux"]
  }'::json
)
ON CONFLICT (slug) DO UPDATE SET
  name                = EXCLUDED.name,
  description         = EXCLUDED.description,
  status              = EXCLUDED.status,
  data_sources        = EXCLUDED.data_sources,
  research_frequency  = EXCLUDED.research_frequency,
  metadata            = EXCLUDED.metadata,
  updated_at          = NOW()
RETURNING id, name, slug;

-- Register brain dependencies for the chauffeur-services niche
-- (uses a DO block so we can reference the niche id by slug)
DO $$
DECLARE
  v_niche_id INTEGER;
BEGIN
  SELECT id INTO v_niche_id FROM niches WHERE slug = 'chauffeur-services';

  -- Remove stale entries so this script is re-runnable
  DELETE FROM brain_dependencies WHERE niche_id = v_niche_id;

  INSERT INTO brain_dependencies
    (niche_id, brain_name, brain_type, display_name, description, depends_on, schedule, config)
  VALUES
    (v_niche_id, 'research_analyst',    'data_collection',       'Research Analyst Brain',      'Collects and normalizes raw data from Reddit, YouTube, and Google Trends.',                              '[]'::json,                                          '0 6 * * *',       '{"max_posts_per_subreddit": 100, "lookback_days": 7}'::json),
    (v_niche_id, 'persona_architect',   'intelligence',          'Persona Architect Brain',     'Synthesizes customer avatars from raw conversation data and buying signals.',                            '["research_analyst"]'::json,                        '0 8 * * 1',       '{"min_data_points": 50, "avatar_depth": "deep"}'::json),
    (v_niche_id, 'insight_extractor',   'intelligence',          'Insight Extractor Brain',     'Identifies actionable market insights, pain points, and desire patterns.',                              '["research_analyst"]'::json,                        '0 9 * * *',       '{"confidence_threshold": 0.75, "max_insights_per_run": 20}'::json),
    (v_niche_id, 'offer_spy',           'competitive_intelligence','Offer Spy Brain',            'Monitors competitor offers, pricing, and conversion elements across platforms.',                        '["research_analyst"]'::json,                        '0 10 * * 2',      '{"platforms": ["facebook_ads", "google_ads", "instagram"], "depth": "full"}'::json),
    (v_niche_id, 'copy_alchemist',      'content_generation',    'Copy Alchemist Brain',        'Generates high-converting marketing copy informed by avatars and insights.',                            '["persona_architect", "insight_extractor"]'::json,  '0 11 * * 3',      '{"copy_types": ["headline", "hook", "email_subject", "ad_body", "cta"], "variants_per_type": 5}'::json),
    (v_niche_id, 'opportunity_hunter',  'strategic_intelligence','Opportunity Hunter Brain',    'Identifies underserved segments, market gaps, and monetization opportunities.',                         '["insight_extractor", "offer_spy"]'::json,          '0 7 * * 4',       '{"min_opportunity_score": 0.6, "focus": ["gaps", "segments", "pricing"]}'::json),
    (v_niche_id, 'disruption_sentinel', 'strategic_intelligence','Disruption Sentinel Brain',  'Monitors macro signals: regulatory changes, tech shifts, and competitive moves.',                       '["research_analyst", "offer_spy"]'::json,           '0 8 1 * *',       '{"signal_categories": ["regulatory", "technology", "consumer_behavior", "competitive"]}'::json),
    (v_niche_id, 'report_synthesizer',  'reporting',             'Report Synthesizer Brain',    'Compiles quarterly industry reports from all intelligence brain outputs.',                              '["insight_extractor", "opportunity_hunter", "disruption_sentinel"]'::json, '0 9 1 1,4,7,10 *', '{"report_sections": ["market_overview", "trends", "opportunities", "competitive", "recommendations"]}'::json);

  RAISE NOTICE 'Chauffeur Services niche seeded — niche_id=%', v_niche_id;
END;
$$;
