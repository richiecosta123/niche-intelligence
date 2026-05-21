#!/usr/bin/env python3
"""
Google Trends scraper for the niche intelligence platform.
- Reads keywords from niches.data_sources.googleTrends.keywords
- Fetches interest over time, related queries, seasonality, trend direction
- Saves to trend_data table
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

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

TIMEFRAME = 'today 5-y'


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_regions(conn, niche_id: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_sources->'googleTrends'->'regions' FROM niches WHERE id = %s",
            (niche_id,)
        )
        row = cur.fetchone()
    if not row or not row[0]:
        return []
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


def get_keywords(conn, niche_id: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_sources->'googleTrends'->'keywords' FROM niches WHERE id = %s",
            (niche_id,)
        )
        row = cur.fetchone()
    if not row or not row[0]:
        return []
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


def save_trend(conn, niche_id: int, keyword: str, geo: str, data_points: list,
               trend_direction: str, trend_value: float,
               seasonality: dict, related: list):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO trend_data
                (niche_id, term, source, trend_value, trend_direction,
                 geo, time_range, related_queries, breakdown, recorded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            niche_id,
            keyword,
            'google_trends',
            round(trend_value, 4),
            trend_direction,
            geo,
            TIMEFRAME,
            json.dumps(related),
            json.dumps({'data_points': data_points, 'seasonality': seasonality}),
            datetime.now(timezone.utc),
        ))
    conn.commit()


# ─── Analysis helpers ──────────────────────────────────────────────────────────

def detect_trend_direction(values: list[float]) -> str:
    """Compare the average of the last 12 months vs the prior 12 months."""
    if len(values) < 24:
        return 'stable'
    recent = sum(values[-12:]) / 12
    prior = sum(values[-24:-12]) / 12
    if prior == 0:
        return 'stable'
    change = (recent - prior) / prior
    if change >= 0.15:
        return 'rising'
    if change <= -0.15:
        return 'declining'
    return 'stable'


def detect_seasonality(data_points: list[dict]) -> dict:
    """Find peak/low months and classify the seasonal pattern."""
    from collections import defaultdict

    monthly_avg: dict[int, list] = defaultdict(list)
    for dp in data_points:
        month = int(dp['date'][5:7])
        monthly_avg[month].append(dp['value'])

    avg_by_month = {m: sum(v) / len(v) for m, v in monthly_avg.items()}
    if not avg_by_month:
        return {'peakMonths': [], 'lowMonths': [], 'pattern': 'unknown'}

    overall_avg = sum(avg_by_month.values()) / len(avg_by_month)
    threshold = overall_avg * 0.15  # 15% above/below = notable

    peak_months = sorted(
        [m for m, v in avg_by_month.items() if v >= overall_avg + threshold],
        key=lambda m: avg_by_month[m], reverse=True
    )
    low_months = sorted(
        [m for m, v in avg_by_month.items() if v <= overall_avg - threshold],
        key=lambda m: avg_by_month[m]
    )

    # Classify pattern
    if not peak_months and not low_months:
        pattern = 'evergreen'
    elif len(peak_months) <= 2:
        pattern = 'highly_seasonal'
    elif len(peak_months) <= 4:
        pattern = 'seasonal'
    else:
        pattern = 'mildly_seasonal'

    month_names = ['Jan','Feb','Mar','Apr','May','Jun',
                   'Jul','Aug','Sep','Oct','Nov','Dec']

    return {
        'peakMonths': [month_names[m - 1] for m in peak_months[:3]],
        'lowMonths': [month_names[m - 1] for m in low_months[:3]],
        'pattern': pattern,
    }


# ─── Scraper ──────────────────────────────────────────────────────────────────

def scrape_keyword(pytrends: TrendReq, keyword: str, geo: str) -> dict | None:
    """Fetch all trend data for one keyword in a given geo. Returns None on failure."""
    try:
        pytrends.build_payload([keyword], timeframe=TIMEFRAME, geo=geo)

        # Interest over time
        iot_df = pytrends.interest_over_time()
        if iot_df.empty or keyword not in iot_df.columns:
            logger.warning(f"   ⚠️  No interest data returned")
            return None

        data_points = [
            {'date': str(date.date()), 'value': int(row[keyword])}
            for date, row in iot_df.iterrows()
            if not row.get('isPartial', False)
        ]
        if not data_points:
            return None

        values = [dp['value'] for dp in data_points]
        trend_value = values[-1]  # most recent month's index value
        trend_direction = detect_trend_direction(values)
        seasonality = detect_seasonality(data_points)

        # Related queries
        related_raw = pytrends.related_queries()
        related: list[dict] = []
        kw_data = related_raw.get(keyword, {})

        for qtype in ('rising', 'top'):
            df = kw_data.get(qtype)
            if df is not None and not df.empty:
                for _, row in df.head(10).iterrows():
                    related.append({
                        'type': qtype,
                        'query': row['query'],
                        'value': str(row['value']),
                    })

        return {
            'data_points': data_points,
            'trend_value': trend_value,
            'trend_direction': trend_direction,
            'seasonality': seasonality,
            'related': related,
        }

    except Exception as e:
        logger.error(f"   ❌ Failed: {e}")
        return None


def scrape_trends(niche_id: int, delay: int, geo: str, use_regions: bool):
    stats: dict[str, int] = {}  # keyed by geo code → success count
    errors = 0

    try:
        conn = get_db_connection()
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"❌ DB connection failed: {e}")
        return

    keywords = get_keywords(conn, niche_id)
    if not keywords:
        logger.error(f"❌ No googleTrends keywords found for niche_id={niche_id}")
        conn.close()
        return

    # Resolve regions list
    if use_regions:
        regions = get_regions(conn, niche_id)
        if not regions:
            logger.warning("⚠️  No regions configured in niche data_sources.googleTrends.regions — falling back to --geo")
            regions = [geo]
        else:
            logger.info(f"🌎 Regions from config: {', '.join(regions)}")
    else:
        regions = [geo]

    total_combinations = len(keywords) * len(regions)
    logger.info(
        f"📋 {len(keywords)} keywords × {len(regions)} region(s) = {total_combinations} records to fetch\n"
    )

    pytrends = TrendReq(hl='en-US', tz=360)
    combo_index = 0

    for region in regions:
        stats[region] = 0
        logger.info(f"🌍 Starting region: {region}")

        for i, keyword in enumerate(keywords, 1):
            combo_index += 1
            logger.info(f"\n🔍 [{combo_index}/{total_combinations}] \"{keyword}\" | Region: {region}")

            result = scrape_keyword(pytrends, keyword, region)

            if result is None:
                errors += 1
            else:
                try:
                    save_trend(
                        conn,
                        niche_id,
                        keyword,
                        region,
                        result['data_points'],
                        result['trend_direction'],
                        result['trend_value'],
                        result['seasonality'],
                        result['related'],
                    )
                    direction_emoji = {'rising': '📈', 'declining': '📉', 'stable': '➡️'}.get(
                        result['trend_direction'], '➡️'
                    )
                    logger.info(
                        f"   ✅ Saved — {direction_emoji} {result['trend_direction']} | "
                        f"value={result['trend_value']} | "
                        f"pattern={result['seasonality']['pattern']} | "
                        f"{len(result['related'])} related queries"
                    )
                    stats[region] += 1
                except Exception as e:
                    logger.error(f"   ❌ DB save failed: {e}")
                    errors += 1

            # Delay between every request except the last
            if combo_index < total_combinations:
                logger.info(f"   ⏳ Waiting {delay}s...")
                time.sleep(delay)

        logger.info(f"✅ Region {region} complete — {stats[region]}/{len(keywords)} saved\n")

    conn.close()

    total_saved = sum(stats.values())
    logger.info("📊 Summary by region:")
    for region, count in stats.items():
        logger.info(f"   {region}: {count} saved")
    logger.info(
        f"\n📊 Done — "
        f"{len(keywords)} keywords × {len(regions)} regions = "
        f"{total_saved} saved | {errors} errors"
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Google Trends scraper for niche intelligence platform'
    )
    parser.add_argument(
        '--niche-id', type=int, default=1,
        help='Niche ID to fetch keywords for (default: 1)'
    )
    parser.add_argument(
        '--delay', type=int, default=2,
        help='Seconds between requests to avoid rate limiting (default: 2)'
    )
    parser.add_argument(
        '--geo', default='US',
        help='Geographic target: country (US, GB, CA), state (US-CA), or metro (US-CA-803) (default: US)'
    )
    parser.add_argument(
        '--regions', action='store_true',
        help='Read target regions from niche config (data_sources.googleTrends.regions)'
    )
    args = parser.parse_args()

    logger.info(
        f"🚀 Google Trends Scraper — "
        f"niche_id={args.niche_id}, geo={args.geo}, "
        f"regions={'config' if args.regions else 'off'}, delay={args.delay}s"
    )
    scrape_trends(args.niche_id, args.delay, args.geo, args.regions)


if __name__ == '__main__':
    main()
