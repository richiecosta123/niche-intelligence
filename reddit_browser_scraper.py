"""
Reddit headless browser scraper using Playwright + old.reddit.com.
No API credentials needed. Uses server-rendered HTML — reliable & fast.
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

OLD_REDDIT = 'https://old.reddit.com'


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


def save_post(conn, post: dict, niche_id: int = 2):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO raw_source_data
                (niche_id, source_type, source_url, source_id, title,
                 content, author, score, engagement_metrics, raw_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            niche_id,
            'reddit',
            post.get('url'),
            post.get('post_id'),
            post.get('title', '')[:500],
            post.get('selftext') or post.get('preview_text', ''),
            post.get('author'),
            int(post.get('score') or 0),
            json.dumps({
                'comment_count': post.get('comment_count', 0),
                'subreddit': post.get('subreddit', ''),
                'keyword': post.get('keyword', ''),
            }),
            json.dumps(post),
        ))
    conn.commit()


# ─── Browser helpers ──────────────────────────────────────────────────────────

async def random_delay(min_s: float = 1.0, max_s: float = 3.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


def parse_score(text: str) -> int:
    """Parse '189 points' or '1.2k points' → int."""
    if not text:
        return 0
    text = text.lower().replace(',', '').strip()
    m = re.search(r'([\d.]+)\s*k', text)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r'(\d+)', text)
    return int(m.group(1)) if m else 0


def parse_comments(text: str) -> int:
    """Parse '86 comments' → 86."""
    if not text:
        return 0
    m = re.search(r'(\d+)', text.replace(',', ''))
    return int(m.group(1)) if m else 0


# ─── Post extraction from old.reddit.com search ───────────────────────────────

async def extract_search_post(el) -> dict | None:
    """Extract post data from a .search-result-link element."""
    try:
        # Post URL + ID
        title_link = await el.query_selector('a.search-title')
        if not title_link:
            return None
        title = (await title_link.inner_text()).strip()
        href = await title_link.get_attribute('href') or ''
        if href.startswith('/'):
            url = f"https://www.reddit.com{href}"
        elif 'reddit.com' in href:
            # Normalise to www
            url = href.replace('old.reddit.com', 'www.reddit.com')
        else:
            return None

        # Extract post ID from URL (r/sub/comments/ID/...)
        post_id = ''
        m = re.search(r'/comments/([a-z0-9]+)/', url)
        if m:
            post_id = m.group(1)

        # Subreddit
        subreddit = ''
        sub_el = await el.query_selector('a.search-subreddit-link')
        if sub_el:
            subreddit = (await sub_el.inner_text()).strip().lstrip('r/')

        # Author
        author = ''
        auth_el = await el.query_selector('a.author')
        if auth_el:
            author = (await auth_el.inner_text()).strip()

        # Score
        score = 0
        score_el = await el.query_selector('span.search-score')
        if score_el:
            score = parse_score(await score_el.inner_text())

        # Comment count
        comment_count = 0
        comments_el = await el.query_selector('a.search-comments')
        if comments_el:
            comment_count = parse_comments(await comments_el.inner_text())

        # Timestamp
        created_at = ''
        time_el = await el.query_selector('time')
        if time_el:
            created_at = await time_el.get_attribute('datetime') or ''

        # Preview / body text visible in search
        preview_text = ''
        body_el = await el.query_selector('.search-result-body .md')
        if body_el:
            preview_text = (await body_el.inner_text()).strip()

        # data-fullname on parent .search-result
        # (search-result-link is inside .search-result)
        fullname = await el.get_attribute('data-fullname') or f't3_{post_id}'

        return {
            'url': url,
            'post_id': post_id,
            'fullname': fullname,
            'title': title,
            'subreddit': subreddit,
            'author': author,
            'score': score,
            'comment_count': comment_count,
            'created_at': created_at,
            'preview_text': preview_text,
            'selftext': '',
            'comments': [],
            'scraped_at': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.debug(f"Element extraction error: {exc}")
        return None


# ─── Full post content ────────────────────────────────────────────────────────

async def scrape_full_post(page, post: dict) -> dict:
    """Visit post on old.reddit.com and get full body + top 20 comments."""
    old_url = post['url'].replace('www.reddit.com', 'old.reddit.com')
    try:
        await page.goto(old_url, wait_until='domcontentloaded', timeout=30000)
        await random_delay(1.0, 2.0)

        result: dict = {}

        # Full self-text
        body_el = await page.query_selector('.usertext-body .md')
        if body_el:
            result['selftext'] = (await body_el.inner_text()).strip()

        # Top comments
        comments = []
        comment_els = await page.query_selector_all('div.comment')
        for c_el in comment_els[:20]:
            try:
                # Skip deleted/removed
                deleted = await c_el.get_attribute('class') or ''
                if 'deleted' in deleted:
                    continue

                body_el2 = await c_el.query_selector('.usertext-body .md')
                body = (await body_el2.inner_text()).strip() if body_el2 else ''

                auth_el = await c_el.query_selector('a.author')
                author = (await auth_el.inner_text()).strip() if auth_el else '[deleted]'

                score_el = await c_el.query_selector('span.score.unvoted, span.score.likes')
                score_text = (await score_el.inner_text()).strip() if score_el else ''
                score = parse_score(score_text)

                if body:
                    comments.append({'author': author, 'body': body[:600], 'score': score})
            except Exception:
                continue

        result['comments'] = comments
        return result

    except PlaywrightTimeoutError:
        logger.warning(f"  ⚠️  Timeout: {old_url[:70]}")
        return {}
    except Exception as exc:
        logger.warning(f"  ⚠️  Error fetching post: {exc}")
        return {}


# ─── Main scraper ─────────────────────────────────────────────────────────────

async def scrape_reddit(args) -> dict:
    keyword: str = args.keywords
    limit: int = args.limit
    fetch_full: bool = args.full_content
    headless: bool = args.headless
    slow_mo: int = args.slow_mo
    niche_id: int = args.niche_id
    dry_run: bool = args.dry_run

    stats = {'new': 0, 'duplicates': 0, 'errors': 0}

    conn = None
    if not dry_run:
        try:
            conn = get_db_connection()
            logger.info("✅ Database connected")
        except Exception as exc:
            logger.error(f"❌ DB connection failed: {exc}")
            return stats

    # old.reddit.com search caps at 25 results per sort order.
    # We rotate through all 4 sort orders to collect up to 100 unique posts.
    SORT_ORDERS = ['relevance', 'top', 'new', 'comments']

    async with async_playwright() as p:
        logger.info("🌐 Opening browser...")

        browser = await p.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
            ],
        )

        ctx = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
            timezone_id='America/New_York',
            extra_http_headers={'Accept-Language': 'en-US,en;q=0.9'},
        )

        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome={runtime:{}};"
        )

        page = await ctx.new_page()

        try:
            logger.info(f"🔍 Searching for: {keyword}")

            posts: list[dict] = []
            seen_urls: set[str] = set()

            for sort in SORT_ORDERS:
                if len(posts) >= limit:
                    break

                search_url = (
                    f"{OLD_REDDIT}/search/?q={quote(keyword)}"
                    f"&sort={sort}&t=all&type=link"
                )
                logger.info(f"  Sort: {sort}")
                await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
                await random_delay(1.5, 2.5)

                try:
                    await page.wait_for_selector('.search-result-link', timeout=12000)
                except PlaywrightTimeoutError:
                    logger.warning(f"  ⚠️  No results for sort={sort}. Skipping.")
                    continue

                elements = await page.query_selector_all('.search-result-link')
                sort_new = 0

                for el in elements:
                    if len(posts) >= limit:
                        break
                    post = await extract_search_post(el)
                    if not post:
                        continue
                    url = post['url']
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    post['keyword'] = keyword
                    posts.append(post)
                    sort_new += 1

                logger.info(f"    +{sort_new} unique posts (running total: {len(posts)})")

                if sort_new == 0:
                    logger.info("    All results already seen — skipping remaining sorts.")
                    break

                if len(posts) < limit:
                    await random_delay(2, 3)

            logger.info(f"📄 Found {len(posts)} posts total")

            # Optional: visit each post for full body + comments
            if fetch_full and posts:
                logger.info(f"📖 Fetching full content for {len(posts)} posts...")
                for i, post in enumerate(posts, 1):
                    logger.info(f"  [{i}/{len(posts)}] {post['title'][:55]}")
                    full = await scrape_full_post(page, post)
                    post.update(full)
                    await random_delay(1.0, 2.5)

            # Save / dry-run output
            for post in posts:
                title_short = post.get('title', 'Unknown')[:60]
                url = post.get('url', '')

                if dry_run:
                    preview = post.get('preview_text', '')[:80].replace('\n', ' ')
                    logger.info(
                        f"\n  📌 {title_short}\n"
                        f"     r/{post.get('subreddit','?')}  "
                        f"↑{post.get('score',0)}  💬{post.get('comment_count',0)}  "
                        f"👤{post.get('author','?')}\n"
                        f"     {url}\n"
                        f"     Preview: {preview}"
                    )
                    stats['new'] += 1
                    continue

                try:
                    if is_duplicate(conn, url):
                        logger.info(f"⏭️  Skipped duplicate: {title_short}")
                        stats['duplicates'] += 1
                    else:
                        save_post(conn, post, niche_id)
                        logger.info(f"✅ Saved: {title_short}")
                        stats['new'] += 1
                except Exception as exc:
                    logger.error(f"❌ Save error: {exc}")
                    stats['errors'] += 1

        except Exception as exc:
            logger.error(f"❌ Scraper crashed: {exc}")
            raise
        finally:
            await browser.close()

    if conn:
        conn.close()

    label = "DRY RUN — " if dry_run else ""
    logger.info(
        f"\n📊 {label}Final stats: "
        f"{stats['new']} new | "
        f"{stats['duplicates']} duplicates | "
        f"{stats['errors']} errors"
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Reddit headless browser scraper (old.reddit.com)')
    parser.add_argument('--keywords', default='exotic car rental', help='Search query')
    parser.add_argument('--limit', type=int, default=50, help='Max posts to collect')
    parser.add_argument('--full-content', action='store_true',
                        help='Visit each post for full body + comments')
    parser.add_argument('--headless', type=lambda v: v.lower() != 'false', default=True,
                        metavar='BOOL', help='Headless mode (default true; pass false to watch)')
    parser.add_argument('--slow-mo', type=int, default=100,
                        help='Milliseconds delay between Playwright actions')
    parser.add_argument('--niche-id', type=int, default=2)
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would be saved — no DB writes')
    args = parser.parse_args()
    asyncio.run(scrape_reddit(args))


if __name__ == '__main__':
    main()
