#!/usr/bin/env python3
"""
Review scraper for the niche intelligence platform.
- Trustpilot: scrapes Turo.com reviews via headed Playwright browser
- Yelp: searches "exotic car rental" in major cities via headed Playwright browser
- Saves to raw_source_data with source_type='trustpilot' or 'yelp'
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BROWSER_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
)

YELP_CITIES = [
    ('Los Angeles', 'CA'),
    ('Miami', 'FL'),
    ('Las Vegas', 'NV'),
    ('New York', 'NY'),
]


# ─── Human-like browser helpers ───────────────────────────────────────────────

def human_delay(min_s: float = 2.0, max_s: float = 5.0):
    time.sleep(random.uniform(min_s, max_s))


def slow_scroll(page: Page, steps: int = 8):
    """Scroll down gradually to trigger lazy-loaded content."""
    for _ in range(steps):
        page.evaluate(f"window.scrollBy(0, {random.randint(180, 380)})")
        time.sleep(random.uniform(0.3, 0.7))


def random_mouse_move(page: Page):
    x = random.randint(200, 1700)
    y = random.randint(100, 900)
    page.mouse.move(x, y)
    time.sleep(random.uniform(0.1, 0.3))


def take_error_screenshot(page: Page, label: str = ''):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = f'/tmp/review_scraper_error_{label}_{ts}.png'
    try:
        page.screenshot(path=path)
        logger.error(f"   📸 Screenshot saved: {path}")
    except Exception as e:
        logger.error(f"   ❌ Screenshot failed: {e}")


def dismiss_cookie_popup(page: Page):
    """Click Trustpilot's cookie consent popup if it appears."""
    try:
        btn = page.locator(
            'button#onetrust-accept-btn-handler, '
            'button:has-text("Accept All")'
        ).first
        btn.wait_for(state='visible', timeout=5000)
        btn.click()
        logger.info("   🍪 Cookie popup dismissed")
        time.sleep(2)
    except Exception:
        pass


def navigate_with_retry(page: Page, url: str,
                        wait_state: str = 'networkidle') -> bool:
    """Navigate to URL, retrying once on failure."""
    for attempt in range(2):
        try:
            page.goto(url, wait_until=wait_state, timeout=30000)
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Navigation attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                human_delay(2, 4)
    return False


# ─── JSON helpers (used for Yelp JSON-LD extraction) ─────────────────────────

def extract_json_ld(html: str) -> list[dict]:
    results = []
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    ):
        try:
            results.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    return results


def find_in_dict(data, key: str) -> list:
    results = []
    if isinstance(data, dict):
        if key in data:
            results.append(data[key])
        for v in data.values():
            results.extend(find_in_dict(v, key))
    elif isinstance(data, list):
        for item in data:
            results.extend(find_in_dict(item, key))
    return results


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def is_duplicate(conn, source_url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM raw_source_data WHERE source_url = %s LIMIT 1",
            (source_url,)
        )
        return cur.fetchone() is not None


def save_review(conn, niche_id: int, source_type: str, source_url: str,
                content: str, meta: dict):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO raw_source_data
                (niche_id, source_type, source_url, content, raw_data)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            niche_id,
            source_type,
            source_url,
            content[:5000],
            json.dumps(meta),
        ))
    conn.commit()


# ─── Trustpilot ───────────────────────────────────────────────────────────────

def _extract_rating_from_card(card) -> int:
    """Pull star rating from a Trustpilot review card locator."""
    rating_el = card.locator('[data-service-review-rating]').first
    if rating_el.count():
        attr = rating_el.get_attribute('data-service-review-rating') or ''
        try:
            return int(attr)
        except ValueError:
            pass
        # Fallback: star image alt text e.g. "Rated 4 out of 5 stars"
        star_img = rating_el.locator('img').first
        if star_img.count():
            alt = star_img.get_attribute('alt') or ''
            m = re.search(r'(\d+)', alt)
            if m:
                return int(m.group(1))
    return 0


def _extract_reviewer_from_card(card) -> str:
    """Try several selectors to get the reviewer display name."""
    for sel in (
        '[data-consumer-name-typography]',
        'span[class*="consumerName"]',
        'aside span',
        'div[class*="consumer"] span',
    ):
        el = card.locator(sel).first
        if el.count():
            name = el.inner_text().strip()
            if name:
                return name
    return 'Anonymous'


def scrape_trustpilot(page: Page, conn, niche_id: int, limit: int) -> dict:
    stats = {'new': 0, 'duplicates': 0, 'errors': 0}
    base_url = 'https://www.trustpilot.com/review/turo.com'
    page_num = 1

    logger.info(f"🌟 Scraping Trustpilot — turo.com (up to {limit} reviews)")

    while stats['new'] + stats['duplicates'] < limit:
        url = f"{base_url}?page={page_num}" if page_num > 1 else base_url
        logger.info(f"   📄 Page {page_num} — {url}")

        if not navigate_with_retry(page, url):
            take_error_screenshot(page, f'trustpilot_p{page_num}')
            break

        dismiss_cookie_popup(page)
        random_mouse_move(page)
        slow_scroll(page, steps=8)
        human_delay(1.0, 2.5)

        cards = page.locator('[data-service-review-card-paper]').all()
        logger.info(f"   📝 Found {len(cards)} review cards")

        if not cards:
            take_error_screenshot(page, f'trustpilot_nocards_p{page_num}')
            logger.warning("   ⚠️  No review cards — page may be blocked or structure changed")
            break

        added_this_page = 0
        for card in cards:
            if stats['new'] + stats['duplicates'] >= limit:
                break
            try:
                text_el = card.locator('[data-service-review-text-typography]').first
                if not text_el.count():
                    continue
                text = text_el.inner_text().strip()
                if not text:
                    continue

                rating = _extract_rating_from_card(card)
                reviewer = _extract_reviewer_from_card(card)

                date_str = ''
                date_el = card.locator('[data-service-review-date-time-ago]').first
                if date_el.count():
                    date_str = date_el.get_attribute('datetime') or date_el.inner_text()
                    if date_str and 'T' in date_str:
                        date_str = date_str[:10]

                review_url = f"{base_url}#review-{hash(text) % 10000000}"

                if is_duplicate(conn, review_url):
                    stats['duplicates'] += 1
                    continue

                save_review(
                    conn, niche_id, 'trustpilot', review_url, text,
                    {
                        'platform': 'trustpilot',
                        'reviewer': reviewer,
                        'rating': rating,
                        'date': date_str,
                        'business_name': 'Turo',
                        'helpful_votes': 0,
                    }
                )
                stats['new'] += 1
                added_this_page += 1

            except Exception as e:
                logger.error(f"   ❌ Card error: {e}")
                stats['errors'] += 1

        logger.info(
            f"   ✅ Page {page_num} — {added_this_page} new | "
            f"{stats['duplicates']} dupes so far"
        )

        # Pagination: look for Next page button/link
        next_btn = page.locator(
            'a[data-pagination-button-next-link], '
            'button[aria-label="Next page"], '
            'a[aria-label="Next page"]'
        ).first
        if not next_btn.count() or stats['new'] + stats['duplicates'] >= limit:
            break

        human_delay(2.0, 4.0)
        next_btn.click()
        page.wait_for_load_state('networkidle')
        page_num += 1

    return stats


# ─── Yelp ─────────────────────────────────────────────────────────────────────

def scrape_yelp_city(page: Page, conn, niche_id: int,
                     city: str, state: str, limit: int) -> dict:
    stats = {'new': 0, 'duplicates': 0, 'errors': 0}
    location = f"{city}, {state}"
    url = (
        f"https://www.yelp.com/search"
        f"?find_desc=exotic+car+rental"
        f"&find_loc={city.replace(' ', '+')}%2C+{state}"
    )

    logger.info(f"   🏙️  {location}")

    if not navigate_with_retry(page, url):
        take_error_screenshot(page, f'yelp_{city.lower().replace(" ", "_")}')
        return stats

    slow_scroll(page, steps=5)
    random_mouse_move(page)
    human_delay(1.0, 3.0)

    # Collect business links from search results
    business_urls: list[str] = []
    seen: set[str] = set()
    for el in page.locator('a[href*="/biz/"]').all():
        href = el.get_attribute('href') or ''
        if href in seen or not href:
            continue
        seen.add(href)
        if any(x in href for x in ('?', 'writeareview', 'not_recommended')):
            continue
        full = f"https://www.yelp.com{href}" if href.startswith('/') else href
        business_urls.append(full)
        if len(business_urls) >= 5:
            break

    if not business_urls:
        logger.warning(f"   ⚠️  No businesses found for {location}")
        take_error_screenshot(page, f'yelp_{city.lower().replace(" ", "_")}_nobiz')
        return stats

    logger.info(f"   📍 Found {len(business_urls)} businesses in {location}")

    for biz_url in business_urls[:3]:
        if stats['new'] >= limit:
            break

        logger.info(f"   🏢 Visiting: {biz_url}")
        human_delay(2.0, 4.0)

        if not navigate_with_retry(page, biz_url):
            take_error_screenshot(page, f'yelp_biz_{hash(biz_url) % 10000}')
            continue

        slow_scroll(page, steps=6)
        human_delay(1.0, 2.5)

        name_el = page.locator('h1').first
        business_name = name_el.inner_text().strip() if name_el.count() else 'Unknown'
        reviews_extracted = 0

        # Strategy 1: JSON-LD embedded in rendered page source
        html = page.content()
        for block in extract_json_ld(html):
            review_list = block.get('review', [])
            if not review_list and block.get('@type') == 'Review':
                review_list = [block]
            for rev in review_list:
                if stats['new'] >= limit:
                    break
                text = (rev.get('reviewBody') or rev.get('description') or '').strip()
                if not text:
                    continue
                rating = (rev.get('reviewRating') or {}).get('ratingValue', 0)
                author = (rev.get('author') or {}).get('name', 'Anonymous')
                date_str = rev.get('datePublished', '')
                review_url = f"{biz_url}#review-{author.lower().replace(' ', '-')}"

                if is_duplicate(conn, review_url):
                    stats['duplicates'] += 1
                    continue
                try:
                    save_review(
                        conn, niche_id, 'yelp', review_url, text,
                        {
                            'platform': 'yelp',
                            'business_name': business_name,
                            'reviewer': author,
                            'rating': float(rating) if rating else 0,
                            'date': date_str[:10] if date_str else '',
                            'city': location,
                            'helpful_votes': 0,
                        }
                    )
                    stats['new'] += 1
                    reviews_extracted += 1
                except Exception as e:
                    logger.error(f"   ❌ DB error: {e}")
                    stats['errors'] += 1

        # Strategy 2: Playwright DOM selectors on rendered content
        if reviews_extracted == 0:
            els = page.locator(
                '[class*="review"] p, [data-review-id] p, li[class*="review"] p'
            ).all()
            for el in els[:10]:
                text = el.inner_text().strip()
                if len(text) < 30:
                    continue
                review_url = f"{biz_url}#dom-{hash(text) % 10000000}"
                if is_duplicate(conn, review_url):
                    stats['duplicates'] += 1
                    continue
                try:
                    save_review(
                        conn, niche_id, 'yelp', review_url, text,
                        {
                            'platform': 'yelp',
                            'business_name': business_name,
                            'reviewer': 'Unknown',
                            'rating': 0,
                            'date': '',
                            'city': location,
                            'helpful_votes': 0,
                        }
                    )
                    stats['new'] += 1
                    reviews_extracted += 1
                except Exception as e:
                    logger.error(f"   ❌ DB error: {e}")
                    stats['errors'] += 1

        logger.info(f"   ✅ {business_name}: {reviews_extracted} reviews saved")

    return stats


def scrape_yelp(page: Page, conn, niche_id: int, limit: int) -> dict:
    total = {'new': 0, 'duplicates': 0, 'errors': 0}
    per_city = max(1, limit // len(YELP_CITIES))

    logger.info(f"⭐ Scraping Yelp — {len(YELP_CITIES)} cities, ~{per_city} reviews each")

    for city, state in YELP_CITIES:
        city_stats = scrape_yelp_city(page, conn, niche_id, city, state, per_city)
        for k in total:
            total[k] += city_stats.get(k, 0)

    return total


# ─── Main orchestrator ────────────────────────────────────────────────────────

def scrape_reviews(niche_id: int, platform: str, limit: int):
    totals: dict[str, dict] = {}

    try:
        conn = get_db_connection()
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")
        return

    with sync_playwright() as pw:
        logger.info("🌐 Launching Chromium (headed mode)...")
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=BROWSER_UA,
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/Los_Angeles',
        )
        page = context.new_page()

        try:
            if platform in ('trustpilot', 'all'):
                logger.info("\n" + "─" * 60)
                totals['trustpilot'] = scrape_trustpilot(page, conn, niche_id, limit)

            if platform in ('yelp', 'all'):
                logger.info("\n" + "─" * 60)
                totals['yelp'] = scrape_yelp(page, conn, niche_id, limit)

        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            take_error_screenshot(page, 'fatal')
        finally:
            browser.close()

    conn.close()

    logger.info("\n" + "═" * 60)
    logger.info("📊 SUMMARY")
    logger.info("─" * 60)
    grand_new = grand_dupes = grand_errors = 0
    for plat, stats in totals.items():
        logger.info(
            f"   {plat.capitalize():12} — "
            f"{stats['new']:3} new | "
            f"{stats['duplicates']:3} dupes | "
            f"{stats['errors']:3} errors"
        )
        grand_new += stats['new']
        grand_dupes += stats['duplicates']
        grand_errors += stats['errors']
    logger.info("─" * 60)
    logger.info(
        f"   {'TOTAL':12} — "
        f"{grand_new:3} new | "
        f"{grand_dupes:3} dupes | "
        f"{grand_errors:3} errors"
    )
    logger.info("═" * 60)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Review scraper for Trustpilot and Yelp (Playwright headed mode)'
    )
    parser.add_argument(
        '--niche-id', type=int, default=1,
        help='Niche ID to tag reviews with (default: 1)'
    )
    parser.add_argument(
        '--platform', choices=['trustpilot', 'yelp', 'all'], default='all',
        help='Platform to scrape (default: all)'
    )
    parser.add_argument(
        '--limit', type=int, default=50,
        help='Max reviews per platform (default: 50)'
    )
    args = parser.parse_args()

    logger.info(
        f"🚀 Review Scraper — "
        f"niche_id={args.niche_id}, platform={args.platform}, limit={args.limit}"
    )
    scrape_reviews(args.niche_id, args.platform, args.limit)


if __name__ == '__main__':
    main()
