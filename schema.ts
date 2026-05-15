import {
  pgTable,
  serial,
  text,
  timestamp,
  integer,
  boolean,
  json,
  decimal,
  varchar,
} from 'drizzle-orm/pg-core';

// ─── FOUNDATION ───────────────────────────────────────────────────────────────

export const niches = pgTable('niches', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  slug: varchar('slug', { length: 100 }).notNull().unique(),
  description: text('description'),
  status: varchar('status', { length: 50 }).notNull().default('active'),
  data_sources: json('data_sources'),         // { reddit: [...], youtube: [...], ... }
  research_frequency: json('research_frequency'), // { daily: [...], weekly: [...] }
  metadata: json('metadata'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const research_jobs = pgTable('research_jobs', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  job_type: varchar('job_type', { length: 100 }).notNull(),
  status: varchar('status', { length: 50 }).notNull().default('pending'),
  brain_name: varchar('brain_name', { length: 100 }),
  priority: integer('priority').notNull().default(5),
  payload: json('payload'),
  result: json('result'),
  error_message: text('error_message'),
  started_at: timestamp('started_at'),
  completed_at: timestamp('completed_at'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const raw_source_data = pgTable('raw_source_data', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  source_type: varchar('source_type', { length: 50 }).notNull(), // reddit, youtube, google_trends, etc.
  source_url: text('source_url'),
  source_id: varchar('source_id', { length: 255 }),
  title: text('title'),
  content: text('content'),
  author: varchar('author', { length: 255 }),
  score: integer('score'),
  engagement_metrics: json('engagement_metrics'),
  raw_data: json('raw_data'),
  collected_at: timestamp('collected_at').notNull().defaultNow(),
  created_at: timestamp('created_at').notNull().defaultNow(),
});

// ─── INTELLIGENCE ─────────────────────────────────────────────────────────────

export const insights = pgTable('insights', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  insight_type: varchar('insight_type', { length: 100 }).notNull(),
  title: text('title').notNull(),
  summary: text('summary'),
  body: text('body'),
  confidence_score: decimal('confidence_score', { precision: 3, scale: 2 }),
  source_ids: json('source_ids'),             // array of raw_source_data ids
  tags: json('tags'),
  is_actionable: boolean('is_actionable').notNull().default(false),
  expires_at: timestamp('expires_at'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const customer_avatars = pgTable('customer_avatars', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  name: text('name').notNull(),
  avatar_type: varchar('avatar_type', { length: 100 }),
  age_range: varchar('age_range', { length: 50 }),
  income_range: varchar('income_range', { length: 100 }),
  psychographics: json('psychographics'),
  pain_points: json('pain_points'),
  desires: json('desires'),
  objections: json('objections'),
  empathy_map: json('empathy_map'),           // { thinks, feels, sees, hears, says, does }
  buying_triggers: json('buying_triggers'),
  preferred_channels: json('preferred_channels'),
  is_primary: boolean('is_primary').notNull().default(false),
  version: integer('version').notNull().default(1),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const avatar_generation_jobs = pgTable('avatar_generation_jobs', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  avatar_id: integer('avatar_id').references(() => customer_avatars.id),
  status: varchar('status', { length: 50 }).notNull().default('pending'),
  generation_config: json('generation_config'),
  source_data_ids: json('source_data_ids'),
  ai_model: varchar('ai_model', { length: 100 }),
  tokens_used: integer('tokens_used'),
  result_summary: json('result_summary'),
  error_message: text('error_message'),
  started_at: timestamp('started_at'),
  completed_at: timestamp('completed_at'),
  created_at: timestamp('created_at').notNull().defaultNow(),
});

export const success_stories = pgTable('success_stories', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  title: text('title').notNull(),
  source_type: varchar('source_type', { length: 50 }),
  source_url: text('source_url'),
  protagonist_profile: json('protagonist_profile'),
  before_state: text('before_state'),
  after_state: text('after_state'),
  transformation: text('transformation'),
  key_mechanism: text('key_mechanism'),
  quantified_results: json('quantified_results'),
  emotional_arc: json('emotional_arc'),
  usable_hooks: json('usable_hooks'),
  verified: boolean('verified').notNull().default(false),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const offer_intelligence = pgTable('offer_intelligence', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  offer_name: text('offer_name').notNull(),
  competitor_name: text('competitor_name'),
  offer_type: varchar('offer_type', { length: 100 }),
  price_point: decimal('price_point', { precision: 10, scale: 2 }),
  pricing_model: varchar('pricing_model', { length: 100 }),
  core_promise: text('core_promise'),
  unique_mechanism: text('unique_mechanism'),
  bonuses: json('bonuses'),
  guarantees: json('guarantees'),
  testimonials_summary: json('testimonials_summary'),
  conversion_elements: json('conversion_elements'),
  weaknesses: json('weaknesses'),
  strengths: json('strengths'),
  source_url: text('source_url'),
  last_seen_at: timestamp('last_seen_at'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const marketing_copy_library = pgTable('marketing_copy_library', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  copy_type: varchar('copy_type', { length: 100 }).notNull(), // headline, hook, cta, email_subject, etc.
  copy_angle: varchar('copy_angle', { length: 100 }),
  content: text('content').notNull(),
  target_avatar_id: integer('target_avatar_id').references(() => customer_avatars.id),
  performance_data: json('performance_data'),
  ai_generated: boolean('ai_generated').notNull().default(true),
  approved: boolean('approved').notNull().default(false),
  tags: json('tags'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const opportunities = pgTable('opportunities', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  title: text('title').notNull(),
  opportunity_type: varchar('opportunity_type', { length: 100 }),
  description: text('description'),
  market_gap: text('market_gap'),
  target_segment: text('target_segment'),
  estimated_market_size: json('estimated_market_size'),
  effort_level: varchar('effort_level', { length: 50 }),
  potential_revenue: json('potential_revenue'),
  time_to_market: varchar('time_to_market', { length: 100 }),
  risk_factors: json('risk_factors'),
  validation_ideas: json('validation_ideas'),
  status: varchar('status', { length: 50 }).notNull().default('identified'),
  priority_score: decimal('priority_score', { precision: 3, scale: 2 }),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const disruption_reports = pgTable('disruption_reports', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  report_title: text('report_title').notNull(),
  report_period: varchar('report_period', { length: 100 }),
  disruption_signals: json('disruption_signals'),
  emerging_technologies: json('emerging_technologies'),
  regulatory_changes: json('regulatory_changes'),
  consumer_behavior_shifts: json('consumer_behavior_shifts'),
  competitive_moves: json('competitive_moves'),
  threat_level: varchar('threat_level', { length: 50 }),
  opportunity_level: varchar('opportunity_level', { length: 50 }),
  recommended_actions: json('recommended_actions'),
  executive_summary: text('executive_summary'),
  published_at: timestamp('published_at'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

export const quarterly_industry_reports = pgTable('quarterly_industry_reports', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  quarter: varchar('quarter', { length: 10 }).notNull(), // e.g. "2024-Q2"
  report_title: text('report_title').notNull(),
  market_overview: text('market_overview'),
  key_trends: json('key_trends'),
  top_performers: json('top_performers'),
  consumer_sentiment: json('consumer_sentiment'),
  pricing_trends: json('pricing_trends'),
  channel_performance: json('channel_performance'),
  ai_generated_insights: json('ai_generated_insights'),
  data_sources_used: json('data_sources_used'),
  confidence_metrics: json('confidence_metrics'),
  published_at: timestamp('published_at'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

// ─── SUPPORTING ───────────────────────────────────────────────────────────────

export const share_links = pgTable('share_links', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  token: varchar('token', { length: 255 }).notNull().unique(),
  link_type: varchar('link_type', { length: 100 }).notNull(), // report, avatar, insight, etc.
  resource_id: integer('resource_id'),
  resource_table: varchar('resource_table', { length: 100 }),
  permissions: json('permissions'),
  view_count: integer('view_count').notNull().default(0),
  expires_at: timestamp('expires_at'),
  created_by: varchar('created_by', { length: 255 }),
  created_at: timestamp('created_at').notNull().defaultNow(),
});

export const brain_dependencies = pgTable('brain_dependencies', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  brain_name: varchar('brain_name', { length: 100 }).notNull(),
  brain_type: varchar('brain_type', { length: 100 }).notNull(),
  display_name: text('display_name'),
  description: text('description'),
  depends_on: json('depends_on'),             // array of brain_names this brain needs first
  config: json('config'),
  schedule: varchar('schedule', { length: 100 }),
  last_run_at: timestamp('last_run_at'),
  next_run_at: timestamp('next_run_at'),
  run_count: integer('run_count').notNull().default(0),
  is_enabled: boolean('is_enabled').notNull().default(true),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});

// ─── EXTENSIBLE ───────────────────────────────────────────────────────────────

export const trend_data = pgTable('trend_data', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  term: text('term').notNull(),
  source: varchar('source', { length: 50 }).notNull(), // google_trends, reddit_trending, etc.
  trend_value: decimal('trend_value', { precision: 10, scale: 4 }),
  trend_direction: varchar('trend_direction', { length: 20 }),
  geo: varchar('geo', { length: 10 }),
  time_range: varchar('time_range', { length: 50 }),
  related_queries: json('related_queries'),
  breakdown: json('breakdown'),
  recorded_at: timestamp('recorded_at').notNull().defaultNow(),
  created_at: timestamp('created_at').notNull().defaultNow(),
});

export const search_term_data = pgTable('search_term_data', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  keyword: text('keyword').notNull(),
  search_volume: integer('search_volume'),
  cpc: decimal('cpc', { precision: 8, scale: 4 }),
  competition: varchar('competition', { length: 20 }),
  competition_score: decimal('competition_score', { precision: 5, scale: 4 }),
  intent: varchar('intent', { length: 50 }),
  serp_features: json('serp_features'),
  related_keywords: json('related_keywords'),
  source: varchar('source', { length: 50 }),
  recorded_at: timestamp('recorded_at').notNull().defaultNow(),
  created_at: timestamp('created_at').notNull().defaultNow(),
});

export const youtubeChannels = pgTable('youtube_channels', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),

  channelName: text('channel_name').notNull(),
  channelId: text('channel_id').notNull(),
  channelUrl: text('channel_url'),

  // Metrics snapshot
  subscriberCount: integer('subscriber_count'),
  totalVideos: integer('total_videos'),
  avgViews: integer('avg_views'),
  avgComments: integer('avg_comments'),
  engagementRatio: decimal('engagement_ratio', { precision: 10, scale: 6 }),

  // Analysis
  authorityScore: integer('authority_score'), // 0-100
  tier: text('tier'), // 'TIER_1', 'TIER_2', 'TIER_3'
  recommendedLimit: integer('recommended_limit'),

  // Tracking
  analyzedAt: timestamp('analyzed_at').defaultNow(),
  scrapeCadence: text('scrape_cadence'), // 'weekly', 'monthly', 'one-time'
});

export const competitor_ad_data = pgTable('competitor_ad_data', {
  id: serial('id').primaryKey(),
  niche_id: integer('niche_id').notNull().references(() => niches.id),
  competitor_name: text('competitor_name').notNull(),
  platform: varchar('platform', { length: 50 }).notNull(), // facebook, google, tiktok, etc.
  ad_id: varchar('ad_id', { length: 255 }),
  ad_type: varchar('ad_type', { length: 50 }),
  headline: text('headline'),
  body_text: text('body_text'),
  cta: varchar('cta', { length: 100 }),
  media_url: text('media_url'),
  landing_page_url: text('landing_page_url'),
  estimated_spend: json('estimated_spend'),
  estimated_impressions: json('estimated_impressions'),
  running_since: timestamp('running_since'),
  last_seen_at: timestamp('last_seen_at'),
  ad_metadata: json('ad_metadata'),
  created_at: timestamp('created_at').notNull().defaultNow(),
  updated_at: timestamp('updated_at').notNull().defaultNow(),
});
