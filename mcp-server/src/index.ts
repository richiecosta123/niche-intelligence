import { config as dotenvConfig } from 'dotenv';
import { fileURLToPath } from 'url';
import path from 'path';
import { spawn } from 'child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenvConfig({ path: path.resolve(__dirname, '../../.env') });
dotenvConfig();

import { saveDisruptionReport } from './brains/market-strategist.js';
import { runHookExtractor } from './brains/hook-extractor.js';
import { runStoryExtractor } from './brains/story-extractor.js';
import { runOfferExtractor } from './brains/offer-extractor.js';
import { runApexPositioningBrain } from './brains/apex-positioning.js';
import { runClientIntelligenceBrain } from './brains/client-intelligence.js';
import { runResearchAnalystBrain } from './brains/research-analyst.js';
import { competitiveIntelligenceTool } from './brains/competitive-intelligence.js';
import { conversationalAssistantTool } from './brains/conversational-assistant.js';
import { copywriterTool } from './brains/copywriter.js';
import { financialAnalystTool } from './brains/financial-analyst.js';
import { offerDesignerTool } from './brains/offer-designer.js';
import { personaArchitectTool } from './brains/persona-architect.js';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { Pool } from 'pg';

const pool = new Pool({ connectionString: process.env.NEON_DB_URL });

// ─── Script Runner ─────────────────────────────────────────────────────────────

const SCRIPTS_DIR = '/Users/ricardo/niche-intelligence';
const SCRIPT_TIMEOUT_MS = 300_000; // 5 min

type ScriptResult = { success: boolean; output: string; error?: string };

function spawnScript(script: string, args: string[]): Promise<ScriptResult> {
  return new Promise((resolve) => {
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];

    const child = spawn('python3', [path.join(SCRIPTS_DIR, script), ...args], {
      cwd: SCRIPTS_DIR,
      env: process.env,
    });

    const timer = setTimeout(() => {
      child.kill('SIGTERM');
      resolve({ success: false, output: '', error: `Timed out after ${SCRIPT_TIMEOUT_MS / 1000}s` });
    }, SCRIPT_TIMEOUT_MS);

    child.stdout.on('data', (d: Buffer) => stdoutChunks.push(d));
    child.stderr.on('data', (d: Buffer) => stderrChunks.push(d));

    child.on('close', (code) => {
      clearTimeout(timer);
      const out = Buffer.concat(stdoutChunks).toString().trim();
      const err = Buffer.concat(stderrChunks).toString().trim();
      // Combine both streams — Python logging goes to stdout in these scrapers
      const output = [out, err].filter(Boolean).join('\n');
      if (code === 0) {
        resolve({ success: true, output });
      } else {
        resolve({ success: false, output, error: `Exit code ${code}` });
      }
    });

    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ success: false, output: '', error: err.message });
    });
  });
}

// ─── Tool Definitions ──────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: 'query_raw_posts',
    description:
      'Fetch raw source posts (Reddit, etc.) from the database for a niche. ' +
      'Use processed=false to get posts not yet analysed, processed=true for already-analysed posts.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to query' },
        limit: { type: 'number', description: 'Max rows to return (default: 50, max: 500)' },
        processed: {
          type: 'boolean',
          description: 'true = processed posts only | false = unprocessed only | omit = all',
        },
        source_type: {
          type: 'string',
          description: 'Filter by source: reddit | trustpilot | youtube | google_news | google_trends',
        },
        offset: { type: 'number', description: 'Rows to skip for pagination (default: 0)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'query_insights',
    description:
      'Fetch structured market insights for a niche, ordered by confidence score. ' +
      'Filter by category to narrow results.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche' },
        category: {
          type: 'string',
          description:
            'Optional insight_type filter: pain_point | buying_trigger | objection | ' +
            'language_pattern | competitor_gap | market_timing',
        },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'save_insight',
    description: 'Save a new market insight to the database.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        insight_type: {
          type: 'string',
          description:
            'pain_point | buying_trigger | objection | language_pattern | competitor_gap | market_timing',
        },
        title: { type: 'string', description: 'Short, specific title (max 200 chars)' },
        summary: {
          type: 'string',
          description: 'One-sentence summary. Auto-derived from body if omitted.',
        },
        body: { type: 'string', description: 'Full analysis text' },
        confidence_score: { type: 'number', description: 'Confidence 0.0–1.0' },
        source_ids: {
          type: 'array',
          items: { type: 'number' },
          description: 'IDs of raw_source_data rows supporting this insight',
        },
        tags: { type: 'array', items: { type: 'string' }, description: 'Keyword tags' },
        is_actionable: {
          type: 'boolean',
          description: 'Whether this insight suggests a direct action (default: true)',
        },
      },
      required: ['niche_id', 'insight_type', 'title', 'body', 'confidence_score'],
    },
  },
  {
    name: 'save_persona',
    description: 'Save a customer avatar/persona to the database.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        name: { type: 'string', description: 'Persona name, e.g. "The Vegas Splurger"' },
        avatar_type: { type: 'string', description: 'Segment label, e.g. "high-roller"' },
        age_range: { type: 'string', description: 'e.g. "28-42"' },
        income_range: { type: 'string', description: 'e.g. "$150k-$500k"' },
        psychographics: {
          type: 'object',
          description: 'Values, lifestyle, personality traits',
        },
        pain_points: { type: 'array', items: { type: 'string' } },
        desires: { type: 'array', items: { type: 'string' } },
        objections: { type: 'array', items: { type: 'string' } },
        empathy_map: {
          type: 'object',
          description: 'Thinks, feels, sees, hears, says, does',
        },
        buying_triggers: { type: 'array', items: { type: 'string' } },
        preferred_channels: { type: 'array', items: { type: 'string' } },
        is_primary: {
          type: 'boolean',
          description: 'Mark as a primary persona (default: false)',
        },
      },
      required: ['niche_id', 'name'],
    },
  },
  {
    name: 'get_niche_config',
    description: 'Get niche configuration including data sources and research frequency settings.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'query_personas',
    description: 'Fetch customer avatars/personas for a niche.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        active: {
          type: 'boolean',
          description: 'true = primary personas only | false = non-primary only | omit = all',
        },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'expand_research',
    description:
      'Identify research gaps and prepare targeted web search queries to fill them. ' +
      'Returns search queries for Claude Desktop to execute via web_search, then save results to raw_source_data.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to expand research for' },
        gaps: {
          type: 'array',
          items: { type: 'string' },
          description: 'Research gaps to fill, e.g. ["corporate events", "international tourist experience"]',
        },
      },
      required: ['niche_id', 'gaps'],
    },
  },
  {
    name: 'save_success_story',
    description: 'Save a story to the stories_library table. Supports multiple story types (default: success_story). Stories must have credibility score 0.5+ to be saved.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        story_title: { type: 'string', description: 'Compelling headline summarizing the story' },
        story_type: { type: 'string', description: 'Type of story: "success_story", "case_study", "testimonial", etc. Default: "success_story"' },
        summary: { type: 'string', description: 'Brief summary of the success story' },
        revenue: {
          type: 'object',
          description: 'Financial metrics',
          properties: {
            amount: { type: 'number', description: 'Revenue amount in dollars' },
            timeframe: { type: 'string', description: 'e.g. "monthly", "yearly", "6 months"' },
            proof_type: { type: 'string', description: '"screenshot", "stated", "inferred"' },
          },
        },
        method: { type: 'string', description: 'What they did to make money (detailed)' },
        platform: { type: 'string', description: 'e.g. "turo", "rental_business", "marketplace"' },
        credibility_score: { type: 'number', description: 'Score 0.0-1.0 based on evidence quality' },
        proof_links: {
          type: 'array',
          items: { type: 'string' },
          description: 'URLs to proof (screenshots, dashboard, etc.)',
        },
        source_url: { type: 'string', description: 'URL of original post/source' },
        source_type: { type: 'string', description: '"reddit", "youtube", "blog", etc.' },
      },
      required: ['niche_id', 'story_title', 'summary', 'method', 'credibility_score', 'source_url'],
    },
  },
  {
    name: 'query_success_stories',
    description: 'Fetch stories from stories_library for a niche, ordered by date. Optionally filter by story_type (e.g. "success_story", "case_study").',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        min_credibility: {
          type: 'number',
          description: 'Minimum credibility score (0.0-1.0). Default: 0.5',
        },
        story_type: {
          type: 'string',
          description: 'Filter by story type: "success_story", "case_study", "testimonial", etc. Omit to return all types.',
        },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'generate_disruption_report',
    description: 'Generate a 20-page market disruption report synthesizing all intelligence (insights, personas, success stories). Returns analysis + saves to disruption_reports table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to analyze' },
        report_period: { type: 'string', description: 'e.g. "Q2_2026_Week_1"' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'save_disruption_report',
    description: 'Save a completed market disruption report to the disruption_reports table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id:                { type: 'number' },
        report_period:           { type: 'string', description: 'e.g. "Q2_2026_Week_1"' },
        executive_summary:       { type: 'string', description: 'Full executive summary text' },
        market_gaps:             { type: 'array', items: { type: 'object' }, description: 'Identified market gaps' },
        emerging_trends:         { type: 'array', items: { type: 'object' }, description: 'Emerging market trends' },
        competitor_moves:        { type: 'array', items: { type: 'object' }, description: 'Notable competitor actions' },
        opportunities_this_week: { type: 'array', items: { type: 'object' }, description: 'Actionable opportunities for this week' },
        page_count:              { type: 'number', description: 'Number of pages in the report' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'save_marketing_copy',
    description: 'Save marketing copy asset (headline, CTA, email subject, body copy) to the marketing_copy_library table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        copy_type: { type: 'string', description: 'headline | cta | email_subject | body_copy' },
        copy_text: { type: 'string' },
        use_case: { type: 'string', description: 'landing_page | email | ad | social' },
        source_type: { type: 'string' },
        avatar_target: { type: 'string' },
        emotional_trigger: { type: 'string' },
        tags: { type: 'array', items: { type: 'string' } },
      },
      required: ['niche_id', 'copy_type', 'copy_text'],
    },
  },
  {
    name: 'save_offer',
    description: 'Save a positioned offer design with pricing strategy to the offer_intelligence table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        offer_name: { type: 'string' },
        offer_type: { type: 'string', description: 'service | product | saas | marketplace' },
        target_avatar: { type: 'string' },
        problem_solved: { type: 'string' },
        unique_value: { type: 'string' },
        pricing: { type: 'object', description: 'Pricing strategy with rationale' },
        market_timing: { type: 'object', description: 'Urgency factors and seasonality' },
        anticipated_objections: { type: 'array', items: { type: 'object' } },
      },
      required: ['niche_id', 'offer_name', 'problem_solved', 'unique_value'],
    },
  },
  {
    name: 'save_financial_analysis',
    description: 'Save financial analysis (TAM, CAC, LTV, unit economics) to validate market opportunities.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        tam_estimate: { type: 'string', description: 'Total addressable market estimate with methodology' },
        average_cac: { type: 'string', description: 'Customer acquisition cost with data sources' },
        average_ltv: { type: 'string', description: 'Lifetime value calculation' },
        ltv_cac_ratio: { type: 'string', description: 'LTV:CAC ratio (healthy = 3:1+)' },
        payback_period: { type: 'string', description: 'Time to recover CAC' },
        churn_rate: { type: 'string', description: 'Customer churn rate' },
        unit_economics: { type: 'object', description: 'Revenue, costs, margins per customer' },
      },
      required: ['niche_id', 'tam_estimate'],
    },
  },
  {
    name: 'save_competitor_analysis',
    description: 'Save competitive analysis identifying strengths, weaknesses, and opportunities.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        competitor_name: { type: 'string' },
        positioning: { type: 'string', description: 'How they position themselves' },
        strengths: { type: 'array', items: { type: 'string' } },
        weaknesses: { type: 'array', items: { type: 'string' } },
        gaps_and_opportunities: { type: 'array', items: { type: 'string' } },
        market_share_estimate: { type: 'string', description: 'Estimated market share' },
        strategy: { type: 'string', description: 'Their go-to-market strategy' },
      },
      required: ['niche_id', 'competitor_name'],
    },
  },
  {
    name: 'query_all_intelligence',
    description: 'Conversational Assistant: Query and synthesize intelligence across all brain outputs to answer user questions.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        query_type: {
          type: 'string',
          description: 'What user wants: pain_points | personas | opportunities | offers | financials | competitors | copy | comprehensive',
        },
      },
      required: ['niche_id', 'query_type'],
    },
  },
  {
    name: 'extract_hooks',
    description:
      'Autonomous Hook Extractor Brain: scans competitor_ad_data, raw_source_data, insights (language_pattern), ' +
      'and stories_library to extract attention-grabbing marketing hooks using Claude AI. ' +
      'Saves unique hooks to hooks_library with ai_generated=false and approved=false (needs human review). ' +
      'Returns count of hooks inserted.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to extract hooks for' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'extract_offers',
    description:
      'Autonomous Offer Extractor Brain: scans competitor_ad_data, raw_source_data, insights ' +
      '(competitor_gap, market_timing), and stories_library to extract product/service offers with ' +
      'pricing, positioning, and value propositions using Claude AI. ' +
      'Saves unique offers to offer_intelligence. Returns count of offers inserted.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to extract offers for' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'extract_stories',
    description:
      'Autonomous Story Extractor Brain: scans raw_source_data (Reddit, YouTube, reviews), competitor_ad_data, ' +
      'and insights to extract transformation narratives, success stories, testimonials, and case studies using Claude AI. ' +
      'Saves unique stories to stories_library with verified=false (needs human review). ' +
      'Returns count of stories inserted.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to extract stories for' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'save_hook',
    description: 'Save a marketing hook to hooks_library. Hooks are attention-grabbing lines used in copy, ads, and content.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        hook_text: { type: 'string', description: 'The hook line itself' },
        hook_type: {
          type: 'string',
          description: 'Hook category: curiosity | fear | desire | social_proof | urgency | pattern_interrupt',
        },
        customer_language_quote: {
          type: 'string',
          description: 'Original customer quote this hook was derived from (if applicable)',
        },
        target_avatar_id: { type: 'number', description: 'Optional: link to a specific customer_avatars.id' },
        source_insight_ids: {
          type: 'array',
          items: { type: 'number' },
          description: 'IDs of insights this hook was derived from',
        },
        usage_context: {
          type: 'string',
          description: 'Where this hook works best: ad | email_subject | landing_page | social_post | vsl_opener',
        },
        ai_generated: {
          type: 'boolean',
          description: 'true if AI-generated copy, false if extracted from real data (default: true)',
        },
        approved: {
          type: 'boolean',
          description: 'Human review flag — false until reviewed (default: false)',
        },
        performance_data: {
          type: 'object',
          description: 'Optional JSONB: e.g. { ctr: 0.04, conversions: 12, platform: "facebook", source_url: "..." }',
        },
        tags: {
          type: 'array',
          items: { type: 'string' },
          description: 'Keyword tags for filtering (e.g. ["deposit", "fear", "lamborghini"])',
        },
      },
      required: ['niche_id', 'hook_text', 'hook_type'],
    },
  },
  {
    name: 'query_hooks',
    description: 'Retrieve marketing hooks from hooks_library for a niche. Filter by type, avatar, or minimum performance score.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        hook_type: {
          type: 'string',
          description: 'Filter by type: curiosity | fear | desire | social_proof | urgency | pattern_interrupt',
        },
        target_avatar_id: { type: 'number', description: 'Filter by linked avatar ID' },
        approved: {
          type: 'boolean',
          description: 'true = approved hooks only | false = pending review | omit = all',
        },
        min_performance_score: {
          type: 'number',
          description: 'Filter by minimum performance score (0.0-1.0) if tracked',
        },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_reddit_scraper',
    description:
      'Spawn the Reddit scraper (run_full_scrape.py) to collect posts for a niche using Playwright headlessly. ' +
      'Saves results to raw_source_data. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to scrape for' },
        limit: { type: 'number', description: 'Posts per keyword (default: 50)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_google_trends',
    description:
      'Spawn the Google Trends scraper to collect weekly search volume, US regional data, and related queries ' +
      'for 9 exotic-car-rental keywords. Saves 3 rows per keyword to raw_source_data. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID (used for logging; scraper targets niche 1)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_youtube_scraper',
    description:
      'Spawn the YouTube scraper to collect videos and comments for a niche. ' +
      'Saves results to raw_source_data. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to tag records with' },
        search: {
          type: 'string',
          description: 'YouTube search query (default: "exotic car rental")',
        },
        limit: { type: 'number', description: 'Max videos to collect (default: 20)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_review_scraper',
    description:
      'Spawn the review scraper (Playwright) to collect Trustpilot or Yelp reviews for a niche. ' +
      'Saves results to raw_source_data. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to tag records with' },
        platform: {
          type: 'string',
          description: 'Review platform to scrape: trustpilot | yelp (default: trustpilot)',
        },
        limit: { type: 'number', description: 'Max reviews to collect (default: 50)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_facebook_scraper',
    description:
      'Spawn the Facebook Ad Library scraper to collect competitor ads for a niche. ' +
      'Saves results to competitor_ad_data. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to tag records with' },
        competitors: {
          type: 'string',
          description: 'Comma-separated competitor/page names, e.g. "Hertz Dream Cars,Gotham Dream Cars"',
        },
        max_ads: { type: 'number', description: 'Max ads per competitor (default: 50)' },
      },
      required: ['niche_id', 'competitors'],
    },
  },
  {
    name: 'run_landing_page_scraper',
    description:
      'Spawn the landing page scraper to visit competitor landing_page_urls from competitor_ad_data ' +
      'and extract pricing, headlines, CTAs, and copy. Saves results to raw_source_data as ' +
      'source_type=landing_page. Skips URLs already scraped. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to scrape landing pages for' },
        limit: { type: 'number', description: 'Max pages to visit (default: 20)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'seed_newsletter_urls',
    description:
      'Seed newsletter article links into raw_source_data as source_type=newsletter_pending ' +
      'for later scraping by run_email_intelligence_scraper. Sender/subject/date metadata is ' +
      'stored in engagement_metrics. Skips URLs that already exist in raw_source_data ' +
      '(any source_type) for this niche.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to seed newsletter URLs for' },
        urls: {
          type: 'array',
          description: 'Links extracted from newsletter emails',
          items: {
            type: 'object' as const,
            properties: {
              url: { type: 'string', description: 'Article/destination URL from the newsletter' },
              source_sender: { type: 'string', description: 'Sender name or email address of the newsletter' },
              source_subject: { type: 'string', description: 'Subject line of the newsletter email' },
              source_date: { type: 'string', description: 'Date the newsletter was received (ISO 8601)' },
            },
            required: ['url'],
          },
        },
      },
      required: ['niche_id', 'urls'],
    },
  },
  {
    name: 'run_email_intelligence_scraper',
    description:
      'Spawn the email intelligence scraper to visit newsletter URLs seeded via ' +
      'seed_newsletter_urls (source_type=newsletter_pending) and extract article title, ' +
      'body text, and publish date. Saves successes as source_type=newsletter and ' +
      'failures (paywall/blocked/timeout) as source_type=newsletter_failed. ' +
      'Visible browser by default. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to scrape newsletter URLs for' },
        limit: { type: 'number', description: 'Max URLs to visit (default: 20)' },
        batch: { type: 'number', description: 'Pause longer after every N URLs (default: 5)' },
        headless: { type: 'boolean', description: 'Run browser headless (default: false)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_magazine_discovery_scraper',
    description:
      'Spawn the magazine discovery scraper to visit configured trade-magazine source pages ' +
      '(Auto Rental News homepage, Luxury Daily automotive category) and extract candidate ' +
      'article links/headlines. New URLs (not already in raw_source_data for this niche, any ' +
      'source_type) are inserted as source_type=newsletter_pending for later scraping by ' +
      'run_email_intelligence_scraper. Visible browser by default. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'Niche ID to discover and tag new articles for' },
        headless: { type: 'boolean', description: 'Run browser headless (default: false)' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_meta_ads_scraper',
    description:
      'Spawn the Meta Ads scraper to search Facebook Ad Library for agency_benchmarks and ' +
      'authority_sources by name. Extracts ad copy, CTAs, formats, and landing page URLs. ' +
      'Saves ad intelligence to agency_benchmarks.meta_ads (JSONB) and ' +
      'authority_sources.paid_amplification (TEXT). Seeds landing_page_url_candidates into ' +
      'raw_source_data for later scraping. Visible browser. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        type: {
          type: 'string',
          description: 'Which tables to scrape: agency | authority | all (default: all)',
        },
        limit: { type: 'number', description: 'Max rows to process (default: 50)' },
      },
      required: [],
    },
  },
  {
    name: 'run_google_ads_scraper',
    description:
      'Spawn the Google Ads Transparency Center scraper for agency_benchmarks and authority_sources. ' +
      'Extracts ad headlines, descriptions, formats, and landing page URLs. ' +
      'Merges results into agency_benchmarks.meta_ads (JSONB) and ' +
      'authority_sources.paid_amplification (TEXT) — adds google_ads key without overwriting Meta data. ' +
      'Seeds landing_page_url_candidates into raw_source_data. Visible browser. Timeout: 5 minutes.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        type: {
          type: 'string',
          description: 'Which tables to scrape: agency | authority | all (default: all)',
        },
        limit: { type: 'number', description: 'Max rows to process (default: 50)' },
      },
      required: [],
    },
  },
  {
    name: 'browse_page',
    description:
      'Visit any URL with a headless Playwright browser, wait for JS to load, and return the full ' +
      'page content as text plus all links. Use for ad hoc research, competitor page analysis, ' +
      'or reading any URL. Returns { title, text_content, links, url }.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        url: { type: 'string', description: 'The URL to visit' },
        wait_for: {
          type: 'string',
          description: 'Optional CSS selector to wait for before extracting content',
        },
      },
      required: ['url'],
    },
  },
  {
    name: 'save_authority_source',
    description: 'Save an authority/thought-leadership source (e.g. consulting firm, research house) to the authority_sources table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        firm_name: { type: 'string', description: 'Name of the firm or authority source' },
        content_hubs: { type: 'object', description: 'JSONB: URLs and sections where they publish (e.g. { blog: "...", reports: "..." })' },
        report_structure: { type: 'string', description: 'How they structure their reports/content' },
        tone_style: { type: 'string', description: 'Writing tone and style (e.g. "authoritative", "data-driven")' },
        visual_design: { type: 'string', description: 'Notes on visual/brand design approach' },
        frameworks: { type: 'object', description: 'JSONB: Proprietary frameworks or methodologies they use' },
        paid_amplification: { type: 'string', description: 'Notes on paid distribution/amplification strategy' },
        luxury_content: { type: 'string', description: 'Notes on luxury/premium content positioning' },
        raw_notes: { type: 'string', description: 'Free-form research notes' },
      },
      required: ['firm_name'],
    },
  },
  {
    name: 'save_association',
    description: 'Save a trade association or industry body to the association_intelligence table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        name: { type: 'string', description: 'Full name of the association' },
        acronym: { type: 'string', description: 'Short acronym, e.g. "NADA"' },
        website: { type: 'string', description: 'Association website URL' },
        geo_focus: { type: 'string', description: 'Geographic scope, e.g. "US", "Global", "Southeast Asia"' },
        vertical: { type: 'string', description: 'Industry vertical, e.g. "automotive", "hospitality"' },
        citation_tier: { type: 'number', description: 'Citation authority tier (1 = highest)' },
        public_publications: { type: 'object', description: 'JSONB: Array/object of publicly available publications' },
        monitor_urls: { type: 'object', description: 'JSONB: Array of URLs to monitor for new content' },
        citation_use: { type: 'string', description: 'Notes on how/when to cite this association' },
        notes: { type: 'string', description: 'Free-form research notes' },
      },
      required: ['name'],
    },
  },
  {
    name: 'save_agency_benchmark',
    description: 'Save a competitor agency benchmark to the agency_benchmarks table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        agency_name: { type: 'string', description: 'Name of the agency' },
        tier: { type: 'string', description: 'Agency tier classification, e.g. "boutique", "mid-market", "enterprise"' },
        website: { type: 'string', description: 'Agency website URL' },
        headline_positioning: { type: 'string', description: 'Their main positioning headline/tagline' },
        outcome_language: { type: 'string', description: 'How they describe client outcomes and results' },
        proprietary_frameworks: { type: 'object', description: 'JSONB: Their proprietary methodologies or frameworks' },
        pricing_signals: { type: 'string', description: 'Pricing tier signals or indicators from their site' },
        case_study_format: { type: 'string', description: 'How they structure and present case studies' },
        meta_ads: { type: 'object', description: 'JSONB: Notes or data on their Meta/Facebook ad strategy' },
        notes: { type: 'string', description: 'Free-form research notes' },
      },
      required: ['agency_name'],
    },
  },
  {
    name: 'run_apex_positioning_brain',
    description:
      'Apex Positioning Brain: gathers Apex\'s scraped website content, all agency benchmarks, ' +
      'all authority/consulting firm sources, and all association intelligence. ' +
      'Returns a structured payload for conversational Claude to analyze positioning gaps, strengths, ' +
      'and opportunities. Save result via save_apex_positioning_brief.',
    inputSchema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'run_client_intelligence_brain',
    description:
      'Client Intelligence Brain: gathers the latest Apex positioning brief (style guide), ' +
      'plus all niche intelligence (insights, personas, stories, hooks, offers, Google Trends, ' +
      'competitor ads, disruption reports) for a niche. ' +
      'Returns a structured payload for conversational Claude to synthesize into a client intelligence report. ' +
      'Save result via save_client_intelligence_report.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id:    { type: 'number', description: 'ID of the niche to gather intelligence for' },
        client_name: { type: 'string', description: 'Optional: specific client name this report is for' },
        city:        { type: 'string', description: 'Optional: city or market this report targets' },
        report_type: {
          type: 'string',
          description: 'Report type: state_of_market | opportunity_brief | competitive_landscape (default: state_of_market)',
        },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'run_research_analyst',
    description:
      'Research Analyst Brain: gathers up to 100 unprocessed raw customer-voice posts ' +
      '(reddit, youtube, trustpilot, yelp, newsletter, forum_*) for a niche, picking up where the ' +
      'last completed research_jobs run left off via max_id_processed. ' +
      'Returns the posts plus a prompt instructing the calling Claude to extract evidence-based insights ' +
      'across 6 categories (pain_points, buying_triggers, objections, language_patterns, competitor_gaps, ' +
      'market_timing). Save each qualifying insight via save_insight.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to analyze raw customer-voice data for' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'save_apex_positioning_brief',
    description: 'Save an Apex positioning brief and style guide to the apex_positioning_briefs table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        version:                     { type: 'string', description: 'Version label, e.g. "v1.0" or date-stamped' },
        current_positioning:         { type: 'string', description: 'Narrative summary of Apex\'s current positioning' },
        positioning_gaps:            { type: 'object', description: 'Areas where Apex is weaker than benchmarks' },
        positioning_strengths:       { type: 'object', description: 'Areas where Apex already leads or differentiates' },
        positioning_opportunities:   { type: 'object', description: 'Specific moves Apex should make' },
        agency_comparisons:          { type: 'object', description: 'Side-by-side benchmark analysis per agency' },
        consulting_firm_comparisons: { type: 'object', description: 'Comparison against authority/consulting firm formats' },
        methodology_recommendations: { type: 'string', description: 'Recommended proprietary methodology to develop' },
        pricing_recommendations:     { type: 'string', description: 'Packaging and pricing tier guidance' },
        packaging_recommendations:   { type: 'string', description: 'How to structure service packages' },
        proposal_language:           { type: 'object', description: 'Recommended language patterns for proposals' },
        citation_recommendations:    { type: 'object', description: 'Which associations/sources to cite and how' },
        report_format:               { type: 'string', description: 'Recommended report structure and section order' },
        tone_guidelines:             { type: 'string', description: 'Voice, tone, and style directives' },
        citation_style:              { type: 'string', description: 'Citation formatting standard to adopt' },
        framework_naming:            { type: 'object', description: 'Proprietary framework names and descriptions' },
        visual_guidelines:           { type: 'string', description: 'Visual design and branding directives' },
        raw_analysis:                { type: 'string', description: 'Full unstructured analysis text' },
      },
      required: ['current_positioning'],
    },
  },
  {
    name: 'save_client_intelligence_report',
    description: 'Save a synthesized client intelligence report to the client_intelligence_reports table.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id:                   { type: 'number' },
        client_name:                { type: 'string', description: 'Name of the specific client (optional)' },
        city:                       { type: 'string', description: 'City or market this report targets (optional)' },
        report_type:                { type: 'string', description: 'state_of_market | opportunity_brief | competitive_landscape' },
        report_period:              { type: 'string', description: 'e.g. "Q2_2026"' },
        positioning_brief_id:       { type: 'number', description: 'ID of apex_positioning_briefs row used as style guide' },
        executive_summary:          { type: 'string', description: '2-3 paragraph executive summary' },
        market_overview:            { type: 'string', description: 'Narrative market analysis' },
        uhnw_persona_profiles:      { type: 'object', description: 'Persona breakdowns relevant to this client' },
        seasonality_data:           { type: 'object', description: 'Seasonal patterns and timing opportunities' },
        competitor_ad_intelligence: { type: 'object', description: 'Curated competitor ad insights' },
        hooks_and_offers:           { type: 'object', description: 'Recommended hooks and offer structures' },
        citations:                  { type: 'object', description: 'Data citations per section' },
        recommendations:            { type: 'object', description: 'Prioritized action items' },
        full_report:                { type: 'string', description: 'Complete formatted report text' },
      },
      required: ['niche_id', 'report_type'],
    },
  },
  {
    name: 'competitive_intelligence',
    description:
      'Competitive Intelligence Brain: dissects named competitors for a niche to find weaknesses ' +
      'and actionable gaps. Query query_insights (competitor_gap), query_success_stories, and ' +
      'query_personas first, then analyse each competitor and save one record per competitor via ' +
      'save_competitor_analysis.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to analyse competitors for' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'conversational_assistant',
    description:
      'Conversational Assistant Brain: returns a system prompt and a map of which query tools to call ' +
      '(query_insights, query_personas, query_success_stories, query_all_intelligence, etc.) for a given ' +
      'query type, so the calling Claude can synthesise a cited, actionable answer. Does not save anything.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to query' },
        query_type: {
          type: 'string',
          description:
            'What the user wants: pain_points | personas | opportunities | offers | ' +
            'financials | competitors | copy | comprehensive',
        },
      },
      required: ['niche_id', 'query_type'],
    },
  },
  {
    name: 'copywriter',
    description:
      'Copywriter Brain: builds a marketing copy asset library from authentic customer language. ' +
      'Query query_insights (language_pattern), query_personas, and query_success_stories first, then ' +
      'generate copy assets and save each via save_marketing_copy.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to generate copy for' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'financial_analyst',
    description:
      'Financial Analyst Brain: calculates TAM, CAC, LTV, payback period, and unit economics to ' +
      'validate market opportunities. Query query_insights, query_success_stories, and any available ' +
      'trend data first, then save results via save_financial_analysis.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to analyse' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'offer_designer',
    description:
      'Offer Designer Brain: designs 2-3 positioned offers per niche anchored to customer pain points ' +
      'and market gaps. Query query_personas, query_insights, and query_success_stories first, then ' +
      'save each designed offer via save_offer.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to design offers for' },
      },
      required: ['niche_id'],
    },
  },
  {
    name: 'persona_architect',
    description:
      'Persona Architect Brain: builds 8-12 psychologically rich customer personas from raw community ' +
      'data. Audit raw_source_data, call expand_research to fill gaps, then save each persona ' +
      'immediately (one at a time, not batched) via save_persona.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number', description: 'ID of the niche to generate personas for' },
      },
      required: ['niche_id'],
    },
  },
];

// ─── Handlers ──────────────────────────────────────────────────────────────────

type Args = Record<string, unknown>;

// Matches normalize_url() in landing_page_scraper.py
function normalizeUrl(u: string): string {
  return u.startsWith('http') ? u : `https://${u}`;
}

async function seedNewsletterUrls(a: Args) {
  const niche_id = a.niche_id as number;
  const urls = (a.urls as Array<Record<string, unknown>> | undefined) ?? [];

  const { rows: existing } = await pool.query<{ source_url: string }>(
    `SELECT source_url FROM raw_source_data WHERE niche_id = $1 AND source_url IS NOT NULL`,
    [niche_id]
  );
  const seen = new Set(existing.map((r) => normalizeUrl(r.source_url)));

  let inserted = 0;
  let skipped = 0;

  for (const item of urls) {
    const rawUrl = item.url as string | undefined;
    if (!rawUrl) {
      skipped++;
      continue;
    }
    const url = normalizeUrl(rawUrl);

    if (seen.has(url)) {
      skipped++;
      continue;
    }
    seen.add(url);

    await pool.query(
      `INSERT INTO raw_source_data
         (niche_id, source_type, source_url, title, engagement_metrics)
       VALUES ($1, 'newsletter_pending', $2, $3, $4)`,
      [
        niche_id,
        url,
        (item.source_subject as string | undefined) ?? null,
        JSON.stringify({
          sender: (item.source_sender as string | undefined) ?? null,
          subject: (item.source_subject as string | undefined) ?? null,
          date: (item.source_date as string | undefined) ?? null,
        }),
      ]
    );
    inserted++;
  }

  return { inserted, skipped_duplicates: skipped, total: urls.length };
}

async function queryRawPosts(a: Args) {
  const niche_id = a.niche_id as number;
  const limit = Math.min((a.limit as number | undefined) ?? 50, 500);
  const processed = a.processed as boolean | undefined;
  const source_type = a.source_type as string | undefined;
  const offset = (a.offset as number | undefined) ?? 0;

  let extraFilter = '';
  if (processed !== undefined) {
    try {
      const { rows } = await pool.query<{ max_id: number }>(
        `SELECT COALESCE(MAX((result->>'max_id_processed')::int), 0) AS max_id
         FROM research_jobs WHERE niche_id = $1 AND status = 'completed'`,
        [niche_id]
      );
      const maxId = rows[0]?.max_id ?? 0;
      if (maxId > 0) {
        extraFilter = processed ? `AND id <= ${maxId}` : `AND id > ${maxId}`;
      }
    } catch {
      // research_jobs unavailable — return all posts without filtering
    }
  }

  const params: unknown[] = [niche_id, limit, offset];
  let sourceFilter = '';
  if (source_type) {
    params.push(source_type);
    sourceFilter = `AND source_type = $${params.length}`;
  }

  const { rows } = await pool.query(
    `SELECT id, niche_id, source_type, source_url, title, content,
            author, score, engagement_metrics, collected_at
     FROM raw_source_data
     WHERE niche_id = $1 ${extraFilter} ${sourceFilter}
     ORDER BY id DESC
     LIMIT $2
     OFFSET $3`,
    params
  );
  return rows;
}

async function queryInsights(a: Args) {
  const niche_id = a.niche_id as number;
  const category = a.category as string | undefined;

  const { rows } = await pool.query(
    `SELECT id, niche_id, insight_type, title, summary, body,
            confidence_score, source_ids, tags, is_actionable, created_at
     FROM insights
     WHERE niche_id = $1 ${category ? 'AND insight_type = $2' : ''}
     ORDER BY confidence_score DESC NULLS LAST`,
    category ? [niche_id, category] : [niche_id]
  );
  return rows;
}

async function saveInsight(a: Args) {
  const body = a.body as string;
  const confidence_score = Math.min(
    Math.max(Number((a.confidence_score as number).toFixed(2)), 0),
    9.99
  );
  const summary = ((a.summary as string | undefined) ?? body.slice(0, 200)).slice(0, 500);

  const { rows } = await pool.query(
    `INSERT INTO insights
       (niche_id, insight_type, title, summary, body, confidence_score,
        source_ids, tags, is_actionable)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
     RETURNING id, created_at`,
    [
      a.niche_id,
      a.insight_type,
      (a.title as string).slice(0, 200),
      summary,
      body,
      confidence_score,
      JSON.stringify((a.source_ids as number[] | undefined) ?? []),
      JSON.stringify((a.tags as string[] | undefined) ?? []),
      (a.is_actionable as boolean | undefined) ?? true,
    ]
  );
  return { success: true, insight_id: rows[0].id, created_at: rows[0].created_at };
}

async function savePersona(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO customer_avatars
       (niche_id, name, avatar_type, age_range, income_range,
        psychographics, pain_points, desires, objections,
        empathy_map, buying_triggers, preferred_channels, is_primary, version)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,1)
     RETURNING id, created_at`,
    [
      a.niche_id,
      a.name,
      (a.avatar_type as string | undefined) ?? null,
      (a.age_range as string | undefined) ?? null,
      (a.income_range as string | undefined) ?? null,
      toJson(a.psychographics),
      toJson(a.pain_points),
      toJson(a.desires),
      toJson(a.objections),
      toJson(a.empathy_map),
      toJson(a.buying_triggers),
      toJson(a.preferred_channels),
      (a.is_primary as boolean | undefined) ?? false,
    ]
  );
  return { success: true, avatar_id: rows[0].id, created_at: rows[0].created_at };
}

async function getNicheConfig(a: Args) {
  const { rows } = await pool.query(
    `SELECT id, name, slug, description, status,
            data_sources, research_frequency, metadata, created_at
     FROM niches WHERE id = $1`,
    [a.niche_id]
  );
  if (rows.length === 0) throw new Error(`Niche ${a.niche_id} not found`);
  return rows[0];
}

async function expandResearch(a: Args) {
  const niche_id = a.niche_id as number;
  const gaps = a.gaps as string[];

  const { rows } = await pool.query<{ name: string }>(
    `SELECT name FROM niches WHERE id = $1`,
    [niche_id]
  );
  if (rows.length === 0) throw new Error(`Niche ${niche_id} not found`);
  const nicheName = rows[0].name;

  const searchQueries = gaps.map(gap => `${nicheName} ${gap} reviews experience`);

  return {
    status: 'ready_for_search',
    niche: nicheName,
    searchQueries,
    instruction:
      'Use web_search for each query above, then save substantive findings ' +
      'via save_insight (insight_type: competitor_gap | pain_point | buying_trigger | language_pattern) ' +
      'so the enriched data is available for persona generation.',
  };
}

async function queryPersonas(a: Args) {
  const niche_id = a.niche_id as number;
  const active = a.active as boolean | undefined;

  const primaryFilter =
    active === true  ? 'AND is_primary = true'  :
    active === false ? 'AND is_primary = false'  : '';

  const { rows } = await pool.query(
    `SELECT id, niche_id, name, avatar_type, age_range, income_range,
            psychographics, pain_points, desires, objections,
            empathy_map, buying_triggers, preferred_channels,
            is_primary, version, created_at
     FROM customer_avatars
     WHERE niche_id = $1 ${primaryFilter}
     ORDER BY is_primary DESC, created_at DESC`,
    [niche_id]
  );
  return rows;
}

async function saveSuccessStory(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO stories_library
       (niche_id, story_type, title, source_type, source_url,
        protagonist_profile, before_state, after_state,
        transformation, key_mechanism, quantified_results,
        emotional_arc, usable_hooks, verified)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
     RETURNING id, created_at`,
    [
      a.niche_id,
      (a.story_type as string | undefined) ?? 'success_story',
      a.story_title ?? a.title,
      (a.source_type as string | undefined) ?? null,
      (a.source_url as string | undefined) ?? null,
      toJson(a.protagonist_profile),
      (a.before_state as string | undefined) ?? null,
      (a.after_state as string | undefined) ?? null,
      (a.transformation as string | undefined) ?? null,
      (a.key_mechanism ?? a.method as string | undefined) ?? null,
      toJson(a.quantified_results ?? a.revenue),
      toJson(a.emotional_arc),
      toJson(a.usable_hooks ?? a.proof_links),
      (a.verified as boolean | undefined) ?? false,
    ]
  );
  return { success: true, story_id: rows[0].id, created_at: rows[0].created_at };
}

async function querySuccessStories(a: Args) {
  const niche_id = a.niche_id as number;
  const min_credibility = (a.min_credibility as number | undefined) ?? 0.5;

  const story_type = a.story_type as string | undefined;
  const params: unknown[] = [niche_id];
  let typeFilter = '';
  if (story_type) {
    params.push(story_type);
    typeFilter = ` AND story_type = $${params.length}`;
  }

  const { rows } = await pool.query(
    `SELECT id, niche_id, story_type, title, source_type, source_url,
            protagonist_profile, key_mechanism, quantified_results,
            usable_hooks, verified, created_at
     FROM stories_library
     WHERE niche_id = $1${typeFilter}
     ORDER BY created_at DESC`,
    params
  );
  return rows;
}

async function generateDisruptionReport(a: Args) {
  const niche_id = a.niche_id as number;
  const report_period = (a.report_period as string | undefined) ?? `Q2_2026_Week_${Math.ceil(Date.now() / (7*24*60*60*1000))}`;

  return {
    status: 'ready_to_generate',
    instruction: 'Use Market Strategist prompt with insights + personas + success stories',
    niche_id,
    report_period,
  };
}

async function saveMarketingCopy(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);
  const avatarId = a.target_avatar_id != null ? Number(a.target_avatar_id) : null;

  const { rows } = await pool.query(
    `INSERT INTO marketing_copy_library
       (niche_id, copy_type, copy_angle, content,
        target_avatar_id, tags)
     VALUES ($1,$2,$3,$4,$5,$6)
     RETURNING id, created_at`,
    [
      a.niche_id,
      a.copy_type,
      (a.copy_angle ?? a.emotional_trigger as string | undefined) ?? null,
      (a.content ?? a.copy_text) as string,
      avatarId,
      toJson(a.tags),
    ]
  );
  return { success: true, copy_id: rows[0].id, created_at: rows[0].created_at };
}

async function saveOffer(a: Args) {
  const pricing = a.pricing as Record<string, unknown> | undefined;
  const pricePoint = pricing?.suggestedPrice != null ? parseFloat(pricing.suggestedPrice as string) : null;
  const pricingModel = (a.pricing_model ?? pricing?.priceRationale) as string | undefined;

  const { rows } = await pool.query(
    `INSERT INTO offer_intelligence
       (niche_id, offer_name, offer_type, competitor_name,
        price_point, pricing_model, core_promise, unique_mechanism)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
     RETURNING id, created_at`,
    [
      a.niche_id,
      a.offer_name,
      (a.offer_type as string | undefined) ?? null,
      (a.competitor_name ?? a.target_avatar as string | undefined) ?? null,
      pricePoint,
      pricingModel ?? null,
      (a.core_promise ?? a.problem_solved) as string ?? null,
      (a.unique_mechanism ?? a.unique_value) as string ?? null,
    ]
  );
  return { success: true, offer_id: rows[0].id, created_at: rows[0].created_at };
}

async function saveFinancialAnalysis(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO financial_analysis
       (niche_id, tam_estimate, average_cac, average_ltv, ltv_cac_ratio,
        payback_period, churn_rate, unit_economics, analyzed_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())
     RETURNING id, analyzed_at`,
    [
      a.niche_id,
      a.tam_estimate,
      (a.average_cac as string | undefined) ?? null,
      (a.average_ltv as string | undefined) ?? null,
      (a.ltv_cac_ratio as string | undefined) ?? null,
      (a.payback_period as string | undefined) ?? null,
      (a.churn_rate as string | undefined) ?? null,
      toJson(a.unit_economics),
    ]
  );
  return { success: true, analysis_id: rows[0].id, analyzed_at: rows[0].analyzed_at };
}

async function saveCompetitorAnalysis(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO competitor_analysis
       (niche_id, competitor_name, positioning, strengths, weaknesses,
        gaps_and_opportunities, market_share_estimate, strategy, analyzed_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())
     RETURNING id, analyzed_at`,
    [
      a.niche_id,
      a.competitor_name,
      (a.positioning as string | undefined) ?? null,
      toJson(a.strengths),
      toJson(a.weaknesses),
      toJson(a.gaps_and_opportunities),
      (a.market_share_estimate as string | undefined) ?? null,
      (a.strategy as string | undefined) ?? null,
    ]
  );
  return { success: true, analysis_id: rows[0].id, analyzed_at: rows[0].analyzed_at };
}

async function saveHook(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO hooks_library
       (niche_id, hook_text, hook_type, customer_language_quote,
        target_avatar_id, source_insight_ids, usage_context,
        performance_data, tags, ai_generated, approved,
        created_at, updated_at)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW(), NOW())
     RETURNING id, created_at`,
    [
      a.niche_id,
      a.hook_text,
      a.hook_type,
      (a.customer_language_quote as string | undefined) ?? null,
      (a.target_avatar_id as number | undefined) ?? null,
      toJson(a.source_insight_ids ?? []),
      (a.usage_context as string | undefined) ?? null,
      toJson(a.performance_data),
      toJson(a.tags),
      (a.ai_generated as boolean | undefined) ?? true,
      (a.approved as boolean | undefined) ?? false,
    ]
  );
  return { success: true, hook_id: rows[0].id, created_at: rows[0].created_at };
}

async function queryHooks(a: Args) {
  const niche_id = a.niche_id as number;
  const hook_type = a.hook_type as string | undefined;
  const target_avatar_id = a.target_avatar_id as number | undefined;
  const approved = a.approved as boolean | undefined;
  const min_performance_score = a.min_performance_score as number | undefined;

  const params: unknown[] = [niche_id];
  const filters: string[] = [];

  if (hook_type) {
    params.push(hook_type);
    filters.push(`hook_type = $${params.length}`);
  }
  if (target_avatar_id != null) {
    params.push(target_avatar_id);
    filters.push(`target_avatar_id = $${params.length}`);
  }
  if (approved != null) {
    params.push(approved);
    filters.push(`approved = $${params.length}`);
  }
  if (min_performance_score != null) {
    params.push(min_performance_score);
    filters.push(`(performance_data->>'score')::numeric >= $${params.length}`);
  }

  const where = filters.length ? ' AND ' + filters.join(' AND ') : '';

  const { rows } = await pool.query(
    `SELECT id, niche_id, hook_text, hook_type, customer_language_quote,
            target_avatar_id, source_insight_ids, usage_context,
            performance_data, tags, ai_generated, approved, created_at
     FROM hooks_library
     WHERE niche_id = $1${where}
     ORDER BY created_at DESC`,
    params
  );
  return rows;
}

async function extractHooks(a: Args) {
  return runHookExtractor(pool, a.niche_id as number);
}

async function extractOffers(a: Args) {
  return runOfferExtractor(pool, a.niche_id as number);
}

async function extractStories(a: Args) {
  return runStoryExtractor(pool, a.niche_id as number);
}

async function queryAllIntelligence(a: Args) {
  const niche_id = a.niche_id as number;
  const query_type = a.query_type as string;

  const summary: Record<string, unknown> = { niche_id, query_type, available_data: {} };

  const counts = await Promise.all([
    pool.query('SELECT COUNT(*) as count FROM insights WHERE niche_id = $1', [niche_id]),
    pool.query('SELECT COUNT(*) as count FROM customer_avatars WHERE niche_id = $1', [niche_id]),
    pool.query('SELECT COUNT(*) as count FROM stories_library WHERE niche_id = $1', [niche_id]),
    pool.query('SELECT COUNT(*) as count FROM marketing_copy_library WHERE niche_id = $1', [niche_id]),
    pool.query('SELECT COUNT(*) as count FROM offer_intelligence WHERE niche_id = $1', [niche_id]),
  ]);

  summary.available_data = {
    insights: parseInt(counts[0].rows[0].count),
    personas: parseInt(counts[1].rows[0].count),
    success_stories: parseInt(counts[2].rows[0].count),
    marketing_copy: parseInt(counts[3].rows[0].count),
    offers: parseInt(counts[4].rows[0].count),
  };

  summary.instruction = 'Use specific query tools (query_insights, query_personas, etc) to fetch and synthesize data';

  return summary;
}

async function runRedditScraper(a: Args): Promise<ScriptResult> {
  return spawnScript('run_full_scrape.py', [
    '--niche-id', String(a.niche_id),
    '--limit',    String((a.limit as number | undefined) ?? 50),
    '--headless',
    '--full-content',
  ]);
}

async function runGoogleTrends(_a: Args): Promise<ScriptResult> {
  return spawnScript('google_trends_scraper.py', []);
}

async function runYoutubeScraper(a: Args): Promise<ScriptResult> {
  return spawnScript('youtube_scraper.py', [
    '--niche-id', String(a.niche_id),
    '--search',   (a.search as string | undefined) ?? 'exotic car rental',
    '--limit',    String((a.limit as number | undefined) ?? 20),
  ]);
}

async function runReviewScraper(a: Args): Promise<ScriptResult> {
  return spawnScript('review_scraper.py', [
    '--niche-id', String(a.niche_id),
    '--platform', (a.platform as string | undefined) ?? 'trustpilot',
    '--limit',    String((a.limit as number | undefined) ?? 50),
  ]);
}

async function runFacebookScraper(a: Args): Promise<ScriptResult> {
  return spawnScript('facebook_ad_scraper.py', [
    '--niche-id',    String(a.niche_id),
    '--competitors', a.competitors as string,
    '--max-ads',     String((a.max_ads as number | undefined) ?? 50),
    '--headless',
  ]);
}

async function runLandingPageScraper(a: Args): Promise<ScriptResult> {
  return spawnScript('landing_page_scraper.py', [
    '--niche-id', String(a.niche_id),
    '--limit',    String((a.limit as number | undefined) ?? 20),
  ]);
}

async function runEmailIntelligenceScraper(a: Args): Promise<ScriptResult> {
  const args = [
    '--niche-id', String(a.niche_id),
    '--limit',    String((a.limit as number | undefined) ?? 20),
    '--batch',    String((a.batch as number | undefined) ?? 5),
  ];
  if (a.headless) args.push('--headless');
  return spawnScript('email_intelligence_scraper.py', args);
}

async function runMagazineDiscoveryScraper(a: Args): Promise<ScriptResult> {
  const args = ['--niche-id', String(a.niche_id)];
  if (a.headless) args.push('--headless');
  return spawnScript('magazine_discovery_scraper.py', args);
}

async function runMetaAdsScraper(a: Args): Promise<ScriptResult> {
  return spawnScript('meta_ads_scraper.py', [
    '--type',  (a.type  as string | undefined) ?? 'all',
    '--limit', String((a.limit as number | undefined) ?? 50),
  ]);
}

async function runGoogleAdsScraper(a: Args): Promise<ScriptResult> {
  return spawnScript('google_ads_scraper.py', [
    '--type',  (a.type  as string | undefined) ?? 'all',
    '--limit', String((a.limit as number | undefined) ?? 50),
  ]);
}

async function browsePage(a: Args): Promise<ScriptResult> {
  const args = ['--url', a.url as string];
  if (a.wait_for) args.push('--wait-for', a.wait_for as string);
  return spawnScript('browser_tool.py', args);
}

async function saveAuthoritySource(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO authority_sources
       (firm_name, content_hubs, report_structure, tone_style, visual_design,
        frameworks, paid_amplification, luxury_content, raw_notes)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
     RETURNING id, created_at`,
    [
      a.firm_name,
      toJson(a.content_hubs),
      (a.report_structure as string | undefined) ?? null,
      (a.tone_style as string | undefined) ?? null,
      (a.visual_design as string | undefined) ?? null,
      toJson(a.frameworks),
      (a.paid_amplification as string | undefined) ?? null,
      (a.luxury_content as string | undefined) ?? null,
      (a.raw_notes as string | undefined) ?? null,
    ]
  );
  return { success: true, id: rows[0].id, created_at: rows[0].created_at };
}

async function saveAssociation(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO association_intelligence
       (name, acronym, website, geo_focus, vertical, citation_tier,
        public_publications, monitor_urls, citation_use, notes)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
     RETURNING id, created_at`,
    [
      a.name,
      (a.acronym as string | undefined) ?? null,
      (a.website as string | undefined) ?? null,
      (a.geo_focus as string | undefined) ?? null,
      (a.vertical as string | undefined) ?? null,
      (a.citation_tier as number | undefined) ?? null,
      toJson(a.public_publications),
      toJson(a.monitor_urls),
      (a.citation_use as string | undefined) ?? null,
      (a.notes as string | undefined) ?? null,
    ]
  );
  return { success: true, id: rows[0].id, created_at: rows[0].created_at };
}

async function saveAgencyBenchmark(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO agency_benchmarks
       (agency_name, tier, website, headline_positioning, outcome_language,
        proprietary_frameworks, pricing_signals, case_study_format, meta_ads, notes)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
     RETURNING id, created_at`,
    [
      a.agency_name,
      (a.tier as string | undefined) ?? null,
      (a.website as string | undefined) ?? null,
      (a.headline_positioning as string | undefined) ?? null,
      (a.outcome_language as string | undefined) ?? null,
      toJson(a.proprietary_frameworks),
      (a.pricing_signals as string | undefined) ?? null,
      (a.case_study_format as string | undefined) ?? null,
      toJson(a.meta_ads),
      (a.notes as string | undefined) ?? null,
    ]
  );
  return { success: true, id: rows[0].id, created_at: rows[0].created_at };
}

async function runApexPositioning() {
  return runApexPositioningBrain(pool);
}

async function runClientIntelligence(a: Args) {
  return runClientIntelligenceBrain(
    pool,
    a.niche_id as number,
    a.client_name as string | undefined,
    a.city        as string | undefined,
    (a.report_type as string | undefined) ?? 'state_of_market',
  );
}

async function runResearchAnalyst(a: Args) {
  return runResearchAnalystBrain(pool, a.niche_id as number);
}

async function runCompetitiveIntelligence(a: Args) {
  return competitiveIntelligenceTool.handler({ nicheId: a.niche_id as number });
}

async function runConversationalAssistant(a: Args) {
  return conversationalAssistantTool.handler({
    nicheId: a.niche_id as number,
    queryType: a.query_type as string,
  });
}

async function runCopywriter(a: Args) {
  return copywriterTool.handler({ nicheId: a.niche_id as number });
}

async function runFinancialAnalyst(a: Args) {
  return financialAnalystTool.handler({ nicheId: a.niche_id as number });
}

async function runOfferDesigner(a: Args) {
  return offerDesignerTool.handler({ nicheId: a.niche_id as number });
}

async function runPersonaArchitect(a: Args) {
  return personaArchitectTool.handler({ nicheId: a.niche_id as number });
}

async function saveApexPositioningBrief(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO apex_positioning_briefs
       (version, current_positioning, positioning_gaps, positioning_strengths,
        positioning_opportunities, agency_comparisons, consulting_firm_comparisons,
        methodology_recommendations, pricing_recommendations, packaging_recommendations,
        proposal_language, citation_recommendations, report_format, tone_guidelines,
        citation_style, framework_naming, visual_guidelines, raw_analysis)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
     RETURNING id, created_at`,
    [
      (a.version                     as string | undefined) ?? null,
      a.current_positioning          as string,
      toJson(a.positioning_gaps),
      toJson(a.positioning_strengths),
      toJson(a.positioning_opportunities),
      toJson(a.agency_comparisons),
      toJson(a.consulting_firm_comparisons),
      (a.methodology_recommendations as string | undefined) ?? null,
      (a.pricing_recommendations     as string | undefined) ?? null,
      (a.packaging_recommendations   as string | undefined) ?? null,
      toJson(a.proposal_language),
      toJson(a.citation_recommendations),
      (a.report_format               as string | undefined) ?? null,
      (a.tone_guidelines             as string | undefined) ?? null,
      (a.citation_style              as string | undefined) ?? null,
      toJson(a.framework_naming),
      (a.visual_guidelines           as string | undefined) ?? null,
      (a.raw_analysis                as string | undefined) ?? null,
    ]
  );
  return { success: true, id: rows[0].id, created_at: rows[0].created_at };
}

async function saveClientIntelligenceReport(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO client_intelligence_reports
       (niche_id, client_name, city, report_type, report_period,
        positioning_brief_id, executive_summary, market_overview,
        uhnw_persona_profiles, seasonality_data, competitor_ad_intelligence,
        hooks_and_offers, citations, recommendations, full_report)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
     RETURNING id, created_at`,
    [
      a.niche_id,
      (a.client_name             as string | undefined) ?? null,
      (a.city                    as string | undefined) ?? null,
      a.report_type              as string,
      (a.report_period           as string | undefined) ?? null,
      (a.positioning_brief_id    as number | undefined) ?? null,
      (a.executive_summary       as string | undefined) ?? null,
      (a.market_overview         as string | undefined) ?? null,
      toJson(a.uhnw_persona_profiles),
      toJson(a.seasonality_data),
      toJson(a.competitor_ad_intelligence),
      toJson(a.hooks_and_offers),
      toJson(a.citations),
      toJson(a.recommendations),
      (a.full_report             as string | undefined) ?? null,
    ]
  );
  return { success: true, id: rows[0].id, created_at: rows[0].created_at };
}

// ─── MCP Server ────────────────────────────────────────────────────────────────

const server = new Server(
  { name: 'niche-intelligence', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const a = (args ?? {}) as Args;

  try {
    let result: unknown;
    switch (name) {
      case 'query_raw_posts':      result = await queryRawPosts(a);      break;
      case 'query_insights':       result = await queryInsights(a);      break;
      case 'save_insight':         result = await saveInsight(a);        break;
      case 'save_persona':         result = await savePersona(a);        break;
      case 'get_niche_config':     result = await getNicheConfig(a);     break;
      case 'query_personas':       result = await queryPersonas(a);      break;
      case 'expand_research':      result = await expandResearch(a);     break;
      case 'save_success_story':   result = await saveSuccessStory(a);   break;
      case 'query_success_stories': result = await querySuccessStories(a); break;
      case 'generate_disruption_report': result = await generateDisruptionReport(a); break;
      case 'save_disruption_report':     result = await saveDisruptionReport(a);     break;
      case 'save_marketing_copy':        result = await saveMarketingCopy(a);        break;
      case 'save_offer':                 result = await saveOffer(a);                break;
      case 'save_financial_analysis':    result = await saveFinancialAnalysis(a);    break;
      case 'save_competitor_analysis':   result = await saveCompetitorAnalysis(a);   break;
      case 'extract_hooks':               result = await extractHooks(a);             break;
      case 'extract_stories':             result = await extractStories(a);           break;
      case 'extract_offers':              result = await extractOffers(a);            break;
      case 'save_hook':                   result = await saveHook(a);                 break;
      case 'query_hooks':                 result = await queryHooks(a);               break;
      case 'query_all_intelligence':      result = await queryAllIntelligence(a);     break;
      case 'run_reddit_scraper':          result = await runRedditScraper(a);         break;
      case 'run_google_trends':           result = await runGoogleTrends(a);          break;
      case 'run_youtube_scraper':         result = await runYoutubeScraper(a);        break;
      case 'run_review_scraper':          result = await runReviewScraper(a);         break;
      case 'run_facebook_scraper':        result = await runFacebookScraper(a);       break;
      case 'run_landing_page_scraper':    result = await runLandingPageScraper(a);    break;
      case 'seed_newsletter_urls':        result = await seedNewsletterUrls(a);       break;
      case 'run_email_intelligence_scraper': result = await runEmailIntelligenceScraper(a); break;
      case 'run_magazine_discovery_scraper': result = await runMagazineDiscoveryScraper(a); break;
      case 'run_meta_ads_scraper':        result = await runMetaAdsScraper(a);        break;
      case 'run_google_ads_scraper':      result = await runGoogleAdsScraper(a);      break;
      case 'browse_page':                 result = await browsePage(a);               break;
      case 'save_authority_source':            result = await saveAuthoritySource(a);           break;
      case 'save_association':                result = await saveAssociation(a);               break;
      case 'save_agency_benchmark':           result = await saveAgencyBenchmark(a);           break;
      case 'run_apex_positioning_brain':      result = await runApexPositioning();             break;
      case 'run_client_intelligence_brain':   result = await runClientIntelligence(a);         break;
      case 'run_research_analyst':            result = await runResearchAnalyst(a);            break;
      case 'competitive_intelligence':        result = await runCompetitiveIntelligence(a);    break;
      case 'conversational_assistant':        result = await runConversationalAssistant(a);    break;
      case 'copywriter':                      result = await runCopywriter(a);                 break;
      case 'financial_analyst':               result = await runFinancialAnalyst(a);           break;
      case 'offer_designer':                  result = await runOfferDesigner(a);              break;
      case 'persona_architect':               result = await runPersonaArchitect(a);           break;
      case 'save_apex_positioning_brief':     result = await saveApexPositioningBrief(a);      break;
      case 'save_client_intelligence_report': result = await saveClientIntelligenceReport(a);  break;
      default:
        return {
          content: [{ type: 'text', text: `Unknown tool: ${name}` }],
          isError: true,
        };
    }
    return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
  } catch (err) {
    return {
      content: [{ type: 'text', text: `Error: ${err}` }],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
console.error(`Niche Intelligence MCP v1.0.0 — ${TOOLS.length} tools registered`);
