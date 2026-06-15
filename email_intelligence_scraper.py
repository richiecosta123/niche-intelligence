"""
Email intelligence scraper using Playwright.
Visits newsletter article URLs seeded via seed_newsletter_urls
(source_type='newsletter_pending') and extracts article title, main body
text, and publish date.

On success: source_type -> 'newsletter', extracted content/title/publish_date
saved to engagement_metrics (merged with seed metadata) and to the
title/content columns, collected_at refreshed.

On failure (timeout, HTTP error, paywall/blocked): source_type ->
'newsletter_failed', error reason saved to engagement_metrics. These rows
are not retried automatically.
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from landing_page_scraper import random_delay

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

MAX_CONTENT_CHARS = 20_000
MIN_CONTENT_CHARS = 100


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_pending_urls(conn, niche_id: int, limit: int) -> list[dict]:
    """Return rows seeded by seed_newsletter_urls and not yet scraped."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source_url, engagement_metrics
            FROM raw_source_data
            WHERE niche_id = %s
              AND source_type = 'newsletter_pending'
              AND source_url IS NOT NULL
              AND source_url != ''
            ORDER BY id ASC
            LIMIT %s
            """,
            (niche_id, limit),
        )
        return [
            {'id': r[0], 'url': r[1], 'engagement_metrics': r[2] or {}}
            for r in cur.fetchall()
        ]


def save_success(conn, row_id: int, title: str, extracted: dict, existing_metrics: dict):
    metrics = dict(existing_metrics)
    metrics.update({
        'publish_date': extracted['publish_date'],
        'scraped_at': datetime.now(timezone.utc).isoformat(),
    })
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE raw_source_data
            SET source_type = 'newsletter',
                title = %s,
                content = %s,
                engagement_metrics = %s,
                collected_at = NOW()
            WHERE id = %s
            """,
            (title[:500], extracted['content'], json.dumps(metrics), row_id),
        )
    conn.commit()


def save_failure(conn, row_id: int, existing_metrics: dict, reason: str):
    metrics = dict(existing_metrics)
    metrics.update({
        'error': reason[:300],
        'failed_at': datetime.now(timezone.utc).isoformat(),
    })
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE raw_source_data
            SET source_type = 'newsletter_failed',
                engagement_metrics = %s
            WHERE id = %s
            """,
            (json.dumps(metrics), row_id),
        )
    conn.commit()


# ─── Extraction helpers ────────────────────────────────────────────────────────

async def safe_text(el) -> str:
    try:
        return (await el.inner_text()).strip()
    except Exception:
        return ''


async def extract_publish_date(page) -> str:
    try:
        time_el = await page.query_selector('time[datetime]')
        if time_el:
            dt = (await time_el.get_attribute('datetime') or '').strip()
            if dt:
                return dt
    except Exception:
        pass

    for selector in (
        'meta[property="article:published_time"]',
        'meta[property="og:published_time"]',
        'meta[name="article:published_time"]',
        'meta[name="publish-date"]',
        'meta[name="date"]',
    ):
        try:
            meta_el = await page.query_selector(selector)
            if meta_el:
                content = (await meta_el.get_attribute('content') or '').strip()
                if content:
                    return content
        except Exception:
            continue

    return ''


async def extract_title(page) -> str:
    """Prefer og:title, then first <h1> inside <article>/<main>, then <title>."""
    try:
        meta_el = await page.query_selector('meta[property="og:title"]')
        if meta_el:
            content = (await meta_el.get_attribute('content') or '').strip()
            if content:
                return content
    except Exception:
        pass

    for selector in ('article h1', 'main h1'):
        try:
            el = await page.query_selector(selector)
            if el:
                text = await safe_text(el)
                if text:
                    return text
        except Exception:
            continue

    return await page.title() or ''


def is_cloudflare_challenge(extracted: dict) -> bool:
    """Detect a Cloudflare 'Just a moment...' interstitial that slipped past
    the HTTP status / networkidle checks."""
    title = (extracted['title'] or '').strip()
    if 'Just a moment' in title:
        return True
    if len(extracted['content']) < 500 and not extracted['publish_date']:
        return True
    return False


async def extract_article(page) -> dict:
    """Extract title, main article text, and publish date from the current page."""
    title = await extract_title(page)

    content = ''
    for selector in ('article', 'main'):
        try:
            el = await page.query_selector(selector)
            if el:
                text = await safe_text(el)
                if len(text) > len(content):
                    content = text
        except Exception:
            continue

    if not content:
        try:
            body_el = await page.query_selector('body')
            if body_el:
                content = await safe_text(body_el)
        except Exception:
            pass

    publish_date = await extract_publish_date(page)

    return {
        'title': title,
        'content': content[:MAX_CONTENT_CHARS],
        'publish_date': publish_date,
    }


# ─── Main scrape loop ─────────────────────────────────────────────────────────

async def scrape(niche_id: int, limit: int, batch_size: int, headless: bool, test: bool):
    conn = get_db_connection()

    fetch_limit = min(limit, 3) if test else limit
    pending = get_pending_urls(conn, niche_id, fetch_limit)

    if not pending:
        logger.info("✅ No pending newsletter URLs to scrape.")
        conn.close()
        return {'success': 0, 'failed': 0}

    mode = " [TEST MODE — no DB writes]" if test else ""
    logger.info(f"📧 Found {len(pending)} newsletter URLs to scrape{mode}")
    stats = {'success': 0, 'failed': 0}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)

        for i, item in enumerate(pending, 1):
            url = item['url']
            row_id = item['id']
            metrics = item['engagement_metrics']
            logger.info(f"[{i}/{len(pending)}] id={row_id} — {url[:80]}")

            # Fresh context per URL — a shared session accumulates cookies/fingerprint
            # signals that some sites (e.g. Cloudflare) use to escalate to a 403
            # on the 2nd+ request.
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={'width': 1280, 'height': 900},
                java_script_enabled=True,
            )
            page = await context.new_page()

            try:
                response = await page.goto(url, wait_until='domcontentloaded', timeout=20_000)

                if response is not None and response.status >= 400:
                    raise ValueError(f"HTTP {response.status}")

                try:
                    await page.wait_for_load_state('networkidle', timeout=10_000)
                except PlaywrightTimeoutError:
                    pass
                await random_delay(2.0, 3.0)

                extracted = await extract_article(page)
                content_len = len(extracted['content'])

                if is_cloudflare_challenge(extracted):
                    raise ValueError('cloudflare_challenge')

                if content_len < MIN_CONTENT_CHARS:
                    raise ValueError(
                        f"insufficient content extracted ({content_len} chars) — likely paywall or block"
                    )

                title = extracted['title'] or url

                if test:
                    logger.info(
                        f"  ✅ [TEST] title={title[:80]!r} | content_len={content_len} | "
                        f"publish_date={extracted['publish_date'] or 'n/a'}"
                    )
                    logger.info(f"  [TEST] content preview: {extracted['content'][:300]!r}")
                else:
                    save_success(conn, row_id, title, extracted, metrics)
                    logger.info(
                        f"  ✅ Saved | title={title[:60]!r} | content_len={content_len} | "
                        f"publish_date={extracted['publish_date'] or 'n/a'}"
                    )
                stats['success'] += 1

            except PlaywrightTimeoutError:
                reason = 'timeout'
                logger.warning(f"  ⏱️  Failed (timeout) — {url[:70]}")
                if not test:
                    save_failure(conn, row_id, metrics, reason)
                stats['failed'] += 1
            except Exception as exc:
                reason = str(exc)
                logger.error(f"  ❌ Failed ({reason}) — {url[:70]}")
                if not test:
                    save_failure(conn, row_id, metrics, reason)
                stats['failed'] += 1
            finally:
                await context.close()

            if i < len(pending):
                if i % batch_size == 0:
                    logger.info(f"  [batch {i // batch_size}] pausing...")
                    await random_delay(20.0, 30.0)
                else:
                    await random_delay(8.0, 15.0)

        await browser.close()

    conn.close()

    logger.info(f"\n📊 Done: {stats['success']} succeeded | {stats['failed']} failed")
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Email intelligence scraper')
    parser.add_argument('--niche-id', type=int, required=True)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--batch', type=int, default=5,
                         help='Pause longer after every N URLs (default: 5)')
    parser.add_argument('--headless', action='store_true', default=False)
    parser.add_argument('--test', action='store_true',
                         help='Process max 3 URLs, no DB writes, print extracted content')
    args = parser.parse_args()

    asyncio.run(scrape(
        niche_id=args.niche_id,
        limit=args.limit,
        batch_size=args.batch,
        headless=args.headless,
        test=args.test,
    ))
