// Niche Intelligence Platform - Complete Database Schema
// Last Updated: [Date]
// Version: 1.0

import { pgTable, serial, text, integer, timestamp, json, boolean } from 'drizzle-orm/pg-core';

// ============================================
// FOUNDATION TABLES
// ============================================

export const niches = pgTable('niches', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(), // "Exotic Car Rental"
  slug: text('slug').notNull().unique(), // "exotic-car-rental"
  description: text('description'),
  
  // Data source configuration
  dataSources: json('data_sources').$type<{
    reddit: { subreddits: string[], keywords: string[] };
    youtube: { channels: string[], keywords: string[] };
    googleTrends: { keywords: string[] };
    forums: { urls: string[] };
    reviews: { platforms: string[] };
  }>(),
  
  // Research settings
  researchFrequency: json('research_frequency').$type<{
    weekly: string[]; // ['success_stories']
    biweekly: string[]; // ['disruption_report']
    monthly: string[]; // ['trend_analysis']
    quarterly: string[]; // ['avatars', 'industry_report']
  }>(),
  
  active: boolean('active').default(true),
  createdAt: timestamp('created_at').defaultNow(),
});

export const researchJobs = pgTable('research_jobs', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  jobType: text('job_type').notNull(), // 'scrape', 'analyze', 'generate_avatars'
  status: text('status').notNull(), // 'pending', 'running', 'complete', 'failed'
  
  startedAt: timestamp('started_at'),
  completedAt: timestamp('completed_at'),
  
  // Results summary
  recordsProcessed: integer('records_processed'),
  recordsCreated: integer('records_created'),
  errorMessage: text('error_message'),
  
  metadata: json('metadata').$type<{
    sourceType?: string;
    brainUsed?: string;
    parameters?: any;
  }>(),
});

export const rawSourceData = pgTable('raw_source_data', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  sourceType: text('source_type').notNull(), // 'reddit', 'youtube', 'google_trends'
  sourceUrl: text('source_url'), // Link to original post/video
  
  content: json('content').$type<{
    title?: string;
    body?: string;
    author?: string;
    upvotes?: number;
    comments?: number;
    timestamp?: string;
    // Extensible: Add fields as new sources are added
  }>().notNull(),
  
  fetchedAt: timestamp('fetched_at').defaultNow(),
  processed: boolean('processed').default(false),
});

// ============================================
// INTELLIGENCE OUTPUT TABLES
// ============================================

export const insights = pgTable('insights', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  category: text('category').notNull(), // 'pain_points', 'buying_triggers', 'objections', 'language_patterns', 'competitor_gaps', 'market_timing'
  title: text('title').notNull(),
  content: text('content').notNull(),
  
  // Structured data for queryability
  structuredData: json('structured_data').$type<{
    items?: Array<{
      title: string;
      description: string;
      evidence: string[]; // URLs or quotes
      frequency?: string; // 'very_common', 'common', 'occasional'
      severity?: number; // 1-10 for pain points
      actionable?: string; // What to do about it
    }>;
  }>(),
  
  confidence: integer('confidence'), // 1-10
  sourceCount: integer('source_count'), // How many data points support this
  
  createdAt: timestamp('created_at').defaultNow(),
});

export const customerAvatars = pgTable('customer_avatars', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  avatarName: text('avatar_name').notNull(), // "Weekend Experience Seeker"
  marketShare: integer('market_share'), // Percentage of market
  
  // Demographics
  demographics: json('demographics').$type<{
    ageRange: string;
    income: string;
    location: string;
    occupation: string;
    gender?: string;
  }>(),
  
  // Empathy Map
  empathyMap: json('empathy_map').$type<{
    thinksAndFeels: {
      worries: string[];
      aspirations: string[];
      dreams: string[];
    };
    sees: string[];
    hears: string[];
    saysAndDoes: {
      says: string[];
      does: string[];
      behaviorGap?: string; // What they say vs what they do
    };
    pains: string[];
    gains: string[];
  }>(),
  
  // Buying behavior
  painPoints: json('pain_points').$type<string[]>(),
  buyingTriggers: json('buying_triggers').$type<string[]>(),
  objections: json('objections').$type<string[]>(),
  languagePatterns: json('language_patterns').$type<string[]>(), // How they talk
  
  // Evidence
  evidenceQuotes: json('evidence_quotes').$type<Array<{
    quote: string;
    source: string;
    url: string;
  }>>(),
  
  // Lifecycle
  generatedAt: timestamp('generated_at').defaultNow(),
  quarterYear: text('quarter_year'), // "Q1_2026"
  active: boolean('active').default(true), // Set false when regenerated
});

export const avatarGenerationJobs = pgTable('avatar_generation_jobs', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  quarterYear: text('quarter_year').notNull(),
  avatarsGenerated: integer('avatars_generated'),
  previousAvatarsDeactivated: integer('previous_avatars_deactivated'),
  
  startedAt: timestamp('started_at'),
  completedAt: timestamp('completed_at'),
  status: text('status'), // 'pending', 'complete', 'failed'
});

export const successStories = pgTable('success_stories', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  storyTitle: text('story_title').notNull(),
  summary: text('summary').notNull(),
  
  // Financial proof
  revenue: json('revenue').$type<{
    amount?: number;
    timeframe?: string; // "monthly", "yearly"
    proofType?: string; // "screenshot", "stated", "inferred"
  }>(),
  
  // Method
  method: text('method').notNull(), // What they did to make money
  platform: text('platform'), // "rental_business", "marketplace", "service"
  
  // Credibility
  credibilityScore: integer('credibility_score'), // 1-10
  proofLinks: json('proof_links').$type<string[]>(),
  
  // Context
  sourceUrl: text('source_url').notNull(),
  sourceType: text('source_type'), // 'reddit', 'youtube', 'blog'
  
  discoveredAt: timestamp('discovered_at').defaultNow(),
});

export const offerIntelligence = pgTable('offer_intelligence', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  offerName: text('offer_name').notNull(),
  offerType: text('offer_type'), // 'service', 'product', 'saas', 'marketplace'
  
  // Positioning
  targetAvatar: text('target_avatar'), // Links to customerAvatars.avatarName
  problemSolved: text('problem_solved').notNull(),
  uniqueValue: text('unique_value').notNull(),
  
  // Pricing
  pricing: json('pricing').$type<{
    suggestedPrice: string;
    priceRationale: string;
    competitorPricing?: string;
    willingness_to_pay_signals: string[];
  }>(),
  
  // Go-to-market
  marketTiming: json('market_timing').$type<{
    urgencyFactors: string[];
    seasonality?: string;
    competitorWeakness?: string;
  }>(),
  
  // Objection handling
  anticipatedObjections: json('anticipated_objections').$type<Array<{
    objection: string;
    response: string;
  }>>(),
  
  generatedAt: timestamp('generated_at').defaultNow(),
});

export const marketingCopyLibrary = pgTable('marketing_copy_library', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  copyType: text('copy_type').notNull(), // 'headline', 'cta', 'email_subject', 'body_copy'
  copyText: text('copy_text').notNull(),
  
  useCase: text('use_case'), // 'landing_page', 'email', 'ad', 'social'
  
  // Source
  sourceType: text('source_type'), // 'customer_language', 'competitor', 'success_story'
  sourceReference: text('source_reference'), // URL or description
  
  // Context
  avatarTarget: text('avatar_target'), // Which avatar this resonates with
  emotionalTrigger: text('emotional_trigger'), // 'urgency', 'aspiration', 'fear', 'social_proof'
  
  // Performance (if tested)
  performanceData: json('performance_data').$type<{
    conversionRate?: number;
    clickThroughRate?: number;
    tested?: boolean;
  }>(),
  
  tags: json('tags').$type<string[]>(),
  createdAt: timestamp('created_at').defaultNow(),
});

export const opportunities = pgTable('opportunities', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  opportunityTitle: text('opportunity_title').notNull(),
  opportunityType: text('opportunity_type'), // 'product', 'service', 'content', 'partnership'
  
  description: text('description').notNull(),
  
  // Scoring
  viabilityScore: integer('viability_score'), // 1-10
  revenueScore: integer('revenue_score'), // 1-10
  competitionScore: integer('competition_score'), // 1-10 (10 = low competition)
  
  // Details
  estimatedRevenue: text('estimated_revenue'),
  timeToMarket: text('time_to_market'),
  capitalRequired: text('capital_required'),
  
  // Supporting evidence
  evidenceFromResearch: json('evidence_from_research').$type<string[]>(),
  customerDemand: json('customer_demand').$type<{
    avatarsWantingThis: string[];
    urgency: string;
    willingness_to_pay: string;
  }>(),
  
  identifiedAt: timestamp('identified_at').defaultNow(),
});

export const disruptionReports = pgTable('disruption_reports', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  reportTitle: text('report_title').notNull(),
  reportPeriod: text('report_period'), // "Q1_2026_Week_4"
  
  // Sections
  executiveSummary: text('executive_summary').notNull(),
  
  marketGaps: json('market_gaps').$type<Array<{
    gapTitle: string;
    description: string;
    evidenceFromResearch: string[];
    opportunitySize: string;
    competitionLevel: string;
    whyUnfulfilled: string;
    customerDemand: {
      avatarsWantingThis: string[];
      urgency: string;
      willingness_to_pay: string;
    };
  }>>(),
  
  emergingTrends: json('emerging_trends').$type<Array<{
    trendName: string;
    trajectory: string;
    timeframe: string;
    implications: string[];
    howToCapitalize: string;
    riskLevel: string;
  }>>(),
  
  competitorMoves: json('competitor_moves').$type<Array<{
    competitor: string;
    action: string;
    ourResponse: string;
    timing: string;
  }>>(),
  
  opportunitiesThisWeek: json('opportunities_this_week').$type<Array<{
    title: string;
    description: string;
    quickWins: string[];
    resourcesNeeded: string[];
  }>>(),
  
  generatedAt: timestamp('generated_at').defaultNow(),
  pageCount: integer('page_count'),
});

export const quarterlyIndustryReports = pgTable('quarterly_industry_reports', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  reportTitle: text('report_title').notNull(),
  quarterYear: text('quarter_year'), // "Q1_2026"
  
  // McKinsey-style sections
  marketStructure: json('market_structure').$type<{
    totalAddressableMarket: { size: string; growthRate: string; sources: string[] };
    marketSegments: Array<{ segment: string; size: string; characteristics: string }>;
    regulatoryEnvironment: string;
  }>(),
  
  competitiveLandscape: json('competitive_landscape').$type<Array<{
    name: string;
    marketShare: string;
    strengths: string[];
    weaknesses: string[];
    strategy: string;
    marketingChannels: Array<{ channel: string; performance: string }>;
    messagingFramework: { primaryMessage: string; proofPoints: string[] };
  }>>(),
  
  customerEconomics: json('customer_economics').$type<{
    averageCAC: string;
    averageLTV: string;
    ltvCacRatio: string;
    paybackPeriod: string;
    churnRate: string;
  }>(),
  
  goToMarket: json('go_to_market').$type<{
    channelROI: Array<{ channel: string; cac: string; ltv: string; competitiveIntensity: string; recommendation: string }>;
    messagingRecommendations: string[];
    timingStrategy: string;
  }>(),
  
  operationalBenchmarks: json('operational_benchmarks').$type<{
    keyMetrics: Array<{ metric: string; industryAverage: string; topQuartile: string }>;
    costStructure: string;
    unitEconomics: string;
  }>(),
  
  strategicRecommendations: json('strategic_recommendations').$type<Array<{
    recommendation: string;
    rationale: string;
    expectedImpact: string;
    timeframe: string;
    resources: string;
  }>>(),
  
  generatedAt: timestamp('generated_at').defaultNow(),
  pageCount: integer('page_count'),
});

// ============================================
// SUPPORTING TABLES
// ============================================

export const shareLinks = pgTable('share_links', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  shareToken: text('share_token').notNull().unique(),
  shareType: text('share_type'), // 'disruption_report', 'industry_report', 'avatars'
  entityId: integer('entity_id'), // ID of the report/avatar being shared
  
  visibleSections: json('visible_sections').$type<string[]>(), // Which parts recipient can see
  
  createdAt: timestamp('created_at').defaultNow(),
  expiresAt: timestamp('expires_at'),
  viewCount: integer('view_count').default(0),
});

export const brainDependencies = pgTable('brain_dependencies', {
  id: serial('id').primaryKey(),
  
  brainName: text('brain_name').notNull(), // 'persona_architect'
  inputTable: text('input_table').notNull(), // 'insights'
  outputTable: text('output_table').notNull(), // 'customer_avatars'
  
  executionOrder: integer('execution_order'), // For orchestration
  
  notes: text('notes'),
});

// ============================================
// EXTENSIBLE DATA SOURCE TABLES (Examples)
// ============================================
// These can be added as new data sources are integrated

export const trendData = pgTable('trend_data', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  searchTerm: text('search_term').notNull(),
  region: text('region'),
  timeframe: text('timeframe'),
  
  dataPoints: json('data_points').$type<Array<{
    date: string;
    value: number;
  }>>().notNull(),
  
  trend: text('trend'), // "rising", "stable", "declining"
  seasonality: json('seasonality').$type<{
    peakMonths: string[];
    lowMonths: string[];
    pattern: string;
  }>(),
  
  relatedQueries: json('related_queries').$type<Array<{
    query: string;
    type: string;
    value: number;
  }>>(),
  
  fetchedAt: timestamp('fetched_at').defaultNow(),
});

export const searchTermData = pgTable('search_term_data', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  domain: text('domain'), // Competitor domain being analyzed
  query: text('query').notNull(),
  
  impressions: integer('impressions'),
  clicks: integer('clicks'),
  ctr: integer('ctr'),
  position: integer('position'),
  
  searchIntent: text('search_intent'),
  opportunityScore: integer('opportunity_score'),
  
  dateRange: text('date_range'),
  fetchedAt: timestamp('fetched_at').defaultNow(),
});

export const competitorAdData = pgTable('competitor_ad_data', {
  id: serial('id').primaryKey(),
  nicheId: integer('niche_id').references(() => niches.id).notNull(),
  
  advertiser: text('advertiser').notNull(),
  estimatedMonthlySpend: integer('estimated_monthly_spend'),
  spendTrend: text('spend_trend'),
  
  adCreatives: json('ad_creatives').$type<Array<{
    adId: string;
    headline: string;
    description: string;
    cta: string;
    landingPage: string;
    firstSeen: string;
    lastSeen: string;
  }>>(),
  
  topPublishers: json('top_publishers').$type<Array<{
    publisher: string;
    impressionShare: number;
  }>>(),
  
  longestRunningAds: json('longest_running_ads').$type<Array<{
    adId: string;
    runningDays: number;
    reasoning: string;
  }>>(),
  
  monthYear: text('month_year'),
  fetchedAt: timestamp('fetched_at').defaultNow(),
});

// ============================================
// SCHEMA VERSION & NOTES
// ============================================

/*
SCHEMA VERSION: 1.0
TOTAL TABLES: 17 (14 core + 3 extensible examples)

EXTENSIBILITY NOTES:
- New data sources: Add tables following the pattern above
- New intelligence types: Add to insights or create specialized table
- New brains: Update brainDependencies table
- Performance tracking: Add tables for email/call/campaign data as needed

NEXT PLANNED EXTENSIONS:
- Email conversation tracking (for prospect analysis)
- Sales call analysis (transcripts + objection tracking)
- Campaign performance (email open rates, reply rates feeding back to copywriter brain)
*/