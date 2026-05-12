/**
 * CLI test tool for Niche Intelligence MCP data access tools.
 *
 * Usage:
 *   node build/test-tools.js <tool_name> [options]
 *
 * Examples:
 *   node build/test-tools.js query_insights --niche-id 2
 *   node build/test-tools.js query_insights --niche-id 2 --category pain_point
 *   node build/test-tools.js query_raw_posts --niche-id 2 --limit 5
 *   node build/test-tools.js query_raw_posts --niche-id 2 --limit 10 --processed false
 *   node build/test-tools.js get_niche_config --niche-id 2
 *   node build/test-tools.js query_personas --niche-id 2
 *   node build/test-tools.js save_insight --niche-id 2 --type pain_point --title "Test" --body "Test body" --score 0.5
 *   node build/test-tools.js save_persona --niche-id 2 --name "The Test Persona"
 */

import { config as dotenvConfig } from 'dotenv';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenvConfig({ path: path.resolve(__dirname, '../../.env') });
dotenvConfig();

import { Pool } from 'pg';

const pool = new Pool({ connectionString: process.env.NEON_DB_URL });

// ─── Arg parsing ───────────────────────────────────────────────────────────────

function parseArgs(): { tool: string; flags: Record<string, string> } {
  const argv = process.argv.slice(2);
  const tool = argv[0] ?? '';
  const flags: Record<string, string> = {};
  for (let i = 1; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const next = argv[i + 1];
      flags[key] = (!next || next.startsWith('--')) ? 'true' : (i++, next);
    }
  }
  return { tool, flags };
}

function get(flags: Record<string, string>, ...keys: string[]): string | undefined {
  for (const k of keys) {
    if (flags[k] !== undefined) return flags[k];
    if (flags[k.replace(/-/g, '_')] !== undefined) return flags[k.replace(/-/g, '_')];
  }
  return undefined;
}
const num = (v: string | undefined, def?: number) => v !== undefined ? Number(v) : def;
const bool = (v: string | undefined): boolean | undefined =>
  v === undefined ? undefined : v === 'true';

// ─── Main ──────────────────────────────────────────────────────────────────────

const { tool, flags } = parseArgs();
const niche_id = num(get(flags, 'niche-id', 'niche_id'), 2)!;

async function run() {
  switch (tool) {

    case 'query_raw_posts': {
      const limit = num(get(flags, 'limit'), 10)!;
      const processed = bool(get(flags, 'processed'));
      let extraFilter = '';
      if (processed !== undefined) {
        try {
          const { rows } = await pool.query<{ max_id: number }>(
            `SELECT COALESCE(MAX((result->>'max_id_processed')::int), 0) AS max_id
             FROM research_jobs WHERE niche_id = $1 AND status = 'completed'`,
            [niche_id]
          );
          const maxId = rows[0]?.max_id ?? 0;
          if (maxId > 0) extraFilter = processed ? `AND id <= ${maxId}` : `AND id > ${maxId}`;
        } catch { /* skip filter */ }
      }
      const { rows } = await pool.query(
        `SELECT id, source_type, title, author, score, collected_at
         FROM raw_source_data WHERE niche_id = $1 ${extraFilter}
         ORDER BY id DESC LIMIT $2`,
        [niche_id, limit]
      );
      console.log(JSON.stringify(rows, null, 2));
      break;
    }

    case 'query_insights': {
      const category = get(flags, 'category');
      const { rows } = await pool.query(
        `SELECT id, insight_type, title, summary, confidence_score, is_actionable, created_at
         FROM insights WHERE niche_id = $1 ${category ? 'AND insight_type = $2' : ''}
         ORDER BY confidence_score DESC NULLS LAST`,
        category ? [niche_id, category] : [niche_id]
      );
      console.log(JSON.stringify(rows, null, 2));
      break;
    }

    case 'save_insight': {
      const insight_type = get(flags, 'type') ?? 'pain_point';
      const title = get(flags, 'title') ?? 'Test Insight';
      const body = get(flags, 'body') ?? 'Test insight body text.';
      const confidence_score = num(get(flags, 'score'), 0.5)!;
      const summary = body.slice(0, 200);
      const { rows } = await pool.query(
        `INSERT INTO insights
           (niche_id, insight_type, title, summary, body, confidence_score, source_ids, tags, is_actionable)
         VALUES ($1,$2,$3,$4,$5,$6,'[]','[]',true)
         RETURNING id, created_at`,
        [niche_id, insight_type, title.slice(0, 200), summary, body, confidence_score]
      );
      console.log(JSON.stringify({ success: true, insight_id: rows[0].id, created_at: rows[0].created_at }, null, 2));
      break;
    }

    case 'save_persona': {
      const name = get(flags, 'name') ?? 'Test Persona';
      const { rows } = await pool.query(
        `INSERT INTO customer_avatars (niche_id, name, is_primary, version)
         VALUES ($1,$2,false,1) RETURNING id, created_at`,
        [niche_id, name]
      );
      console.log(JSON.stringify({ success: true, avatar_id: rows[0].id, created_at: rows[0].created_at }, null, 2));
      break;
    }

    case 'get_niche_config': {
      const { rows } = await pool.query(
        `SELECT id, name, slug, description, status, data_sources, research_frequency, metadata
         FROM niches WHERE id = $1`,
        [niche_id]
      );
      if (rows.length === 0) throw new Error(`Niche ${niche_id} not found`);
      console.log(JSON.stringify(rows[0], null, 2));
      break;
    }

    case 'query_personas': {
      const active = bool(get(flags, 'active'));
      const primaryFilter =
        active === true  ? 'AND is_primary = true'  :
        active === false ? 'AND is_primary = false'  : '';
      const { rows } = await pool.query(
        `SELECT id, name, avatar_type, age_range, income_range, is_primary, version, created_at
         FROM customer_avatars WHERE niche_id = $1 ${primaryFilter}
         ORDER BY is_primary DESC, created_at DESC`,
        [niche_id]
      );
      console.log(JSON.stringify(rows, null, 2));
      break;
    }

    default: {
      console.error(`Unknown tool: "${tool}"\n`);
      console.error('Available tools:');
      console.error('  query_raw_posts    --niche-id <n> [--limit <n>] [--processed true|false]');
      console.error('  query_insights     --niche-id <n> [--category <type>]');
      console.error('  save_insight       --niche-id <n> --type <type> --title <t> --body <b> --score <0-1>');
      console.error('  save_persona       --niche-id <n> --name <name>');
      console.error('  get_niche_config   --niche-id <n>');
      console.error('  query_personas     --niche-id <n> [--active true|false]');
      process.exit(1);
    }
  }
}

run()
  .catch(e => { console.error('Error:', e.message); process.exit(1); })
  .finally(() => pool.end());
