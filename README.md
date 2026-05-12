# Niche Intelligence Platform

**Multi-Brain AI Market Intelligence System**

⚠️ **PRIVATE REPOSITORY** - Contains proprietary AI prompts, market intelligence strategy, and competitive research methodology.

Automated market research platform that collects data from web sources (Reddit, YouTube, Google Trends), processes it through specialized AI "brains," and stores actionable intelligence in PostgreSQL.

---

## 🎯 What This Does

Turns **raw social media discussions** into **strategic market intelligence**:

- **Scrapes** Reddit, YouTube, forums for customer conversations
- **Analyzes** with AI to extract pain points, buying triggers, objections, language patterns
- **Generates** customer personas with empathy maps
- **Delivers** conversational intelligence via Claude Desktop

---

## 📊 Current Status

**Phase:** Foundation Complete ✅  
**Version:** v0.3.0  
**Intelligence Generated:** 17 insights, 10 personas from 232 Reddit posts  
**Niche:** Exotic Car Rental (proof of concept)

### What's Working
- ✅ Neon PostgreSQL database (17 tables)
- ✅ Reddit headless scraper (Playwright)
- ✅ Research Analyst brain (MCP skill)
- ✅ Persona Architect brain (MCP skill)
- ✅ Research expansion via conversational web search
- ✅ Claude Desktop conversational queries

---

## 🏗️ Architecture

```
┌─────────────────┐
│  Data Sources   │
│ Reddit, YouTube │
│ Google Trends   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Python Scrapers │
│  (Playwright)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Neon PostgreSQL │
│  (17 tables)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   AI Brains     │
│  (MCP Skills)   │
│ - Research      │
│ - Personas      │
│ - Stories       │
│ - Strategist    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Claude Desktop  │
│ (Conversational)│
└─────────────────┘
```

---

## 🗂️ Database Schema

**17 Tables in 4 Groups:**

### Foundation (3)
- `niches` - Niche configurations with data sources
- `research_jobs` - Job tracking and progress
- `raw_source_data` - Scraped posts/videos/trends

### Intelligence (8)
- `insights` - Pain points, triggers, objections, patterns, gaps, timing
- `customer_avatars` - Persona profiles with empathy maps
- `success_stories` - Money-making examples with credibility scoring
- `offer_intelligence` - Positioned offers with pricing strategy
- `marketing_copy_library` - Proven marketing language
- `opportunities` - Market gaps with scoring
- `disruption_reports` - Bi-weekly strategic analysis
- `quarterly_industry_reports` - McKinsey-style deep dives

### Supporting (2)
- `share_links` - Shareable report links
- `brain_dependencies` - Brain orchestration DAG

### Extensible (4)
- `trend_data` - Google Trends
- `search_term_data` - SEO opportunities
- `competitor_ad_data` - Competitor ad intelligence

**See:** `niche-intel-schema.ts` for complete schema

---

## 🧠 AI Brains (9 Total)

Each brain is a specialized MCP skill with Claude API integration:

1. **Research Analyst** ✅ - Extract insights from raw data
2. **Persona Architect** ✅ - Generate evidence-based avatars quarterly
3. **Market Strategist** 🔜 - Create disruption reports bi-weekly
4. **Copywriter** 🔜 - Extract marketing language patterns
5. **Offer Designer** 🔜 - Design positioned offers with pricing
6. **Financial Analyst** 🔜 - Calculate TAM/CAC/LTV
7. **Competitive Intelligence** 🔜 - Analyze competitor gaps
8. **Success Story Hunter** 🔜 - Find money-making stories weekly
9. **Conversational Assistant** 🔜 - Real-time user queries

**See:** `brain-prompts.md` for complete system prompts

---

## 🚀 Quick Start

### 1. Database Setup

```bash
# Create Neon PostgreSQL database
# Get connection string from https://neon.tech

# Copy environment template
cp .env.example .env

# Add your credentials to .env:
NEON_DB_URL=postgresql://...
ANTHROPIC_API_KEY=sk-ant-...
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

### 2. Install Dependencies

**Python (Scraper):**
```bash
pip install playwright psycopg2-binary python-dotenv beautifulsoup4
playwright install chromium
```

**Node.js (MCP Server):**
```bash
npm install
```

### 3. Run Database Migration

```bash
npm run migrate
npm run seed
```

### 4. Scrape Data

```bash
# Scrape 50 Reddit posts across 5 keywords
python reddit_browser_scraper.py --limit 50

# Or run full scrape (all keywords)
python run_full_scrape.py
```

### 5. Process with AI Brains

**Via Claude Desktop:**
```
"Run research_analyst for nicheId 2"
"Generate personas for exotic car rental"
```

**Via Standalone CLI:**
```bash
cd mcp-server
npm run research-analyst
```

---

## 📁 Repository Structure

```
niche-intelligence/
├── README.md                          # This file
├── CHANGELOG.md                       # Version history
├── package.json                       # Node.js dependencies
├── tsconfig.json                      # TypeScript config
├── .env.example                       # Environment variables template
├── .gitignore                         # Git ignore rules
│
├── schema/
│   ├── niche-intel-schema.ts         # 17 table definitions
│   ├── migrate.ts                     # Database migration
│   ├── test-db.ts                     # Validation script
│   └── seed-exotic-car-niche.ts      # Initial data
│
├── scrapers/
│   ├── reddit_browser_scraper.py     # Playwright headless scraper
│   ├── run_full_scrape.py            # Multi-keyword orchestrator
│   └── requirements.txt              # Python dependencies
│
├── mcp-server/
│   ├── package.json                  # MCP dependencies
│   ├── tsconfig.json                 # Node16 ESM config
│   └── src/
│       ├── index.ts                  # MCP server entry
│       ├── run.ts                    # Standalone CLI runner
│       └── brains/
│           ├── prompts.ts            # System prompts
│           ├── research-analyst.ts   # Brain logic
│           └── persona-architect.ts  # Brain logic
│
├── prompts/
│   ├── brain-prompts.md              # All 9 brain system prompts
│   ├── mcp-skill-template.ts         # Code pattern for brains
│   └── exotic-car-rental-keywords.md # Search terms
│
├── docs/
│   ├── build-roadmap.md              # Phased build plan
│   ├── testing-checklist.md          # QA checklist
│   ├── STATUS_REPORT_v0_1_0.md       # Database setup
│   ├── STATUS_REPORT_v0_1_1.md       # Scraper deployment
│   ├── STATUS_REPORT_v0_2_0.md       # Research Analyst brain
│   └── PHASE_1_WEEK_2_COMPLETE.md    # Week 2 summary
│
└── examples/
    └── example-reddit-data.json      # Sample Reddit data
```

---

## 🔧 Environment Variables

**Required:**
- `NEON_DB_URL` - PostgreSQL connection string
- `ANTHROPIC_API_KEY` - Claude API key

**Optional:**
- `REDDIT_CLIENT_ID` - Reddit API credentials
- `REDDIT_CLIENT_SECRET` - Reddit API credentials
- `YOUTUBE_API_KEY` - YouTube Data API v3
- `ADBEAT_API_KEY` - AdBeat competitor data (paid)

**See:** `.env.example` for full list

---

## 💡 Key Features

### Evidence-Based Intelligence
- Every insight requires 2+ real quotes
- No generic AI buzzwords
- Confidence scoring (0-100%)
- Actionable recommendations included

### Stateless Progress Tracking
```sql
-- Track processing with max_id_processed
SELECT max_id_processed FROM research_jobs 
WHERE niche_id = 2 AND brain_name = 'research_analyst';
```

### Multi-Source Data Collection
- Reddit (configured) ✅
- YouTube (planned)
- Google Trends (planned)
- Forums (planned)
- Review sites (planned)

### Conversational Interface
Query via Claude Desktop:
```
"What are the biggest pain points?"
"Show me customer personas"
"Generate disruption report"
```

---

## 📊 Current Intelligence (Exotic Car Rental)

### Insights Generated: 17

**Top 5 by Confidence:**
1. Weddings drive reliable demand (0.90)
2. Dubai deposit scams (0.88)
3. Bucket list fulfillment (0.82)
4. "Legit" not "reputable" language (0.80)
5. Insurance complexity barrier (0.78)

### Personas Generated: 10

**Primary Personas (4):**
- The Weekend Experience Seeker (28-38, $75k-$150k)
- The Bucket List Gearhead (38-58, $95k-$175k)
- The Wedding/Special Occasion Planner (26-45, $65k-$140k)

**Secondary Personas (6):**
- The Corporate Event Planner (B2B)
- The Track Day Enthusiast (performance-focused)
- The International Tourist (Dubai/Miami/Vegas)
- The Social Media Influencer (content creator)
- The Cost-Conscious Turo Refugee (price-sensitive)
- The Under-25 Aspiring Renter (excluded demographic)
- The Secondary Market Opportunist (underserved cities)

---

## 🛣️ Roadmap

### Phase 1: Foundation (Weeks 1-2) ✅
- ✅ Database infrastructure (17 tables)
- ✅ Reddit scraper (232 posts, 0 errors)
- ✅ Research Analyst brain (15 insights)
- ✅ Persona Architect brain (10 personas)

### Phase 2: Core Brains (Weeks 3-4)
- 🔜 Success Story Hunter brain
- 🔜 Market Strategist brain (disruption reports)
- 🔜 Copywriter brain
- 🔜 Offer Designer brain

### Phase 3: Data Expansion (Weeks 5-8)
- 🔜 YouTube transcript scraper
- 🔜 Google Trends integration
- 🔜 Forum scraper
- 🔜 Review site scraper

### Phase 4: Generalization (Weeks 9-10)
- 🔜 Multi-niche support
- 🔜 Niche configuration UI
- 🔜 Automated scheduling

---

## 🧪 Testing

```bash
# Database validation
npm run test-db

# Scraper dry-run
python reddit_browser_scraper.py --dry-run --limit 10

# Brain validation
npm run test-research-analyst
```

**See:** `testing-checklist.md` for complete QA checklist

---

## 📈 Performance Metrics

**Week 2 Results:**
- Reddit scraping: 232 posts in 120 seconds (100% success rate)
- AI processing: 232 posts → 15 insights in ~2 minutes
- Cost: ~$0.60 per 232-post batch (Claude Sonnet 4)
- Database queries: <50ms average

---

## 🔒 Security & Privacy

### Why This Repo is PRIVATE

This repository contains:
- ✅ **Proprietary AI prompts** - Brain system prompts are competitive IP
- ✅ **Market intelligence methodology** - How we extract insights is the secret sauce
- ✅ **Strategic research approach** - Which data sources and why
- ✅ **Competitive positioning** - Exotic car rental insights reveal business strategy

### What's Protected

**In This Private Repo:**
- AI brain prompts (proprietary methodology)
- Research strategies and data source selection
- Exotic car rental intelligence approach
- Strategic roadmap and priorities

**In Neon PostgreSQL (Separate, Also Private):**
- 17 market insights (exotic car rental)
- 10 customer personas with empathy maps
- 232 raw Reddit posts
- All accumulated intelligence data

### Never Commit to Git

- ❌ `.env` file (contains credentials)
- ❌ `node_modules/`
- ❌ `__pycache__/`
- ❌ Any API keys
- ❌ Database exports with real data

**Safe to commit:**
- ✅ Schema files (no credentials)
- ✅ Scraper code (no secrets)
- ✅ Brain prompts (private repo protects)
- ✅ Documentation
- ✅ Example data (sanitized)

---

## 📄 License

**Proprietary & Confidential**

All rights reserved. This code, methodology, and associated documentation are proprietary and confidential. 

Unauthorized copying, distribution, or use is strictly prohibited.

---

## 🙏 Acknowledgments

- **Claude (Anthropic)** - AI processing via API
- **Neon** - PostgreSQL database hosting
- **Playwright** - Headless browser automation
- **MCP** - Model Context Protocol for tool orchestration

---

## 📞 Contact

**Repository:** Private  
**Status:** Phase 1 Complete, Phase 2 In Progress  
**Purpose:** Proprietary market intelligence system

---

**Built with:** TypeScript, Python, PostgreSQL, Claude API, Playwright, MCP
