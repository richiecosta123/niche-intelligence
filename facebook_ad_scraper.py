"""
Facebook Ad Library scraper using Playwright.
Tracks individual competitor ads over time using upsert logic on ad_id.
No API credentials required — uses the public Ad Library.

Usage:
  python facebook_ad_scraper.py --niche-id 1 --competitor "Hertz Dream Cars"
  python facebook_ad_scraper.py --niche-id 1 --competitor "Gotham Dream Cars" --country US --max-ads 100
  python facebook_ad_scraper.py --niche-id 1 --competitors "Hertz,Gotham Dream Cars,Exotic Car Rental Miami"
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

FB_AD_LIBRARY_BASE = 'https://www.facebook.com/ads/library/'

# Patterns for extracting structured data from ad card text
RE_LIBRARY_ID = re.compile(r'Library ID[:\s#]+(\d{10,})', re.IGNORECASE)
RE_RUNNING_SINCE = re.compile(
    r'Started running on\s+([A-Z][a-z]+ \d{1,2},\s*\d{4})',
    re.IGNORECASE,
)
RE_RUNNING_SINCE_SHORT = re.compile(
    r'Started running on\s+(\d{1,2}/\d{1,2}/\d{2,4})',
    re.IGNORECASE,
)


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def upsert_ad(conn, ad: dict, niche_id: int) -> str:
    """
    Insert a new ad or update last_seen_at if ad_id already exists for
    this niche + platform. Returns 'inserted' or 'updated'.
    """
    with conn.cursor() as cur:
        if ad.get('ad_id'):
            cur.execute(
                """
                SELECT id FROM competitor_ad_data
                WHERE niche_id = %s AND platform = %s AND ad_id = %s
                LIMIT 1
                """,
                (niche_id, ad['platform'], ad['ad_id']),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE competitor_ad_data
                    SET last_seen_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (row[0],),
                )
                conn.commit()
                return 'updated'

        cur.execute(
            """
            INSERT INTO competitor_ad_data
                (niche_id, competitor_name, platform, ad_id, ad_type,
                 headline, body_text, cta, media_url, landing_page_url,
                 running_since, last_seen_at, ad_metadata,
                 created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s,
                 %s, NOW(), %s,
                 NOW(), NOW())
            """,
            (
                niche_id,
                ad['competitor_name'],
                ad['platform'],
                ad.get('ad_id'),
                ad.get('ad_type'),
                ad.get('headline'),
                ad.get('body_text'),
                ad.get('cta'),
                ad.get('media_url'),
                ad.get('landing_page_url'),
                ad.get('running_since'),
                json.dumps(ad.get('metadata', {})),
            ),
        )
    conn.commit()
    return 'inserted'


# ─── Parsing helpers ──────────────────────────────────────────────────────────

def parse_running_since(text: str) -> datetime | None:
    """Parse 'Started running on Month DD, YYYY' or MM/DD/YY from card text."""
    m = RE_RUNNING_SINCE.search(text)
    if m:
        raw = m.group(1).strip()
        for fmt in ('%B %d, %Y', '%b %d, %Y'):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    m = RE_RUNNING_SINCE_SHORT.search(text)
    if m:
        raw = m.group(1).strip()
        for fmt in ('%m/%d/%Y', '%m/%d/%y'):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    return None


def extract_library_id(text: str) -> str | None:
    m = RE_LIBRARY_ID.search(text)
    return m.group(1) if m else None


async def random_delay(min_s: float = 1.5, max_s: float = 3.5):
    await asyncio.sleep(random.uniform(min_s, max_s))


# ─── Ad card extraction ───────────────────────────────────────────────────────

async def extract_cards(page, competitor_name: str) -> list[dict]:
    """
    Pull structured data from all currently-visible ad cards on the page.
    Uses JavaScript evaluation for reliability against React's synthetic DOM.
    """
    cards = await page.evaluate("""
        () => {
            const results = [];

            // Facebook renders ad cards in various container patterns.
            // We search for elements containing the "Library ID" marker text
            // which is reliably present on every card.
            const allDivs = Array.from(document.querySelectorAll('div'));

            // Find leaf containers that hold an individual ad
            const cardDivs = allDivs.filter(div => {
                const txt = div.innerText || '';
                return txt.includes('Library ID') && txt.length < 5000;
            });

            for (const card of cardDivs) {
                const text = card.innerText || '';

                // Skip if this is a parent container that holds multiple Library IDs
                const idMatches = (text.match(/Library ID/gi) || []).length;
                if (idMatches > 1) continue;

                // Headline: first <strong> or largest bold text in the card
                let headline = '';
                const strongs = card.querySelectorAll('strong, h1, h2, h3, h4');
                for (const el of strongs) {
                    const t = (el.innerText || '').trim();
                    if (t.length > 5 && t.length < 200) {
                        headline = t;
                        break;
                    }
                }

                // Body: longest text block that isn't the headline or metadata
                let bodyText = '';
                const spans = card.querySelectorAll('span, p, div');
                for (const el of spans) {
                    if (el.children.length > 3) continue; // skip container divs
                    const t = (el.innerText || '').trim();
                    if (
                        t.length > bodyText.length &&
                        t.length > 30 &&
                        t.length < 2000 &&
                        !t.includes('Library ID') &&
                        !t.includes('Started running') &&
                        t !== headline
                    ) {
                        bodyText = t;
                    }
                }

                // CTA button text
                let cta = '';
                const buttons = card.querySelectorAll('a[role="button"], button, a');
                const ctaKeywords = [
                    'Learn More', 'Sign Up', 'Shop Now', 'Book Now', 'Contact Us',
                    'Get Quote', 'Apply Now', 'Subscribe', 'Download', 'Get Started',
                    'Reserve', 'Schedule', 'Call Now', 'Message', 'Watch More',
                ];
                for (const btn of buttons) {
                    const t = (btn.innerText || '').trim();
                    if (ctaKeywords.some(k => t.toLowerCase().includes(k.toLowerCase()))) {
                        cta = t;
                        break;
                    }
                }

                // Media URL: first img src or video src
                let mediaUrl = '';
                const img = card.querySelector('img[src*="facebook"], img[src*="fbcdn"]');
                if (img) mediaUrl = img.src;
                if (!mediaUrl) {
                    const video = card.querySelector('video source, video');
                    if (video) mediaUrl = video.src || video.currentSrc || '';
                }

                // Landing page: link that goes outside facebook.com
                let landingPageUrl = '';
                const links = card.querySelectorAll('a[href]');
                for (const link of links) {
                    const href = link.href || '';
                    if (href && !href.includes('facebook.com') && href.startsWith('http')) {
                        landingPageUrl = href;
                        break;
                    }
                }

                // Ad type hint from media
                let adType = 'image';
                if (card.querySelector('video')) adType = 'video';
                if (card.querySelectorAll('img').length > 2) adType = 'carousel';

                results.push({
                    rawText: text,
                    headline: headline,
                    bodyText: bodyText,
                    cta: cta,
                    mediaUrl: mediaUrl,
                    landingPageUrl: landingPageUrl,
                    adType: adType,
                });
            }
            return results;
        }
    """)

    ads = []
    for card in cards:
        raw_text = card.get('rawText', '')
        library_id = extract_library_id(raw_text)
        running_since = parse_running_since(raw_text)

        ad = {
            'competitor_name': competitor_name,
            'platform': 'facebook',
            'ad_id': library_id,
            'ad_type': card.get('adType', 'image'),
            'headline': card.get('headline') or None,
            'body_text': card.get('bodyText') or None,
            'cta': card.get('cta') or None,
            'media_url': card.get('mediaUrl') or None,
            'landing_page_url': card.get('landingPageUrl') or None,
            'running_since': running_since,
            'metadata': {'raw_text_length': len(raw_text)},
        }
        ads.append(ad)

    return ads


# ─── Page interaction ─────────────────────────────────────────────────────────

async def dismiss_dialogs(page):
    """Dismiss cookie consent and login prompts if they appear."""
    # Cookie / GDPR consent buttons
    consent_selectors = [
        'button[data-cookiebanner="accept_button"]',
        'button[title="Accept All"]',
        'button:has-text("Accept All")',
        'button:has-text("Allow all cookies")',
        '[aria-label="Allow all cookies"]',
    ]
    for sel in consent_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                logger.info('Dismissed cookie consent')
                await random_delay(1, 2)
                break
        except Exception:
            pass

    # Login / signup wall — close it if present
    close_selectors = [
        '[aria-label="Close"]',
        'div[role="dialog"] button:has-text("Close")',
        'div[role="dialog"] [aria-label="Close"]',
    ]
    for sel in close_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                logger.info('Closed login dialog')
                await random_delay(1, 2)
                break
        except Exception:
            pass


async def scroll_and_load(page, target_count: int, seen_ids: set) -> list[dict]:
    """
    Scroll the page repeatedly, extracting new ads on each pass.
    Stops when target_count unique ad_ids are found or no new ads appear after 3 attempts.
    """
    all_ads = []
    stale_rounds = 0
    max_stale = 3
    scroll_pause = 2.5

    while len(all_ads) < target_count and stale_rounds < max_stale:
        cards = await extract_cards(page, competitor_name='')  # name patched by caller
        new_this_round = 0

        for card in cards:
            ad_id = card.get('ad_id')
            # Deduplicate within this run by ad_id (or by headline+body if no ID)
            dedup_key = ad_id or f"{card.get('headline','')[:50]}|{card.get('body_text','')[:50]}"
            if dedup_key not in seen_ids:
                seen_ids.add(dedup_key)
                all_ads.append(card)
                new_this_round += 1

        if new_this_round == 0:
            stale_rounds += 1
            logger.debug(f'No new ads found (stale round {stale_rounds}/{max_stale})')
        else:
            stale_rounds = 0
            logger.info(f'  Found {new_this_round} new ads this scroll (total: {len(all_ads)})')

        if len(all_ads) >= target_count:
            break

        # Scroll down
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await asyncio.sleep(scroll_pause)

        # Click "See More" / "Load more" buttons if present
        try:
            more_btn = page.locator(
                'div[role="button"]:has-text("See More Ads"), '
                'button:has-text("Load more"), '
                'div[role="button"]:has-text("Load More")'
            ).first
            if await more_btn.is_visible(timeout=1500):
                await more_btn.click()
                await asyncio.sleep(2)
        except Exception:
            pass

    return all_ads


# ─── Main scraping logic ──────────────────────────────────────────────────────

async def scrape_competitor(
    page,
    competitor_name: str,
    country: str,
    max_ads: int,
    conn,
    niche_id: int,
) -> dict:
    """Scrape all ads for a single competitor and upsert to DB."""
    encoded = quote(competitor_name)
    url = (
        f"{FB_AD_LIBRARY_BASE}"
        f"?active_status=all&ad_type=all&country={country}"
        f"&q={encoded}&search_type=keyword_unordered"
    )

    logger.info(f'Scraping: {competitor_name}')
    logger.info(f'URL: {url}')

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)
    except PlaywrightTimeoutError:
        logger.warning('Page load timeout — continuing with partial content')

    await random_delay(2, 4)
    await dismiss_dialogs(page)
    await random_delay(1, 2)

    # Wait for ad cards to appear
    try:
        await page.wait_for_selector(
            'div:has-text("Library ID")',
            timeout=15_000,
        )
    except PlaywrightTimeoutError:
        logger.warning(f'No ads found for "{competitor_name}" — may require login or page has no ads')
        return {'inserted': 0, 'updated': 0, 'skipped': 0}

    seen_ids: set = set()
    ads = await scroll_and_load(page, max_ads, seen_ids)

    # Patch competitor name (scroll_and_load uses blank placeholder)
    for ad in ads:
        ad['competitor_name'] = competitor_name

    inserted = updated = skipped = 0
    for ad in ads[:max_ads]:
        if not ad.get('ad_id') and not ad.get('headline') and not ad.get('body_text'):
            skipped += 1
            continue
        try:
            result = upsert_ad(conn, ad, niche_id)
            if result == 'inserted':
                inserted += 1
            else:
                updated += 1
        except Exception as exc:
            logger.error(f'DB error for ad {ad.get("ad_id")}: {exc}')
            conn.rollback()
            skipped += 1

    logger.info(
        f'  {competitor_name}: {inserted} inserted, {updated} updated, {skipped} skipped'
    )
    return {'inserted': inserted, 'updated': updated, 'skipped': skipped}


# ─── CLI entry point ──────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description='Facebook Ad Library scraper')
    parser.add_argument('--niche-id', type=int, required=True, help='DB niche ID')
    parser.add_argument('--competitor', type=str, help='Single competitor/page name to search')
    parser.add_argument(
        '--competitors',
        type=str,
        help='Comma-separated list of competitor names',
    )
    parser.add_argument('--country', type=str, default='US', help='Ad Library country code (default: US)')
    parser.add_argument('--max-ads', type=int, default=50, help='Max ads per competitor (default: 50)')
    parser.add_argument('--headless', action='store_true', default=False, help='Run browser headlessly')
    return parser.parse_args()


async def main():
    args = parse_args()

    if not args.competitor and not args.competitors:
        logger.error('Provide --competitor or --competitors')
        sys.exit(1)

    competitors = []
    if args.competitors:
        competitors = [c.strip() for c in args.competitors.split(',') if c.strip()]
    if args.competitor:
        competitors.append(args.competitor.strip())

    competitors = list(dict.fromkeys(competitors))  # dedupe, preserve order
    logger.info(f'Competitors to scrape: {competitors}')
    logger.info(f'Niche ID: {args.niche_id} | Country: {args.country} | Max ads: {args.max_ads}')

    conn = get_db_connection()

    totals = {'inserted': 0, 'updated': 0, 'skipped': 0}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=args.headless,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
        )
        # Mask automation signals
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = await context.new_page()

        for competitor in competitors:
            result = await scrape_competitor(
                page=page,
                competitor_name=competitor,
                country=args.country,
                max_ads=args.max_ads,
                conn=conn,
                niche_id=args.niche_id,
            )
            for k in totals:
                totals[k] += result[k]

            if len(competitors) > 1:
                await random_delay(3, 6)

        await browser.close()

    conn.close()

    logger.info('\n=== Run complete ===')
    logger.info(f"Total inserted : {totals['inserted']}")
    logger.info(f"Total updated  : {totals['updated']}")
    logger.info(f"Total skipped  : {totals['skipped']}")


if __name__ == '__main__':
    asyncio.run(main())
