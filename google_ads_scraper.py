"""
Google Ads Transparency Center scraper — agency_benchmarks and authority_sources.

IMPORTANT — what this site actually exposes:
  adstransparency.google.com is a client-side Angular app. Loading
  `?query=X` in the URL does NOT perform a search — it just loads the
  (geo-localized) homepage. A search only happens by typing into the
  on-page search box and clicking one of the autocomplete suggestions
  that appear; that click is what navigates to real results.

  Every individual ad creative (image, video, *and* text/search ads) is
  rendered as a static PNG snapshot (served from tpc.googlesyndication.com)
  for most ad cards — confirmed via the underlying LookupService/SearchCreatives
  RPC responses, which carry no headline/body/landing-URL text, only an
  embedded `<img>` snippet.

  BUT: native/Discovery-style ads (a subset of "Format: Image" cards) render
  inside a live iframe — tpc.googlesyndication.com/pagead/gadgets/discover_ads/
  discover_ads.html — whose DOM contains real, accessible text and a real
  landing-page <a href>. This is a genuine, exact-match extraction path, not
  a selector bug fix.

  Large IAB display formats (e.g. 300x600) render as a *third* type: a
  sandboxed HTML5 ad bundle (tpc.googlesyndication.com/archive/sadbundle/...).
  These are usually canvas-rendered (no live text either), but the whole
  creative is wrapped in a real <a href> pointing to Google's click-tracking
  redirect, which embeds the real destination in its `adurl` query param —
  so the landing URL is exactly recoverable even with no headline/description.

  Everything else (flattened simgad snapshots) has no live text in the DOM
  at all, so we fall back to Tesseract OCR on the downloaded snapshot image.

  Tiered per-ad extraction (see extract_ad_detail):
    1. discover_ads iframe present -> extract_iframe_ad_content (exact text+link, confidence=100)
    2. sadbundle iframe present -> extract_sadbundle_link (exact link only, no text, confidence=100)
    3. else -> download the snapshot PNG and run extract_ocr_ad_content
       (Tesseract OCR, confidence-filtered; low-confidence/ungroupable results
       are explicitly marked skipped rather than guessed at)
  Each ad record is tagged with extraction_method ('iframe_text' | 'iframe_link_only'
  | 'ocr_fallback' | 'skipped_video' | 'not_attempted') and a confidence score, so
  exact records can be told apart from OCR-derived ones downstream.

Search strategy (per target):
  1. Load the Transparency Center homepage (?hl=en to force English)
  2. Type `name` into the real search box and wait for autocomplete suggestions
  3. Score suggestions by word-overlap with `name` (+ verified/ambiguous signals)
  4. Click the best-matching advertiser suggestion (no match -> no_advertiser_match)
  5. Extract ad count + creative thumbnails from the resulting view
  6. For up to --max-ads-per-advertiser non-video ads, visit the creative detail
     page and run the tiered extraction above

Merges results into agency_benchmarks.meta_ads (JSONB) and
authority_sources.paid_amplification (TEXT) — preserves existing Meta data.

Usage:
  python google_ads_scraper.py --type all --limit 50
  python google_ads_scraper.py --type agency --limit 10
  python google_ads_scraper.py --type authority
  python google_ads_scraper.py --test --names Tinuiti Wpromote "Boston Consulting Group"

Dependencies beyond requirements.txt: the `tesseract` binary must be
installed on the host (macOS: `brew install tesseract`) for OCR fallback.
"""

import argparse
import asyncio
import io
import json
import logging
import os
import random
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import psycopg2
import pytesseract
from dotenv import load_dotenv
from PIL import Image
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


def lookup_websites(conn, names: list[str]) -> dict[str, str | None]:
    """Read-only lookup used by --names so ad-hoc tests can still apply the
    client-campaign domain filter without writing anything."""
    websites: dict[str, str | None] = {}
    with conn.cursor() as cur:
        for n in names:
            cur.execute(
                "SELECT website FROM agency_benchmarks WHERE lower(agency_name) = lower(%s)",
                (n,),
            )
            row = cur.fetchone()
            websites[n] = row[0] if row else None
    return websites


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


# ─── Advertiser search (real autocomplete flow) ────────────────────────────────

SEARCH_INPUT_SELECTOR = 'input.input-area'
SUGGESTION_ITEM_SELECTOR = 'material-select-item.item'
CONTENT_LOADED_SELECTOR = 'creative-grid, advertiser-info-card'

_WORD_RE = re.compile(r'[a-zA-Z0-9]+')


def _name_words(name: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(name) if len(w) > 2]


def _normalize_name(text: str) -> str:
    """Lowercase and collapse punctuation/whitespace so 'TBWA\\Worldwide' and
    'TBWA Worldwide' (or 'Wpromote, LLC' and 'Wpromote') compare equal."""
    cleaned = re.sub(r'[^a-z0-9]+', ' ', text.lower())
    return re.sub(r'\s+', ' ', cleaned).strip()


# Generic corporate-entity words a suggestion's name is allowed to wrap the
# target name in (prefix or suffix) and still count as a confident match.
# Anything else wrapping the target (e.g. "Creative" in "Creative Power
# Digital", or "Link"/"Group" interleaved in "Power Link Digital Group") is a
# different company that merely shares some words, not a name match.
_CORP_WRAPPER_WORDS = {
    'the', 'a', 'inc', 'llc', 'corp', 'corporation', 'co', 'company',
    'ltd', 'limited', 'group', 'holdings', 'international', 'global',
    'worldwide', 'enterprises', 'partners', 'plc', 'gmbh', 'srl', 'sro',
    'bv', 'ag', 'sa', 'kg', 'cie',
}


def _is_confident_name_match(name: str, candidate_name: str) -> bool:
    """True if `name`'s words appear as a contiguous, in-order run inside
    `candidate_name`'s words, with only generic corporate-wrapper words
    (if any) outside that run."""
    target_words = _normalize_name(name).split()
    candidate_words = _normalize_name(candidate_name).split()
    if not target_words or len(candidate_words) < len(target_words):
        return False
    n = len(target_words)
    for start in range(len(candidate_words) - n + 1):
        if candidate_words[start:start + n] == target_words:
            wrapper_words = candidate_words[:start] + candidate_words[start + n:]
            if all(w in _CORP_WRAPPER_WORDS for w in wrapper_words):
                return True
    return False


def _parse_ads_count(text: str) -> int | None:
    """Parse strings like '26 ads', '~32 ads', '~2.2K ads' into an int estimate."""
    m = re.search(r'([\d.]+)\s*(K|M)?\s*ads?', text, re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1))
    suffix = (m.group(2) or '').upper()
    if suffix == 'K':
        value *= 1_000
    elif suffix == 'M':
        value *= 1_000_000
    return int(value)


async def _score_suggestion(item, name: str, target_words: list[str]) -> dict:
    text = (await item.inner_text()).strip()
    lower = text.lower()
    is_domain = await item.evaluate("el => !!el.querySelector('.domain-suggestion')")
    if is_domain:
        return {'item': item, 'kind': 'domain', 'score': -1, 'text': text}

    name_line = text.splitlines()[0] if text else ''
    ambiguous = 'multiple advertiser' in lower
    verified = 'verified' in lower
    overlap = sum(1 for w in target_words if w in lower)

    # A confident match requires `name`'s words to appear as a contiguous run
    # inside the suggestion's name, wrapped by nothing but generic corporate
    # words ("The X Inc", "X, LLC"). Rejects a different company that merely
    # contains the same words via a substantive prefix/interleaving, e.g.
    # "Power Digital" inside "Creative Power Digital" or "Power Link Digital Group".
    is_substring_match = _is_confident_name_match(name, name_line)

    if is_substring_match:
        length_penalty = max(0, len(name_line) - len(name))
        score = 1000 - length_penalty + (5 if verified else 0) - (3 if ambiguous else 0)
    else:
        score = overlap * 10 + (2 if verified else 0) - (1 if ambiguous else 0)

    return {
        'item': item,
        'kind': 'advertiser',
        'score': score,
        'overlap': overlap,
        'verified': verified,
        'ambiguous': ambiguous,
        'is_substring_match': is_substring_match,
        'name_line': name_line,
        'ads_count_hint': _parse_ads_count(text),
        'text': text,
    }


async def resolve_advertiser(page, name: str) -> dict:
    """
    Perform a real search on the Ads Transparency Center: load the homepage,
    type `name` into the actual search box, wait for autocomplete suggestions,
    and click the best-matching advertiser suggestion.

    Returns a dict describing what happened:
      {'method': 'advertiser_match', 'suggestion_text': str, 'verified': bool,
       'ambiguous': bool, 'ads_count_hint': int|None}
      {'method': 'no_match'}            -- no autocomplete suggestions at all
      {'method': 'no_relevant_match'}   -- suggestions existed but none shared a word with `name`
      {'method': 'low_confidence_match', 'rejected_candidate': str}
          -- a suggestion shared words with `name` but `name` wasn't a contiguous
             substring of it (e.g. "Power Digital" vs "Power Link Digital Group")
             — NOT auto-selected; surfaced for manual review instead.
      {'method': 'error', 'reason': str}
    """
    home_url = f"{GOOGLE_ADS_BASE}?region=anywhere&hl=en"
    try:
        await page.goto(home_url, wait_until='domcontentloaded', timeout=30_000)
    except PlaywrightTimeoutError:
        logger.warning("  Homepage load timeout")
        return {'method': 'error', 'reason': 'homepage_timeout'}

    await asyncio.sleep(random.uniform(2, 3))
    await dismiss_dialogs(page)

    try:
        await page.click(SEARCH_INPUT_SELECTOR, timeout=8_000)
    except PlaywrightTimeoutError:
        logger.warning("  Search input not found on homepage")
        return {'method': 'error', 'reason': 'search_input_not_found'}

    await page.fill(SEARCH_INPUT_SELECTOR, name)
    await asyncio.sleep(random.uniform(2, 3))

    items = await page.query_selector_all(SUGGESTION_ITEM_SELECTOR)
    if not items:
        logger.info(f"  No autocomplete suggestions for {name!r}")
        return {'method': 'no_match'}

    target_words = _name_words(name)
    scored = [await _score_suggestion(it, name, target_words) for it in items]
    candidates = [s for s in scored if s['kind'] == 'advertiser' and s['overlap'] > 0]

    if not candidates:
        logger.info(f"  Suggestions exist for {name!r} but none matched by name")
        return {'method': 'no_relevant_match'}

    confident = [c for c in candidates if c['is_substring_match']]
    if not confident:
        candidates.sort(key=lambda s: (s['score'], s['ads_count_hint'] or 0), reverse=True)
        rejected = candidates[0]
        logger.info(
            f"  No confident match for {name!r} — best candidate {rejected['name_line']!r} "
            f"rejected (shares words but isn't a substring match); not auto-selecting"
        )
        return {'method': 'low_confidence_match', 'rejected_candidate': rejected['name_line']}

    confident.sort(key=lambda s: (s['score'], s['ads_count_hint'] or 0), reverse=True)
    best = confident[0]

    logger.info(f"  Best match: {best['text'].splitlines()[0]!r} (score={best['score']})")
    await best['item'].click()
    await asyncio.sleep(random.uniform(2, 3))

    try:
        await page.wait_for_selector(CONTENT_LOADED_SELECTOR, timeout=12_000)
    except PlaywrightTimeoutError:
        logger.warning(f"  Clicked suggestion but no results content loaded for {name!r}")
        return {'method': 'error', 'reason': 'content_not_loaded'}

    return {
        'method': 'advertiser_match',
        'suggestion_text': best['text'],
        'verified': best['verified'],
        'ambiguous': best['ambiguous'],
        'ads_count_hint': best['ads_count_hint'],
    }


# ─── Ad extraction ─────────────────────────────────────────────────────────────
#
# Grid-level extraction pulls advertiser metadata, total ad count, and
# per-creative format/snapshot/detail-link — this part is universal and cheap
# (no per-ad page visit). 'static' covers both image and text ads since the
# grid renders both identically and indistinguishably; the per-ad tiered
# extraction below (extract_ad_detail) is what actually resolves real text.

DISCOVER_ADS_MARKER = 'discover_ads'
SADBUNDLE_MARKER = 'sadbundle'
OCR_CONFIDENCE_THRESHOLD = 60   # tesseract per-word confidence (0-100) to keep a word
OCR_MIN_KEPT_WORDS = 4          # below this many kept words, the OCR pass is too noisy to trust

_DISPLAY_URL_RE = re.compile(r'\b(?:www\.)?[a-z0-9-]+\.[a-z]{2,}(?:/[\w/-]*)?\b', re.IGNORECASE)


def _extract_domain(text: str) -> str | None:
    """Pull a bare registrable-ish domain (no scheme, no www.) out of a real
    URL or a noisy OCR string that contains one somewhere. Returns None
    (never a guess) when no URL-shaped substring is actually present, so
    plain ad-copy text like 'B2B Communications Agency' never gets
    misread as a fake domain."""
    if not text:
        return None
    if text.lower().startswith('http'):
        candidate = text
    else:
        m = _DISPLAY_URL_RE.search(text)
        if not m:
            return None
        candidate = 'http://' + m.group(0)
    try:
        netloc = urllib.parse.urlparse(candidate).netloc.lower().split(':')[0]
    except Exception:
        return None
    return netloc[4:] if netloc.startswith('www.') else (netloc or None)


def _resolve_ad_domain(ad: dict) -> str | None:
    """Look for a recognizable domain anywhere we might have captured one,
    in order of trustworthiness (real link first, OCR text last)."""
    for field in ('landing_url', 'display_url_text', 'headline', 'ad_text'):
        domain = _extract_domain(ad.get(field) or '')
        if domain:
            return domain
    return None


def _is_client_campaign(ad: dict, own_domain: str | None) -> bool:
    """True only on POSITIVE evidence the ad promotes a different domain than
    the agency's own — missing/unclear domain data is never treated as evidence
    of client work, to avoid over-filtering."""
    if not own_domain:
        return False
    ad_domain = _resolve_ad_domain(ad)
    return bool(ad_domain) and ad_domain != own_domain


def _ad_text_blob(ad: dict) -> str:
    """All text we extracted for an ad, concatenated, for substring checks."""
    return ' '.join(
        ad[field] for field in ('headline', 'description', 'ad_text', 'display_url_text')
        if ad.get(field)
    )


def _mentions_name(text: str, name: str) -> bool:
    """True if `name`'s words appear as a contiguous run anywhere inside
    `text` (after normalization) — e.g. 'Boost your funnel with Hawke Media'
    mentions advertiser name 'Hawke Media'. Unlike _is_confident_name_match,
    there's no restriction on what's allowed to surround the match: ad copy
    can wrap a brand mention in anything, not just corporate suffixes."""
    name_words = _normalize_name(name).split()
    text_words = _normalize_name(text).split()
    if not name_words or len(text_words) < len(name_words):
        return False
    n = len(name_words)
    return any(text_words[i:i + n] == name_words for i in range(len(text_words) - n + 1))


def _needs_content_review(ad: dict, own_domain: str | None, advertiser_name: str | None) -> bool:
    """Secondary filter for the gap the domain filter can't cover: when an ad's
    OCR'd/iframe text contains no extractable domain at all, _is_client_campaign
    has nothing to check and would silently let the ad through as self_brand —
    even when it's clearly unrelated client content (e.g. a museum or university
    landing page with no domain visible in the OCR crop). Only applies when the
    agency's own domain is actually on file (so the domain filter is meaningful
    for this target) and this specific ad resolved no domain whatsoever; in that
    case, fall back to checking whether the agency's own name is mentioned
    anywhere in the ad copy. If not, this can't be confirmed as self-brand and
    shouldn't be auto-saved as one."""
    if not own_domain or _resolve_ad_domain(ad):
        return False
    return not _mentions_name(_ad_text_blob(ad), advertiser_name or '')


def _split_headline_description(text: str) -> tuple[str | None, str | None]:
    """Best-effort split of a combined ad-copy blob at the first sentence boundary."""
    if not text:
        return None, None
    m = re.search(r'[.!?]\s+', text)
    if m and m.end() < len(text):
        return text[:m.end()].strip(), text[m.end():].strip()
    return text.strip(), None


def _download_image_bytes(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENTS[0]})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception as exc:
        logger.warning(f"  Image download failed: {exc}")
        return None


def _garbled_ratio(text: str) -> float:
    """Fraction of 'words' that are short, non-alphanumeric OCR noise (e.g. '+>', '€')
    — a signal that a paragraph is decorative graphic text, not real ad copy."""
    words = text.split()
    if not words:
        return 1.0
    garbled = sum(1 for w in words if len(w) <= 2 and not w.isalnum())
    return garbled / len(words)


def _ocr_paragraphs(image_bytes: bytes) -> list[dict]:
    """Run Tesseract, keep only confident words, and group them back into the
    paragraphs Tesseract's own layout analysis detected (so a wrapped two-line
    headline stays one unit instead of fragmenting into separate lines)."""
    img = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    groups: dict[tuple, list[tuple[str, int]]] = {}
    order: list[tuple] = []
    for i, word in enumerate(data['text']):
        word = word.strip()
        try:
            conf = int(data['conf'][i])
        except (ValueError, TypeError):
            conf = -1
        if not word or conf < OCR_CONFIDENCE_THRESHOLD:
            continue
        key = (data['block_num'][i], data['par_num'][i])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((word, conf))

    paragraphs = []
    for key in order:
        words = groups[key]
        text = ' '.join(w for w, _ in words)
        avg_conf = sum(c for _, c in words) / len(words)
        paragraphs.append({'text': text, 'confidence': round(avg_conf, 1), 'word_count': len(words)})
    return paragraphs


def extract_ocr_ad_content(image_bytes: bytes, advertiser_name: str | None) -> dict:
    """OCR fallback for flattened ad snapshots (no discover_ads iframe available).
    Tier 1 anchors on a display-URL-looking paragraph (the common 'Format: Text'
    SERP-mockup layout: Sponsored / advertiser / URL / headline / description).
    Tier 2 (no URL line found — banner/native-style images) takes the first two
    non-decorative paragraphs as headline/description. If neither tier finds
    anything trustworthy, the result is explicitly marked skipped — never guessed."""
    paragraphs = _ocr_paragraphs(image_bytes)
    name_lower = (advertiser_name or '').strip().lower()
    total_kept_words = sum(p['word_count'] for p in paragraphs)
    overall_conf = (
        round(sum(p['confidence'] * p['word_count'] for p in paragraphs) / total_kept_words, 1)
        if total_kept_words else 0.0
    )

    def is_boilerplate(p):
        t = p['text'].strip().lower()
        if t in ('sponsored', 'ad'):
            return True
        if name_lower and name_lower in t and len(t) <= len(name_lower) + 15:
            return True
        return False

    candidates = [p for p in paragraphs if not is_boilerplate(p)]

    def skip(reason):
        return {
            'extraction_method': 'ocr_fallback', 'confidence': overall_conf,
            'skipped': True, 'skip_reason': reason,
            'ad_text': None, 'headline': None, 'description': None, 'display_url_text': None,
        }

    if total_kept_words < OCR_MIN_KEPT_WORDS or not candidates:
        return skip('low_confidence')

    url_idx = next(
        (i for i, p in enumerate(candidates) if _DISPLAY_URL_RE.search(p['text']) and len(p['text']) < 80),
        None,
    )
    display_url_text = None
    headline = description = None
    submethod = None

    if url_idx is not None:
        display_url_text = candidates[url_idx]['text']
        rest = candidates[url_idx + 1:]
        if rest:
            headline = rest[0]['text']
        if len(rest) > 1:
            description = rest[1]['text']
        submethod = 'url_anchored'
    else:
        clean = [p for p in candidates if p['word_count'] >= 3 and _garbled_ratio(p['text']) < 0.3]
        if clean:
            headline = clean[0]['text']
            if len(clean) > 1:
                description = clean[1]['text']
            submethod = 'positional_fallback'

    if not headline:
        return skip('no_reliable_headline')

    return {
        'extraction_method': 'ocr_fallback',
        'confidence': overall_conf,
        'skipped': False,
        'ocr_submethod': submethod,
        'ad_text': ' '.join(t for t in (headline, description) if t),
        'headline': headline,
        'description': description,
        'display_url_text': display_url_text,
    }


async def extract_iframe_ad_content(page, advertiser_name: str | None) -> dict | None:
    """If the creative detail page rendered a live discover_ads gadget iframe
    (native/Discovery-style ads), pull exact text + the real landing-page link
    straight from its DOM. Returns None when no such iframe exists, so the
    caller can fall back to OCR."""
    frame = next((f for f in page.frames if DISCOVER_ADS_MARKER in f.url), None)
    if not frame:
        return None

    try:
        raw_text = (await frame.inner_text('body')).strip()
        links = await frame.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
        )
    except Exception as exc:
        logger.warning(f"  discover_ads iframe extraction error: {exc}")
        return None
    if not raw_text:
        return None

    name_lower = (advertiser_name or '').strip().lower()
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    ad_lines = [
        l for l in lines
        if l.lower().rstrip('•').strip() != 'ad'
        and not (name_lower and l.lower() == name_lower)
    ]
    ad_text = ' '.join(ad_lines) if ad_lines else raw_text
    headline, description = _split_headline_description(ad_text)

    return {
        'extraction_method': 'iframe_text',
        'confidence': 100.0,
        'skipped': False,
        'ad_text': ad_text,
        'headline': headline,
        'description': description,
        'landing_url': links[0] if links else None,
    }


async def extract_sadbundle_link(page) -> str | None:
    """Large IAB display formats (e.g. 300x600) render as a sandboxed HTML5 ad
    bundle iframe (tpc.googlesyndication.com/archive/sadbundle/...). These are
    usually canvas-rendered with no live text, but the whole creative is
    wrapped in a real <a href> pointing to Google's click-tracking redirect,
    which embeds the real destination in its `adurl` query param."""
    frame = next((f for f in page.frames if SADBUNDLE_MARKER in f.url), None)
    if not frame:
        return None
    try:
        links = await frame.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
        )
    except Exception as exc:
        logger.warning(f"  sadbundle iframe extraction error: {exc}")
        return None
    for href in links:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if qs.get('adurl'):
            return qs['adurl'][0]
    return None


async def extract_ad_detail(page, detail_url: str, advertiser_name: str | None) -> dict:
    """Visit one creative's detail page and run the tiered extraction:
    live discover_ads iframe first (exact text+link), then a sadbundle
    click-wrapper (exact link only), then OCR on the flattened snapshot
    (confidence-filtered, may come back explicitly skipped)."""
    try:
        await page.goto(detail_url, wait_until='domcontentloaded', timeout=30_000)
    except PlaywrightTimeoutError:
        return {'extraction_method': 'error', 'confidence': 0.0, 'skipped': True, 'skip_reason': 'page_timeout'}

    await asyncio.sleep(random.uniform(3, 4.5))

    iframe_result = await extract_iframe_ad_content(page, advertiser_name)
    if iframe_result:
        return iframe_result

    sadbundle_landing_url = await extract_sadbundle_link(page)
    if sadbundle_landing_url:
        return {
            'extraction_method': 'iframe_link_only',
            'confidence': 100.0,
            'skipped': False,
            'ad_text': None,
            'headline': None,
            'description': None,
            'landing_url': sadbundle_landing_url,
        }

    try:
        snapshot_url = await page.evaluate("""
            () => {
                const els = Array.from(document.querySelectorAll('html-renderer'));
                const visible = els.find(el => el.getBoundingClientRect().width > 0);
                const img = visible ? visible.querySelector('img') : null;
                return img ? img.src : null;
            }
        """)
    except Exception as exc:
        logger.warning(f"  Snapshot lookup error: {exc}")
        snapshot_url = None

    if not snapshot_url:
        return {'extraction_method': 'ocr_fallback', 'confidence': 0.0, 'skipped': True, 'skip_reason': 'no_snapshot_found'}

    image_bytes = await asyncio.to_thread(_download_image_bytes, snapshot_url)
    if not image_bytes:
        return {'extraction_method': 'ocr_fallback', 'confidence': 0.0, 'skipped': True, 'skip_reason': 'image_download_failed'}

    result = await asyncio.to_thread(extract_ocr_ad_content, image_bytes, advertiser_name)
    result['snapshot_image_url'] = snapshot_url
    return result


_CREATIVE_GRID_JS = """
    () => {
        const advertiserCard = document.querySelector('advertiser-info-card');
        const advertiserInfo = advertiserCard ? {
            name: advertiserCard.querySelector('.advertiser-name')?.innerText?.trim() || null,
            legalName: advertiserCard.querySelector('.legal-name')?.innerText?.replace('Legal name:', '').trim() || null,
            location: advertiserCard.querySelector('.location')?.innerText?.replace('Based in:', '').trim() || null,
        } : null;

        const adsCountText = document.querySelector('.ads-count')?.innerText?.trim() || null;

        const previews = Array.from(document.querySelectorAll('creative-preview')).slice(0, 30);
        const creatives = previews.map(preview => {
            const link = preview.querySelector('a[href*="/advertiser/"]');
            const href = link?.getAttribute('href') || null;
            const match = href ? href.match(/\\/advertiser\\/([^/]+)\\/creative\\/([^/?]+)/) : null;
            const img = preview.querySelector('img');
            const isVideo = (preview.innerText || '').includes('videocam') ||
                             !!preview.querySelector('[icon="videocam"]');
            return {
                advertiserId: match ? match[1] : null,
                creativeId: match ? match[2] : null,
                detailUrl: href,
                snapshotImageUrl: img?.getAttribute('src') || null,
                adFormat: isVideo ? 'video' : 'static',
            };
        }).filter(c => c.creativeId);

        return { advertiserInfo, adsCountText, creatives };
    }
"""


async def extract_advertiser_data(
    page, search_name: str, max_ads_per_advertiser: int = 5, own_website: str | None = None,
) -> dict:
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(random.uniform(1.5, 2.5))

    try:
        data = await page.evaluate(_CREATIVE_GRID_JS)
    except Exception as exc:
        logger.warning(f"  Creative grid extraction error: {exc}")
        data = {'advertiserInfo': None, 'adsCountText': None, 'creatives': []}

    creatives = data.get('creatives') or []
    advertiser_info = data.get('advertiserInfo')
    advertiser_name = (advertiser_info or {}).get('name') or search_name
    own_domain = _extract_domain(own_website) if own_website else None

    ads = [
        {
            'creative_id': c['creativeId'],
            'advertiser_id': c['advertiserId'],
            'ad_format': c['adFormat'],
            'detail_url': f"{GOOGLE_ADS_BASE.rstrip('/')}{c['detailUrl']}" if c.get('detailUrl') else None,
            'snapshot_image_url': c.get('snapshotImageUrl'),
        }
        for c in creatives
    ]

    deep_dive_count = 0
    filtered_client_count = 0
    needs_review_count = 0
    for ad in ads:
        if ad['ad_format'] == 'video':
            ad['extraction_method'] = 'skipped_video'
            continue
        if not ad['detail_url'] or deep_dive_count >= max_ads_per_advertiser:
            ad['extraction_method'] = 'not_attempted'
            continue

        deep_dive_count += 1
        logger.info(f"    [{deep_dive_count}/{max_ads_per_advertiser}] Extracting ad content: {ad['creative_id']}")
        try:
            detail = await extract_ad_detail(page, ad['detail_url'], advertiser_name)
        except Exception as exc:
            logger.warning(f"  Ad detail extraction error for {ad['creative_id']}: {exc}")
            detail = {'extraction_method': 'error', 'confidence': 0.0, 'skipped': True, 'skip_reason': str(exc)}
        ad.update(detail)

        if not detail.get('skipped') and _is_client_campaign(ad, own_domain):
            ad_domain = _resolve_ad_domain(ad)
            logger.info(
                f"      Filtering as client campaign: ad domain {ad_domain!r} != "
                f"agency domain {own_domain!r}"
            )
            ad['pre_filter_method'] = ad['extraction_method']
            ad['extraction_method'] = 'filtered_client_campaign'
            ad['filter_reason'] = f"ad domain ({ad_domain}) != agency's own domain ({own_domain})"
            filtered_client_count += 1
        elif not detail.get('skipped') and _needs_content_review(ad, own_domain, advertiser_name):
            logger.info(
                f"      Flagging needs_review: no domain extractable and agency "
                f"name ({advertiser_name!r}) not found in ad text"
            )
            ad['pre_filter_method'] = ad['extraction_method']
            ad['extraction_method'] = 'needs_review'
            ad['filter_reason'] = (
                f"no domain extractable from ad text, and agency name "
                f"({advertiser_name!r}) not found in headline/body"
            )
            needs_review_count += 1
        else:
            logger.info(
                f"      method={detail.get('extraction_method')} confidence={detail.get('confidence')} "
                f"skipped={detail.get('skipped')} headline={(detail.get('headline') or '')[:60]!r}"
            )
        await asyncio.sleep(random.uniform(2.5, 4))

    landing_urls = sorted({
        ad['landing_url'] for ad in ads
        if ad.get('landing_url') and ad.get('extraction_method') not in ('filtered_client_campaign', 'needs_review')
    })
    self_brand_count = sum(
        1 for ad in ads
        if ad.get('extraction_method') in ('iframe_text', 'iframe_link_only', 'ocr_fallback')
        and not ad.get('skipped')
    )

    return {
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'source': 'google_ads_transparency',
        'search_name': search_name,
        'advertiser_info': advertiser_info,
        'ads_count_text': data.get('adsCountText'),
        'ads_found': len(ads) > 0,
        'ad_count_found': len(ads),
        'ads_deep_extracted': deep_dive_count,
        'ads_self_brand_count': self_brand_count,
        'ads_filtered_client_count': filtered_client_count,
        'ads_needs_review_count': needs_review_count,
        'ads': ads,
        'landing_page_urls': landing_urls,
    }


# ─── Main search orchestrator ──────────────────────────────────────────────────

async def search_transparency_center(
    page, name: str, max_ads_per_advertiser: int = 5, own_website: str | None = None,
) -> dict:
    """
    Resolve `name` to a real advertiser via the Transparency Center's autocomplete
    search, then extract whatever genuine ad/creative data is available.
    """
    resolution = await resolve_advertiser(page, name)
    method = resolution['method']

    if method != 'advertiser_match':
        logger.info(f"  No advertiser resolved for {name!r} (method={method})")
        result = {
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            'source': 'google_ads_transparency',
            'search_name': name,
            'search_method': method,
            'ads_found': False,
            'ad_count_found': 0,
            'ads': [],
            'landing_page_urls': [],
        }
        if method == 'low_confidence_match':
            result['rejected_candidate'] = resolution['rejected_candidate']
        return result

    result = await extract_advertiser_data(
        page, name, max_ads_per_advertiser=max_ads_per_advertiser, own_website=own_website,
    )
    result['search_method'] = method
    result['matched_suggestion'] = resolution['suggestion_text'].splitlines()[0]
    result['matched_verified'] = resolution['verified']
    result['matched_ambiguous'] = resolution['ambiguous']
    return result


# ─── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description='Google Ads Transparency scraper for agencies and authority sources'
    )
    parser.add_argument('--type', choices=['agency', 'authority', 'all'], default='all')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument(
        '--test', action='store_true',
        help='Dry run: extract and print results without writing to the DB',
    )
    parser.add_argument(
        '--names', nargs='+', default=None,
        help='Test specific advertiser names directly (implies --test, no DB involved)',
    )
    parser.add_argument(
        '--headless', action='store_true',
        help='Run the browser headless (default is visible, for manual inspection)',
    )
    parser.add_argument(
        '--max-ads-per-advertiser', type=int, default=5,
        help='How many non-video ads per advertiser to visit for tiered text extraction (default 5)',
    )
    args = parser.parse_args()

    dry_run = args.test or bool(args.names)
    conn = None

    if args.names:
        websites: dict[str, str | None] = {}
        try:
            lookup_conn = get_db_connection()
            try:
                websites = lookup_websites(lookup_conn, args.names)
            finally:
                lookup_conn.close()
        except Exception as exc:
            logger.warning(f"Could not look up agency websites for --names targets: {exc}")
        targets = [
            {'id': None, 'name': n, 'website': websites.get(n), 'table': None}
            for n in args.names
        ]
    else:
        conn = get_db_connection()
        targets = get_targets(conn, args.type)[:args.limit]
        if not targets:
            logger.info("No targets found")
            conn.close()
            return

    logger.info(
        f"Targets: {len(targets)} | dry_run={dry_run} | "
        f"{'names=' + str(args.names) if args.names else f'type={args.type} limit={args.limit}'}"
    )
    stats = {'saved': 0, 'errors': 0, 'landing_urls': 0, 'advertiser_hits': 0}

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
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = await context.new_page()

        for i, target in enumerate(targets, 1):
            logger.info(f"\n[{i}/{len(targets)}] [{target['table']}] {target['name']}")
            try:
                results = await search_transparency_center(
                    page, target['name'],
                    max_ads_per_advertiser=args.max_ads_per_advertiser,
                    own_website=target.get('website'),
                )
                landing_urls = results.get('landing_page_urls', [])

                if dry_run:
                    if results.get('search_method') == 'low_confidence_match':
                        logger.info(
                            f"  [DRY RUN] low_confidence_match — rejected candidate: "
                            f"{results.get('rejected_candidate')!r} (not auto-selected)"
                        )
                    else:
                        logger.info(
                            f"  [DRY RUN] advertiser_info={results.get('advertiser_info')} "
                            f"ads_count_text={results.get('ads_count_text')} "
                            f"self_brand={results.get('ads_self_brand_count')} "
                            f"filtered_client={results.get('ads_filtered_client_count')} "
                            f"needs_review={results.get('ads_needs_review_count')}"
                        )
                    for ad in results.get('ads', []):
                        logger.info(
                            f"    ad={ad.get('creative_id')} format={ad.get('ad_format')} "
                            f"method={ad.get('extraction_method')} confidence={ad.get('confidence')} "
                            f"skipped={ad.get('skipped')} "
                            f"headline={(ad.get('headline') or '')[:80]!r} "
                            f"url={ad.get('landing_url') or ad.get('display_url_text')}"
                        )
                else:
                    merge_and_save(conn, target, results)
                    seed_landing_page_urls(conn, landing_urls, target, 'google_ads')

                stats['saved'] += 1
                stats['landing_urls'] += len(landing_urls)
                if results.get('search_method') == 'advertiser_match':
                    stats['advertiser_hits'] += 1

                logger.info(
                    f"  Done | method={results['search_method']} "
                    f"| ads={results['ad_count_found']} "
                    f"| landing_urls={len(landing_urls)}"
                )
            except Exception as exc:
                logger.error(f"  Error: {exc}")
                stats['errors'] += 1
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            if i < len(targets):
                await random_delay(5, 10)

        await browser.close()

    if conn:
        conn.close()
    logger.info(
        f"\n=== Done: {stats['saved']} processed | {stats['errors']} errors | "
        f"{stats['advertiser_hits']} advertiser matches | "
        f"{stats['landing_urls']} landing URLs seeded | dry_run={dry_run} ==="
    )


if __name__ == '__main__':
    asyncio.run(main())
