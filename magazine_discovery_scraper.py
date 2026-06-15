"""
Magazine discovery scraper using Playwright.
Visits configured magazine source/category pages and extracts candidate
article links (+ titles, + dates where available). New URLs (not already
present in raw_source_data for the niche, any source_type) are inserted as
source_type='newsletter_pending' so the existing email_intelligence_scraper.py
pipeline picks them up for content extraction.
"""

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import psycopg2
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from landing_page_scraper import normalize_url, random_delay

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

ARTICLE_PATH_RE = re.compile(r'/(articles|news|blogposts|digital-cover-features)/')

MAGAZINES = [
    {
        'name': 'Auto Rental News',
        'url': 'https://www.autorentalnews.com/',
        'method': 'top_links',
        'section': 'homepage',
        'max_items': 8,
    },
    {
        'name': 'Luxury Daily',
        'url': 'https://www.luxurydaily.com/category/sectors/automotive-industry-sectors/',
        'method': 'dated_listing',
        'section': 'automotive-industry-sectors',
        'max_age_days': 7,
    },
]


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_existing_urls(conn, niche_id: int) -> set[str]:
    """Normalized (trailing-slash-stripped) source_urls already present for this niche."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_url FROM raw_source_data WHERE niche_id = %s AND source_url IS NOT NULL",
            (niche_id,),
        )
        return {normalize_url(r[0]).rstrip('/') for r in cur.fetchall() if r[0]}


def save_pending(conn, niche_id: int, url: str, title: str, magazine_name: str, section: str):
    metrics = {
        'magazine_name': magazine_name,
        'discovery_method': 'magazine_scrape',
        'section': section,
        'discovered_at': datetime.now(timezone.utc).isoformat(),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_source_data (niche_id, source_type, source_url, title, engagement_metrics)
            VALUES (%s, 'newsletter_pending', %s, %s, %s)
            """,
            (niche_id, url, title[:500], json.dumps(metrics)),
        )
    conn.commit()


# ─── Extraction helpers ────────────────────────────────────────────────────────

async def safe_text(el) -> str:
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ''


def is_real_headline(text: str) -> bool:
    """Filter out nav/category labels: require length > 15 and at least one
    lowercase letter (nav labels here are typically short or ALL CAPS)."""
    text = text.strip()
    return len(text) > 15 and bool(re.search(r'[a-z]', text))


async def extract_top_links(page, base_url: str, max_items: int) -> list[dict]:
    """Auto Rental News homepage: <a> tags whose href matches one of the
    article path patterns and whose text looks like a real headline. The
    same href is often linked multiple times with different label variants
    (numbered tiles, category-prefixed labels); pick the shortest qualifying
    text as the cleanest headline."""
    seen_order: list[str] = []
    candidates: dict[str, list[str]] = {}

    els = await page.query_selector_all('a[href]')
    for el in els:
        href = (await el.get_attribute('href') or '').strip()
        if not href:
            continue
        abs_url = normalize_url(urljoin(base_url, href)).rstrip('/')
        if not ARTICLE_PATH_RE.search(abs_url):
            continue

        text = await safe_text(el)
        if abs_url not in candidates:
            candidates[abs_url] = []
            seen_order.append(abs_url)
        if text:
            candidates[abs_url].append(text)

    results: list[dict] = []
    for url in seen_order:
        headline_texts = [t for t in candidates[url] if is_real_headline(t)]
        if not headline_texts:
            continue
        title = min(headline_texts, key=len)
        results.append({'url': url, 'title': title, 'date': None})
        if len(results) >= max_items:
            break

    return results


def parse_listing_date(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), '%B %d, %Y').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def extract_dated_listing(page, base_url: str, max_age_days: int) -> list[dict]:
    """Luxury Daily category listing: each article is a div.newsbox containing
    an <h6><a> headline link and a span.thicken date ('June 12, 2026')."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    results: list[dict] = []

    boxes = await page.query_selector_all('div.newsbox')
    for box in boxes:
        link_el = await box.query_selector('h6 a')
        if not link_el:
            continue

        href = (await link_el.get_attribute('href') or '').strip()
        title = await safe_text(link_el)
        if not href or not title:
            continue

        date_el = await box.query_selector('span.thicken')
        date_text = (await safe_text(date_el)) if date_el else ''
        published = parse_listing_date(date_text)
        if published is None or published < cutoff:
            continue

        abs_url = normalize_url(urljoin(base_url, href)).rstrip('/')
        results.append({'url': abs_url, 'title': title, 'date': published.date().isoformat()})

    return results


# ─── Main scrape loop ─────────────────────────────────────────────────────────

async def scrape(niche_id: int, headless: bool, test: bool):
    conn = get_db_connection()
    existing = get_existing_urls(conn, niche_id)

    mode = " [TEST MODE — no DB writes]" if test else ""
    logger.info(f"🔎 Magazine discovery for niche {niche_id}{mode}")
    stats = {'discovered': 0, 'new': 0, 'duplicates': 0}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)

        for i, magazine in enumerate(MAGAZINES, 1):
            logger.info(f"[{i}/{len(MAGAZINES)}] {magazine['name']} — {magazine['url']}")

            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={'width': 1280, 'height': 900},
                java_script_enabled=True,
            )
            page = await context.new_page()

            try:
                response = await page.goto(magazine['url'], wait_until='domcontentloaded', timeout=20_000)
                if response is not None and response.status >= 400:
                    raise ValueError(f"HTTP {response.status}")

                try:
                    await page.wait_for_load_state('networkidle', timeout=10_000)
                except PlaywrightTimeoutError:
                    pass
                await random_delay(2.0, 3.0)

                if magazine['method'] == 'top_links':
                    candidates = await extract_top_links(page, magazine['url'], magazine['max_items'])
                else:
                    candidates = await extract_dated_listing(page, magazine['url'], magazine['max_age_days'])

                logger.info(f"  Found {len(candidates)} candidate article(s)")

                for item in candidates:
                    stats['discovered'] += 1
                    url = item['url']
                    title = item['title']
                    date_suffix = f" | {item['date']}" if item['date'] else ""

                    if url in existing:
                        stats['duplicates'] += 1
                        logger.info(f"  ⏭️  Skip (exists): {title[:60]!r}")
                        continue

                    existing.add(url)
                    stats['new'] += 1

                    if test:
                        logger.info(f"  🆕 [TEST] {title[:70]!r}{date_suffix} | {url}")
                    else:
                        save_pending(conn, niche_id, url, title, magazine['name'], magazine['section'])
                        logger.info(f"  ✅ Saved: {title[:60]!r}{date_suffix} | {url}")

            except PlaywrightTimeoutError:
                logger.warning(f"  ⏱️  Timeout — {magazine['url']}")
            except Exception as exc:
                logger.error(f"  ❌ Error: {exc} — {magazine['url']}")
            finally:
                await context.close()

            if i < len(MAGAZINES):
                await random_delay(8.0, 15.0)

        await browser.close()

    conn.close()

    logger.info(
        f"\n📊 Done{mode}: {stats['discovered']} found | "
        f"{stats['new']} new | {stats['duplicates']} duplicates"
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Magazine discovery scraper')
    parser.add_argument('--niche-id', type=int, required=True)
    parser.add_argument('--headless', action='store_true', default=False)
    parser.add_argument('--test', action='store_true',
                         help='Print discovered URLs without DB writes')
    args = parser.parse_args()

    asyncio.run(scrape(
        niche_id=args.niche_id,
        headless=args.headless,
        test=args.test,
    ))
