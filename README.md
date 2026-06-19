# Niche Intelligence Platform

A market-research pipeline: Python scrapers pull data (Reddit, YouTube, reviews, ad libraries, forums, trade press, Google Trends) into Postgres, and a single MCP server exposes that data — plus a set of "brain" tools — to Claude Desktop (or any MCP client) for analysis and synthesis.

This README describes what is actually in this repository today, verified by reading every scraper, the MCP server source, every brain module, and the schema/migration files. Where the code disagrees with older docs in this repo, the code wins and the doc is flagged as stale below.

---

## Current status

- **One niche is actually populated with data: Exotic Car Rental (`niche_id = 1`).** A second niche, Chauffeur Services (`niche_id = 2`), has a config row and keyword notes but no evidence of scraped data.
- **17 Python scrapers**, all runnable standalone from the repo root. All are individually functional (error handling, dedup, anti-detection delays); none have automated tests.
- **One MCP server** (`mcp-server/`), a single `src/index.ts`, registering **46 tools**. Most are direct Postgres reads/writes; 11 spawn one of the Python scrapers as a subprocess; 11 are "brain" orchestration tools.
- **14 "brain" modules** exist in `mcp-server/src/brains/`. **11 are wired into the MCP server** and reachable as tools (5 query the DB themselves and bundle real rows into their response; 6 just return a system prompt + instructions telling the calling Claude which `query_*`/`save_*` tools to use itself). **1 more (`market-strategist.ts`) is partially wired** — only its `saveDisruptionReport()` helper is imported; its own data-gathering tool is reimplemented inline in `index.ts` instead. **1 is only reachable through a separate, unrelated CLI script** (`run.ts`), not through the MCP server, and **1 is an explicit stub**. See [Brains](#brains) below for the exact breakdown.
- **No brain calls an LLM.** `@anthropic-ai/sdk` is a declared dependency in `mcp-server/package.json` but is never imported or invoked anywhere in the codebase. Every brain tool just gathers rows from Postgres (or doesn't) and returns a system prompt + a `saveSchema`; the actual reasoning is done by whatever Claude session called the tool, which is then expected to call the matching `save_*` tool with its output.
- **The database schema is in drift.** The only committed migration (`migrate.ts`) creates 18 tables. But `index.ts` and two brains (`apex-positioning.ts`, `client-intelligence.ts`) read and write **9 additional tables** — `authority_sources`, `association_intelligence`, `agency_benchmarks`, `hooks_library`, `stories_library`, `apex_positioning_briefs`, `client_intelligence_reports`, `financial_analysis`, `competitor_analysis` — that no committed script creates. These exist only in whatever live Neon database someone has set up by hand. **A fresh clone + `npm run migrate` will not have working tables for roughly a third of the 46 MCP tools.** Details in [Database](#database).
- Older docs in this repo — the previous `README.md`, `CHANGELOG.md`, `build-roadmap.md`, `STATUS_REPORT_v0_1_0.md`, `testing-checklist.md`, `PHASE_1_WEEK_2_COMPLETE.md` — describe a snapshot from ~May 2026 (v0.1–v0.3, 2 brains, 17 tables, single Reddit scraper). The code has moved well past that. See [Stale docs](#stale-docs-in-this-repo).

---

## How the pipeline actually works

1. **A niche is a row in the `niches` table.** Niche 1 (exotic-car-rental) was created by `seed-exotic-car-niche.ts`. Niche 2 (chauffeur-services) was created by manually running `add-chauffeur-niche.sql`. Per-niche keyword lists and source notes also live as static files in `niches/<slug>/keywords.md` and `niches/<slug>/data-sources.json` — these are reference notes for a human running scrapers; no code reads them.
2. **Data collection** happens by running a Python scraper directly from the repo root (e.g. `python3 reddit_browser_scraper.py --niche-id 1`), or by asking Claude (connected to the MCP server) to call one of the `run_*_scraper` tools, which spawns the identical script as a subprocess with a 5-minute timeout and returns its stdout/stderr.
3. Most scrapers write into `raw_source_data`, tagged by `source_type` (`reddit`, `youtube`, `google_news`, `google_trends`, `trustpilot`, `yelp`, `forum_fastlane`, `forum_warrior`, `forum_ferrarichat`, `landing_page`, `newsletter_pending` / `newsletter` / `newsletter_failed`, `landing_page_url_candidate`). The Facebook ad scraper writes into `competitor_ad_data` instead. The Meta and Google ad-library scrapers update `agency_benchmarks.meta_ads` / `authority_sources.paid_amplification` directly.
4. Two scrapers are two-stage pipelines: `magazine_discovery_scraper.py` finds candidate article URLs on trade-press sites and inserts them as `source_type='newsletter_pending'`; `email_intelligence_scraper.py` later visits those same URLs and flips each row to `'newsletter'` (success, with extracted body text) or `'newsletter_failed'`.
5. Once raw data exists, Claude can call one of the 11 wired brain tools. Five of them (`extract_hooks`, `extract_offers`, `extract_stories`, `run_apex_positioning_brain`, `run_client_intelligence_brain`) query the DB themselves and hand back real rows plus a prompt. The other six (`competitive_intelligence`, `conversational_assistant`, `copywriter`, `financial_analyst`, `offer_designer`, `persona_architect`) don't query anything — they hand back a system prompt and an instruction telling the calling Claude which `query_*` tools to call itself first. Either way, there is no automatic save step: the calling Claude session does the actual analysis and is expected to call the matching `save_*` tool with the result.
6. Every output type also has a direct `save_*` tool (for manually-entered or web-search-derived intelligence) and a matching `query_*` tool to read it back.

---

## Repository structure (actual)

Everything is flat at the repo root — there is no `scrapers/`, `schema/`, `docs/`, or `prompts/` subfolder, despite what older docs describe.

```
niche-intelligence/
├── README.md                        # this file
├── CHANGELOG.md, build-roadmap.md, brain-prompts.md,
│   testing-checklist.md, GITHUB_UPLOAD_CHECKLIST.md,
│   STATUS_REPORT_v0_1_0.md, PHASE_1_WEEK_2_COMPLETE.md,
│   SCHEMA.md                        # legacy docs — see "Stale docs" below
│
├── package.json, package-lock.json, tsconfig.json   # root Node project: DB tooling only
├── .env / .env.example, .gitignore, requirements.txt
│
├── schema.ts                        # Drizzle schema, 18 tables — matches migrate.ts (live)
├── niche-intel-schema.ts            # second Drizzle schema, 17 tables, camelCase, renamed/typed differently — not what migrate.ts runs, not applied anywhere
├── migrate.ts                       # drops + recreates the 18 tables from schema.ts ("npm run migrate")
├── test-db.ts                       # checks those 18 tables exist ("npm run test-db")
├── seed-exotic-car-niche.ts         # inserts the exotic-car-rental niche row ("npm run seed")
├── add-chauffeur-niche.sql          # raw SQL to insert the chauffeur-services niche — run manually via psql, no npm script
├── mcp-skill-template.ts            # boilerplate reference for writing a new brain — not executed by anything
│
├── browser_tool.py                  # generic Playwright "fetch any URL" helper, used by the browse_page MCP tool
├── check_library.py, test_transcript.py   # throwaway scripts to sanity-check youtube_transcript_api — not part of the pipeline
├── run_full_scrape.py               # orchestrator — loops 5 hardcoded keywords through reddit_browser_scraper.py
├── *_scraper.py, forum_discovery.py # the 14 remaining scrapers — see Python scrapers section
│
├── niches/
│   ├── exotic-car-rental/{keywords.md, data-sources.json}     # static reference notes, not read by code
│   └── chauffeur-services/{keywords.md, data-sources.json}
│
└── mcp-server/
    ├── package.json, tsconfig.json
    ├── EXAMPLE_OUTPUT.md            # shows fabricated output for the research_analyst brain, which is actually a stub — do not trust this file
    ├── build/                       # compiled JS from `npm run build` (gitignored)
    └── src/
        ├── index.ts                 # the entire MCP server: all 46 tool definitions + handlers, one file
        ├── run.ts                   # tiny separate CLI (`npx tsx src/run.ts <brain_name> --niche-id <id>`); only wires up research_analyst (stub) and success_story_hunter — not used by the MCP server
        ├── test-tools.ts            # CLI for exercising MCP tools directly without an MCP client
        └── brains/
            ├── *.ts                 # 14 brain modules — see Brains section for which are reachable
            └── prompts/*.md         # system-prompt text, loaded by 11 of the 14 brains
```

---

## Environment variables

Actually read by code:

| Variable | Used by | Notes |
|---|---|---|
| `NEON_DB_URL` | every TS entry point and every Python scraper | Postgres (Neon) connection string. The only variable required to run anything. |
| `YOUTUBE_API_KEY` | `youtube_scraper.py` | YouTube Data API v3, for search/video metadata. Transcripts come from `yt-dlp`, not this key. |
| `ANTHROPIC_API_KEY` | loaded via `dotenv` in `mcp-skill-template.ts` and the MCP server's env setup | **Never actually used** — no code anywhere calls the Anthropic SDK or any Claude API endpoint. Safe to leave unset. |

Declared in `.env.example` but referenced by no code in the repo: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` (Reddit scraping is done by driving a real browser with Playwright, not the Reddit API), `ADBEAT_API_KEY`, `GOOGLE_SEARCH_CONSOLE_CLIENT_ID`, `GOOGLE_SEARCH_CONSOLE_CLIENT_SECRET`.

The MCP server loads env vars from the **repo-root `.env`** (`dotenvConfig({ path: '../../.env' })` relative to `mcp-server/src/`) — there is no separate `mcp-server/.env`.

---

## Database

### Setup
```bash
npm install
cp .env.example .env        # fill in NEON_DB_URL at minimum
npm run migrate              # DROP CASCADE + recreate 18 tables from schema.ts
npm run seed                 # inserts the exotic-car-rental niche (id 1)
npm run test-db               # confirms those 18 tables exist
```

`migrate.ts` is a destructive reset, not a versioned migration system: it drops every table with `CASCADE` and recreates them from hand-written `CREATE TABLE` statements. Running it again wipes all data.

### Tables `npm run migrate` actually creates (18)
`niches`, `research_jobs`, `raw_source_data`, `insights`, `customer_avatars`, `avatar_generation_jobs`, `success_stories`, `offer_intelligence`, `marketing_copy_library`, `opportunities`, `disruption_reports`, `quarterly_industry_reports`, `share_links`, `brain_dependencies`, `trend_data`, `search_term_data`, `competitor_ad_data`, `youtube_channels`.

### Tables the code requires that no committed script creates
`authority_sources`, `association_intelligence`, `agency_benchmarks`, `hooks_library`, `stories_library`, `apex_positioning_briefs`, `client_intelligence_reports`, `financial_analysis`, `competitor_analysis`.

These are read/written directly in `mcp-server/src/index.ts` (`save_hook`/`query_hooks`, `save_authority_source`, `save_association`, `save_agency_benchmark`, `save_apex_positioning_brief`, `save_client_intelligence_report`, `save_financial_analysis`, `save_competitor_analysis`, `save_success_story`/`query_success_stories`) and by `apex-positioning.ts` / `client-intelligence.ts`. They presumably exist in whoever's live Neon instance this was last run against, created by hand. `SCHEMA.md` documents most of them as part of a "Hook-Story-Offer Framework" reorg, but that document was never turned into an actual migration — `schema.ts`, `niche-intel-schema.ts`, and `migrate.ts` all predate it.

Note also `success_stories` (created by `migrate.ts`) and `stories_library` (what the live code actually queries) are two different table names for what looks like the same concept — further evidence the committed schema and the live database have diverged.

**If you're setting this up from scratch**, plan to write `CREATE TABLE` statements for the 9 missing tables yourself. Cross-check `SCHEMA.md`'s column descriptions against actual usage in `index.ts` (search for `INSERT INTO`/`UPDATE` on each table name) before trusting it exactly, since the doc may have drifted too.

---

## Python scrapers

All live at the repo root. All connect to Postgres with `psycopg2`/`NEON_DB_URL` (except `forum_discovery.py`, which only writes a local JSON file, and `browser_tool.py`, `check_library.py`, `test_transcript.py`, which don't touch the DB). Most use Playwright; `news_scraper.py` uses RSS; `youtube_scraper.py` uses the YouTube Data API + `yt-dlp`.

#### `news_scraper.py`
- **Does:** Pulls articles from the Google News RSS feed for a search query.
- **Run:** `python3 news_scraper.py --niche-id 1 --query "exotic car rental" --limit 20`
- **Flags:** `--niche-id` (int, default 1), `--query` (str, default `"exotic car rental"`), `--limit` (int, default 20)
- **Writes to:** `raw_source_data` (`source_type='google_news'`); dedupes on `source_url`.

#### `reddit_browser_scraper.py`
- **Does:** Drives old.reddit.com with Playwright, searching a keyword across 4 sort orders (relevance/top/new/comments) to collect up to `--limit` unique posts; optionally visits each post for full body + top 20 comments.
- **Run:** `python3 reddit_browser_scraper.py --keywords "exotic car rental" --limit 50 --full-content --niche-id 1`
- **Flags:** `--keywords` (str, default `"exotic car rental"`), `--limit` (int, default 50), `--full-content` (flag), `--headless` (str `"true"`/`"false"`, default true), `--slow-mo` (int ms, default 100), `--niche-id` (int, default 2), `--dry-run` (flag, no DB writes)
- **Writes to:** `raw_source_data` (`source_type='reddit'`); dedupes on `source_id` (post id).

#### `run_full_scrape.py`
- **Does:** Orchestrator — calls `reddit_browser_scraper.py`'s `scrape_reddit()` once per keyword in a hardcoded 5-keyword list (`exotic car rental`, `supercar rental`, `Turo exotic car`, `luxury car business`, `exotic car insurance`), with a 5s pause between keywords. Despite the name, it only drives the Reddit scraper.
- **Run:** `python3 run_full_scrape.py --niche-id 1 --limit 50 --full-content --headless`
- **Flags:** `--niche-id` (int, required), `--keywords-list` (space-separated str list, overrides the default 5), `--limit` (int, default 50, per keyword), `--full-content` (flag), `--headless` (flag), `--slow-mo` (int, default 100), `--dry-run` (flag)
- **Writes to:** same as `reddit_browser_scraper.py`.

#### `review_scraper.py`
- **Does:** Scrapes Trustpilot reviews of Turo and Yelp reviews of "exotic car rental" businesses in 4 hardcoded US cities (LA, Miami, Las Vegas, NYC).
- **Run:** `python3 review_scraper.py --niche-id 1 --platform all --limit 50`
- **Flags:** `--niche-id` (int, default 1), `--platform` (choice: `trustpilot`/`yelp`/`all`, default `all`), `--limit` (int, default 50)
- **Writes to:** `raw_source_data` (`source_type='trustpilot'` or `'yelp'`). Saves error screenshots to `/tmp/review_scraper_error_*.png` on failure.

#### `youtube_scraper.py`
- **Does:** Searches/scrapes YouTube video metadata, transcripts (via `yt-dlp`), and comments (via YouTube Data API v3). Also supports a standalone channel-quality analysis mode that scores a channel 0–100 and assigns a tier.
- **Run:** `python3 youtube_scraper.py --niche-id 1 --search "exotic car" --limit 20` or `python3 youtube_scraper.py --analyze-channel "ChannelName"`
- **Flags:** `--niche-id` (int, required for scraping), `--search` (str), `--channel` (str), `--limit` (int, default 20), `--no-comments` (flag), `--analyze-channel` (str, standalone mode)
- **Writes to:** `raw_source_data` (`source_type='youtube'`) for scraping; `youtube_channels` for `--analyze-channel` runs.

#### `google_trends_scraper.py`
- **Does:** Pulls Google Trends interest-over-time, related queries, and US regional interest for **9 hardcoded exotic-car-rental keywords**. Takes no arguments at all.
- **Run:** `python3 google_trends_scraper.py`
- **Flags:** none. `NICHE_ID` is hardcoded to `1` in the script — the `niche_id` parameter on the corresponding MCP tool (`run_google_trends`) is accepted but has no effect on what the script actually does.
- **Writes to:** `raw_source_data` (`source_type='google_trends'`), 3 rows per keyword (one each for interest-over-time, related queries, regional interest). Has retry/backoff and a post-run DB verification query.

#### `forum_scraper.py`
- **Does:** Scrapes 3 hardcoded forums — Fastlane Forum, Warrior Forum, FerrariChat — using hardcoded search queries, with dual extraction strategies per forum (XenForo-specific + generic vBulletin fallback).
- **Run:** `python3 forum_scraper.py --niche-id 1 --forum all --limit 20`
- **Flags:** `--niche-id` (int, default 1), `--forum` (choice: `fastlane`/`warrior`/`ferrarichat`/`all`, default `all`), `--limit` (int, default 20, per forum)
- **Writes to:** `raw_source_data` (`source_type='forum_fastlane'`/`'forum_warrior'`/`'forum_ferrarichat'`); dedupes on `source_url`. Saves error screenshots to `/tmp/forum_scraper_error_*.png`.

#### `forum_discovery.py`
- **Does:** Google-searches a keyword to find candidate forums, visits each, counts on-forum search hits, and classifies activity level (HIGH/MEDIUM/LOW). Discovery only — does not scrape thread content.
- **Run:** `python3 forum_discovery.py --keyword "exotic car rental" --min-results 10`
- **Flags:** `--keyword` (str, required), `--min-results` (int, default 5)
- **Writes to:** **nothing in the DB.** Writes a local JSON report (`forum_discovery_{keyword}_{timestamp}.json`) — the output is meant to be read by a human, who then hardcodes any new forums into `forum_scraper.py`.

#### `facebook_ad_scraper.py`
- **Does:** Searches the Facebook Ad Library for one or more named competitors and extracts their active/inactive ads.
- **Run:** `python3 facebook_ad_scraper.py --niche-id 1 --competitors "Hertz Dream Cars,Gotham Dream Cars" --max-ads 50`
- **Flags:** `--niche-id` (int, required), `--competitor` (single name) or `--competitors` (comma-separated), `--country` (str, default `US`), `--max-ads` (int, default 50), `--headless` (flag)
- **Writes to:** `competitor_ad_data` (`platform='facebook'`); upserts on `(niche_id, ad_id)`, refreshing `last_seen_at` on repeat sightings.

#### `meta_ads_scraper.py`
- **Does:** Same Ad Library, but targets rows already in `agency_benchmarks` / `authority_sources` by name (rather than niche competitors), with autocomplete-dropdown matching, redirect-URL decoding, and domain filtering for landing pages.
- **Run:** `python3 meta_ads_scraper.py --type all --limit 50 --batch 5` (or `--test` for a hardcoded 2-target dry run with no DB writes)
- **Flags:** `--type` (choice: `agency`/`authority`/`all`, default `all`), `--limit` (int, default 50), `--batch` (int, default 5, pause cadence), `--test` (flag)
- **Writes to:** `agency_benchmarks.meta_ads` (JSONB) or `authority_sources.paid_amplification` (TEXT); also inserts discovered landing-page URLs into `raw_source_data` as `source_type='landing_page_url_candidate'`. Skips rows that already have data populated.

#### `google_ads_scraper.py`
- **Does:** Same idea as `meta_ads_scraper.py` but against the Google Ads Transparency Center.
- **Run:** `python3 google_ads_scraper.py --type all --limit 50`
- **Flags:** `--type` (choice: `agency`/`authority`/`all`, default `all`), `--limit` (int, default 50)
- **Writes to:** merges into `agency_benchmarks.meta_ads` / `authority_sources.paid_amplification` (adds a `google_ads` key without clobbering existing Meta data); also seeds `landing_page_url_candidate` rows in `raw_source_data`.

#### `landing_page_scraper.py`
- **Does:** Visits landing-page URLs pulled from 4 sources — `competitor_ad_data`, `authority_sources` content hubs, agency websites, and the `landing_page_url_candidate` rows seeded by the ad scrapers above — and extracts hero headline, pricing, CTAs, and body copy.
- **Run:** `python3 landing_page_scraper.py --niche-id 1 --limit 20`
- **Flags:** `--niche-id` (int, required — only filters the `competitor_ad_data` source; the other 3 sources are global), `--limit` (int, default 20), `--headless` (flag)
- **Writes to:** `raw_source_data` (`source_type='landing_page'`); `ON CONFLICT DO NOTHING` on `source_url`. Exposes `normalize_url()` and `random_delay()`, imported by `magazine_discovery_scraper.py`.

#### `magazine_discovery_scraper.py`
- **Does:** Visits 2 hardcoded trade-press pages (Auto Rental News homepage, Luxury Daily automotive section), extracts article links/headlines, filters out nav junk, and seeds new ones for later content scraping.
- **Run:** `python3 magazine_discovery_scraper.py --niche-id 1` (`--test` to print discoveries without writing)
- **Flags:** `--niche-id` (int, required), `--headless` (flag), `--test` (flag)
- **Writes to:** `raw_source_data` (`source_type='newsletter_pending'`); deduped against any existing `source_url` for the niche regardless of source type.

#### `email_intelligence_scraper.py`
- **Does:** Second half of the magazine pipeline — visits URLs seeded as `source_type='newsletter_pending'`, extracts title/body/publish date, and flips the row's status. Detects Cloudflare "Just a moment" challenge pages and gives each URL a fresh browser context to avoid fingerprint accumulation.
- **Run:** `python3 email_intelligence_scraper.py --niche-id 1 --limit 20 --batch 5` (`--test` limits to 3 URLs and skips DB writes)
- **Flags:** `--niche-id` (int, required), `--limit` (int, default 20), `--batch` (int, default 5, pause cadence), `--headless` (flag, default off/headed), `--test` (flag)
- **Writes to:** updates existing `raw_source_data` rows: `source_type` → `'newsletter'` (success) or `'newsletter_failed'` (paywall/blocked/timeout/too-short).

#### `browser_tool.py`
- **Does:** General-purpose "load this URL with a real browser and give me the text + links" helper. Not imported by any scraper — it's a standalone utility, also wrapped by the MCP `browse_page` tool.
- **Run:** `python3 browser_tool.py --url "https://example.com" --wait-for "div.content"`
- **Flags:** `--url` (str, required), `--wait-for` (CSS selector, optional)
- **Output:** JSON to stdout (`title`, `text_content`, `links`) — no DB writes.

#### `check_library.py` / `test_transcript.py`
Two 8–12 line throwaway scripts that print the installed `youtube_transcript_api` version and fetch a known test transcript, respectively. Diagnostic only, not part of the pipeline, no DB writes.

---

## MCP server

```bash
cd mcp-server
npm install
npm run dev            # tsx src/index.ts, for local/Claude Desktop development
# or
npm run build && npm start    # compiled: tsc -> node build/index.js
```

The server reads `NEON_DB_URL` from the repo-root `.env` (see [Environment variables](#environment-variables)) and connects with a single `pg.Pool`. To use it from Claude Desktop, point an MCP server entry at `node <repo>/mcp-server/build/index.js` (after `npm run build`) or `npx tsx <repo>/mcp-server/src/index.ts` in your `claude_desktop_config.json`.

`npm run test-tools -- <tool_name> --flag value` exercises a tool directly without an MCP client, e.g. `npm run test-tools -- query_insights --niche-id 1`. Note: `test-tools.ts` has its own small hardcoded dispatcher predating most of the tool list — it only recognizes 6 tools (`query_raw_posts`, `query_insights`, `save_insight`, `save_persona`, `get_niche_config`, `query_personas`), not all 46. For anything else, call the tool through an actual MCP client (Claude Desktop) or add a case to `test-tools.ts`.

### Tools — direct database read/write (24)

| Tool | Parameters | What it does |
|---|---|---|
| `query_raw_posts` | `niche_id`* (number), `limit` (default 50, max 500), `processed` (bool), `source_type` (string), `offset` (default 0) | Reads `raw_source_data`, optionally filtered by processed status (via `research_jobs`) and source type. |
| `query_insights` | `niche_id`* (number), `category` (string) | Reads `insights`, ordered by `confidence_score` desc. |
| `save_insight` | `niche_id`*, `insight_type`* (pain_point/buying_trigger/objection/language_pattern/competitor_gap/market_timing), `title`*, `summary`, `body`*, `confidence_score`* (0–9.99, clamped), `source_ids`[], `tags`[], `is_actionable` (default true) | Inserts into `insights`. |
| `save_persona` | `niche_id`*, `name`*, `avatar_type`, `age_range`, `income_range`, `psychographics`{}, `pain_points`[], `desires`[], `objections`[], `empathy_map`{}, `buying_triggers`[], `preferred_channels`[], `is_primary` (default false) | Inserts into `customer_avatars` with `version=1`. |
| `query_personas` | `niche_id`*, `active` (bool) | Reads `customer_avatars`, optional primary-only filter. |
| `get_niche_config` | `niche_id`* | Reads one row from `niches`. Throws if not found. |
| `expand_research` | `niche_id`*, `gaps`*[] | No DB write — turns research gaps into suggested web-search query strings for the calling Claude to run, with an instruction to save findings via `save_insight`. |
| `save_success_story` | `niche_id`*, `story_title`*, `story_type` (default success_story), `summary`*, `revenue`{}, `method`, `platform`, `credibility_score`*, `proof_links`[], `source_url`*, `source_type` | Inserts into `stories_library` (see [schema drift](#database)). Note: `credibility_score` is accepted but not actually filtered/enforced anywhere. |
| `query_success_stories` | `niche_id`*, `min_credibility` (default 0.5), `story_type` | Reads `stories_library`. Note: `min_credibility` is declared but **not applied** in the SQL — always returns all rows regardless of score. |
| `generate_disruption_report` | `niche_id`*, `report_period` (auto-generated if omitted) | No DB write — orchestration only; tells the calling Claude to gather insights/personas/stories and call `save_disruption_report`. |
| `save_disruption_report` | `niche_id`*, `report_period`, `executive_summary`, `market_gaps`[], `emerging_trends`[], `competitor_moves`[], `opportunities_this_week`[], `page_count` | Inserts into `disruption_reports` via `market-strategist.ts`'s `saveDisruptionReport()`. |
| `save_marketing_copy` | `niche_id`*, `copy_type`* (headline/cta/email_subject/body_copy), `copy_text`*, `use_case`, `source_type`, `avatar_target`, `emotional_trigger`, `tags`[] | Inserts into `marketing_copy_library`. |
| `save_offer` | `niche_id`*, `offer_name`*, `offer_type`, `target_avatar`, `problem_solved`*, `unique_value`*, `pricing`{}, `market_timing`{}, `anticipated_objections`[] | Inserts into `offer_intelligence`. |
| `save_financial_analysis` | `niche_id`*, `tam_estimate`*, `average_cac`, `average_ltv`, `ltv_cac_ratio`, `payback_period`, `churn_rate`, `unit_economics`{} | Inserts into `financial_analysis` (missing table — see [Database](#database)). |
| `save_competitor_analysis` | `niche_id`*, `competitor_name`*, `positioning`, `strengths`[], `weaknesses`[], `gaps_and_opportunities`[], `market_share_estimate`, `strategy` | Inserts into `competitor_analysis` (missing table — see [Database](#database)). |
| `query_all_intelligence` | `niche_id`*, `query_type`* (pain_points/personas/opportunities/offers/financials/competitors/copy/comprehensive) | No real query — counts rows across several tables and tells the calling Claude which `query_*` tool to use for the real data. |
| `save_hook` | `niche_id`*, `hook_text`*, `hook_type`* (curiosity/fear/desire/social_proof/urgency/pattern_interrupt), `customer_language_quote`, `target_avatar_id`, `source_insight_ids`[], `usage_context`, `ai_generated` (default true), `approved` (default false), `performance_data`{}, `tags`[] | Inserts into `hooks_library` (missing table — see [Database](#database)). |
| `query_hooks` | `niche_id`*, `hook_type`, `target_avatar_id`, `approved` (bool), `min_performance_score` | Reads `hooks_library`. |
| `seed_newsletter_urls` | `niche_id`*, `urls`*[] (`{url, source_sender?, source_subject?, source_date?}`) | Inserts `raw_source_data` rows with `source_type='newsletter_pending'`, skipping URLs already present for the niche. Manual alternative to `magazine_discovery_scraper.py`. |
| `save_authority_source` | `firm_name`*, `content_hubs`{}, `report_structure`, `tone_style`, `visual_design`, `frameworks`{}, `paid_amplification`, `luxury_content`, `raw_notes` | Inserts into `authority_sources` (missing table — see [Database](#database)). |
| `save_association` | `name`*, `acronym`, `website`, `geo_focus`, `vertical`, `citation_tier`, `public_publications`{}, `monitor_urls`{}, `citation_use`, `notes` | Inserts into `association_intelligence` (missing table). |
| `save_agency_benchmark` | `agency_name`*, `tier`, `website`, `headline_positioning`, `outcome_language`, `proprietary_frameworks`{}, `pricing_signals`, `case_study_format`, `meta_ads`{}, `notes` | Inserts into `agency_benchmarks` (missing table). |
| `save_apex_positioning_brief` | `version`, `current_positioning`*, `positioning_gaps`{}, `positioning_strengths`{}, `positioning_opportunities`{}, `agency_comparisons`{}, `consulting_firm_comparisons`{}, `methodology_recommendations`, `pricing_recommendations`, `packaging_recommendations`, `proposal_language`{}, `citation_recommendations`{}, `report_format`, `tone_guidelines`, `citation_style`, `framework_naming`{}, `visual_guidelines`, `raw_analysis` | Inserts into `apex_positioning_briefs` (missing table). |
| `save_client_intelligence_report` | `niche_id`*, `client_name`, `city`, `report_type`*, `report_period`, `positioning_brief_id`, `executive_summary`, `market_overview`, `uhnw_persona_profiles`{}, `seasonality_data`{}, `competitor_ad_intelligence`{}, `hooks_and_offers`{}, `citations`{}, `recommendations`{}, `full_report` | Inserts into `client_intelligence_reports` (missing table). |

\* required

### Tools — brain orchestration (11)

None of these call an LLM or save anything themselves — that's left to the calling Claude. There are two distinct shapes. See [Brains](#brains).

**Self-querying — these hit the DB and bundle real rows into the response (5)**

| Tool | Parameters | What it does |
|---|---|---|
| `extract_hooks` | `niche_id`* | Pulls up to 60 competitor ads, 120 raw posts, 100 `language_pattern` insights, 50 stories; dedupes against existing `hooks_library` rows; returns data + prompt for the calling Claude to extract hooks and call `save_hook`. |
| `extract_offers` | `niche_id`* | Same pattern, sourced from ads/posts/insights (`competitor_gap`, `market_timing`, `buying_trigger`, `pain_point`)/success stories; targets `save_offer`. |
| `extract_stories` | `niche_id`* | Same pattern across ads, posts (reddit/youtube/google_news/trustpilot/forum), and all insight types; targets `save_success_story`. |
| `run_apex_positioning_brain` | none | Gathers Apex's own scraped site content plus all `agency_benchmarks`, `authority_sources`, `association_intelligence` rows; returns data + prompt; targets `save_apex_positioning_brief`. |
| `run_client_intelligence_brain` | `niche_id`*, `client_name`, `city`, `report_type` (default state_of_market) | Gathers the latest Apex positioning brief plus a wide slice of niche intelligence (insights, personas, stories, hooks, offers, trends, competitor ads, disruption reports); returns data + prompt; targets `save_client_intelligence_report`. |

**Instruction-only — these never touch the DB, they just hand back a system prompt + a to-do list of `query_*`/`save_*` tools for the calling Claude to use (6)**

| Tool | Parameters | What it does |
|---|---|---|
| `competitive_intelligence` | `niche_id`* | Returns the competitive-intelligence system prompt and an instruction to query `query_insights` (competitor_gap), `query_success_stories`, and `query_personas`, then save one record per competitor via `save_competitor_analysis`. |
| `conversational_assistant` | `niche_id`*, `query_type`* (pain_points/personas/opportunities/offers/financials/competitors/copy/comprehensive) | Returns a system prompt and a map of which `query_*` tools to call for the given `query_type`, so the calling Claude can synthesise a cited answer. No save target — read-only. |
| `copywriter` | `niche_id`* | Returns an instruction to query `query_insights` (language_pattern), `query_personas`, and `query_success_stories`, then save generated copy assets via `save_marketing_copy`. |
| `financial_analyst` | `niche_id`* | Returns an instruction to query insights, success stories, and any available trend data, then save a TAM/CAC/LTV analysis via `save_financial_analysis`. |
| `offer_designer` | `niche_id`* | Returns an instruction to query personas, insights, and success stories, then save 2-3 designed offers via `save_offer`. |
| `persona_architect` | `niche_id`* | Returns an instruction to audit `raw_source_data`, call `expand_research` to fill gaps, then save each of 8-12 personas immediately (one at a time, not batched) via `save_persona`. |

### Tools — spawn a Python scraper (11)

Each spawns `python3 <script>.py ...` from the repo root with a 5-minute timeout and returns `{success, output, error?}`.

| Tool | Parameters | Spawns |
|---|---|---|
| `run_reddit_scraper` | `niche_id`*, `limit` (default 50) | `run_full_scrape.py --niche-id {id} --limit {limit} --headless --full-content` |
| `run_google_trends` | `niche_id`* (accepted but ignored — script hardcodes niche 1) | `google_trends_scraper.py` (no args) |
| `run_youtube_scraper` | `niche_id`*, `search` (default "exotic car rental"), `limit` (default 20) | `youtube_scraper.py --niche-id {id} --search {q} --limit {limit}` |
| `run_review_scraper` | `niche_id`*, `platform` (default trustpilot), `limit` (default 50) | `review_scraper.py --niche-id {id} --platform {p} --limit {limit}` |
| `run_facebook_scraper` | `niche_id`*, `competitors`* (comma-separated), `max_ads` (default 50) | `facebook_ad_scraper.py --niche-id {id} --competitors {list} --max-ads {n} --headless` |
| `run_landing_page_scraper` | `niche_id`*, `limit` (default 20) | `landing_page_scraper.py --niche-id {id} --limit {limit}` |
| `seed_newsletter_urls` | *(listed above with the DB tools — it's a direct insert, not a scraper spawn)* | — |
| `run_email_intelligence_scraper` | `niche_id`*, `limit` (default 20), `batch` (default 5), `headless` (default false) | `email_intelligence_scraper.py --niche-id {id} --limit {limit} --batch {batch} [--headless]` |
| `run_magazine_discovery_scraper` | `niche_id`*, `headless` (default false) | `magazine_discovery_scraper.py --niche-id {id} [--headless]` |
| `run_meta_ads_scraper` | `type` (default all), `limit` (default 50) | `meta_ads_scraper.py --type {type} --limit {limit}` |
| `run_google_ads_scraper` | `type` (default all), `limit` (default 50) | `google_ads_scraper.py --type {type} --limit {limit}` |
| `browse_page` | `url`*, `wait_for` | `browser_tool.py --url {url} [--wait-for {selector}]` |

\* required

---

## Brains

"Brains" are TypeScript modules in `mcp-server/src/brains/` meant to package a research task (gather data + system prompt + save schema) for an LLM to execute. None of them call an LLM directly — see [Current status](#current-status).

The 6 brains wired in this pass (`competitive-intelligence.ts`, `conversational-assistant.ts`, `copywriter.ts`, `financial-analyst.ts`, `offer-designer.ts`, `persona-architect.ts`) each already exported a complete, self-contained `{name, description, inputSchema, handler}` tool object using camelCase args (`nicheId`, `queryType`). `index.ts` imports each tool object directly and defines its own `niche_id`/`query_type` (snake_case) entry in `TOOLS` to match the naming convention every other tool in this API uses, with a thin wrapper function translating the args before calling `.handler()`. The brain files themselves were not modified.

| Brain | Status | Reachable via |
|---|---|---|
| `hook-extractor.ts` | **Wired** | `extract_hooks` MCP tool |
| `offer-extractor.ts` | **Wired** | `extract_offers` MCP tool |
| `story-extractor.ts` | **Wired** | `extract_stories` MCP tool |
| `apex-positioning.ts` | **Wired** | `run_apex_positioning_brain` MCP tool |
| `client-intelligence.ts` | **Wired** | `run_client_intelligence_brain` MCP tool |
| `market-strategist.ts` | **Wired** (partially) | Its `saveDisruptionReport()` export backs `save_disruption_report`; the brain's own data-gathering tool (`generate_disruption_report`) is wired but implemented inline in `index.ts`, not by importing the brain's full handler. Also opens its own separate `pg.Pool` rather than reusing the server's. |
| `competitive-intelligence.ts` | **Wired** | `competitive_intelligence` MCP tool. The brain already exported a complete `{name, description, inputSchema, handler}` tool object (loading `prompts/competitive-intelligence.md`); `index.ts` now imports it and dispatches to it directly. |
| `conversational-assistant.ts` | **Wired** | `conversational_assistant` MCP tool. Same import-and-dispatch pattern. Note it overlaps conceptually with the older, simpler `query_all_intelligence` tool (which just counts rows) — both exist side by side. |
| `copywriter.ts` | **Wired** | `copywriter` MCP tool. |
| `financial-analyst.ts` | **Wired** | `financial_analyst` MCP tool. |
| `offer-designer.ts` | **Wired** | `offer_designer` MCP tool. Targets the same `save_offer` tool as `offer-extractor.ts` — one designs new offers from scratch, the other extracts offers already visible in scraped data. |
| `persona-architect.ts` | **Wired** | `persona_architect` MCP tool — notable because its prompt instructs the calling Claude to save personas one at a time rather than in a batch. |
| `success-story-hunter.ts` | **Built, reachable only via `run.ts`** | `npx tsx mcp-server/src/run.ts success_story_hunter --niche-id <id>` — a standalone CLI separate from the 46 MCP tools above. Its `saveSchema` uses camelCase field names (`storyTitle`, `proofLinks`), inconsistent with `story-extractor.ts`'s snake_case for the same `save_success_story` tool. |
| `research-analyst.ts` | **Stub** | `npx tsx mcp-server/src/run.ts research_analyst --niche-id <id>` returns `{status: 'stub — not yet implemented'}` and nothing else. Not in the MCP server. |

Of the 14 brains, 11 load a system prompt from `mcp-server/src/brains/prompts/*.md`. `apex-positioning.ts`, `client-intelligence.ts`, and the stub `research-analyst.ts` do not.

---

## Testing

There is no automated test suite (no Jest/pytest config, no CI). What actually exists to verify things work:

- `npm run test-db` — confirms the 18 `migrate.ts` tables exist in the connected database.
- `npm run test-tools -- <tool> --flag value` (in `mcp-server/`) — calls any MCP tool directly and prints the result.
- Most scrapers accept `--dry-run` or `--test` to print what they'd do without writing to the DB (`reddit_browser_scraper.py`, `run_full_scrape.py`, `magazine_discovery_scraper.py`, `email_intelligence_scraper.py`, `meta_ads_scraper.py`).
- `testing-checklist.md` is a QA checklist template (unchecked items, no dates) — it documents what *should* be tested, not a record of what has been.

---

## Stale docs in this repo

These files describe earlier states of the project and contain claims that no longer match the code. Treat them as historical record, not current documentation:

- **`CHANGELOG.md`, `build-roadmap.md`, `STATUS_REPORT_v0_1_0.md`, `PHASE_1_WEEK_2_COMPLETE.md`** — describe v0.1–v0.3, 2 working brains, a single Reddit scraper, and 17 tables. All superseded by what's described above.
- **`mcp-server/EXAMPLE_OUTPUT.md`** — shows fabricated sample output for `research_analyst`, which is an explicit stub that returns nothing of the kind. It also references `npm run run-brain`, a script that does not exist in `mcp-server/package.json`.
- **`SCHEMA.md`** — documents a "Hook-Story-Offer Framework" schema (the 9 missing tables described in [Database](#database)) that was never turned into a committed migration; useful as a *description of intent* for those tables' columns, not as proof they're set up correctly.
- **`testing-checklist.md`** — a template, not a completed checklist.
- **`brain-prompts.md`** — this one does check out: it's the source material that the actual `mcp-server/src/brains/prompts/*.md` files were built from, and matches the prompts loaded in code.
- **`GITHUB_UPLOAD_CHECKLIST.md`** — a still-valid procedural note on what's safe to commit (no credentials, etc.), not a status claim.

---

## Security & privacy

This is a private repository containing proprietary research prompts and methodology, plus a `.env` with live database/API credentials (excluded via `.gitignore`). Never commit `.env`, `node_modules/`, `__pycache__/`, `.venv/`, or any database export containing real scraped/derived data.
