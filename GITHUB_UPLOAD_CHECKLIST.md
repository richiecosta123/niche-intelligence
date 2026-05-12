# 📦 GitHub Upload Checklist

## ✅ What to Upload to GitHub

### Root Files
- [ ] `README.md` ← Comprehensive project overview
- [ ] `CHANGELOG.md` ← Version history
- [ ] `package.json` ← Node.js dependencies
- [ ] `tsconfig.json` ← TypeScript config
- [ ] `.env.example` ← Environment template (NO CREDENTIALS)
- [ ] `.gitignore` ← Git ignore rules
- [ ] `LICENSE` ← MIT License (if you want)

### `/schema/` - Database
- [ ] `niche-intel-schema.ts` ← 17 table definitions
- [ ] `migrate.ts` ← Database migration script
- [ ] `test-db.ts` ← Validation script
- [ ] `seed-exotic-car-niche.ts` ← Initial data seeder

### `/scrapers/` - Data Collection
- [ ] `reddit_browser_scraper.py` ← Playwright headless scraper
- [ ] `run_full_scrape.py` ← Multi-keyword orchestrator
- [ ] `requirements.txt` ← Python dependencies

### `/mcp-server/` - AI Brains
- [ ] `package.json` ← MCP dependencies
- [ ] `tsconfig.json` ← Node16 ESM config
- [ ] `src/index.ts` ← MCP server entry
- [ ] `src/run.ts` ← Standalone CLI runner
- [ ] `src/brains/prompts.ts` ← System prompts
- [ ] `src/brains/research-analyst.ts` ← Research brain logic
- [ ] `src/brains/persona-architect.ts` ← Persona brain logic

### `/prompts/` - Brain System Prompts
- [ ] `brain-prompts.md` ← All 9 brain system prompts
- [ ] `mcp-skill-template.ts` ← Code pattern for brains
- [ ] `exotic-car-rental-keywords.md` ← Search terms reference

### `/docs/` - Documentation
- [ ] `build-roadmap.md` ← Phased build plan
- [ ] `testing-checklist.md` ← QA checklist
- [ ] `STATUS_REPORT_v0_1_0.md` ← Database setup report
- [ ] `STATUS_REPORT_v0_1_1.md` ← Scraper deployment report
- [ ] `STATUS_REPORT_v0_2_0.md` ← Research Analyst brain report
- [ ] `PHASE_1_WEEK_2_COMPLETE.md` ← Week 2 completion summary

### `/examples/` - Sample Data
- [ ] `example-reddit-data.json` ← Sample Reddit data (sanitized)

---

## ❌ What NOT to Upload to GitHub

### Never Commit These:
- ❌ `.env` file (contains actual credentials)
- ❌ `node_modules/` folder (huge, auto-generated)
- ❌ `__pycache__/` folder (Python cache)
- ❌ Database backup files (.sql, .db)
- ❌ Any file with API keys or passwords
- ❌ Personal notes with sensitive info

### Your .gitignore Handles These Automatically
The `.gitignore` file prevents these from being committed accidentally.

---

## 🚀 Quick Upload Steps

### Option 1: Via GitHub Website (Easiest)

1. **Create PRIVATE repo on GitHub:**
   - Go to https://github.com/new
   - Name: `niche-intelligence`
   - Description: `Multi-Brain AI Market Intelligence System`
   - ⚠️ **CRITICAL: Select "Private"** ← This is proprietary! Your prompts, strategy, and intelligence methodology are competitive advantages
   - ✅ Do NOT check "Initialize with README" (we have one)
   - Click "Create repository"

2. **Upload files:**
   - Click "uploading an existing file"
   - Drag all files/folders from checklist above
   - Commit message: "Initial commit: Niche Intelligence Platform v0.3.0"
   - Click "Commit changes"

3. **Done!** Your PRIVATE repo is live and protected.

### Option 2: Via Command Line (If you have git)

```bash
# Navigate to your project folder
cd /path/to/your/niche-intelligence

# Initialize git
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Niche Intelligence Platform v0.3.0"

# Link to GitHub (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/niche-intelligence.git

# Push to GitHub
git branch -M main
git push -u origin main
```

---

## 🔒 Security Double-Check

Before uploading, verify NO credentials are included:

```bash
# Search for potential secrets
grep -r "sk-ant-" .
grep -r "postgresql://" .
grep -r "password" .
```

If any matches found in files you're uploading → REMOVE THEM!

**Safe references:**
- ✅ `ANTHROPIC_API_KEY=your_key_here` (in .env.example) ← Template only
- ❌ `ANTHROPIC_API_KEY=sk-ant-abc123...` (in .env) ← Real key, NEVER commit

---

## 📋 Final Checklist Before Upload

- [ ] `.env` file is NOT in upload list
- [ ] `.env.example` has placeholder values only (no real credentials)
- [ ] All documentation is up-to-date
- [ ] README.md is comprehensive
- [ ] CHANGELOG.md includes latest version
- [ ] No sensitive data in example files
- [ ] License file added (if desired)

---

## 🎯 What You'll Have on GitHub

Once uploaded, your GitHub repo will contain:

✅ **All code** (scrapers, MCP servers, migrations)  
✅ **All prompts** (brain system prompts, templates)  
✅ **All documentation** (roadmap, status reports, guides)  
✅ **Setup instructions** (README, .env.example)  
✅ **Version history** (CHANGELOG.md)  

❌ **No credentials** (database URL, API keys - safe in your local .env)  
❌ **No data** (insights/personas stay in Neon PostgreSQL)  

---

**Your intelligence (17 insights, 10 personas, 232 posts) stays safe in Neon PostgreSQL.**  
**GitHub gets your code, prompts, and documentation — everything needed to reproduce the system.**

Perfect separation! 🎉
