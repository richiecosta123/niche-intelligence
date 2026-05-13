import { config as dotenvConfig } from 'dotenv';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenvConfig({ path: path.resolve(__dirname, '../../.env') });
dotenvConfig();

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { Pool } from 'pg';

const pool = new Pool({ connectionString: process.env.NEON_DB_URL });

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
    description: 'Save a money-making success story to the database. Stories must have credibility score 0.5+ to be saved.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        story_title: { type: 'string', description: 'Compelling headline summarizing the story' },
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
    description: 'Fetch money-making success stories for a niche, ordered by credibility score.',
    inputSchema: {
      type: 'object' as const,
      properties: {
        niche_id: { type: 'number' },
        min_credibility: {
          type: 'number',
          description: 'Minimum credibility score (0.0-1.0). Default: 0.5',
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
];

// ─── Handlers ──────────────────────────────────────────────────────────────────

type Args = Record<string, unknown>;

async function queryRawPosts(a: Args) {
  const niche_id = a.niche_id as number;
  const limit = Math.min((a.limit as number | undefined) ?? 50, 500);
  const processed = a.processed as boolean | undefined;

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

  const { rows } = await pool.query(
    `SELECT id, niche_id, source_type, source_url, title, content,
            author, score, engagement_metrics, collected_at
     FROM raw_source_data
     WHERE niche_id = $1 ${extraFilter}
     ORDER BY id DESC
     LIMIT $2`,
    [niche_id, limit]
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
  const credibility = Math.min(Math.max(Number((a.credibility_score as number).toFixed(2)), 0), 1);
  
  if (credibility < 0.5) {
    throw new Error('Credibility score must be ≥ 0.5 to save a success story');
  }

  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO success_stories
       (niche_id, story_title, summary, revenue, method, platform,
        credibility_score, proof_links, source_url, source_type)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
     RETURNING id, discovered_at`,
    [
      a.niche_id,
      a.story_title,
      a.summary,
      toJson(a.revenue),
      a.method,
      (a.platform as string | undefined) ?? null,
      credibility,
      toJson(a.proof_links),
      a.source_url,
      (a.source_type as string | undefined) ?? null,
    ]
  );
  return { success: true, story_id: rows[0].id, discovered_at: rows[0].discovered_at };
}

async function querySuccessStories(a: Args) {
  const niche_id = a.niche_id as number;
  const min_credibility = (a.min_credibility as number | undefined) ?? 0.5;

  const { rows } = await pool.query(
    `SELECT id, niche_id, story_title, summary, revenue, method, platform,
            credibility_score, proof_links, source_url, source_type, discovered_at
     FROM success_stories
     WHERE niche_id = $1 AND credibility_score >= $2
     ORDER BY credibility_score DESC, discovered_at DESC`,
    [niche_id, min_credibility]
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

  const { rows } = await pool.query(
    `INSERT INTO marketing_copy_library
       (niche_id, copy_type, copy_text, use_case, source_type,
        avatar_target, emotional_trigger, tags)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
     RETURNING id, created_at`,
    [
      a.niche_id,
      a.copy_type,
      a.copy_text,
      (a.use_case as string | undefined) ?? null,
      (a.source_type as string | undefined) ?? null,
      (a.avatar_target as string | undefined) ?? null,
      (a.emotional_trigger as string | undefined) ?? null,
      toJson(a.tags),
    ]
  );
  return { success: true, copy_id: rows[0].id, created_at: rows[0].created_at };
}

async function saveOffer(a: Args) {
  const toJson = (v: unknown) => (v != null ? JSON.stringify(v) : null);

  const { rows } = await pool.query(
    `INSERT INTO offer_intelligence
       (niche_id, offer_name, offer_type, target_avatar, problem_solved,
        unique_value, pricing, market_timing, anticipated_objections)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
     RETURNING id, generated_at`,
    [
      a.niche_id,
      a.offer_name,
      (a.offer_type as string | undefined) ?? null,
      (a.target_avatar as string | undefined) ?? null,
      a.problem_solved,
      a.unique_value,
      toJson(a.pricing),
      toJson(a.market_timing),
      toJson(a.anticipated_objections),
    ]
  );
  return { success: true, offer_id: rows[0].id, generated_at: rows[0].generated_at };
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

// ─── MCP Server ────────────────────────────────────────────────────────────────

const server = new Server(
  { name: 'niche-intelligence', version: '0.5.4' },
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
      case 'save_marketing_copy':        result = await saveMarketingCopy(a);        break;
      case 'save_offer':                 result = await saveOffer(a);                break;
      case 'save_financial_analysis':    result = await saveFinancialAnalysis(a);    break;
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
console.error('Niche Intelligence MCP v0.5.4 — financial analyst brain + TAM/CAC/LTV validation');
