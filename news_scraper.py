#!/usr/bin/env python3
"""
Google News RSS scraper for the niche intelligence platform.
- Fetches articles via Google News RSS feed
- Saves to raw_source_data with source_type='google_news'
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

RSS_BASE = 'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'


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


def save_article(conn, niche_id: int, article: dict):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO raw_source_data
                (niche_id, source_type, source_url, title, content, raw_data)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            niche_id,
            'google_news',
            article['url'],
            article['title'][:500],
            article['description'],
            json.dumps({
                'title': article['title'],
                'description': article['description'],
                'published': article['published'],
                'url': article['url'],
            }),
        ))
    conn.commit()


# ─── Parsing ──────────────────────────────────────────────────────────────────

def parse_published(entry) -> str:
    """Return ISO timestamp string from feed entry, fallback to now."""
    raw = entry.get('published', '') or entry.get('updated', '')
    if raw:
        try:
            return parsedate_to_datetime(raw).isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()


def parse_description(entry) -> str:
    """Extract plain-text summary, stripping HTML if present."""
    raw = entry.get('summary', '') or ''
    # feedparser usually returns HTML for Google News; strip tags naively
    import re
    return re.sub(r'<[^>]+>', '', raw).strip()[:2000]


# ─── Scraper ──────────────────────────────────────────────────────────────────

def scrape_news(niche_id: int, query: str, limit: int):
    stats = {'new': 0, 'duplicates': 0, 'errors': 0}

    try:
        conn = get_db_connection()
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")
        return stats

    rss_url = RSS_BASE.format(query=quote_plus(query))
    logger.info(f"📡 Fetching RSS feed for: \"{query}\"")
    logger.info(f"   URL: {rss_url}")

    feed = feedparser.parse(rss_url)

    if feed.bozo and not feed.entries:
        logger.error(f"❌ Failed to parse RSS feed: {feed.bozo_exception}")
        conn.close()
        return stats

    entries = feed.entries[:limit]
    logger.info(f"📰 Found {len(feed.entries)} articles, processing up to {limit}\n")

    for i, entry in enumerate(entries, 1):
        url = entry.get('link', '')
        title = entry.get('title', '').strip()

        if not url or not title:
            logger.warning(f"⚠️  [{i}/{len(entries)}] Skipping entry with missing url/title")
            stats['errors'] += 1
            continue

        if is_duplicate(conn, url):
            logger.info(f"⏭️  [{i}/{len(entries)}] Duplicate — {title[:60]}")
            stats['duplicates'] += 1
            continue

        article = {
            'url': url,
            'title': title,
            'description': parse_description(entry),
            'published': parse_published(entry),
        }

        try:
            save_article(conn, niche_id, article)
            logger.info(f"✅ [{i}/{len(entries)}] Saved — {title[:60]}")
            stats['new'] += 1
        except Exception as e:
            logger.error(f"❌ [{i}/{len(entries)}] DB error: {e}")
            stats['errors'] += 1

    conn.close()

    logger.info(
        f"\n📊 Done — "
        f"{stats['new']} new | "
        f"{stats['duplicates']} duplicates skipped | "
        f"{stats['errors']} errors"
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Google News RSS scraper for niche intelligence platform'
    )
    parser.add_argument(
        '--niche-id', type=int, default=1,
        help='Niche ID to tag articles with (default: 1)'
    )
    parser.add_argument(
        '--query', default='exotic car rental',
        help='Search query for Google News (default: "exotic car rental")'
    )
    parser.add_argument(
        '--limit', type=int, default=20,
        help='Max articles to fetch (default: 20)'
    )
    args = parser.parse_args()

    logger.info(f"🚀 News Scraper — niche_id={args.niche_id}, query=\"{args.query}\", limit={args.limit}")
    scrape_news(args.niche_id, args.query, args.limit)


if __name__ == '__main__':
    main()
