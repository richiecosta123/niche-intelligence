"""
Landing page scraper using Playwright.
Visits URLs from three sources and extracts pricing, headlines, CTAs, and copy.
Sources: competitor_ad_data.landing_page_url, authority_sources.content_hubs->primary_url,
         agency_benchmarks.website. Saves to raw_source_data with source_type='landing_page'.
"""

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
]

RE_PRICE = re.compile(r'\$[\d,]+(?:\.\d{2})?(?:\s*/\s*(?:day|night|week|month|hr|hour))?', re.IGNORECASE)


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_pending_urls(conn, niche_id: int, limit: int) -> list[dict]:
    """
    Return URLs not yet scraped (source_type='landing_page') from three sources:
      1. competitor_ad_data.landing_page_url  (filtered by niche_id)
      2. authority_sources.content_hubs->>'primary_url'  (global)
      3. agency_benchmarks.website  (global)
    Each item carries source_table and source_id for engagement_metrics tagging.
    """
    with conn.cursor() as cur:
        # Build a set of already-scraped URLs for this niche to skip duplicates.
        cur.execute(
            "SELECT source_url FROM raw_source_data WHERE source_type = 'landing_page' AND niche_id = %s",
            (niche_id,),
        )
        scraped: set[str] = {r[0] for r in cur.fetchall()}

        pending: list[dict] = []

        def normalize(u: str) -> str:
            return u if u.startswith('http') else 'https://' + u

        # 1. competitor_ad_data — scoped to niche_id
        cur.execute(
            """
            SELECT DISTINCT ON (landing_page_url)
                   id, competitor_name, landing_page_url
            FROM competitor_ad_data
            WHERE niche_id = %s
              AND landing_page_url IS NOT NULL
              AND landing_page_url != ''
            ORDER BY landing_page_url, last_seen_at DESC NULLS LAST
            """,
            (niche_id,),
        )
        for row in cur.fetchall():
            url = normalize(row[2])
            if url not in scraped:
                pending.append({
                    'url': url,
                    'label': row[1] or url,
                    'source_table': 'competitor_ad_data',
                    'source_id': row[0],
                })
                scraped.add(url)

        # 2. authority_sources — global; extract primary_url from content_hubs JSONB
        cur.execute(
            """
            SELECT id, firm_name, content_hubs->>'primary_url'
            FROM authority_sources
            WHERE content_hubs->>'primary_url' IS NOT NULL
              AND content_hubs->>'primary_url' != ''
            """
        )
        for row in cur.fetchall():
            url = normalize(row[2])
            if url not in scraped:
                pending.append({
                    'url': url,
                    'label': row[1] or url,
                    'source_table': 'authority_sources',
                    'source_id': row[0],
                })
                scraped.add(url)

        # 3. agency_benchmarks — global; plain text website column
        cur.execute(
            """
            SELECT id, agency_name, website
            FROM agency_benchmarks
            WHERE website IS NOT NULL
              AND website != ''
            """
        )
        for row in cur.fetchall():
            url = normalize(row[2])
            if url not in scraped:
                pending.append({
                    'url': url,
                    'label': row[1] or url,
                    'source_table': 'agency_benchmarks',
                    'source_id': row[0],
                })
                scraped.add(url)

    return pending[:limit]


def save_landing_page(
    conn,
    niche_id: int,
    url: str,
    title: str,
    extracted: dict,
    source_table: str,
    source_id: int,
):
    engagement_metrics = {'source_table': source_table, 'source_id': source_id}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_source_data
                (niche_id, source_type, source_url, title, content, raw_data, engagement_metrics)
            VALUES (%s, 'landing_page', %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                niche_id,
                url,
                title[:500],
                json.dumps(extracted),
                json.dumps(extracted),
                json.dumps(engagement_metrics),
            ),
        )
    conn.commit()


# ─── Extraction helpers ────────────────────────────────────────────────────────

async def safe_text(el) -> str:
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ''


async def extract_page_data(page) -> dict:
    """Extract all relevant content from the current page."""

    # Meta
    title = await page.title() or ''
    meta_desc = ''
    try:
        meta_el = await page.query_selector('meta[name="description"]')
        if meta_el:
            meta_desc = (await meta_el.get_attribute('content') or '').strip()
    except Exception:
        pass

    # Headings
    headings: dict[str, list[str]] = {'h1': [], 'h2': [], 'h3': []}
    for tag in ('h1', 'h2', 'h3'):
        els = await page.query_selector_all(tag)
        for el in els[:10]:
            t = await safe_text(el)
            if t:
                headings[tag].append(t[:300])

    # Hero: first visible h1 + first <p> near it as subheadline
    hero_headline = headings['h1'][0] if headings['h1'] else ''
    hero_sub = ''
    try:
        p_els = await page.query_selector_all('p')
        for p_el in p_els[:5]:
            t = await safe_text(p_el)
            if len(t) > 20:
                hero_sub = t[:300]
                break
    except Exception:
        pass

    # Pricing
    page_text = ''
    try:
        body_el = await page.query_selector('body')
        if body_el:
            page_text = await safe_text(body_el)
    except Exception:
        pass

    prices = list(dict.fromkeys(RE_PRICE.findall(page_text)))[:20]

    # Pricing plan names: look for common plan containers
    plan_names: list[str] = []
    try:
        plan_els = await page.query_selector_all(
            '[class*="plan"], [class*="tier"], [class*="price"], [class*="package"]'
        )
        for el in plan_els[:10]:
            t = await safe_text(el)
            first_line = t.split('\n')[0].strip()
            if first_line and len(first_line) < 60:
                plan_names.append(first_line)
        plan_names = list(dict.fromkeys(plan_names))[:8]
    except Exception:
        pass

    # CTAs: buttons and submit inputs
    ctas: list[str] = []
    try:
        btn_els = await page.query_selector_all('button, input[type="submit"], a[class*="btn"], a[class*="cta"]')
        for el in btn_els[:20]:
            t = await safe_text(el)
            if not t:
                t = (await el.get_attribute('value') or '').strip()
            if t and len(t) < 100 and t not in ctas:
                ctas.append(t)
        ctas = ctas[:15]
    except Exception:
        pass

    # Body copy: meaningful paragraphs, up to 1000 chars total
    body_copy = ''
    try:
        p_els = await page.query_selector_all('p')
        chunks: list[str] = []
        total = 0
        for p_el in p_els:
            t = await safe_text(p_el)
            if len(t) < 30:
                continue
            chunks.append(t)
            total += len(t)
            if total >= 1000:
                break
        body_copy = ' | '.join(chunks)[:1000]
    except Exception:
        pass

    return {
        'meta_description': meta_desc,
        'headings': headings,
        'hero': {
            'headline': hero_headline,
            'subheadline': hero_sub,
        },
        'pricing': {
            'price_mentions': prices,
            'plan_names': plan_names,
        },
        'ctas': ctas,
        'body_copy': body_copy,
    }


# ─── Main scrape loop ─────────────────────────────────────────────────────────

async def scrape(niche_id: int, limit: int, headless: bool):
    conn = get_db_connection()
    pending = get_pending_urls(conn, niche_id, limit)

    if not pending:
        logger.info("✅ No new landing pages to scrape.")
        conn.close()
        return {'new': 0, 'skipped': 0, 'errors': 0}

    logger.info(f"🌐 Found {len(pending)} landing pages to scrape")
    stats = {'new': 0, 'skipped': 0, 'errors': 0}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1280, 'height': 900},
            java_script_enabled=True,
        )
        page = await context.new_page()

        for i, item in enumerate(pending, 1):
            url = item['url']
            label = item['label']
            source_table = item['source_table']
            source_id = item['source_id']
            logger.info(f"[{i}/{len(pending)}] [{source_table}] {label[:50]} — {url[:80]}")

            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=20_000)
                await page.wait_for_timeout(1500)

                title = await page.title() or url
                extracted = await extract_page_data(page)

                save_landing_page(
                    conn, niche_id, url, title, extracted, source_table, source_id
                )

                logger.info(
                    f"  ✅ Saved | H1: {extracted['hero']['headline'][:60]!r} | "
                    f"Prices: {extracted['pricing']['price_mentions'][:3]} | "
                    f"CTAs: {extracted['ctas'][:3]}"
                )
                stats['new'] += 1

            except PlaywrightTimeoutError:
                logger.warning(f"  ⏱️  Timeout — skipping {url[:70]}")
                stats['skipped'] += 1
            except Exception as exc:
                logger.error(f"  ❌ Error scraping {url[:70]}: {exc}")
                stats['errors'] += 1

            if i < len(pending):
                await asyncio.sleep(random.uniform(3.0, 5.0))

        await browser.close()

    conn.close()

    logger.info(
        f"\n📊 Done: {stats['new']} saved | "
        f"{stats['skipped']} timed out | "
        f"{stats['errors']} errors"
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Landing page scraper')
    parser.add_argument('--niche-id', type=int, required=True)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--headless', action='store_true', default=False)
    args = parser.parse_args()

    asyncio.run(scrape(
        niche_id=args.niche_id,
        limit=args.limit,
        headless=args.headless,
    ))
