# Example Brain Output

When you run `npm run run-brain -- --dry-run --limit 50`, you will see:

```
🧠 Research Analyst Brain
   Niche : Exotic Car Rental (id=2)
   Limit : 50 posts
   Mode  : DRY RUN (no DB writes)

  📌 Resuming from post id > 0
  📄 Fetched 50 posts (ids 1–50)
  🤖 Calling Claude (claude-sonnet-4-6)...
  ✨ Claude returned 12 insights

  [DRY RUN] Would save these insights:
    [pain_point] Rental damage fees charged without mechanic invoices
    [pain_point] Deposit holds freeze $2k+ for 2 weeks post-rental
    [buying_trigger] Birthday/bachelor party milestone drives rental decision
    [buying_trigger] Content creators need exotic backdrop for YouTube/Instagram
    [objection] "What if I get a scratch?" anxiety prevents first-time renters
    [objection] Age restrictions (25+) block younger affluent renters on Turo
    [language_pattern] "Dream car" framing dominates rental motivation language
    [language_pattern] Renters call it "experiencing" not "renting" the car
    [competitor_gap] No transparent damage-fee escrow service exists yet
    [competitor_gap] No managed exotic rental for owners who want passive income
    [market_timing] Vegas demand spikes during F1, NFR, and fight weekends
    [market_timing] Content creator demand highest Q4 (end-of-year wrap videos)

═══════════════════════════════════════════════
📊 RESULTS
═══════════════════════════════════════════════
  Posts processed   : 50
  Insights created  : 12

  Category breakdown:
    buying_trigger       2
    competitor_gap       2
    language_pattern     2
    market_timing        2
    objection            2
    pain_point           2

  Sample insights (first 3):

  ┌─ [pain_point] Rental damage fees charged without mechanic invoices
  │  Confidence : 0.9  |  Sources : 14  |  Actionable: true
  │  Renters and owners both report exotic car companies inflating repair bills
  │  with zero supporting documentation, creating post-rental disputes.
  │  Quote: "I asked Jasen repeatedly for the actual mechanic invoice and never received it..."
  └─ Tags: trust, transparency, damage, billing, disputes

  ┌─ [buying_trigger] Birthday/bachelor party milestone drives rental decision
  │  Confidence : 0.87  |  Sources : 22  |  Actionable: true
  │  Life events (birthdays, bachelor parties, proposals) are the #1 stated reason
  │  for renting; customers are buying a "once-in-a-lifetime" memory, not transport.
  │  Quote: "Rented a Lambo for my 30th — it was the best day of my life honestly..."
  └─ Tags: occasions, emotion, milestone, birthday, marketing

  ┌─ [competitor_gap] No managed exotic rental service for car owners
  │  Confidence : 0.75  |  Sources : 8  |  Actionable: true
  │  Multiple exotic car owners want to monetise their cars on Turo but fear damage
  │  and lack management support. No trusted white-glove management layer exists.
  │  Quote: "I gave my Lamborghini to VSSR to rent to guests under a management
  │  agreement — it was a nightmare..."
  └─ Tags: owner, turo, management, passive-income, opportunity
═══════════════════════════════════════════════
```

## Run for real (after adding API key)

```bash
# Add key to parent .env
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> /Users/ricardo/niche-intelligence/.env

# Dry-run first (no DB writes)
npm run run-brain -- --dry-run --limit 50

# Live run — saves to insights table
npm run run-brain -- --limit 100

# Then query the DB
```

## Database verification queries

```sql
-- Count by category
SELECT insight_type AS category, COUNT(*) AS count
FROM insights
WHERE niche_id = 2
GROUP BY insight_type
ORDER BY count DESC;

-- Top insights by confidence
SELECT insight_type, title, confidence_score,
       (source_ids::json)::text AS source_count
FROM insights
WHERE niche_id = 2
ORDER BY confidence_score DESC
LIMIT 10;

-- Sample insight body
SELECT title, body, tags
FROM insights
WHERE niche_id = 2
ORDER BY created_at DESC
LIMIT 3;
```
