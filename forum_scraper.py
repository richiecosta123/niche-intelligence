#!/usr/bin/env python3
"""
Forum scraper for the niche intelligence platform.
Scrapes discussion threads from:
  - Fastlane Forum (XenForo) — exotic car / supercar rental
  - Warrior Forum (custom/vBulletin) — exotic car rental / car rental business
  - FerrariChat (XenForo) — rental
Saves to raw_source_data with source_type='forum_fastlane', etc.
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime

import psycopg2
from bs4 import BeautifulSoup
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

FASTLANE_BASE    = 'https://www.thefastlaneforum.com/community'
WARRIOR_BASE     = 'https://www.warriorforum.com'
FERRARICHAT_BASE = 'https://www.ferrarichat.com/forum'

FASTLANE_QUERIES    = ['exotic car rental', 'supercar rental']
WARRIOR_QUERIES     = ['exotic car rental', 'car rental business']
FERRARICHAT_QUERIES = ['car rental', 'rental']


# ─── Browser helpers ──────────────────────────────────────────────────────────

def human_delay(min_s: float = 2.0, max_s: float = 5.0):
    time.sleep(random.uniform(min_s, max_s))


def slow_scroll(page: Page, steps: int = 6):
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
    path = f'/tmp/forum_scraper_error_{label}_{ts}.png'
    try:
        page.screenshot(path=path)
        logger.error(f"   📸 Screenshot saved: {path}")
    except Exception as e:
        logger.error(f"   ❌ Screenshot failed: {e}")


def navigate_with_retry(page: Page, url: str,
                        wait_state: str = 'networkidle') -> bool:
    for attempt in range(2):
        try:
            page.goto(url, wait_until=wait_state, timeout=30000)
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Nav attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                human_delay(2, 4)
    return False


def dismiss_cookie_popup(page: Page):
    try:
        btn = page.locator(
            'button#onetrust-accept-btn-handler, '
            'button:has-text("Accept All"), '
            'button:has-text("Accept all cookies"), '
            'button:has-text("I Accept"), '
            'button:has-text("Agree")'
        ).first
        btn.wait_for(state='visible', timeout=5000)
        btn.click()
        logger.info("   🍪 Cookie popup dismissed")
        time.sleep(2)
    except Exception:
        pass


def is_login_wall(page: Page) -> bool:
    body = page.content().lower()
    signals = [
        'you must be logged in',
        'please login to view',
        'register to view',
        'log in or register to reply',
        'login required',
        'you must register',
        'must be a registered member',
        'members only',
    ]
    return any(s in body for s in signals)


# ─── Text utilities ───────────────────────────────────────────────────────────

def strip_html(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    text = soup.get_text(separator=' ')
    return re.sub(r'\s+', ' ', text).strip()


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


def save_thread(conn, niche_id: int, source_type: str, source_url: str,
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


# ─── XenForo helpers (Fastlane + FerrariChat) ─────────────────────────────────

def get_xenforo_thread_links(page: Page, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for sel in (
        '.structItem-title a[href*="/threads/"]',
        'h3.structItem-title a',
        'div.structItem a[href*="/threads/"]',
        'a[href*="/threads/"]',
    ):
        for el in page.locator(sel).all():
            href = el.get_attribute('href') or ''
            if not href or href in seen:
                continue
            if any(skip in href for skip in ('page-', '/members/', '/attachments/', 'goto', '#')):
                continue
            if href.startswith('/'):
                href = base_url.rstrip('/') + href
            elif not href.startswith('http'):
                continue
            seen.add(href)
            links.append(href)
        if links:
            break
    return links


def get_thread_title(page: Page) -> str:
    for sel in ('h1.p-title-value', 'h1[class*="title"]', '.threadTitle', 'h1'):
        el = page.locator(sel).first
        if el.count():
            title = el.inner_text().strip()
            if title:
                return title
    return ''


def extract_xenforo_thread(page: Page) -> dict:
    result = {'content': '', 'author': 'Unknown', 'date': '', 'replies': 0, 'views': 0}

    first_post = page.locator('article.message, .message').first
    if not first_post.count():
        return result

    for sel in (
        '.message-body .bbWrapper',
        '.message-userContent .bbWrapper',
        '.message-body',
        '.message-userContent',
    ):
        el = first_post.locator(sel).first
        if el.count():
            result['content'] = strip_html(el.inner_html())
            break

    for sel in ('.message-name a.username', '.message-name a', '.username', 'h4.message-name'):
        el = first_post.locator(sel).first
        if el.count():
            name = el.inner_text().strip()
            if name:
                result['author'] = name
                break

    time_el = first_post.locator('time[datetime]').first
    if time_el.count():
        dt = time_el.get_attribute('datetime') or ''
        result['date'] = dt[:10]

    for pair in page.locator('.pairs--justified, .pairJustified').all():
        label_el = pair.locator('.label, dt').first
        value_el = pair.locator('.value, dd').first
        if not label_el.count() or not value_el.count():
            continue
        label = label_el.inner_text().strip().lower()
        raw = re.sub(r'[^\d]', '', value_el.inner_text())
        if not raw:
            continue
        val = int(raw)
        if 'repl' in label:
            result['replies'] = val
        elif 'view' in label:
            result['views'] = val

    return result


# ─── Generic vBulletin/forum helpers (Warrior Forum) ──────────────────────────

_THREAD_URL_PATTERNS = [
    re.compile(r'/showthread\.php\?t=\d+'),
    re.compile(r'/\d{4,}-[\w-]+\.html'),
    re.compile(r'/threads?/[\w-]+-\d+'),
    re.compile(r'/topic/[\w-]+'),
    re.compile(r'/t/[\w-]+/\d+'),
]

_SKIP_URL_FRAGMENTS = (
    'member', 'user', 'profile', 'login', 'register',
    'search', 'javascript', 'mailto', '#', 'attachment',
    'forumdisplay', 'newthread', 'newreply',
)


def get_generic_thread_links(page: Page, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    soup = BeautifulSoup(page.content(), 'html.parser')

    for a in soup.find_all('a', href=True):
        href = a['href']
        if not href or href in seen:
            continue
        if any(skip in href.lower() for skip in _SKIP_URL_FRAGMENTS):
            continue
        if any(pat.search(href) for pat in _THREAD_URL_PATTERNS):
            if href.startswith('/'):
                href = base_url.rstrip('/') + href
            elif not href.startswith('http'):
                continue
            seen.add(href)
            links.append(href)

    return links


def extract_generic_thread(page: Page) -> dict:
    result = {'content': '', 'author': 'Unknown', 'date': '', 'replies': 0, 'views': 0}
    soup = BeautifulSoup(page.content(), 'html.parser')

    # Post body — ordered by specificity
    body_candidates = [
        soup.find(class_=re.compile(r'post-?content|postcontent|message-?body|postbody', re.I)),
        soup.find(class_=re.compile(r'post-?message|post-?text|messageText', re.I)),
        soup.find('blockquote', class_=re.compile(r'postcontent|restore', re.I)),
    ]
    post_body = next((c for c in body_candidates if c), None)

    # Fallback: first element with "post" in its class that has children
    if not post_body:
        for tag in soup.find_all(['article', 'div', 'li']):
            cls = ' '.join(tag.get('class', []))
            if re.search(r'\bpost\b', cls, re.I) and tag.find(['p', 'span']):
                post_body = tag
                break

    if post_body:
        for tag in post_body.find_all(['script', 'style']):
            tag.decompose()
        text = post_body.get_text(separator=' ')
        result['content'] = re.sub(r'\s+', ' ', text).strip()

    # Author
    for sel in [
        re.compile(r'username|author|poster|postauthor', re.I),
        re.compile(r'userinfo', re.I),
    ]:
        el = soup.find(class_=sel)
        if el:
            name = el.get_text().strip()
            if name and len(name) < 60:
                result['author'] = name.splitlines()[0].strip()
                break

    # Date
    for el in soup.find_all(True, class_=re.compile(r'date|time|when|postdate', re.I)):
        dt = el.get('datetime') or el.get('title') or el.get_text()
        dt = dt.strip() if dt else ''
        if re.search(r'\d{4}', dt):
            result['date'] = dt[:20]
            break

    # Replies / views from page text
    page_text = soup.get_text()
    for pattern, key in [
        (r'Replies?[:\s]+(\d[\d,]*)', 'replies'),
        (r'Views?[:\s]+([\d,]+)', 'views'),
    ]:
        m = re.search(pattern, page_text, re.I)
        if m:
            result[key] = int(m.group(1).replace(',', ''))

    return result


# ─── Per-thread processing (shared logic) ─────────────────────────────────────

def _process_thread(
    page: Page, conn, url: str,
    niche_id: int, source_type: str, forum_name: str,
    use_xenforo: bool,
) -> str:
    """Navigate to a thread, extract data, save. Returns 'saved'/'dupe'/'skip'/'error'."""

    if is_duplicate(conn, url):
        return 'dupe'

    logger.info(f"   📖 {url}")
    human_delay(2.0, 4.5)

    if not navigate_with_retry(page, url):
        take_error_screenshot(page, f'{source_type}_{abs(hash(url)) % 9999}')
        return 'error'

    dismiss_cookie_popup(page)

    if is_login_wall(page):
        logger.info("   🔒 Login wall — skipping")
        return 'skip'

    slow_scroll(page, steps=4)
    title = get_thread_title(page)
    data = extract_xenforo_thread(page) if use_xenforo else extract_generic_thread(page)

    # XenForo fallback to generic
    if use_xenforo and not data['content']:
        data = extract_generic_thread(page)

    if not data['content']:
        logger.warning("   ⚠️  No content extracted — skipping")
        return 'error'

    try:
        save_thread(conn, niche_id, source_type, url, data['content'], {
            'title': title,
            'author': data['author'],
            'replies': data['replies'],
            'views': data['views'],
            'date': data['date'],
            'forum_name': forum_name,
        })
        logger.info(f"   ✅ Saved: {title[:70]}")
        return 'saved'
    except Exception as e:
        logger.error(f"   ❌ DB error: {e}")
        return 'error'


def _tally(stats: dict, outcome: str):
    mapping = {'saved': 'new', 'dupe': 'duplicates', 'skip': 'skipped', 'error': 'errors'}
    stats[mapping.get(outcome, 'errors')] += 1


# ─── Fastlane Forum ───────────────────────────────────────────────────────────

def scrape_fastlane(page: Page, conn, niche_id: int, limit: int) -> dict:
    stats = {'new': 0, 'duplicates': 0, 'errors': 0, 'skipped': 0}
    pool: list[str] = []
    seen: set[str] = set()

    logger.info(f"🚗 Fastlane Forum — up to {limit} threads")

    for query in FASTLANE_QUERIES:
        if len(pool) >= limit * 2:
            break
        encoded = query.replace(' ', '+')
        search_url = f"{FASTLANE_BASE}/search/?q={encoded}&t=thread&o=date"
        logger.info(f"   🔍 Query: '{query}'")

        if not navigate_with_retry(page, search_url):
            take_error_screenshot(page, 'fastlane_search')
            continue

        dismiss_cookie_popup(page)
        random_mouse_move(page)
        slow_scroll(page, steps=4)
        human_delay(1.5, 3.0)

        links = get_xenforo_thread_links(page, FASTLANE_BASE)
        new = [l for l in links if l not in seen]
        seen.update(new)
        pool.extend(new)
        logger.info(f"   📋 {len(new)} new links (pool: {len(pool)})")

    for url in pool[:limit * 2]:
        if stats['new'] >= limit:
            break
        outcome = _process_thread(
            page, conn, url, niche_id,
            'forum_fastlane', 'Fastlane Forum', use_xenforo=True,
        )
        _tally(stats, outcome)

    return stats


# ─── Warrior Forum ────────────────────────────────────────────────────────────

def scrape_warrior(page: Page, conn, niche_id: int, limit: int) -> dict:
    stats = {'new': 0, 'duplicates': 0, 'errors': 0, 'skipped': 0}
    pool: list[str] = []
    seen: set[str] = set()

    logger.info(f"⚔️  Warrior Forum — up to {limit} threads")

    for query in WARRIOR_QUERIES:
        if len(pool) >= limit * 2:
            break
        encoded = query.replace(' ', '+')
        search_url = f"{WARRIOR_BASE}/search?q={encoded}"
        logger.info(f"   🔍 Query: '{query}'")

        if not navigate_with_retry(page, search_url):
            take_error_screenshot(page, 'warrior_search')
            continue

        dismiss_cookie_popup(page)
        random_mouse_move(page)
        slow_scroll(page, steps=4)
        human_delay(1.5, 3.0)

        # Try XenForo selectors first, fall back to generic pattern matching
        links = get_xenforo_thread_links(page, WARRIOR_BASE)
        if not links:
            links = get_generic_thread_links(page, WARRIOR_BASE)

        new = [l for l in links if l not in seen]
        seen.update(new)
        pool.extend(new)
        logger.info(f"   📋 {len(new)} new links (pool: {len(pool)})")

    for url in pool[:limit * 2]:
        if stats['new'] >= limit:
            break
        outcome = _process_thread(
            page, conn, url, niche_id,
            'forum_warrior', 'Warrior Forum', use_xenforo=False,
        )
        _tally(stats, outcome)

    return stats


# ─── FerrariChat ──────────────────────────────────────────────────────────────

def scrape_ferrarichat(page: Page, conn, niche_id: int, limit: int) -> dict:
    stats = {'new': 0, 'duplicates': 0, 'errors': 0, 'skipped': 0}
    pool: list[str] = []
    seen: set[str] = set()

    logger.info(f"🏎️  FerrariChat — up to {limit} threads")

    for query in FERRARICHAT_QUERIES:
        if len(pool) >= limit * 2:
            break
        encoded = query.replace(' ', '+')
        search_url = f"{FERRARICHAT_BASE}/search/?q={encoded}&t=thread&o=date"
        logger.info(f"   🔍 Query: '{query}'")

        if not navigate_with_retry(page, search_url):
            take_error_screenshot(page, 'ferrarichat_search')
            continue

        dismiss_cookie_popup(page)
        random_mouse_move(page)
        slow_scroll(page, steps=4)
        human_delay(1.5, 3.0)

        links = get_xenforo_thread_links(page, FERRARICHAT_BASE)
        new = [l for l in links if l not in seen]
        seen.update(new)
        pool.extend(new)
        logger.info(f"   📋 {len(new)} new links (pool: {len(pool)})")

    for url in pool[:limit * 2]:
        if stats['new'] >= limit:
            break
        outcome = _process_thread(
            page, conn, url, niche_id,
            'forum_ferrarichat', 'FerrariChat', use_xenforo=True,
        )
        _tally(stats, outcome)

    return stats


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def scrape_forums(niche_id: int, forum: str, limit: int):
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
            if forum in ('fastlane', 'all'):
                logger.info("\n" + "─" * 60)
                totals['fastlane'] = scrape_fastlane(page, conn, niche_id, limit)

            if forum in ('warrior', 'all'):
                logger.info("\n" + "─" * 60)
                totals['warrior'] = scrape_warrior(page, conn, niche_id, limit)

            if forum in ('ferrarichat', 'all'):
                logger.info("\n" + "─" * 60)
                totals['ferrarichat'] = scrape_ferrarichat(page, conn, niche_id, limit)

        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            take_error_screenshot(page, 'fatal')
        finally:
            browser.close()

    conn.close()

    logger.info("\n" + "═" * 60)
    logger.info("📊 SUMMARY")
    logger.info("─" * 60)
    grand = {'new': 0, 'duplicates': 0, 'errors': 0, 'skipped': 0}
    for f, s in totals.items():
        logger.info(
            f"   {f.capitalize():15} — "
            f"{s['new']:3} new | "
            f"{s['duplicates']:3} dupes | "
            f"{s['errors']:3} errors | "
            f"{s['skipped']:3} skipped"
        )
        for k in grand:
            grand[k] += s.get(k, 0)
    logger.info("─" * 60)
    logger.info(
        f"   {'TOTAL':15} — "
        f"{grand['new']:3} new | "
        f"{grand['duplicates']:3} dupes | "
        f"{grand['errors']:3} errors | "
        f"{grand['skipped']:3} skipped"
    )
    logger.info("═" * 60)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Forum scraper — Fastlane, Warrior, FerrariChat (Playwright headed)'
    )
    parser.add_argument('--niche-id', type=int, default=1,
                        help='Niche ID to tag threads with (default: 1)')
    parser.add_argument('--forum', choices=['fastlane', 'warrior', 'ferrarichat', 'all'],
                        default='all', help='Forum to scrape (default: all)')
    parser.add_argument('--limit', type=int, default=20,
                        help='Max threads per forum (default: 20)')
    args = parser.parse_args()

    logger.info(
        f"🚀 Forum Scraper — "
        f"niche_id={args.niche_id}, forum={args.forum}, limit={args.limit}"
    )
    scrape_forums(args.niche_id, args.forum, args.limit)


if __name__ == '__main__':
    main()
