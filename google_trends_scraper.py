#!/usr/bin/env python3
"""
Google Trends scraper — saves search volume and seasonality data to raw_source_data.
Collects for 9 keywords: interest over time (52 weeks), interest by region (US states),
and related queries (top + rising). Batches up to 5 keywords per request.
"""

import json
import logging
import os
import random
import sys
import time
from urllib.parse import quote

import psycopg2
from dotenv import load_dotenv
from pytrends.request import TrendReq

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

NICHE_ID = 1
TIMEFRAME = 'today 12-m'
BATCH_SIZE = 5
REFRESH_AFTER_DAYS = 30

PRIMARY_KEYWORDS = [
    "exotic car rental",
    "supercar rental",
    "luxury car rental",
    "lamborghini rental",
    "ferrari rental",
]
SECONDARY_KEYWORDS = [
    "turo exotic",
    "rent exotic car",
    "exotic car for a day",
    "supercar experience",
]
ALL_KEYWORDS = PRIMARY_KEYWORDS + SECONDARY_KEYWORDS


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_existing_status(conn, source_id: str):
    """None = no existing row. True = existing row is stale (>= REFRESH_AFTER_DAYS old,
    needs refresh). False = existing row is still fresh (skip)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT collected_at < NOW() - (%s * INTERVAL '1 day')
            FROM raw_source_data
            WHERE source_id = %s AND source_type = 'google_trends'
            LIMIT 1
            """,
            (REFRESH_AFTER_DAYS, source_id)
        )
        row = cur.fetchone()
        return row[0] if row else None


def save_record(conn, keyword: str, data_type: str, content_data: dict) -> bool:
    source_id = f"{keyword}:{data_type}:{TIMEFRAME}"
    source_url = f"https://trends.google.com/trends/explore?q={quote(keyword)}"
    metadata = {
        'data_type': data_type,
        'keyword': keyword,
        'date_range': TIMEFRAME,
        'region': 'US',
    }

    is_stale = get_existing_status(conn, source_id)

    if is_stale is False:
        logger.info(f"   ⏭️  Duplicate (< {REFRESH_AFTER_DAYS}d old) — skipping {keyword} / {data_type}")
        return False

    if is_stale is True:
        logger.info(f"   🔄 Stale (>= {REFRESH_AFTER_DAYS}d old) — refreshing {keyword} / {data_type}")
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE raw_source_data
                SET content = %s, collected_at = NOW()
                WHERE source_id = %s AND source_type = 'google_trends'
            """, (
                json.dumps(content_data),
                source_id,
            ))
        conn.commit()
        return True

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO raw_source_data
                (niche_id, source_type, source_url, source_id, title,
                 content, engagement_metrics)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            NICHE_ID,
            'google_trends',
            source_url,
            source_id,
            keyword,
            json.dumps(content_data),
            json.dumps(metadata),
        ))
    conn.commit()
    return True


# ─── Helpers ──────────────────────────────────────────────────────────────────

def retry_with_backoff(fn, max_retries=3, base_delay=30):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = base_delay * (2 ** attempt) + random.uniform(0, 5)
            logger.warning(f"   ⚠️  Attempt {attempt + 1} failed: {e}. Retrying in {wait:.0f}s...")
            time.sleep(wait)


def random_delay(min_s=5, max_s=10):
    d = random.uniform(min_s, max_s)
    logger.info(f"   ⏳ Waiting {d:.1f}s...")
    time.sleep(d)


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ─── Scraping phases ──────────────────────────────────────────────────────────

def fetch_interest_over_time_and_related(pytrends: TrendReq, batch: list) -> tuple:
    """One API call: interest_over_time + related_queries for up to 5 keywords."""
    def do_request():
        pytrends.build_payload(batch, timeframe=TIMEFRAME, geo='US')
        iot_df = pytrends.interest_over_time()
        related_raw = pytrends.related_queries()
        return iot_df, related_raw

    return retry_with_backoff(do_request)


def fetch_interest_by_region(pytrends: TrendReq, keyword: str) -> object:
    """Fetch US state-level data for a single keyword (independent 0-100 scale)."""
    def do_request():
        pytrends.build_payload([keyword], timeframe=TIMEFRAME, geo='US')
        return pytrends.interest_by_region(resolution='REGION', inc_low_vol=True)

    return retry_with_backoff(do_request)


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_scraper():
    try:
        conn = get_db_connection()
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")
        sys.exit(1)

    pytrends = TrendReq(hl='en-US', tz=360)
    saved = {'interest_over_time': 0, 'interest_by_region': 0, 'related_queries': 0}
    skipped = 0
    errors = 0

    # ── Phase 1: interest over time + related queries ──────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 1: Interest Over Time + Related Queries")
    logger.info(f"{'='*60}")

    keyword_batches = list(batches(ALL_KEYWORDS, BATCH_SIZE))
    for batch_idx, batch in enumerate(keyword_batches, 1):
        logger.info(f"\n📦 Batch {batch_idx}/{len(keyword_batches)}: {batch}")

        try:
            iot_df, related_raw = fetch_interest_over_time_and_related(pytrends, batch)
        except Exception as e:
            logger.error(f"   ❌ Batch failed: {e}")
            errors += len(batch)
            if batch_idx < len(keyword_batches):
                random_delay(10, 20)
            continue

        for keyword in batch:
            # ── interest_over_time ──
            if not iot_df.empty and keyword in iot_df.columns:
                data_points = [
                    {
                        'date': str(date.date()),
                        'search_value': int(row[keyword]),
                        'is_partial': bool(row.get('isPartial', False)),
                    }
                    for date, row in iot_df.iterrows()
                ]
                ok = save_record(conn, keyword, 'interest_over_time', {
                    'keyword': keyword,
                    'timeframe': TIMEFRAME,
                    'geo': 'US',
                    'data_points': data_points,
                    'point_count': len(data_points),
                })
                if ok:
                    saved['interest_over_time'] += 1
                    logger.info(f"   ✅ interest_over_time: {keyword} — {len(data_points)} weekly points")
                else:
                    skipped += 1
            else:
                logger.warning(f"   ⚠️  No interest data for: {keyword}")
                errors += 1

            # ── related_queries ──
            queries: list = []
            kw_data = related_raw.get(keyword, {})
            for qtype in ('top', 'rising'):
                df = kw_data.get(qtype)
                if df is not None and not df.empty:
                    for _, row in df.head(20).iterrows():
                        queries.append({
                            'query': row['query'],
                            'query_type': qtype,
                            'search_value': str(row['value']),
                        })

            if queries:
                ok = save_record(conn, keyword, 'related_queries', {
                    'keyword': keyword,
                    'timeframe': TIMEFRAME,
                    'geo': 'US',
                    'queries': queries,
                    'query_count': len(queries),
                })
                if ok:
                    saved['related_queries'] += 1
                    logger.info(f"   ✅ related_queries:    {keyword} — {len(queries)} queries")
                else:
                    skipped += 1
            else:
                logger.warning(f"   ⚠️  No related queries for: {keyword}")

        if batch_idx < len(keyword_batches):
            random_delay(5, 10)

    # ── Phase 2: interest by region (per keyword, independent scale) ───────────
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 2: Interest by Region (US States)")
    logger.info(f"{'='*60}")

    for kw_idx, keyword in enumerate(ALL_KEYWORDS, 1):
        logger.info(f"\n[{kw_idx}/{len(ALL_KEYWORDS)}] {keyword}")

        try:
            region_df = fetch_interest_by_region(pytrends, keyword)
        except Exception as e:
            logger.error(f"   ❌ Failed: {e}")
            errors += 1
            if kw_idx < len(ALL_KEYWORDS):
                random_delay(10, 20)
            continue

        if region_df.empty or keyword not in region_df.columns:
            logger.warning(f"   ⚠️  No regional data returned")
            errors += 1
            if kw_idx < len(ALL_KEYWORDS):
                random_delay(5, 10)
            continue

        regions = sorted(
            [
                {'region': str(name), 'search_value': int(row[keyword])}
                for name, row in region_df.iterrows()
                if int(row[keyword]) > 0
            ],
            key=lambda x: x['search_value'],
            reverse=True,
        )

        ok = save_record(conn, keyword, 'interest_by_region', {
            'keyword': keyword,
            'timeframe': TIMEFRAME,
            'geo': 'US',
            'resolution': 'REGION',
            'regions': regions,
            'region_count': len(regions),
        })
        if ok:
            saved['interest_by_region'] += 1
            logger.info(f"   ✅ interest_by_region: {keyword} — {len(regions)} US states")
        else:
            skipped += 1

        if kw_idx < len(ALL_KEYWORDS):
            random_delay(5, 10)

    conn.close()

    # ── Summary ────────────────────────────────────────────────────────────────
    total_saved = sum(saved.values())
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"  interest_over_time : {saved['interest_over_time']} rows")
    logger.info(f"  related_queries    : {saved['related_queries']} rows")
    logger.info(f"  interest_by_region : {saved['interest_by_region']} rows")
    logger.info(f"  Total saved        : {total_saved}")
    logger.info(f"  Skipped (dup)      : {skipped}")
    logger.info(f"  Errors             : {errors}")

    # ── DB verification ────────────────────────────────────────────────────────
    try:
        conn2 = get_db_connection()
        with conn2.cursor() as cur:
            cur.execute("""
                SELECT
                    engagement_metrics->>'data_type' AS data_type,
                    COUNT(*)                         AS count
                FROM raw_source_data
                WHERE niche_id = %s AND source_type = 'google_trends'
                GROUP BY 1
                ORDER BY 1
            """, (NICHE_ID,))
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM raw_source_data WHERE niche_id = %s AND source_type = 'google_trends'",
                (NICHE_ID,)
            )
            total_db = cur.fetchone()[0]
        conn2.close()

        logger.info(f"\n📊 Database verification (niche_id={NICHE_ID}, source_type=google_trends):")
        for data_type, count in rows:
            logger.info(f"   {data_type or 'null':<25} {count} rows")
        logger.info(f"   {'TOTAL':<25} {total_db} rows")
    except Exception as e:
        logger.error(f"❌ Verification query failed: {e}")


if __name__ == '__main__':
    logger.info("🚀 Google Trends Scraper")
    logger.info(f"   Keywords : {len(ALL_KEYWORDS)} total "
                f"({len(PRIMARY_KEYWORDS)} primary + {len(SECONDARY_KEYWORDS)} secondary)")
    logger.info(f"   Timeframe: {TIMEFRAME} (weekly data)")
    logger.info(f"   Data types: interest_over_time, interest_by_region, related_queries")
    logger.info(f"   Target table: raw_source_data (niche_id={NICHE_ID})")
    run_scraper()
