**\# Testing Checklist \- Niche Intelligence Platform**

Last Updated: \[Date\]  
Version: 1.0

\---

**\#\# DATABASE TESTS**

**\#\#\# Schema Creation**  
\- \[ \] All 14+ tables created successfully  
\- \[ \] Foreign key relationships work  
\- \[ \] JSON columns accept valid data  
\- \[ \] Timestamps auto-populate on insert

**\#\#\# Data Insertion**  
\- \[ \] Can insert niche record  
\- \[ \] Can insert rawSourceData  
\- \[ \] Can insert insights with structuredData JSON  
\- \[ \] Can insert customerAvatars with empathy map JSON

**\#\#\# Queries**  
\- \[ \] Can query by nicheId  
\- \[ \] JSON queries work (e.g., \`content-\>\>'title'\`)  
\- \[ \] Can join tables (insights → niches)  
\- \[ \] Indexes improve query speed

\---

**\#\# PYTHON SCRAPER TESTS**

**\#\#\# Reddit Scraper**  
\- \[ \] PRAW connects to Reddit successfully  
\- \[ \] Can search subreddits with keywords  
\- \[ \] Retrieves post data (title, body, URL, upvotes)  
\- \[ \] Saves to rawSourceData table  
\- \[ \] Deduplication works (doesn't re-save same post)  
\- \[ \] Handles rate limiting gracefully  
\- \[ \] Logs errors to console

**\#\#\# Test Execution:**  
\`\`\`bash  
python3 reddit\_scraper.py \--niche 1 \--limit 50  
\# Should scrape 50 posts and save to database  
\`\`\`

\---

**\#\# MCP SKILL TESTS**

**\#\#\# Postgres Connector**  
\- \[ \] Can connect to Neon database  
\- \[ \] query\_database tool returns results  
\- \[ \] Handles SQL errors gracefully  
\- \[ \] Returns data in expected format

**\#\#\# Test from Claude Desktop:**

User: "Query the database for niches" Claude: \[Calls query\_database tool\] Expected: Returns exotic car rental niche data

\---

\#\# BRAIN SKILL TESTS

\#\#\# Research Analyst Brain  
\- \[ \] Fetches rawSourceData from database  
\- \[ \] Calls Claude API with system prompt  
\- \[ \] Parses JSON output correctly  
\- \[ \] Saves insights to database  
\- \[ \] Marks raw data as processed  
\- \[ \] Handles parse errors gracefully

\#\#\# Test Execution:

User: "Run research\_analyst for nicheId 1" Expected:

* Processes 50-100 raw posts  
* Creates 20-40 insights  
* Insights have evidence quotes  
* No generic buzzwords

\#\#\# Persona Architect Brain  
\- \[ \] Reads insights from database  
\- \[ \] Generates 8-12 avatars  
\- \[ \] Avatars have complete empathy maps  
\- \[ \] Evidence quotes present (10+ per avatar)  
\- \[ \] Market shares sum to \~100%  
\- \[ \] Sets old avatars inactive when regenerating

\#\#\# Success Story Hunter Brain  
\- \[ \] Finds stories with revenue mentioned  
\- \[ \] Credibility scoring works (1-10 scale)  
\- \[ \] Deduplication prevents re-saving  
\- \[ \] Proof links extracted correctly  
\- \[ \] Only saves stories with credibility 6+

\#\#\# Market Strategist Brain  
\- \[ \] Generates disruption report JSON  
\- \[ \] Market gaps have evidence  
\- \[ \] Trends include trajectory and timeframe  
\- \[ \] Opportunities scored correctly  
\- \[ \] Report is 20+ pages worth of content

\---

\#\# INTEGRATION TESTS

\#\#\# End-to-End Workflow  
\- \[ \] Scrape Reddit → Save rawSourceData  
\- \[ \] Run Research Analyst → Create insights  
\- \[ \] Run Persona Architect → Create avatars  
\- \[ \] Run Success Story Hunter → Find stories  
\- \[ \] Run Market Strategist → Generate report  
\- \[ \] Query via Conversational Assistant → Get synthesized answer

\#\#\# Test Query:

User: "What are the biggest pain points for exotic car rental owners?" Expected:

* Queries insights table (category \= 'pain\_points')  
* Returns specific pain points with evidence  
* Cites data sources (e.g., "Based on 147 Reddit posts...")

\---

\#\# DATA QUALITY TESTS

\#\#\# Insights Quality  
\- \[ \] No generic insights ("poor customer service")  
\- \[ \] Specific insights only ("$2k deposits scare away 60% of inquiries")  
\- \[ \] Evidence quotes present (real URLs)  
\- \[ \] Frequency noted ("very\_common", "occasional")  
\- \[ \] Actionable recommendations included

\#\#\# Avatar Quality  
\- \[ \] No generic personas ("budget-conscious buyer")  
\- \[ \] Specific demographics (age, income, occupation)  
\- \[ \] Complete empathy maps (all 6 sections)  
\- \[ \] Behavior gaps identified (says vs does)  
\- \[ \] 10+ evidence quotes with URLs

\#\#\# Success Story Quality  
\- \[ \] Revenue amounts stated (not vague "makes money")  
\- \[ \] Method explained (how they did it)  
\- \[ \] Proof provided or strongly implied  
\- \[ \] Credibility 6+ only  
\- \[ \] No duplicate stories

\---

\#\# ERROR HANDLING TESTS

\#\#\# Database Errors  
\- \[ \] Handles connection failures gracefully  
\- \[ \] SQL errors don't crash system  
\- \[ \] Returns meaningful error messages

\#\#\# API Errors  
\- \[ \] Claude API timeout handled  
\- \[ \] Rate limiting handled  
\- \[ \] Invalid JSON parsing handled  
\- \[ \] Returns partial results if some fail

\#\#\# Scraper Errors  
\- \[ \] Reddit API down → logs error, continues  
\- \[ \] Invalid subreddit → skips, continues  
\- \[ \] Rate limit hit → waits, retries

\---

\#\# PERFORMANCE TESTS

\#\#\# Response Times  
\- \[ \] Database query \< 1 second  
\- \[ \] Claude API call \< 30 seconds  
\- \[ \] Full brain execution \< 5 minutes (for 100 records)  
\- \[ \] Scraper processes 100 posts \< 2 minutes

\#\#\# Resource Usage  
\- \[ \] Python scripts don't leak memory  
\- \[ \] Database connections closed properly  
\- \[ \] No zombie processes after execution

\---

\#\# CONVERSATIONAL ASSISTANT TESTS

\#\#\# Query Capabilities  
\- \[ \] "What are the pain points?" → Returns insights  
\- \[ \] "Show me avatars" → Returns customer personas  
\- \[ \] "Find success stories about insurance" → Filters correctly  
\- \[ \] "Generate disruption report" → Orchestrates Market Strategist  
\- \[ \] "What offer should I create?" → Calls Offer Designer

\#\#\# Response Quality  
\- \[ \] Cites data sources (table, date)  
\- \[ \] Provides specific numbers/quotes  
\- \[ \] Actionable recommendations  
\- \[ \] No hallucinations (everything from DB)

\---

\#\# PHASE COMPLETION CRITERIA

\#\#\# Phase 1 Complete When:  
\- \[ \] Neon database accessible from Python and MCP  
\- \[ \] Reddit scraper saves data successfully  
\- \[ \] Can query database from Claude Desktop  
\- \[ \] All database tests pass

\#\#\# Phase 2 Complete When:  
\- \[ \] Research Analyst brain generates quality insights  
\- \[ \] Insights saved to database correctly  
\- \[ \] No generic outputs  
\- \[ \] All brain tests pass

\#\#\# Phase 3 Complete When:  
\- \[ \] Persona Architect creates 8-12 avatars  
\- \[ \] Success Story Hunter finds 5-10 stories weekly  
\- \[ \] Market Strategist generates 20-page report  
\- \[ \] All integration tests pass

\---

\#\# MANUAL VALIDATION

\#\#\# Human Review Required:  
\- \[ \] Read 5 sample insights → Are they specific enough?  
\- \[ \] Read 2 sample avatars → Do they feel real?  
\- \[ \] Read 3 success stories → Are they credible?  
\- \[ \] Read disruption report → Is it actionable?

\#\#\# Quality Bar:  
\- \*\*Insights:\*\* Would you pay $500 for this intelligence?  
\- \*\*Avatars:\*\* Could you sell to this persona based on the detail provided?  
\- \*\*Reports:\*\* Would a client see value in this analysis?

\---

\#\# REGRESSION TESTS (After Changes)

When modifying a brain:  
\- \[ \] Re-run all tests for that brain  
\- \[ \] Check downstream brains (do they still work with new output format?)  
\- \[ \] Verify database schema compatibility

When adding a new table:  
\- \[ \] Test foreign key relationships  
\- \[ \] Test JSON column queries  
\- \[ \] Update relevant brain prompts to consume new data

\---

\#\# NOTES

\*\*Test Frequency:\*\*  
\- Run database tests after every schema change  
\- Run brain tests after every prompt update  
\- Run integration tests weekly  
\- Run manual validation before marking any phase complete

\*\*Test Data:\*\*  
\- Use real exotic car rental Reddit data  
\- Don't test with synthetic/fake data (AI will pick up on it)  
\- Save "golden" test datasets for regression testing

\*\*Bug Tracking:\*\*  
\- Log all failed tests  
\- Track fixes in build-roadmap.md  
\- Re-test after fix before marking complete  
