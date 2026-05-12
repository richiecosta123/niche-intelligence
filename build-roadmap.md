\# Build Roadmap \- Niche Intelligence Platform

Last Updated: \[Date\]

Status: Foundation Phase

\---

\#\# PHASE 1: FOUNDATION (Weeks 1-2)

\#\#\# Week 1: Database & Infrastructure

\*\*Goal:\*\* Working database with basic connectivity

\- \[ \] \*\*Task 1.1:\*\* Create Neon Postgres database

  \- Sign up for Neon free tier

  \- Create database: \`niche\_intelligence\`

  \- Save connection string to .env


\- \[ \] \*\*Task 1.2:\*\* Run schema migration

  \- Execute niche-intel-schema.ts

  \- Verify all 14+ tables created

  \- Test: Insert sample niche record


\- \[ \] \*\*Task 1.3:\*\* Build Postgres MCP server (connection only)

  \- Create MCP server project

  \- Implement \`query\_database\` tool

  \- Test: Query from Claude Desktop


\- \[ \] \*\*Task 1.4:\*\* Seed initial data

  \- Insert exotic car rental niche (nicheId=1)

  \- Configure data sources (Reddit, YouTube, etc.)

  \- Set research frequency

\*\*Deliverable:\*\* Claude Desktop can query the database and see exotic car rental niche

\---

\#\#\# Week 2: First Data Pipeline

\*\*Goal:\*\* Scrape Reddit → Save to DB → Process with AI

\- \[ \] \*\*Task 2.1:\*\* Build Reddit scraper (Python)

  \- Install PRAW (Reddit API wrapper)

  \- Create script: \`reddit\_scraper.py\`

  \- Target: r/entrepreneur, r/smallbusiness, r/exoticcars

  \- Search terms: "exotic car rental", "supercar rental", "luxury car business"


\- \[ \] \*\*Task 2.2:\*\* Save raw data to database

  \- Connect to Neon from Python (psycopg2)

  \- Insert into rawSourceData table

  \- Test: Scrape 50 posts, verify in DB


\- \[ \] \*\*Task 2.3:\*\* Build Research Analyst MCP skill

  \- Create MCP skill: \`research\_analyst\_brain\`

  \- Implement system prompt from brain-prompts.md

  \- Test: Process 50 posts → Generate insights


\- \[ \] \*\*Task 2.4:\*\* Validate insights quality

  \- Review generated insights

  \- Check: Evidence quotes present? Specific enough?

  \- Refine prompt if needed

\*\*Deliverable:\*\* "Process Reddit data" command in Claude Desktop → Insights saved to DB

\---

\#\# PHASE 2: CORE BRAINS (Weeks 3-4)

\#\#\# Week 3: Avatar System

\*\*Goal:\*\* Generate customer personas from insights

\- \[ \] \*\*Task 3.1:\*\* Build Persona Architect MCP skill

  \- Implement brain-prompts.md system prompt

  \- Input: Query insights table

  \- Output: Save to customerAvatars table


\- \[ \] \*\*Task 3.2:\*\* Test avatar generation

  \- Run on exotic car rental insights

  \- Target: 8-12 personas

  \- Validate: Evidence quotes? Empathy maps complete?


\- \[ \] \*\*Task 3.3:\*\* Quarterly regeneration logic

  \- Create avatarGenerationJobs table tracking

  \- Implement "mark old avatars inactive" logic

  \- Test: Regenerate → Old avatars set active=false

\*\*Deliverable:\*\* "Generate avatars" command → 8-12 personas with empathy maps

\---

\#\#\# Week 4: Success Stories & Disruption Reports

\*\*Goal:\*\* Weekly stories \+ bi-weekly strategic reports

\- \[ \] \*\*Task 4.1:\*\* Build Success Story Hunter MCP skill

  \- Implement system prompt

  \- Credibility scoring logic

  \- Deduplication check (don't re-save existing stories)


\- \[ \] \*\*Task 4.2:\*\* Test story hunting

  \- Run on Reddit data

  \- Target: 5-10 stories with credibility 6+

  \- Validate: Revenue proof? Method explained?


\- \[ \] \*\*Task 4.3:\*\* Build Market Strategist MCP skill

  \- Implement disruption report prompt

  \- Input: Insights \+ stories \+ avatars

  \- Output: 20-page report JSON


\- \[ \] \*\*Task 4.4:\*\* Generate first disruption report

  \- Run Market Strategist brain

  \- Review output quality

  \- Iterate on prompt if needed

\*\*Deliverable:\*\* Bi-weekly disruption report with market gaps, trends, opportunities

\---

\#\# PHASE 3: REMAINING BRAINS (Weeks 5-6)

\#\#\# Week 5: Copy, Offers, Finance

\- \[ \] \*\*Task 5.1:\*\* Copywriter Brain

  \- Extract marketing language from insights

  \- Build marketingCopyLibrary table


\- \[ \] \*\*Task 5.2:\*\* Offer Designer Brain

  \- Generate positioned offers

  \- Test: Create ExoticInsure offer


\- \[ \] \*\*Task 5.3:\*\* Financial Analyst Brain

  \- Calculate TAM using Google Trends data

  \- Estimate CAC from AdBeat (if integrated)

\#\#\# Week 6: Competitive Intel & Conversational Assistant

\- \[ \] \*\*Task 6.1:\*\* Competitive Intelligence Brain

  \- Analyze Turo, Enterprise, competitors

  \- Generate competitive landscape report


\- \[ \] \*\*Task 6.2:\*\* Conversational Assistant

  \- Build query orchestration logic

  \- Test: "What are the pain points?" → Synthesize across tables


\- \[ \] \*\*Task 6.3:\*\* Full workflow test

  \- Scrape → Analyze → Report → Query

  \- End-to-end validation

\*\*Deliverable:\*\* All 9 brains operational, full intelligence cycle working

\---

\#\# PHASE 4: DATA SOURCE EXPANSION (Weeks 7-8)

\#\#\# Week 7: Google Trends Integration

\- \[ \] \*\*Task 7.1:\*\* Build Google Trends scraper

  \- Use pytrends library

  \- Fetch search volume, related queries

  \- Save to trendData table


\- \[ \] \*\*Task 7.2:\*\* Update brains to consume trend data

  \- Market Strategist: Use for trend analysis

  \- Financial Analyst: Use for TAM calculation

  \- Offer Designer: Use for seasonality

\#\#\# Week 8: YouTube & Forums

\- \[ \] \*\*Task 8.1:\*\* YouTube comment scraper

  \- Target channels in exotic car niche

  \- Extract comments on rental/business videos


\- \[ \] \*\*Task 8.2:\*\* Forum scraper (optional)

  \- Identify relevant forums

  \- Scrape discussions


\*\*Deliverable:\*\* Multi-source intelligence (Reddit \+ Trends \+ YouTube)

\---

\#\# PHASE 5: GENERALIZATION (Weeks 9-10)

\#\#\# Week 9: Abstract to Multi-Niche

\- \[ \] \*\*Task 9.1:\*\* Parameterize scrapers

  \- Pass nicheId, keywords from niches table

  \- Remove hardcoded "exotic car rental"


\- \[ \] \*\*Task 9.2:\*\* Abstract brain prompts

  \- Replace niche-specific references with {niche.name}

  \- Test with exotic car rental (should still work)


\- \[ \] \*\*Task 9.3:\*\* Add niche \#2: Chauffeur Services

  \- Create new niche record

  \- Configure data sources

  \- Run full pipeline

  \- Validate: Separate avatars, insights, reports

\#\#\# Week 10: Dashboard & Refinement

\- \[ \] \*\*Task 10.1:\*\* Simple query interface

  \- Claude Desktop conversational queries work

  \- Test common questions


\- \[ \] \*\*Task 10.2:\*\* Automation setup

  \- Cron jobs for weekly/bi-weekly tasks

  \- OR manual trigger scripts


\- \[ \] \*\*Task 10.3:\*\* Documentation

  \- User guide for querying intelligence

  \- Developer guide for adding new niches

\*\*Deliverable:\*\* Multi-niche platform ready for scaling

\---

\#\# FUTURE EXTENSIONS (Post-MVP)

\#\#\# Search Console Integration

\- Requires access to competitor sites or client sites

\- Provides keyword opportunity data

\- Feeds Competitive Intelligence brain

\#\#\# AdBeat Integration

\- Paid service ($250-500/month)

\- Competitor ad spend and creative analysis

\- Feeds Copywriter & Competitive Intelligence brains

\#\#\# Email/Call Tracking

\- Track prospect email conversations

\- Analyze sales call transcripts

\- Feed performance data back to brains (self-improvement loop)

\#\#\# Quarterly Industry Reports

\- Full 40-page McKinsey-style reports

\- TAM, CAC, LTV, competitive landscape, GTM playbook

\- Requires Financial Analyst \+ all accumulated data

\---

\#\# CURRENT STATUS

\*\*Phase:\*\* Foundation

\*\*Week:\*\* 1

\*\*Next Task:\*\* Create Neon database and run schema migration

\*\*Blockers:\*\* None

\*\*Notes:\*\* Starting with exotic car rental as proof of concept

\---

\*\*Updates:\*\* This roadmap will be updated weekly with progress and adjustments