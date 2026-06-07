"""
Google Ads Transparency Center scraper — agency_benchmarks and authority_sources.

Search strategy (per target):
  1. Load the Transparency Center search results for `name`
  2. Find the best-matching advertiser result link (/advertiser/{id})
  3. Navigate to the advertiser detail page for clean, single-advertiser results
  4. Fallback: extract from the keyword search results page if no advertiser page found

Merges results into agency_benchmarks.meta_ads (JSONB) and
authority_sources.paid_amplification (TEXT) — preserves existing Meta data.

Usage:
  python google_ads_scraper.py --type all --limit 50
  python google_ads_scraper.py --type agency --limit 10
  python google_ads_scraper.py --type authority
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from urllib.parse import quote

import psycopg2
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
]

GOOGLE_ADS_BASE = 'https://adstransparency.google.com/'


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_targets(conn, target_type: str) -> list[dict]:
    targets = []
    with conn.cursor() as cur:
        if target_type in ('agency', 'all'):
            cur.execute("SELECT id, agency_name, website FROM agency_benchmarks ORDER BY id")
            for row in cur.fetchall():
                targets.append({
                    'id': row[0], 'name': row[1], 'website': row[2],
                    'table': 'agency_benchmarks',
                })
        if target_type in ('authority', 'all'):
            cur.execute("SELECT id, firm_name FROM authority_sources ORDER BY id")
            for row in cur.fetchall():
                targets.append({
                    'id': row[0], 'name': row[1], 'website': None,
                    'table': 'authority_sources',
                })
    return targets


def merge_and_save(conn, target: dict, new_data: dict):
    """Merge Google Ads data into existing column without overwriting Meta data."""
    with conn.cursor() as cur:
        if target['table'] == 'agency_benchmarks':
            cur.execute(
                """
                UPDATE agency_benchmarks
                SET meta_ads = COALESCE(meta_ads, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (json.dumps(new_data), target['id']),
            )
        else:
            cur.execute(
                "SELECT paid_amplification FROM authority_sources WHERE id = %s",
                (target['id'],),
            )
            row = cur.fetchone()
            existing: dict = {}
            if row and row[0]:
                try:
                    existing = json.loads(row[0])
                    if not isinstance(existing, dict):
                        existing = {'legacy': existing}
                except Exception:
                    existing = {'legacy_text': row[0]}
            merged = {**existing, **new_data}
            cur.execute(
                "UPDATE authority_sources SET paid_amplification = %s WHERE id = %s",
                (json.dumps(merged), target['id']),
            )
    conn.commit()


def seed_landing_page_urls(conn, urls: list[str], target: dict, found_via: str):
    if not urls:
        return
    with conn.cursor() as cur:
        for url in urls:
            cur.execute(
                """
                INSERT INTO raw_source_data
                    (niche_id, source_type, source_url, title, content, engagement_metrics)
                VALUES (1, 'landing_page_url_candidate', %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    url,
                    f"{target['name']} ad landing page",
                    f"Landing page URL discovered via {found_via} for {target['name']}",
                    json.dumps({
                        'source_table': target['table'],
                        'source_id': target['id'],
                        'found_via': found_via,
                    }),
                ),
            )
    conn.commit()


# ─── Browser helpers ───────────────────────────────────────────────────────────

async def random_delay(min_s: float = 5.0, max_s: float = 10.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def dismiss_dialogs(page):
    for sel in [
        'button:has-text("Accept all")',
        'button:has-text("I agree")',
        'button[aria-label="Accept all"]',
        'form[action*="consent"] button',
        'button:has-text("Agree")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await asyncio.sleep(1.5)
                break
        except Exception:
            pass


# ─── Advertiser page lookup ────────────────────────────────────────────────────

async def find_advertiser_url(page, name: str) -> str | None:
    """
    Load the Transparency Center search for `name` and return the URL of the
    best-matching advertiser detail page (/advertiser/{id}).

    After this call, the browser is on the search results page. If an advertiser
    URL is returned, the caller should navigate to it. If None is returned,
    the caller should extract results directly from this page (keyword fallback).
    """
    search_url = f"{GOOGLE_ADS_BASE}?region=anywhere&query={quote(name)}"
    logger.info(f"  [advertiser lookup] {search_url}")

    try:
        await page.goto(search_url, wait_until='domcontentloaded', timeout=30_000)
    except PlaywrightTimeoutError:
        logger.warning("  Page load timeout during advertiser lookup")
        return None

    await asyncio.sleep(random.uniform(2, 3))
    await dismiss_dialogs(page)
    await asyncio.sleep(2)

    # Score each /advertiser/ link by how many words from `name` appear in its container
    target_words = json.dumps([w.lower() for w in name.split() if len(w) > 2])

    advertiser_url: str | None = await page.evaluate(
        f"""
        () => {{
            const targetWords = {target_words};

            // Advertiser results link to /advertiser/{{id}} paths
            const links = Array.from(document.querySelectorAll('a[href*="/advertiser/"]'));
            const candidates = [];

            for (const link of links) {{
                const href = link.href || '';
                if (!href.includes('/advertiser/')) continue;

                const container =
                    link.closest('[class*="result"]') ||
                    link.closest('[class*="advertiser"]') ||
                    link.closest('li') ||
                    link.parentElement;
                const text = (
                    (container?.innerText || '') + ' ' + (link.innerText || '')
                ).toLowerCase();

                const score = targetWords.filter(w => text.includes(w)).length;
                candidates.push({{ href, score }});
            }}

            if (!candidates.length) return null;
            candidates.sort((a, b) => b.score - a.score);

            // Only use the result if at least one target word matched
            const best = candidates[0];
            return best.score > 0 ? best.href : (candidates.length === 1 ? best.href : null);
        }}
        """
    )

    if advertiser_url:
        logger.info(f"  Found advertiser page: {advertiser_url}")
    else:
        logger.info(f"  No advertiser page found for {name!r} — will use keyword results")

    return advertiser_url or None


# ─── Ad extraction ─────────────────────────────────────────────────────────────

# Landing URL extractor for Google Ads Transparency — collects all external links
# that aren't Google properties, which on advertiser pages are ad destinations.
_GOOGLE_LANDING_URL_JS = """
    () => {
        const seen = new Set();
        const urls = [];
        const blocked = [
            'google.com', 'gstatic.com', 'googleapis.com',
            'youtube.com', 'blogger.com', 'doubleclick.net',
        ];

        document.querySelectorAll('a[href]').forEach(link => {
            const href = link.href || '';
            if (!href.startsWith('http')) return;
            if (blocked.some(d => href.includes(d))) return;
            if (!seen.has(href)) {
                seen.add(href);
                urls.push(href);
            }
        });

        return urls.slice(0, 30);
    }
"""

_GOOGLE_AD_CARDS_JS = """
    () => {
        const results = [];

        // Advertiser detail page — ad cards use class patterns like creative-preview,
        // ad-creative, or similar. We try common selectors then fall back to text blocks.
        const cardSelectors = [
            '[class*="ad-creative"]',
            '[class*="creative-preview"]',
            '[class*="ad-card"]',
            '[class*="creative"]',
            '[data-index]',
        ];

        let cards = [];
        for (const sel of cardSelectors) {
            cards = Array.from(document.querySelectorAll(sel))
                        .filter(el => (el.innerText || '').length > 10);
            if (cards.length > 0) break;
        }

        for (const card of cards.slice(0, 30)) {
            const text = (card.innerText || card.textContent || '').trim();
            if (!text || text.length < 5) continue;

            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
            const headline = lines[0] || '';
            const description = lines.slice(1, 4).join(' ').slice(0, 300);

            let adFormat = 'text';
            if (card.querySelector('img, video')) adFormat = 'display';
            if (card.querySelector('video')) adFormat = 'video';

            if (headline.length > 3) {
                results.push({ headline, description, adFormat });
            }
        }

        // Fallback: generic text blocks if no structured cards found
        if (results.length === 0) {
            const blocks = Array.from(document.querySelectorAll('h1, h2, h3, p'));
            for (const el of blocks.slice(0, 20)) {
                const t = (el.innerText || '').trim();
                if (t.length > 10 && t.length < 300) {
                    results.push({ headline: t, description: '', adFormat: 'text' });
                }
            }
        }

        return results.slice(0, 20);
    }
"""


async def extract_google_ads(page, search_name: str) -> dict:
    await asyncio.sleep(1.5)

    try:
        cards_data: list[dict] = await page.evaluate(_GOOGLE_AD_CARDS_JS)
    except Exception as exc:
        logger.warning(f"  JS card extraction error: {exc}")
        cards_data = []

    try:
        landing_urls: list[str] = await page.evaluate(_GOOGLE_LANDING_URL_JS)
    except Exception as exc:
        logger.warning(f"  JS landing URL extraction error: {exc}")
        landing_urls = []

    # Check for empty-state text
    ads_found = bool(cards_data)
    try:
        body = await page.query_selector('body')
        if body:
            body_text = (await body.inner_text()).lower()
            if 'no results' in body_text or 'no ads' in body_text:
                ads_found = False
    except Exception:
        pass

    ads = [
        {
            'headline': c.get('headline') or None,
            'description': c.get('description') or None,
            'ad_format': c.get('adFormat', 'text'),
        }
        for c in cards_data
    ]

    return {
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'source': 'google_ads_transparency',
        'search_name': search_name,
        'ads_found': ads_found,
        'ad_count_found': len(ads),
        'ads': ads,
        'landing_page_urls': landing_urls,
    }


# ─── Main search orchestrator ──────────────────────────────────────────────────

async def search_transparency_center(page, name: str) -> dict:
    """
    1. Search for `name` on Google Ads Transparency Center.
    2. If an advertiser page is found, navigate there for clean results.
    3. Otherwise extract from the keyword search results page directly.
    """
    # find_advertiser_url loads the search page and returns the best /advertiser/ URL.
    # After the call, the browser is already on the search results page.
    advertiser_url = await find_advertiser_url(page, name)

    if advertiser_url:
        # Navigate to the clean advertiser page
        logger.info(f"  [ad fetch] {advertiser_url}")
        try:
            await page.goto(advertiser_url, wait_until='domcontentloaded', timeout=30_000)
        except PlaywrightTimeoutError:
            logger.warning("  Advertiser page load timeout — falling back to search results")
            advertiser_url = None

        if advertiser_url:
            await asyncio.sleep(random.uniform(1.5, 2.5))
            await dismiss_dialogs(page)
            await asyncio.sleep(1)
            search_method = 'advertiser_page'
    else:
        # Already on the search results page from find_advertiser_url — use it
        search_method = 'keyword_fallback'
        logger.info(f"  Using keyword search results page directly")

    # Wait for ad content or empty state
    try:
        await page.wait_for_selector(
            '[class*="ad-creative"], [class*="creative-preview"], [class*="ad-card"], '
            '[class*="result"], [class*="no-result"], [class*="empty"]',
            timeout=12_000,
        )
    except PlaywrightTimeoutError:
        logger.warning(f"  Content selector not found for {name!r}")

    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(2)

    result = await extract_google_ads(page, name)
    result['search_method'] = search_method
    if advertiser_url:
        result['advertiser_url'] = advertiser_url
    return result


# ─── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description='Google Ads Transparency scraper for agencies and authority sources'
    )
    parser.add_argument('--type', choices=['agency', 'authority', 'all'], default='all')
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()

    conn = get_db_connection()
    targets = get_targets(conn, args.type)[:args.limit]

    if not targets:
        logger.info("No targets found")
        conn.close()
        return

    logger.info(f"Targets: {len(targets)} | Type: {args.type} | Limit: {args.limit}")
    stats = {'saved': 0, 'errors': 0, 'landing_urls': 0, 'advertiser_hits': 0}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = await context.new_page()

        for i, target in enumerate(targets, 1):
            logger.info(f"\n[{i}/{len(targets)}] [{target['table']}] {target['name']}")
            try:
                results = await search_transparency_center(page, target['name'])
                landing_urls = results.get('landing_page_urls', [])

                merge_and_save(conn, target, results)
                seed_landing_page_urls(conn, landing_urls, target, 'google_ads')

                stats['saved'] += 1
                stats['landing_urls'] += len(landing_urls)
                if results.get('search_method') == 'advertiser_page':
                    stats['advertiser_hits'] += 1

                logger.info(
                    f"  Saved | method={results['search_method']} "
                    f"| ads={results['ad_count_found']} "
                    f"| landing_urls={len(landing_urls)}"
                )
            except Exception as exc:
                logger.error(f"  Error: {exc}")
                stats['errors'] += 1
                try:
                    conn.rollback()
                except Exception:
                    pass

            if i < len(targets):
                await random_delay(5, 10)

        await browser.close()

    conn.close()
    logger.info(
        f"\n=== Done: {stats['saved']} saved | {stats['errors']} errors | "
        f"{stats['advertiser_hits']} advertiser page hits | "
        f"{stats['landing_urls']} landing URLs seeded ==="
    )


if __name__ == '__main__':
    asyncio.run(main())
