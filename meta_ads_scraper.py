"""
Meta Ads scraper — agency_benchmarks and authority_sources.

Search approach — Meta Ad Library UI:
  1. Navigate to https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL
  2. Find the search input and type the company name (character by character)
  3. Wait for autocomplete dropdown suggestions
     → If a matching advertiser appears: click it → loads only that advertiser's ads (clean)
     → If no dropdown match: press Enter → keyword results, then filter cards by advertiser name
  4. Extract ad copy, CTAs, formats, and per-card landing URLs

Landing URL filtering:
  - Decode Facebook's l.facebook.com/l.php?u= redirects
  - Keep only URLs whose root domain matches the agency's website, OR belong to
    a known ad/landing-page platform, OR contain UTM parameters
  - URLs that don't match are logged and dropped

Usage:
  python meta_ads_scraper.py                        # all rows, limit 50
  python meta_ads_scraper.py --type agency          # agency_benchmarks only
  python meta_ads_scraper.py --type authority       # authority_sources only
  python meta_ads_scraper.py --limit 20 --batch 5  # 20 total, pause after every 5
  python meta_ads_scraper.py --test                 # Tinuiti + Wpromote, DEBUG logging
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
from urllib.parse import quote, urlparse

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

FB_AD_LIBRARY_URL = (
    'https://www.facebook.com/ads/library/'
    '?active_status=all&ad_type=all&country=ALL'
)

# Test mode — no DB writes required
TEST_TARGETS = [
    {'id': None, 'name': 'Tinuiti',  'website': 'tinuiti.com',  'table': 'agency_benchmarks'},
    {'id': None, 'name': 'Wpromote', 'website': 'wpromote.com', 'table': 'agency_benchmarks'},
]

# Landing page platforms whose domains are treated as valid even when they differ
# from the agency's own domain (agencies host content there).
KNOWN_AD_PLATFORMS = {
    'unbounce.com', 'unbouncepages.com',
    'instapage.com',
    'leadpages.net', 'leadpages.co',
    'clickfunnels.com',
    'hs-sites.com', 'hubspot.com', 'hubspotpagebuilder.com',
    'webflow.io', 'webflow.com',
    'squarespace.com', 'wixsite.com',
    'typeform.com', 'jotform.com',
    'calendly.com',
    'bit.ly', 'hubs.ly', 'ow.ly',
}


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_targets(conn, target_type: str) -> list[dict]:
    """
    Return rows not yet scraped.
    Skips agency_benchmarks rows where meta_ads is already populated.
    Skips authority_sources rows where paid_amplification IS NOT NULL.
    """
    targets: list[dict] = []
    skipped = 0

    with conn.cursor() as cur:
        if target_type in ('agency', 'all'):
            cur.execute(
                """
                SELECT id, agency_name, website,
                       (meta_ads IS NOT NULL AND meta_ads::text != '{}') AS done
                FROM agency_benchmarks
                ORDER BY id
                """
            )
            for row in cur.fetchall():
                id_, name, website, done = row
                if done:
                    logger.info(f"  [skip] agency [{id_}] {name} — already scraped")
                    skipped += 1
                else:
                    targets.append({'id': id_, 'name': name, 'website': website,
                                    'table': 'agency_benchmarks'})

        if target_type in ('authority', 'all'):
            cur.execute(
                """
                SELECT id, firm_name,
                       (paid_amplification IS NOT NULL) AS done
                FROM authority_sources
                ORDER BY id
                """
            )
            for row in cur.fetchall():
                id_, name, done = row
                if done:
                    logger.info(f"  [skip] authority [{id_}] {name} — already scraped")
                    skipped += 1
                else:
                    targets.append({'id': id_, 'name': name, 'website': None,
                                    'table': 'authority_sources'})

    if skipped:
        logger.info(f"  Skipped {skipped} already-scraped row(s)")
    return targets


def save_meta_results(conn, target: dict, results: dict):
    if target['id'] is None:
        logger.info("  [test] Skipping DB write")
        return
    with conn.cursor() as cur:
        if target['table'] == 'agency_benchmarks':
            cur.execute(
                "UPDATE agency_benchmarks SET meta_ads = %s::jsonb WHERE id = %s",
                (json.dumps(results), target['id']),
            )
        else:
            cur.execute(
                "UPDATE authority_sources SET paid_amplification = %s WHERE id = %s",
                (json.dumps(results), target['id']),
            )
    conn.commit()


def seed_landing_page_urls(conn, urls: list[str], target: dict, found_via: str):
    if not urls or target['id'] is None:
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


# ─── URL utilities ─────────────────────────────────────────────────────────────

def extract_root_domain(url_or_domain: str) -> str:
    """Return eTLD+1 (e.g. 'tinuiti.com') from a URL or bare domain."""
    try:
        s = url_or_domain if '://' in url_or_domain else 'https://' + url_or_domain
        host = urlparse(s).netloc.lower().split(':')[0]
        if host.startswith('www.'):
            host = host[4:]
        parts = host.split('.')
        return '.'.join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return ''


def filter_landing_urls(
    urls: list[str],
    agency_website: str | None,
    name: str,
) -> list[str]:
    """
    Keep a landing URL if any of these are true:
      1. Its root domain matches the agency's own website domain
      2. It is hosted on a known ad/landing-page platform
      3. It contains UTM tracking parameters (= intentional ad destination)
    If agency_website is unknown, keep all (can't filter).
    """
    if not agency_website:
        return urls

    agency_root = extract_root_domain(agency_website)
    if not agency_root:
        return urls

    kept: list[str] = []
    dropped: list[str] = []

    for url in urls:
        url_root = extract_root_domain(url)
        if not url_root:
            continue
        if url_root == agency_root:
            kept.append(url)
        elif url_root in KNOWN_AD_PLATFORMS:
            kept.append(url)
        elif 'utm_' in url:
            kept.append(url)
        else:
            dropped.append(url)

    if dropped:
        dropped_roots = list(dict.fromkeys(extract_root_domain(u) for u in dropped))
        logger.info(
            f"  Filtered {len(dropped)} URL(s) — domain mismatch: {dropped_roots[:6]}"
        )

    return kept


# ─── Browser helpers ───────────────────────────────────────────────────────────

async def random_delay(min_s: float = 2.0, max_s: float = 3.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def find_search_input(page):
    """
    Locate the advertiser/keyword search input on the Ad Library page,
    explicitly skipping the country selector input.

    Strategy:
      1. Log every input on the page (placeholder, aria-label, visibility) so
         we can see exactly what Facebook is rendering at runtime.
      2. Try specific positive selectors (placeholder/aria-label containing
         "keyword" or "advertiser").
      3. Fall back to the first visible text-type input whose placeholder/
         aria-label does NOT contain "country".
    """
    # ── Priority 1: specific positive match ───────────────────────────────────
    positive = [
        'input[placeholder*="keyword"]',
        'input[placeholder*="Keyword"]',
        'input[placeholder*="advertiser"]',
        'input[placeholder*="Advertiser"]',
        'input[aria-label*="keyword"]',
        'input[aria-label*="Keyword"]',
        'input[aria-label*="advertiser"]',
        'input[aria-label*="Advertiser"]',
        'input[placeholder*="Search by"]',
        'input[aria-label*="Search by"]',
    ]
    for sel in positive:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=500):
                ph = await loc.get_attribute('placeholder') or await loc.get_attribute('aria-label') or ''
                logger.info(f"  Found search input: placeholder={ph!r} (via {sel!r})")
                return loc
        except Exception:
            pass

    # ── Priority 2: first visible text input that is not the country selector ─
    result = await page.evaluate("""
        () => {
            const skip_types = new Set(['hidden','submit','checkbox','radio','file','password','button']);
            const inputs = Array.from(document.querySelectorAll('input'));
            for (let i = 0; i < inputs.length; i++) {
                const el = inputs[i];
                if (el.offsetWidth === 0 || el.offsetHeight === 0) continue;
                if (skip_types.has(el.type)) continue;
                const ph = (el.placeholder || '').toLowerCase();
                const al = (el.getAttribute('aria-label') || '').toLowerCase();
                if (ph.includes('country') || al.includes('country')) continue;
                return { idx: i, placeholder: el.placeholder || el.getAttribute('aria-label') || '' };
            }
            return null;
        }
    """)

    if result:
        logger.info(f"  Found search input: placeholder={result['placeholder']!r} (exclusion fallback, DOM index {result['idx']})")
        return page.locator('input').nth(result['idx'])

    raise RuntimeError("Could not locate the advertiser search input on the Ad Library page")


async def dismiss_dialogs(page):
    for sel in [
        'button[data-cookiebanner="accept_button"]',
        'button[title="Accept All"]',
        'button:has-text("Accept All")',
        'button:has-text("Allow all cookies")',
        '[aria-label="Allow all cookies"]',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await asyncio.sleep(0.8)
                break
        except Exception:
            pass

    for sel in ['[aria-label="Close"]', 'div[role="dialog"] button:has-text("Close")']:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=800):
                await btn.click()
                await asyncio.sleep(0.5)
                break
        except Exception:
            pass


# ─── Name matching ─────────────────────────────────────────────────────────────

def names_match(advertiser_name: str, search_name: str) -> bool:
    """
    Return True if advertiser_name is a recognisable match for search_name.
    Returns False for empty/None — null stub cards are excluded, not kept.
    """
    if not advertiser_name:
        return False
    a = advertiser_name.lower().strip()
    s = search_name.lower().strip()
    if a == s or s in a or a in s:
        return True
    # Word-level: ≥60% of significant search words must appear in advertiser name
    words = [w for w in s.split() if len(w) > 2]
    if words:
        return sum(1 for w in words if w in a) >= max(1, len(words) * 0.6)
    return False


# ─── Dropdown interaction ──────────────────────────────────────────────────────

async def try_click_dropdown(page, name: str) -> str:
    """
    After typing `name` into the search box, try to click a matching advertiser
    in the autocomplete dropdown.

    Returns:
      'dropdown_click'  — a match was found and clicked; ads are now advertiser-only
      'keyword_search'  — no match; caller should press Enter for keyword results
    """
    # Dropdown selectors in priority order (Facebook's Ad Library uses listbox/option roles)
    dropdown_selectors = [
        '[role="option"]',
        'ul[role="listbox"] li',
        '[role="listbox"] [role="option"]',
        '[data-testid*="typeahead"] [role="option"]',
        '[aria-autocomplete] ~ * [role="option"]',
    ]

    appeared = False
    for sel in dropdown_selectors:
        try:
            await page.wait_for_selector(sel, timeout=3_000)
            appeared = True
            break
        except PlaywrightTimeoutError:
            continue

    if not appeared:
        logger.info(f"  No dropdown appeared — will use Enter/keyword search")
        return 'keyword_search'

    name_lower = name.lower()
    name_words = [w.lower() for w in name.split() if len(w) > 2]

    for sel in dropdown_selectors:
        try:
            options = page.locator(sel)
            count = await options.count()
            logger.debug(f"  Dropdown has {count} option(s) via {sel!r}")

            for idx in range(min(count, 10)):
                try:
                    opt = options.nth(idx)
                    raw_text = await opt.inner_text()
                    first_line = raw_text.strip().split('\n')[0].lower()

                    match = (
                        name_lower in first_line
                        or first_line in name_lower
                        or (
                            name_words
                            and sum(1 for w in name_words if w in first_line)
                            >= max(1, len(name_words) * 0.6)
                        )
                    )

                    if match:
                        logger.info(f"  Dropdown match: {raw_text.strip()[:60]!r}")
                        await opt.click()
                        return 'dropdown_click'

                    logger.debug(f"  Skipping option [{idx}]: {first_line[:50]!r}")
                except Exception as exc:
                    logger.debug(f"  Option [{idx}] error: {exc}")
                    continue

        except Exception:
            continue

    logger.info(f"  No matching advertiser in dropdown for {name!r}")
    return 'keyword_search'


# ─── Ad extraction ─────────────────────────────────────────────────────────────

# Extracts one record per ad card. Each record includes:
#   advertiserName — the Facebook page name shown on the card (for post-search filtering)
#   landingUrl     — decoded first external link in the card (CTA destination)
#   headline, bodyText, cta, adType, isActive
_AD_CARDS_JS = """
    () => {
        const ctaKeywords = [
            'Learn More', 'Sign Up', 'Shop Now', 'Book Now', 'Contact Us',
            'Get Quote', 'Apply Now', 'Subscribe', 'Download', 'Get Started',
            'Reserve', 'Schedule', 'Call Now', 'Message', 'Watch More', 'Visit Website',
        ];
        const skipText = ['Library ID', 'Started running', 'Sponsored', 'See more', 'See less'];
        const skipLineRe = /^(Like|Follow|Share|Comment|Send|\\d{1,2}\\s*(min|hr|h|d|w))$/i;
        const statusLabels = new Set(['active', 'inactive', 'active status', 'inactive status', 'ended', 'paused']);
        function isStatusLabel(t) {
            const lower = t.toLowerCase().trim();
            if (statusLabels.has(lower)) return true;
            // single- or two-word strings that are pure status labels
            const words = lower.split(/\\s+/);
            return words.length <= 2 && words.every(w => statusLabels.has(w) || /^(ad|status|badge|label)$/.test(w));
        }

        function decodeFbUrl(href) {
            if (!href) return '';
            if (href.includes('facebook.com/l.php') || href.includes('fb.com/l.php')) {
                try {
                    const dest = new URL(href).searchParams.get('u');
                    if (dest && dest.startsWith('http')) return decodeURIComponent(dest);
                } catch(e) {}
            }
            return href;
        }

        function isExternal(url) {
            return (
                url.startsWith('http') &&
                !url.includes('facebook.com') &&
                !url.includes('fb.com') &&
                !url.includes('fb.watch') &&
                !url.includes('instagram.com')
            );
        }

        function isButtonEl(el) {
            const role = (el.getAttribute('role') || '').toLowerCase();
            return el.tagName === 'BUTTON' || role === 'button';
        }

        function cleanText(t) { return (t || '').trim(); }
        function usable(t) { return t.length > 0 && !skipText.some(s => t.includes(s)); }

        // ── Find leaf-level ad cards: each contains exactly one "Library ID" ──
        const cardDivs = Array.from(document.querySelectorAll('div')).filter(div => {
            const txt = div.innerText || '';
            return txt.includes('Library ID') && txt.length < 8000;
        }).filter(div => {
            // Keep only innermost wrappers (parent also has Library ID → skip parent)
            const txt = div.innerText || '';
            return (txt.match(/Library ID/gi) || []).length === 1;
        });

        const results = [];

        for (const card of cardDivs) {
            const text = card.innerText || '';

            // ── Advertiser name ──────────────────────────────────────────────
            // Pass 1: first Facebook page profile link (not ads/search/l.php)
            let advertiserName = '';
            for (const link of card.querySelectorAll('a[href]')) {
                const href = link.href || '';
                const t = cleanText(link.innerText);
                if (
                    t.length > 0 && t.length < 100 &&
                    href.indexOf('facebook.com/') > -1 &&
                    href.indexOf('/ads/') === -1 &&
                    href.indexOf('/search/') === -1 &&
                    href.indexOf('l.php') === -1
                ) {
                    advertiserName = t;
                    break;
                }
            }
            // Pass 2: first short text in card that looks like a page name
            if (!advertiserName) {
                const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 1 && l.length < 80);
                for (const line of lines) {
                    if (!skipText.some(s => line.includes(s)) && !skipLineRe.test(line)) {
                        advertiserName = line;
                        break;
                    }
                }
            }

            // ── Headline ─────────────────────────────────────────────────────
            let headline = '';

            // Pass 1: semantic bold/heading elements
            for (const el of card.querySelectorAll('strong, b, h1, h2, h3, h4')) {
                const t = cleanText(el.innerText);
                if (t.length > 5 && t.length < 300 && usable(t) && !isStatusLabel(t)) { headline = t; break; }
            }

            // Pass 2: computed font-weight ≥ 600 on leaf-ish spans/divs
            if (!headline) {
                for (const el of card.querySelectorAll('span, div, p')) {
                    if (el.children.length > 2 || isButtonEl(el)) continue;
                    const t = cleanText(el.innerText);
                    if (t.length < 5 || t.length > 300 || !usable(t) || isStatusLabel(t)) continue;
                    try {
                        const fw = parseInt(window.getComputedStyle(el).fontWeight, 10);
                        if (fw >= 600) { headline = t; break; }
                    } catch(e) {}
                }
            }

            // Pass 3: first substantial line from raw card text (heuristic)
            if (!headline) {
                const lines = text.split('\\n').map(l => l.trim());
                for (const line of lines) {
                    if (line.length > 10 && line.length < 250 && usable(line) && !skipLineRe.test(line) && !isStatusLabel(line)) {
                        headline = line; break;
                    }
                }
            }

            // ── Body text ─────────────────────────────────────────────────────
            let bodyText = '';

            // Pass 1: spans/p/div — relaxed child count, not a button, longer than 50 chars
            for (const el of card.querySelectorAll('span, p, div')) {
                if (isButtonEl(el) || el.children.length > 8) continue;
                const t = cleanText(el.innerText);
                if (
                    t.length > bodyText.length && t.length > 50 && t.length < 2000 &&
                    usable(t) && t !== headline
                ) {
                    bodyText = t;
                }
            }

            // Pass 2: longest line from raw card text that isn't the headline
            if (!bodyText) {
                const lines = text.split('\\n').map(l => l.trim()).filter(l =>
                    l.length > 50 && l !== headline && usable(l) && !skipLineRe.test(l)
                );
                if (lines.length) bodyText = lines.reduce((a, b) => a.length >= b.length ? a : b, '');
            }

            // ── CTA ───────────────────────────────────────────────────────────
            let cta = '';
            for (const btn of card.querySelectorAll('a[role="button"], button, a')) {
                const t = cleanText(btn.innerText);
                if (ctaKeywords.some(k => t.toLowerCase().includes(k.toLowerCase()))) {
                    cta = t; break;
                }
            }

            // ── Landing URL ───────────────────────────────────────────────────
            let landingUrl = '';
            for (const btn of card.querySelectorAll('a[role="button"], a')) {
                const t = cleanText(btn.innerText);
                if (!ctaKeywords.some(k => t.toLowerCase().includes(k.toLowerCase()))) continue;
                const decoded = decodeFbUrl(btn.href || '');
                if (isExternal(decoded)) { landingUrl = decoded; break; }
            }
            if (!landingUrl) {
                for (const link of card.querySelectorAll('a[href]')) {
                    const decoded = decodeFbUrl(link.href || '');
                    if (isExternal(decoded)) { landingUrl = decoded; break; }
                }
            }

            // ── Format / status ───────────────────────────────────────────────
            let adType = 'image';
            if (card.querySelector('video')) adType = 'video';
            if (card.querySelectorAll('img').length > 2) adType = 'carousel';

            const lower = text.toLowerCase();
            const isActive = !lower.includes('inactive') && !lower.includes('ended');

            results.push({
                advertiserName: advertiserName || null,
                headline:       headline       || null,
                bodyText:       bodyText       || null,
                cta:            cta            || null,
                landingUrl:     landingUrl     || null,
                adType,
                isActive,
                cardTextLen:    text.length,
            });
        }

        return results;
    }
"""


async def extract_ads(page, search_name: str) -> dict:
    try:
        cards: list[dict] = await page.evaluate(_AD_CARDS_JS)
    except Exception as exc:
        logger.warning(f"  JS extraction error: {exc}")
        cards = []

    logger.info(f"  JS found {len(cards)} card(s) on page")

    ads = []
    landing_urls: list[str] = []
    seen_urls: set[str] = set()

    for i, c in enumerate(cards):
        # Build the ad record from top-level JS fields (same keys, no indirection)
        ad = {
            'advertiser_name': c.get('advertiserName') or None,
            'headline':        c.get('headline') or None,
            'body_text':       c.get('bodyText') or None,
            'cta':             c.get('cta') or None,
            'ad_format':       c.get('adType', 'image'),
            'is_active':       c.get('isActive', True),
            'landing_url':     c.get('landingUrl') or None,
        }
        # Log from the exact same dict that goes into storage — no separate _debug path
        logger.info(
            f"  Card [{i}] "
            f"advertiser={ad['advertiser_name']!r} "
            f"headline={(ad['headline'] or '')[:60]!r} "
            f"body={(ad['body_text'] or '')[:80]!r} "
            f"cta={ad['cta']!r} "
            f"url={ad['landing_url']!r} "
            f"textLen={c.get('cardTextLen')}"
        )
        ads.append(ad)
        url = ad['landing_url'] or ''
        if url and url not in seen_urls:
            seen_urls.add(url)
            landing_urls.append(url)

    return {
        'scraped_at':        datetime.now(timezone.utc).isoformat(),
        'source':            'meta_ad_library',
        'search_name':       search_name,
        'ad_count_found':    len(ads),
        'ads':               ads[:20],
        'landing_page_urls': landing_urls,
    }


# ─── Main search orchestrator ──────────────────────────────────────────────────

async def search_ad_library(page, name: str, website: str | None) -> dict:
    """
    Full UI-driven search flow:
      1. Navigate to Ad Library base URL
      2. Type name into search box
      3. Click matching advertiser from dropdown  → clean single-advertiser results
         OR press Enter for keyword results       → filter cards by advertiser name
      4. Extract ads and landing URLs
      5. Filter landing URLs by agency domain
    """
    logger.info(f"  [UI] Loading Ad Library: {FB_AD_LIBRARY_URL}")
    try:
        # 'load' waits for the load event (scripts executed); needed so React has
        # mounted all inputs before we try to locate them.
        await page.goto(FB_AD_LIBRARY_URL, wait_until='load', timeout=20_000)
    except PlaywrightTimeoutError:
        logger.warning("  Page load timeout — continuing anyway")

    # Wait for at least one input to appear (React mount signal)
    try:
        await page.wait_for_selector('input', timeout=8_000)
    except PlaywrightTimeoutError:
        logger.warning("  No inputs appeared after load")

    # Extra render time — Facebook's Ad Library is a heavy React app
    await asyncio.sleep(3.0)
    await dismiss_dialogs(page)
    await asyncio.sleep(0.5)

    # ── Click "Ad category" → "All ads" to enable the search input ────────────
    try:
        # Debug: dump every visible element that contains "Ad category" text
        ad_cat_elements = await page.evaluate("""
            () => {
                const walk = (el, depth) => {
                    if (depth > 8) return [];
                    const text = (el.innerText || el.textContent || '').trim();
                    if (!text.includes('Ad category')) return [];
                    const r = el.getBoundingClientRect();
                    const visible = r.width > 0 && r.height > 0 && el.offsetParent !== null;
                    const results = [{
                        tag:      el.tagName,
                        role:     el.getAttribute('role') || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        text:     text.slice(0, 80),
                        visible:  visible,
                        rect:     { x: Math.round(r.x), y: Math.round(r.y),
                                    w: Math.round(r.width), h: Math.round(r.height) },
                    }];
                    for (const child of el.children) results.push(...walk(child, depth + 1));
                    return results;
                };
                return walk(document.body, 0);
            }
        """)
        logger.info(f"  'Ad category' elements on page ({len(ad_cat_elements)}):")
        for el in ad_cat_elements:
            logger.info(
                f"    {el['tag']} role={el['role']!r} aria={el['ariaLabel']!r} "
                f"visible={el['visible']} rect={el['rect']} text={el['text']!r}"
            )

        # Take a screenshot so we can see the page state
        await page.screenshot(path='/tmp/adlib_before_category.png')
        logger.info("  Screenshot saved to /tmp/adlib_before_category.png")

        # Try selectors in order — log which one works
        ad_cat_clicked = False
        candidates = [
            ('get_by_text exact',       lambda: page.get_by_text('Ad category', exact=True).first),
            ('aria-label contains',     lambda: page.locator('[aria-label*="Ad category"]').first),
            ('div:has-text last',       lambda: page.locator('div:has-text("Ad category")').last),
            ('span:has-text last',      lambda: page.locator('span:has-text("Ad category")').last),
        ]
        for label, make_loc in candidates:
            try:
                loc = make_loc()
                if await loc.is_visible(timeout=1_500):
                    await loc.click(timeout=3_000)
                    logger.info(f"  Clicked 'Ad category' via [{label}]")
                    ad_cat_clicked = True
                    break
            except Exception as exc:
                logger.info(f"  [{label}] failed: {exc}")

        if not ad_cat_clicked:
            logger.warning("  Could not click 'Ad category' — proceeding without it")
        else:
            await asyncio.sleep(0.8)

            # Wait for the dropdown menu / listbox to appear
            menu_sel = (
                '[role="listbox"],'
                '[role="menu"],'
                '[role="dialog"],'
                'ul[role="listbox"]'
            )
            try:
                await page.wait_for_selector(menu_sel, timeout=4_000)
            except PlaywrightTimeoutError:
                logger.warning("  Dropdown menu did not appear after clicking 'Ad category'")

            await page.screenshot(path='/tmp/adlib_category_open.png')
            logger.info("  Screenshot saved to /tmp/adlib_category_open.png")

            # Click "All ads" — try role-based then text-based selectors
            all_ads_candidates = [
                ('option exact',      lambda: page.get_by_role('option', name='All ads').first),
                ('menuitem exact',    lambda: page.get_by_role('menuitem', name='All ads').first),
                ('get_by_text exact', lambda: page.get_by_text('All ads', exact=True).first),
                ('li:has-text last',  lambda: page.locator('li:has-text("All ads")').last),
                ('div:has-text last', lambda: page.locator('div:has-text("All ads")').last),
            ]
            all_ads_clicked = False
            for label, make_loc in all_ads_candidates:
                try:
                    loc = make_loc()
                    if await loc.is_visible(timeout=1_500):
                        await loc.click(timeout=3_000)
                        logger.info(f"  Selected 'All ads' via [{label}]")
                        all_ads_clicked = True
                        break
                except Exception as exc:
                    logger.info(f"  [All ads / {label}] failed: {exc}")

            if not all_ads_clicked:
                logger.warning("  Could not select 'All ads' option")

            await asyncio.sleep(1.5)   # wait for search input to become enabled

    except Exception as exc:
        logger.warning(f"  'Ad category' block failed unexpectedly: {exc} — proceeding anyway")

    # ── Find search input ──────────────────────────────────────────────────────
    try:
        search_input = await find_search_input(page)
        await search_input.click(timeout=5_000)
    except Exception as exc:
        logger.warning(f"  Search input not found: {exc}")
        return {
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            'source': 'meta_ad_library',
            'search_name': name,
            'search_method': 'error_no_input',
            'ad_count_found': 0,
            'ads': [],
            'landing_page_urls': [],
        }

    await asyncio.sleep(0.3)

    # Clear any existing content, then type character by character
    await page.keyboard.press('Control+a')
    await search_input.type(name, delay=60)   # 60 ms between keystrokes

    logger.info(f"  Typed {name!r} — waiting for dropdown")
    await asyncio.sleep(1.5)   # let autocomplete fire

    # ── Dropdown or keyword fallback ──────────────────────────────────────────
    search_method = await try_click_dropdown(page, name)

    if search_method == 'dropdown_click':
        logger.info(f"  Dropdown advertiser clicked — waiting for advertiser results")
        await asyncio.sleep(1.5)
    else:
        logger.info(f"  Pressing Enter for keyword search")
        await search_input.press('Enter')
        await asyncio.sleep(1.5)

    # ── Wait for result cards ─────────────────────────────────────────────────
    try:
        await page.wait_for_selector(
            'div:has-text("Library ID"),'
            'div:has-text("No results found"),'
            'div:has-text("No ads"),'
            'div:has-text("no ads")',
            timeout=8_000,
        )
    except PlaywrightTimeoutError:
        logger.warning(f"  Results selector not found for {name!r}")

    # Scroll to trigger lazy-loaded ad cards, then give React 2 s to render
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(2.0)
    await page.evaluate("window.scrollTo(0, 0)")   # scroll back to top so cards are in view
    await asyncio.sleep(0.5)

    await page.screenshot(path='/tmp/adlib_ads_loaded.png')
    logger.info("  Screenshot saved to /tmp/adlib_ads_loaded.png")

    # ── Extract ───────────────────────────────────────────────────────────────
    result = await extract_ads(page, name)
    result['search_method'] = search_method

    # ── Filter ad cards by advertiser name (always, both search methods) ────────
    original_count = len(result['ads'])
    matched_ads = [
        ad for ad in result['ads']
        if names_match(ad.get('advertiser_name') or '', name)
    ]
    discarded = original_count - len(matched_ads)
    if discarded:
        logger.info(f"  Filtered {discarded} ad card(s) — no advertiser match")

    # ── Deduplicate by body_text — same ad rendered multiple times per page ───
    deduped_ads: list[dict] = []
    seen_bodies: set[str] = set()
    for ad in matched_ads:
        key = (ad.get('body_text') or '').strip()
        if key and key in seen_bodies:
            continue
        if key:
            seen_bodies.add(key)
        deduped_ads.append(ad)

    if len(deduped_ads) < len(matched_ads):
        logger.info(
            f"  Deduplicated {len(matched_ads) - len(deduped_ads)} duplicate card(s) "
            f"→ {len(deduped_ads)} unique ad(s)"
        )

    # Rebuild landing URLs from deduped ads only
    matched_urls: list[str] = []
    seen_u: set[str] = set()
    for ad in deduped_ads:
        u = ad.get('landing_url') or ''
        if u and u not in seen_u:
            seen_u.add(u)
            matched_urls.append(u)

    result['ads'] = deduped_ads[:20]
    result['ad_count_found'] = len(deduped_ads)
    result['landing_page_urls'] = matched_urls

    # ── Filter landing URLs by domain ─────────────────────────────────────────
    filtered_urls = filter_landing_urls(result['landing_page_urls'], website, name)
    result['landing_page_urls'] = filtered_urls

    return result


# ─── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description='Meta Ads scraper — Ad Library UI approach'
    )
    parser.add_argument('--type',  choices=['agency', 'authority', 'all'], default='all')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--batch', type=int, default=5,
                        help='Pause after every N targets (default: 5)')
    parser.add_argument('--test',  action='store_true',
                        help='Run Tinuiti + Wpromote only, DEBUG logging, no DB writes')
    args = parser.parse_args()

    if args.test:
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("=== TEST MODE: Tinuiti + Wpromote, no DB writes ===")
        conn = None
        targets = TEST_TARGETS
    else:
        conn = get_db_connection()
        targets = get_targets(conn, args.type)[:args.limit]

    if not targets:
        logger.info("No targets found")
        if conn:
            conn.close()
        return

    logger.info(f"Targets: {len(targets)} | Type: {args.type} | Batch: {args.batch}")
    stats = {
        'saved': 0, 'errors': 0, 'landing_urls': 0,
        'dropdown_clicks': 0, 'keyword_searches': 0,
    }

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
                results = await search_ad_library(page, target['name'], target.get('website'))
                landing_urls = results.get('landing_page_urls', [])
                method = results.get('search_method', 'unknown')

                if conn:
                    save_meta_results(conn, target, results)
                    seed_landing_page_urls(conn, landing_urls, target, 'meta_ads')
                else:
                    logger.info(
                        f"  [test] ads={results['ad_count_found']} "
                        f"landing_urls={len(landing_urls)}"
                    )
                    logger.debug(f"  [test] landing_urls={landing_urls}")
                    logger.debug(f"  [test] ads={json.dumps(results.get('ads', [])[:3], indent=2)}")

                stats['saved'] += 1
                stats['landing_urls'] += len(landing_urls)
                if method == 'dropdown_click':
                    stats['dropdown_clicks'] += 1
                else:
                    stats['keyword_searches'] += 1

                logger.info(
                    f"  ✓ method={method} | ads={results['ad_count_found']} "
                    f"| landing_urls={len(landing_urls)}"
                )

            except Exception as exc:
                logger.error(f"  ✗ Error: {exc}", exc_info=args.test)
                stats['errors'] += 1
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            if i < len(targets):
                if i % args.batch == 0:
                    logger.info(f"  [batch {i // args.batch}] pausing...")
                    await random_delay(5.0, 8.0)
                else:
                    await random_delay(2.0, 3.0)

        await browser.close()

    if conn:
        conn.close()

    logger.info(
        f"\n=== Done ==="
        f"\n  Saved:           {stats['saved']}"
        f"\n  Errors:          {stats['errors']}"
        f"\n  Dropdown clicks: {stats['dropdown_clicks']}"
        f"\n  Keyword searches:{stats['keyword_searches']}"
        f"\n  Landing URLs:    {stats['landing_urls']}"
    )


if __name__ == '__main__':
    asyncio.run(main())
