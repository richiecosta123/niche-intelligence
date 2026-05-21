#!/usr/bin/env python3
"""
Forum discovery for the niche intelligence platform.
Searches Google to find forums active for a given keyword, visits each
candidate, estimates thread depth, and writes a JSON report.

Usage:
    python forum_discovery.py --keyword "exotic car rental"
    python forum_discovery.py --keyword "exotic car rental" --min-results 10
"""

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Page, sync_playwright

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

# URL fragments that suggest a forum (used to filter Google results)
FORUM_SIGNALS = ('forum', 'community', 'board', 'discuss', 'bbs', 'subreddit', 'talk')

# Domains to exclude from forum candidates
EXCLUDE_DOMAINS = (
    'google.', 'youtube.', 'facebook.', 'twitter.', 'instagram.',
    'amazon.', 'linkedin.', 'yelp.', 'trustpilot.', 'wikipedia.',
    'reddit.com/r/',  # individual subreddit pages — keep reddit.com/search
    'quora.', 'pinterest.', 'tiktok.', 'ebay.', 'etsy.',
)

# Search URL templates to try per forum, most specific first
SEARCH_TEMPLATES = [
    '{base}/search/?q={q}&t=thread&o=date',           # XenForo (date-sorted)
    '{base}/search/?q={q}&t=thread',                  # XenForo
    '{base}/search/?q={q}',                           # XenForo / Discourse
    '{base}/search?q={q}',                            # Discourse / generic
    '{base}/search?query={q}',                        # generic
    '{base}/search.php?query={q}',                    # vBulletin
    '{base}/search.php?keywords={q}&searchsubmit=1',  # phpBB
    '{base}/search.php?action=do_search&keywords={q}',# MyBB
    '{base}/?s={q}',                                  # WordPress
    '{base}/index.php?action=search2&search={q}',     # SMF
]

# CSS selectors that indicate real thread/topic content
THREAD_SELECTORS = (
    'a[href*="/threads/"]',
    'a[href*="/topic/"]',
    'a[href*="showthread"]',
    '[class*="structItem"]',
    '[class*="ThreadListItem"]',
    '[class*="thread-item"]',
    '[class*="topic-item"]',
    '[class*="post-row"]',
    '.search-result',
    'tr.search-result',
    '[class*="searchResult"]',
    '[class*="search_result"]',
)

# Google search queries — multiple to maximise forum discovery
GOOGLE_QUERIES = [
    '{kw} forum',
    '{kw} discussion board site:forum OR site:community',
    '{kw} community site:*.forum',
]


# ─── Browser helpers ──────────────────────────────────────────────────────────

def human_delay(min_s: float = 1.5, max_s: float = 3.5):
    time.sleep(random.uniform(min_s, max_s))


def slow_scroll(page: Page, steps: int = 4):
    for _ in range(steps):
        page.evaluate(f"window.scrollBy(0, {random.randint(200, 400)})")
        time.sleep(random.uniform(0.3, 0.6))


def random_mouse_move(page: Page):
    page.mouse.move(random.randint(200, 1700), random.randint(100, 900))
    time.sleep(random.uniform(0.1, 0.3))


def navigate_with_retry(page: Page, url: str,
                        wait_state: str = 'networkidle') -> bool:
    for attempt in range(2):
        try:
            page.goto(url, wait_until=wait_state, timeout=25000)
            return True
        except Exception as e:
            logger.warning(f"   ⚠️  Nav attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                human_delay(2, 4)
    return False


def dismiss_popup(page: Page):
    """Dismiss cookie / consent popups, including Google's."""
    candidates = [
        'button#onetrust-accept-btn-handler',
        'button#L2AGLb',           # Google "Accept all" (English)
        'button#accept-choices',
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        'button:has-text("I agree")',
        'button:has-text("Agree")',
        'button:has-text("Consent")',
        'button:has-text("OK")',
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click()
                time.sleep(1.5)
                return
        except Exception:
            pass


def is_captcha_page(page: Page) -> bool:
    url = page.url.lower()
    body = page.content().lower()
    return 'recaptcha' in body or '/sorry/' in url or 'captcha' in url


# ─── URL utilities ────────────────────────────────────────────────────────────

def forum_base_url(url: str) -> str:
    """Return the forum root URL (scheme + host + optional first path segment)."""
    p = urlparse(url)
    parts = [s for s in p.path.strip('/').split('/') if s]
    root: list[str] = []
    for part in parts:
        if any(sig in part.lower() for sig in FORUM_SIGNALS):
            root.append(part)
            break
        root.append(part)
        break  # keep at most one path segment
    path = '/' + '/'.join(root) if root else ''
    return f"{p.scheme}://{p.netloc}{path}"


def forum_display_name(url: str) -> str:
    host = re.sub(r'^www\.', '', urlparse(url).netloc.lower())
    # Turn "thefastlaneforum.com" → "Fastlane Forum" style is too complex;
    # just title-case the subdomain part.
    return host.split('.')[0].replace('-', ' ').title()


def looks_like_forum(url: str) -> bool:
    url_lower = url.lower()
    if any(ex in url_lower for ex in EXCLUDE_DOMAINS):
        return False
    if not url.startswith('http'):
        return False
    return any(sig in url_lower for sig in FORUM_SIGNALS)


# ─── Google search phase ──────────────────────────────────────────────────────

def google_search_forums(page: Page, keyword: str) -> list[str]:
    """
    Run Google searches and return unique forum base URLs found.
    Handles Google's consent popup and detects CAPTCHAs.
    """
    found: dict[str, str] = {}   # base_url → original_url (for dedup)
    captcha_hit = False

    for query_template in GOOGLE_QUERIES:
        if captcha_hit:
            break
        query = query_template.format(kw=keyword)
        search_url = f"https://www.google.com/search?q={quote_plus(query)}&num=20&hl=en"
        logger.info(f"🔎 Google: \"{query}\"")

        if not navigate_with_retry(page, search_url, wait_state='domcontentloaded'):
            logger.warning("   ⚠️  Google navigation failed")
            continue

        human_delay(1.5, 2.5)
        dismiss_popup(page)
        human_delay(0.5, 1.0)

        if is_captcha_page(page):
            logger.warning("   🛑 Google CAPTCHA — stopping search phase early")
            captcha_hit = True
            break

        random_mouse_move(page)
        slow_scroll(page, steps=3)

        # Collect all hrefs; Google wraps external links in /url?q=<actual>
        for el in page.locator('a[href]').all():
            raw = el.get_attribute('href') or ''
            # Unwrap Google redirect
            m = re.search(r'[?&]q=(https?://[^&]+)', raw)
            href = m.group(1) if m else raw

            if not href.startswith('http'):
                continue
            if not looks_like_forum(href):
                continue

            base = forum_base_url(href)
            if base not in found:
                found[base] = href
                logger.info(f"   📌 Candidate: {base}")

        human_delay(3.0, 5.0)   # polite gap between Google requests

    return list(found.keys())


# ─── Thread counting ──────────────────────────────────────────────────────────

def count_threads_on_page(page: Page) -> int:
    """Estimate thread count via CSS selectors and text patterns."""
    best = 0

    # Selector-based count
    for sel in THREAD_SELECTORS:
        try:
            n = page.locator(sel).count()
            best = max(best, n)
        except Exception:
            pass

    # Text-based count ("42 results", "Showing 1-20 of 150", etc.)
    body = page.content()
    for pattern in (
        r'(\d[\d,]*)\s+results?',
        r'(\d[\d,]*)\s+threads?',
        r'(\d[\d,]*)\s+topics?',
        r'(\d[\d,]*)\s+matches',
        r'found\s+(\d[\d,]*)',
        r'showing\s+\d+[-–]\d+\s+of\s+(\d[\d,]*)',
        r'(\d[\d,]*)\s+posts?',
    ):
        m = re.search(pattern, body, re.I)
        if m:
            val = int(m.group(1).replace(',', ''))
            best = max(best, val)

    return best


def _try_search_form(page: Page, keyword: str) -> tuple[int, str]:
    """
    Fill the forum's own search input with the keyword and count results.
    Returns (thread_count, search_url_used).
    """
    input_selectors = (
        'input[type="search"]',
        'input[name="q"]',
        'input[name="query"]',
        'input[name="keywords"]',
        'input[name="search"]',
        'input[name="searchquery"]',
        'input[placeholder*="earch" i]',
    )
    for sel in input_selectors:
        inp = page.locator(sel).first
        try:
            if not inp.count() or not inp.is_visible():
                continue
            inp.click()
            inp.fill(keyword)
            inp.press('Enter')
            page.wait_for_load_state('networkidle', timeout=15000)
            human_delay(0.5, 1.5)
            n = count_threads_on_page(page)
            if n > 0:
                return n, page.url
        except Exception:
            pass
    return 0, ''


# ─── Forum assessment ─────────────────────────────────────────────────────────

def assess_forum(page: Page, forum_url: str, keyword: str,
                 min_results: int) -> dict:
    """
    Visit a forum, search for the keyword, count threads, classify activity.
    """
    result = {
        'url': forum_url,
        'name': forum_display_name(forum_url),
        'threads': 0,
        'search_url': '',
        'reachable': False,
        'activity': 'LOW',
        'recommendation': 'SKIP',
    }

    logger.info(f"\n   🔬 Assessing: {forum_url}")

    if not navigate_with_retry(page, forum_url):
        logger.warning("   ❌ Unreachable")
        return result

    result['reachable'] = True
    dismiss_popup(page)
    human_delay(1.0, 2.0)

    # Strategy 1: use the forum's own search form
    count, search_url = _try_search_form(page, keyword)
    if count > 0:
        result['threads'] = count
        result['search_url'] = search_url
        _classify(result, min_results)
        _log_result(result)
        return result

    # Strategy 2: try known URL patterns
    q = quote_plus(keyword)
    for template in SEARCH_TEMPLATES:
        url = template.format(base=forum_url.rstrip('/'), q=q)
        if not navigate_with_retry(page, url):
            continue
        dismiss_popup(page)
        human_delay(0.5, 1.5)
        count = count_threads_on_page(page)
        if count > 0:
            result['threads'] = count
            result['search_url'] = url
            break
        human_delay(0.5, 1.0)

    _classify(result, min_results)
    _log_result(result)
    return result


def _classify(result: dict, min_results: int):
    n = result['threads']
    if n >= 20:
        result['activity'] = 'HIGH'
        result['recommendation'] = 'SCRAPE'
    elif n >= min_results:
        result['activity'] = 'MEDIUM'
        result['recommendation'] = 'SCRAPE'
    else:
        result['activity'] = 'LOW'
        result['recommendation'] = 'SKIP'


def _log_result(r: dict):
    icon = '✅' if r['recommendation'] == 'SCRAPE' else '⏭️ '
    logger.info(
        f"   {icon} {r['threads']:3} threads — "
        f"{r['activity']:6} — {r['recommendation']}"
    )


# ─── Output ───────────────────────────────────────────────────────────────────

def print_table(keyword: str, results: list[dict]):
    if not results:
        print("\nNo forums found.")
        return

    # Column widths
    name_w  = max(len('Forum'),      max(len(r['name']) for r in results))
    url_w   = max(len('URL'),        max(len(urlparse(r['url']).netloc) for r in results))
    thrd_w  = max(len('Threads'), 7)
    act_w   = max(len('Activity'), 8)
    act_w   = 8
    rec_w   = max(len('Action'), 6)

    sep = f"{'─' * (name_w + url_w + thrd_w + act_w + rec_w + 16)}"
    header = (
        f"  {'Forum':<{name_w}}  {'URL':<{url_w}}  "
        f"{'Threads':>{thrd_w}}  {'Activity':<{act_w}}  {'Action':<{rec_w}}"
    )

    print(f"\n{sep}")
    print(f"  FORUM DISCOVERY: \"{keyword}\"")
    print(sep)
    print(header)
    print(sep)

    for r in sorted(results, key=lambda x: -x['threads']):
        host = urlparse(r['url']).netloc
        row = (
            f"  {r['name']:<{name_w}}  {host:<{url_w}}  "
            f"{r['threads']:>{thrd_w}}  {r['activity']:<{act_w}}  "
            f"{r['recommendation']:<{rec_w}}"
        )
        print(row)

    print(sep)
    scrape_count = sum(1 for r in results if r['recommendation'] == 'SCRAPE')
    print(f"  {scrape_count} forum(s) recommended for scraping "
          f"| {len(results)} assessed total")
    print(f"{sep}\n")


def save_json(keyword: str, results: list[dict]) -> str:
    slug = re.sub(r'[^\w]+', '_', keyword.lower()).strip('_')
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"forum_discovery_{slug}_{ts}.json"

    payload = {
        'keyword': keyword,
        'generated_at': datetime.now().isoformat(),
        'forums_found': [
            {
                'name': r['name'],
                'url': r['url'],
                'threads': r['threads'],
                'activity': r['activity'],
                'recommendation': r['recommendation'],
                'search_url': r['search_url'],
            }
            for r in sorted(results, key=lambda x: -x['threads'])
        ],
    }

    with open(filename, 'w') as f:
        json.dump(payload, f, indent=2)

    return filename


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def discover_forums(keyword: str, min_results: int):
    logger.info(f"🚀 Forum Discovery — keyword=\"{keyword}\" min_results={min_results}")

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
            # Phase 1: Google search → candidate list
            logger.info("\n" + "─" * 60)
            logger.info("Phase 1: Google search for forum candidates")
            logger.info("─" * 60)
            candidates = google_search_forums(page, keyword)

            if not candidates:
                logger.warning("⚠️  No forum candidates found via Google.")
                browser.close()
                return

            logger.info(f"\n📋 {len(candidates)} unique forum candidates to assess\n")

            # Phase 2: Assess each candidate
            logger.info("─" * 60)
            logger.info("Phase 2: Assessing each forum")
            logger.info("─" * 60)
            results: list[dict] = []
            for url in candidates:
                try:
                    r = assess_forum(page, url, keyword, min_results)
                    results.append(r)
                except Exception as e:
                    logger.error(f"   ❌ Unexpected error assessing {url}: {e}")
                    results.append({
                        'url': url,
                        'name': forum_display_name(url),
                        'threads': 0,
                        'search_url': '',
                        'reachable': False,
                        'activity': 'LOW',
                        'recommendation': 'SKIP',
                    })
                human_delay(2.0, 4.0)

        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            results = []
        finally:
            browser.close()

    if not results:
        logger.warning("No results to report.")
        return

    # Phase 3: Output
    print_table(keyword, results)
    filename = save_json(keyword, results)
    logger.info(f"💾 Report saved → {filename}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Discover active forums for a niche keyword via Google + Playwright'
    )
    parser.add_argument(
        '--keyword', required=True,
        help='Niche keyword to search for (e.g. "exotic car rental")'
    )
    parser.add_argument(
        '--min-results', type=int, default=5,
        help='Min thread count to qualify as active (default: 5)'
    )
    args = parser.parse_args()
    discover_forums(args.keyword, args.min_results)


if __name__ == '__main__':
    main()
