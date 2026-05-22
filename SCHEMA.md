# Niche Intelligence Platform - Database Schema

**Version:** 1.0  
**Last Updated:** May 22, 2026  
**Total Tables:** 19 (4 foundation + 10 intelligence + 2 supporting + 3 extensible)

> **Purpose:** This document serves as the single source of truth for all database schema information, ensuring alignment between TypeScript definitions, SQL migrations, and MCP tool implementations.

> **Hook-Story-Offer Framework:** Intelligence tables now organized around Russell Brunson's copywriting framework: `hooks_library` (attention), `stories_library` (connection), `offer_intelligence` (conversion).

---

## Table of Contents

1. [Foundation Tables](#foundation-tables)
2. [Intelligence Tables](#intelligence-tables)
3. [Supporting Tables](#supporting-tables)
4. [Extensible Data Source Tables](#extensible-data-source-tables)
5. [Foreign Key Relationships](#foreign-key-relationships)
6. [JSON Column Structures](#json-column-structures)
7. [Brain → Table Mapping](#brain--table-mapping)
8. [Brain Dependency Flow](#brain-dependency-flow)
9. [MCP Tool → Table Reference](#mcp-tool--table-reference)
10. [Known Discrepancies](#known-discrepancies)

---

## Foundation Tables

### niches

Configuration and data source tracking per niche market.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| name | TEXT | NOT NULL | e.g. "Exotic Car Rental" |
| slug | TEXT | NOT NULL UNIQUE | URL-safe identifier |
| description | TEXT | | Market overview |
| data_sources | JSON | | Reddit, YouTube, Google Trends config (see JSON section) |
| research_frequency | JSON | | Scheduling config per brain type |
| is_active | BOOLEAN | NOT NULL DEFAULT true | Kill switch |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### research_jobs

Job queue for all async scraping and analysis operations.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| job_type | VARCHAR(100) | NOT NULL | scrape \| analyze \| generate_avatars \| disruption_report |
| status | VARCHAR(50) | NOT NULL DEFAULT 'pending' | pending \| running \| completed \| failed |
| brain_name | VARCHAR(100) | | Which brain executed this job |
| priority | INTEGER | NOT NULL DEFAULT 5 | 1 (highest) → 10 (lowest) |
| payload | JSON | | Input parameters for the job |
| result | JSON | | Output summary; result->>'max_id_processed' used by query_raw_posts |
| error_message | TEXT | | Set on failure |
| started_at | TIMESTAMP | | |
| completed_at | TIMESTAMP | | |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### raw_source_data

Raw scraped content from all data sources. Input for every brain.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| source_type | VARCHAR(50) | NOT NULL | reddit \| youtube \| google_trends \| google_news \| trustpilot \| forum |
| source_url | TEXT | | Link to original post/video |
| source_id | VARCHAR(255) | | Platform-native ID (e.g. Reddit post ID) |
| title | TEXT | | Post/video title |
| content | TEXT | | Body text or transcript |
| author | VARCHAR(255) | | Username or channel name |
| score | INTEGER | | Upvotes, view count, or platform score |
| engagement_metrics | JSON | | Platform-specific metrics (see JSON section) |
| raw_data | JSON | | Full API response payload, preserved for re-processing |
| collected_at | TIMESTAMP | NOT NULL DEFAULT NOW() | When scraper fetched this |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Note:** "Processed" rows are determined by research_jobs.result->>'max_id_processed', not a column on this table.

---

## Intelligence Tables

### insights

Structured market intelligence extracted from raw_source_data. Central output of Research Analyst brain.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| insight_type | VARCHAR(100) | NOT NULL | See valid values below |
| title | TEXT | NOT NULL | Short, specific title (max 200 chars) |
| summary | TEXT | | One-sentence summary (max 500 chars) |
| body | TEXT | | Full analysis text |
| confidence_score | DECIMAL(3,2) | | 0.00–1.00 (or 0.00–9.99; see discrepancies) |
| source_ids | JSON | | Array of raw_source_data.id values |
| tags | JSON | | String array of keyword tags |
| is_actionable | BOOLEAN | NOT NULL DEFAULT false | Whether this insight implies direct action |
| expires_at | TIMESTAMP | | Optional TTL for time-sensitive insights |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Valid insight_type values:**
- `pain_point` — frustrations customers express
- `buying_trigger` — moments that prompt purchase decisions
- `objection` — hesitations that block conversion
- `language_pattern` — exact phrases and vocabulary customers use
- `competitor_gap` — weaknesses or missing offerings from competitors
- `market_timing` — seasonal, trend, or urgency signals

---

### customer_avatars

Psychologically rich customer personas generated by Persona Architect brain.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| name | TEXT | NOT NULL | Memorable archetype label, e.g. "The Vegas Splurger" |
| avatar_type | VARCHAR(100) | | Segment label, e.g. "high-roller", "weekend-seeker" |
| age_range | VARCHAR(50) | | e.g. "28-42" |
| income_range | VARCHAR(100) | | e.g. "$150k-$500k" |
| psychographics | JSON | | Values, lifestyle, personality traits (see JSON section) |
| pain_points | JSON | | String array of real hesitations from source data |
| desires | JSON | | String array of motivations and aspirations |
| objections | JSON | | String array of buying hesitations with source language |
| empathy_map | JSON | | { thinks, feels, sees, hears, says, does } (see JSON section) |
| buying_triggers | JSON | | String array of specific moments that push them to buy |
| preferred_channels | JSON | | String array of where they consume content and make decisions |
| is_primary | BOOLEAN | NOT NULL DEFAULT false | True for highest-volume / highest-revenue segment |
| version | INTEGER | NOT NULL DEFAULT 1 | Incremented on regeneration |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### stories_library

**Part of Hook-Story-Offer Framework**

Customer success stories and transformation narratives for copywriting. Combines evidence-based research stories with crafted narrative templates.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| story_type | VARCHAR(50) | NOT NULL DEFAULT 'success_story' | success_story \| transformation_narrative \| case_study \| testimonial_template |
| title | TEXT | NOT NULL | Compelling headline summarizing the story |
| source_type | VARCHAR(50) | | reddit \| youtube \| blog \| forum \| other |
| source_url | TEXT | | URL of original post/source |
| protagonist_profile | JSON | | Who this person is (see JSON section) |
| before_state | TEXT | | Situation before the success |
| after_state | TEXT | | Situation after the success |
| transformation | TEXT | | What specifically changed |
| key_mechanism | TEXT | | The core strategy or method that drove results |
| quantified_results | JSON | | Revenue amounts, timeframes, metrics (see JSON section) |
| emotional_arc | JSON | | Emotional journey for copywriting use |
| usable_hooks | JSON | | String array of copy hooks extracted from the story |
| story_template | TEXT | | Narrative template for copywriters to adapt |
| usage_context | JSONB | | Where this story works best (ads, landing pages, VSLs) |
| verified | BOOLEAN | NOT NULL DEFAULT false | Human-verified credibility |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Note:** Renamed from `success_stories` May 2026. Added `story_type` to support multiple narrative formats beyond just success stories.

---

### hooks_library

**Part of Hook-Story-Offer Framework**

Attention-grabbing hooks extracted from customer language patterns and insights. Used by Copywriter brain to generate marketing copy.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| hook_text | TEXT | NOT NULL | The hook line itself |
| hook_type | VARCHAR(50) | NOT NULL | curiosity \| fear \| desire \| social_proof \| urgency \| pattern_interrupt |
| target_avatar_id | INTEGER | FK → customer_avatars.id | Which persona this hook resonates with |
| usage_context | VARCHAR(100) | | ad \| email_subject \| landing_page \| social_post \| vsl_opener |
| source_insight_ids | JSONB | | Array of insight IDs this hook came from |
| customer_language_quote | TEXT | | Actual customer quote if hook derived from language patterns |
| performance_data | JSONB | | {impressions, clicks, ctr, conversions} |
| ai_generated | BOOLEAN | NOT NULL DEFAULT true | |
| approved | BOOLEAN | NOT NULL DEFAULT false | Human review gate |
| tags | JSONB | | String array of keyword tags |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### offer_intelligence

Positioned offers designed by Offer Designer brain, anchored to customer pain points.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| offer_name | TEXT | NOT NULL | Specific, clear name for the offer |
| competitor_name | TEXT | | Optional competitor this offer undercuts or improves on |
| offer_type | VARCHAR(100) | | service \| product \| saas \| marketplace |
| price_point | DECIMAL(10,2) | | Suggested price in USD |
| pricing_model | VARCHAR(100) | | one_time \| monthly \| annual \| usage \| tiered |
| core_promise | TEXT | | The #1 transformation this offer delivers |
| unique_mechanism | TEXT | | What makes this offer different / defensible |
| bonuses | JSON | | Array of optional add-ons that increase perceived value |
| guarantees | JSON | | Array of risk-reversals (e.g. 30-day money-back) |
| testimonials_summary | JSON | | Summary of social proof to source |
| conversion_elements | JSON | | Urgency, scarcity, and social proof tactics |
| weaknesses | JSON | | String array of known risks or limitations |
| strengths | JSON | | String array of competitive advantages |
| source_url | TEXT | | Optional reference or inspiration URL |
| last_seen_at | TIMESTAMP | | When this offer was last observed live |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Note:** The MCP save_offer tool writes different columns (problem_solved, unique_value, pricing, etc.) than the live schema. See Known Discrepancies.

---

### marketing_copy_library

100+ copy assets generated by Copywriter brain from authentic customer language.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| copy_type | VARCHAR(100) | NOT NULL | headline \| hook \| cta \| email_subject \| body_copy |
| copy_angle | VARCHAR(100) | | Emotional angle, e.g. "fear_of_missing_out", "aspiration" |
| content | TEXT | NOT NULL | The actual copy text |
| target_avatar_id | INTEGER | FK → customer_avatars.id | Which persona this resonates with |
| performance_data | JSON | | { impressions, clicks, ctr } if A/B tested |
| ai_generated | BOOLEAN | NOT NULL DEFAULT true | |
| approved | BOOLEAN | NOT NULL DEFAULT false | Human review gate |
| tags | JSON | | String array of keyword tags |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### opportunities

Market gaps and business opportunities identified by Market Strategist brain.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| title | TEXT | NOT NULL | Opportunity title |
| opportunity_type | VARCHAR(100) | | product \| service \| content \| partnership |
| description | TEXT | | Full description of the opportunity |
| market_gap | TEXT | | Specific unmet need this addresses |
| target_segment | TEXT | | Which avatar segment this targets |
| estimated_market_size | JSON | | { size, methodology, confidence } |
| effort_level | VARCHAR(50) | | low \| medium \| high |
| potential_revenue | JSON | | Revenue range and assumptions |
| time_to_market | VARCHAR(100) | | e.g. "2-4 weeks" |
| risk_factors | JSON | | String array of identified risks |
| validation_ideas | JSON | | String array of cheap ways to test this |
| status | VARCHAR(50) | NOT NULL DEFAULT 'identified' | identified \| validating \| pursuing \| abandoned |
| priority_score | DECIMAL(3,2) | | 0.00–1.00 composite of viability × revenue × timing |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### disruption_reports

Weekly/bi-weekly market disruption reports generated by Market Strategist brain.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| report_title | TEXT | NOT NULL | e.g. "Market Disruption Report - Q2_2026_Week_1" |
| report_period | VARCHAR(100) | | e.g. "Q2_2026_Week_1" |
| disruption_signals | JSON | | Array of market disruption signals with evidence |
| emerging_technologies | JSON | | Array of relevant tech shifts and implications |
| regulatory_changes | JSON | | Array of regulatory factors affecting the niche |
| consumer_behavior_shifts | JSON | | Array of documented buyer behaviour changes |
| competitive_moves | JSON | | Array of notable competitor actions |
| threat_level | VARCHAR(50) | | low \| medium \| high \| critical |
| opportunity_level | VARCHAR(50) | | low \| medium \| high \| exceptional |
| recommended_actions | JSON | | Array of prioritized next steps with owners |
| executive_summary | TEXT | | 2-page plain-text summary |
| published_at | TIMESTAMP | | When made visible to users |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

**Note:** The MCP save_disruption_report tool passes market_gaps as disruption_signals and emerging_trends as emerging_technologies. Column mapping is handled in market-strategist.ts:saveDisruptionReport.

---

### quarterly_industry_reports

McKinsey-style quarterly reports generated by Market Strategist brain.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| quarter | VARCHAR(10) | NOT NULL | e.g. "2026-Q2" |
| report_title | TEXT | NOT NULL | |
| market_overview | TEXT | | Narrative market summary |
| key_trends | JSON | | Array of trend objects with trajectory and implications |
| top_performers | JSON | | Competitor performance benchmarks |
| consumer_sentiment | JSON | | Sentiment analysis across sources |
| pricing_trends | JSON | | Pricing movement data and signals |
| channel_performance | JSON | | ROI by acquisition channel |
| ai_generated_insights | JSON | | Strategic recommendations from AI synthesis |
| data_sources_used | JSON | | Metadata about data freshness and coverage |
| confidence_metrics | JSON | | Per-section confidence scores |
| published_at | TIMESTAMP | | |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

## Supporting Tables

### share_links

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| token | VARCHAR(255) | NOT NULL UNIQUE | Random token used in share URL |
| link_type | VARCHAR(100) | NOT NULL | report \| avatar \| insight \| disruption_report |
| resource_id | INTEGER | | PK of the resource being shared |
| resource_table | VARCHAR(100) | | Name of the source table |
| permissions | JSON | | Which sections are visible to the recipient |
| view_count | INTEGER | NOT NULL DEFAULT 0 | |
| expires_at | TIMESTAMP | | Optional expiry |
| created_by | VARCHAR(255) | | Email or user identifier |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

### brain_dependencies

Registry of brains per niche — execution order, scheduling, and dependency graph.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| id | SERIAL | PK | |
| niche_id | INTEGER | NOT NULL FK → niches.id | |
| brain_name | VARCHAR(100) | NOT NULL | e.g. "persona_architect" |
| brain_type | VARCHAR(100) | NOT NULL | e.g. "intelligence", "scraper" |
| display_name | TEXT | | Human-friendly name |
| description | TEXT | | What this brain does |
| depends_on | JSON | | String array of brain_name values that must run first |
| config | JSON | | Brain-specific configuration |
| schedule | VARCHAR(100) | | Cron expression or frequency label |
| last_run_at | TIMESTAMP | | |
| next_run_at | TIMESTAMP | | |
| run_count | INTEGER | NOT NULL DEFAULT 0 | Total successful runs |
| is_enabled | BOOLEAN | NOT NULL DEFAULT true | Kill switch per-niche |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | |

---

## Extensible Data Source Tables

### trend_data

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | |
| niche_id | INTEGER FK | |
| term | TEXT NOT NULL | Search term tracked |
| source | VARCHAR(50) NOT NULL | google_trends \| reddit_trending |
| trend_value | DECIMAL(10,4) | Normalized interest value |
| trend_direction | VARCHAR(20) | rising \| stable \| declining |
| geo | VARCHAR(10) | Country/region code |
| time_range | VARCHAR(50) | e.g. "past_90_days" |
| related_queries | JSON | Array of { query, type, value } |
| breakdown | JSON | Geographic or category breakdown |
| recorded_at | TIMESTAMP NOT NULL DEFAULT NOW() | |
| created_at | TIMESTAMP NOT NULL DEFAULT NOW() | |

---

### search_term_data

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | |
| niche_id | INTEGER FK | |
| keyword | TEXT NOT NULL | |
| search_volume | INTEGER | Monthly searches |
| cpc | DECIMAL(8,4) | Cost per click in USD |
| competition | VARCHAR(20) | low \| medium \| high |
| competition_score | DECIMAL(5,4) | 0.0000–1.0000 |
| intent | VARCHAR(50) | informational \| commercial \| transactional |
| serp_features | JSON | Featured snippets, PAA boxes, etc. |
| related_keywords | JSON | String array of related terms |
| source | VARCHAR(50) | Tool that provided this data |
| recorded_at | TIMESTAMP NOT NULL DEFAULT NOW() | |
| created_at | TIMESTAMP NOT NULL DEFAULT NOW() | |

---

### competitor_ad_data

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | |
| niche_id | INTEGER FK | |
| competitor_name | TEXT NOT NULL | |
| platform | VARCHAR(50) NOT NULL | facebook \| google \| tiktok \| instagram |
| ad_id | VARCHAR(255) | Platform-native ad ID |
| ad_type | VARCHAR(50) | image \| video \| carousel |
| headline | TEXT | Ad headline |
| body_text | TEXT | Ad body copy |
| cta | VARCHAR(100) | Call to action text |
| media_url | TEXT | URL of ad creative |
| landing_page_url | TEXT | Where the ad points |
| estimated_spend | JSON | { min, max, currency } |
| estimated_impressions | JSON | { min, max } |
| running_since | TIMESTAMP | First observed date |
| last_seen_at | TIMESTAMP | Last observed date |
| ad_metadata | JSON | Platform-specific extra fields |
| created_at | TIMESTAMP NOT NULL DEFAULT NOW() | |
| updated_at | TIMESTAMP NOT NULL DEFAULT NOW() | |

---

### youtube_channels

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | |
| niche_id | INTEGER FK | |
| channel_name | TEXT NOT NULL | |
| channel_id | TEXT NOT NULL | YouTube channel ID |
| channel_url | TEXT | Full URL |
| subscriber_count | INTEGER | |
| total_videos | INTEGER | |
| avg_views | INTEGER | Average views per video |
| avg_comments | INTEGER | Average comments per video |
| engagement_ratio | DECIMAL(10,6) | Comments/views ratio |
| authority_score | INTEGER | 0–100 composite score |
| tier | TEXT | TIER_1 \| TIER_2 \| TIER_3 |
| recommended_limit | INTEGER | Max videos to scrape from this channel |
| analyzed_at | TIMESTAMP DEFAULT NOW() | |
| scrape_cadence | TEXT | weekly \| monthly \| one-time |

---

## Foreign Key Relationships

```
niches (id)
├── research_jobs.niche_id
├── raw_source_data.niche_id
├── insights.niche_id
├── customer_avatars.niche_id
│   └── avatar_generation_jobs.avatar_id → customer_avatars.id
│   └── marketing_copy_library.target_avatar_id → customer_avatars.id
├── avatar_generation_jobs.niche_id
├── success_stories.niche_id
├── offer_intelligence.niche_id
├── marketing_copy_library.niche_id
├── opportunities.niche_id
├── disruption_reports.niche_id
├── quarterly_industry_reports.niche_id
├── share_links.niche_id
├── brain_dependencies.niche_id
├── trend_data.niche_id
├── search_term_data.niche_id
├── competitor_ad_data.niche_id
└── youtube_channels.niche_id
```

---

## JSON Column Structures

### niches.data_sources

```json
{
  "reddit": {
    "subreddits": ["exoticcars", "carrentals"],
    "keywords": ["exotic rental", "lamborghini rent"]
  },
  "youtube": {
    "channels": ["UCxxxxxx"],
    "keywords": ["exotic car rental review"]
  },
  "googleTrends": { "keywords": ["exotic car rental"] },
  "forums": { "urls": ["https://forums.example.com/rental"] },
  "reviews": { "platforms": ["trustpilot", "google_maps"] }
}
```

### niches.research_frequency

```json
{
  "daily": ["raw_source_data"],
  "weekly": ["success_stories", "insights"],
  "biweekly": ["disruption_reports"],
  "monthly": ["trend_data"],
  "quarterly": ["customer_avatars", "quarterly_industry_reports"]
}
```

### raw_source_data.engagement_metrics

```json
{
  "comments": 142,
  "shares": 37,
  "views": 85000,
  "likes": 1200,
  "upvote_ratio": 0.94
}
```

### customer_avatars.psychographics

```json
{
  "values": ["status", "exclusivity", "experience"],
  "lifestyle": "High-disposable-income professional seeking memorable experiences",
  "personality": ["thrill-seeker", "brand-conscious", "spontaneous"],
  "media_diet": ["Instagram", "YouTube car channels", "Reddit r/cars"]
}
```

### customer_avatars.empathy_map

```json
{
  "thinks": ["Will this impress my group?", "Is it worth the price?"],
  "feels": ["Excited", "Slightly anxious about damage liability"],
  "sees": ["Instagram posts of friends renting exotics", "Turo listings"],
  "hears": ["Friends bragging about rental experiences", "Influencer reviews"],
  "says": ["I've always wanted to drive a Lamborghini"],
  "does": ["Googles 'rent Ferrari for a day'", "Checks reviews on multiple sites"]
}
```

### success_stories.quantified_results

```json
{
  "revenue_amount": 8500,
  "revenue_timeframe": "monthly",
  "proof_type": "screenshot",
  "time_to_first_revenue": "3 weeks",
  "roi_multiple": 4.2
}
```

### disruption_reports.disruption_signals

```json
[{
  "signal": "AI-powered dynamic pricing adoption",
  "evidence": ["r/turo post: 'competitors now repricing hourly'"],
  "opportunity_size": "Medium",
  "urgency": "high",
  "recommended_response": "Implement dynamic pricing within 30 days"
}]
```

---

## Brain → Table Mapping

| Brain | Reads From | Writes To |
|-------|-----------|-----------|
| Research Analyst | raw_source_data | insights |
| Persona Architect | insights, raw_source_data | customer_avatars, avatar_generation_jobs |
| Success Story Hunter | raw_source_data | stories_library |
| Offer Designer | customer_avatars, insights, stories_library | offer_intelligence |
| Copywriter | insights (language_pattern), customer_avatars, stories_library | hooks_library, marketing_copy_library |
| Financial Analyst | insights, stories_library, trend_data | financial_analysis ⚠️ |
| Competitive Intelligence | insights (competitor_gap), stories_library, customer_avatars | competitor_analysis ⚠️ |
| Market Strategist | insights, customer_avatars, stories_library | disruption_reports, opportunities |
| Conversational Assistant | all intelligence tables | — (read-only synthesis) |

⚠️ **financial_analysis** and **competitor_analysis** are referenced by MCP tools but do not exist in the live schema.

---

## Brain Dependency Flow

```
raw_source_data  (scrapers populate)
        │
        ▼
┌─────────────────┐
│ Research Analyst│  → insights
└─────────────────┘
        │
        ├──────────────────────────────────────────────┐
        ▼                                              ▼
┌──────────────────┐                      ┌─────────────────────┐
│ Persona Architect│ → customer_avatars   │ Success Story Hunter│ → success_stories
└──────────────────┘                      └─────────────────────┘
        │                                              │
        └─────────────────┬────────────────────────────┘
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
   ┌──────────────────┐    ┌────────────────────────┐
   │  Offer Designer  │    │   Financial Analyst    │
   │→ offer_intel     │    │ → financial_analysis⚠️ │
   └──────────────────┘    └────────────────────────┘
             │
             ▼
   ┌──────────────────────┐
   │     Copywriter       │  → marketing_copy_library
   └──────────────────────┘

   ┌──────────────────────┐
   │ Competitive Intel    │  → competitor_analysis ⚠️
   └──────────────────────┘

   ┌──────────────────────────────────────────┐
   │         Market Strategist                │
   │ (reads: insights + avatars + stories)    │
   │ → disruption_reports, opportunities      │
   └──────────────────────────────────────────┘
```

**Execution order:**
1. Scrapers → raw_source_data
2. Research Analyst → insights
3. (parallel) Persona Architect, Success Story Hunter
4. (parallel) Offer Designer, Financial Analyst, Competitive Intelligence
5. Copywriter
6. Market Strategist

---

## MCP Tool → Table Reference

| MCP Tool | Operation | Table(s) |
|----------|-----------|----------|
| query_raw_posts | SELECT | raw_source_data, research_jobs |
| save_insight | INSERT | insights |
| query_insights | SELECT | insights |
| save_persona | INSERT | customer_avatars |
| query_personas | SELECT | customer_avatars |
| get_niche_config | SELECT | niches |
| expand_research | SELECT | niches (read-only) |
| save_success_story | INSERT | stories_library |
| query_success_stories | SELECT | stories_library |
| save_hook | INSERT | hooks_library |
| query_hooks | SELECT | hooks_library |
| generate_disruption_report | — | No DB write |
| save_disruption_report | INSERT | disruption_reports |
| save_marketing_copy | INSERT | marketing_copy_library ⚠️ |
| save_offer | INSERT | offer_intelligence ⚠️ |
| save_financial_analysis | INSERT | financial_analysis ⚠️ |
| save_competitor_analysis | INSERT | competitor_analysis ⚠️ |
| query_all_intelligence | SELECT | insights, customer_avatars, stories_library, marketing_copy_library, offer_intelligence, hooks_library |

---

## Known Discrepancies

### FIXED (May 21, 2026)

#### ✅ 1. success_stories column names
**Status:** FIXED - MCP tool now uses correct snake_case columns

#### ✅ 2. marketing_copy_library column names  
**Status:** FIXED - MCP tool now maps copy_text → content, etc.

#### ✅ 3. offer_intelligence column names
**Status:** FIXED - MCP tool now maps to core_promise, unique_mechanism, price_point

#### ✅ 4. disruption_reports column mapping
**Status:** FIXED - MCP tool correctly maps to disruption_signals, emerging_technologies

---

#### ✅ 5. financial_analysis table schema
**Status:** FIXED - Table recreated to match MCP tool (tam_estimate, average_cac, average_ltv as TEXT)

#### ✅ 6. competitor_analysis table schema
**Status:** FIXED - Table recreated to match MCP tool (strategy, strengths, weaknesses as expected)

---

### MINOR CLEANUP (Non-Breaking)

#### ⚠️ 7. insights.confidence_score range ambiguity
**Issue:** DECIMAL(3,2) can store 0.00–9.99, but tool description says 0.0–1.0  
**Impact:** None - tool works correctly, just unclear documentation  
**Resolution:** Decide on canonical range (0-1 or 0-10) and update docs accordingly

---

**Summary:** All core functionality working. All 9 brains operational. All tables aligned with MCP tools.

---

**End of Schema Documentation**
