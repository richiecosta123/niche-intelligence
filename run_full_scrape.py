"""
Multi-keyword Reddit scraper.
Loops through all niche keywords and aggregates results.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from reddit_browser_scraper import scrape_reddit

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

EXOTIC_CAR_KEYWORDS = [
    'exotic car rental',
    'supercar rental',
    'Turo exotic car',
    'luxury car business',
    'exotic car insurance',
]


class ScraperArgs:
    """Simulates argparse namespace so we can call scrape_reddit() directly."""

    def __init__(
        self,
        keywords: str,
        limit: int = 50,
        full_content: bool = False,
        headless: bool = True,
        slow_mo: int = 100,
        niche_id: int = 2,
        dry_run: bool = False,
    ):
        self.keywords = keywords
        self.limit = limit
        self.full_content = full_content
        self.headless = headless
        self.slow_mo = slow_mo
        self.niche_id = niche_id
        self.dry_run = dry_run


async def run_all(args):
    keywords = args.keywords_list or EXOTIC_CAR_KEYWORDS
    total = {'new': 0, 'duplicates': 0, 'errors': 0}
    start = datetime.now(timezone.utc)

    logger.info("=" * 60)
    logger.info(f"🚀 Starting full scrape — {len(keywords)} keywords")
    logger.info(f"   Limit per keyword: {args.limit}")
    logger.info(f"   Niche ID: {args.niche_id}")
    logger.info(f"   Dry run: {args.dry_run}")
    logger.info("=" * 60)

    for i, kw in enumerate(keywords, 1):
        logger.info(f"\n[{i}/{len(keywords)}] ── Keyword: \"{kw}\" ──")
        scraper_args = ScraperArgs(
            keywords=kw,
            limit=args.limit,
            full_content=args.full_content,
            headless=args.headless,
            slow_mo=args.slow_mo,
            niche_id=args.niche_id,
            dry_run=args.dry_run,
        )
        try:
            stats = await scrape_reddit(scraper_args)
            for k in total:
                total[k] += stats.get(k, 0)
        except Exception as exc:
            logger.error(f"❌ Keyword failed: {kw} — {exc}")
            total['errors'] += 1

        # Pause between keywords to avoid rate limiting
        if i < len(keywords):
            logger.info("  ⏳ Waiting 5s before next keyword...")
            await asyncio.sleep(5)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("\n" + "=" * 60)
    logger.info("🏁 FULL SCRAPE COMPLETE")
    logger.info(f"   ✅ New posts saved : {total['new']}")
    logger.info(f"   ⏭️  Duplicates skipped: {total['duplicates']}")
    logger.info(f"   ❌ Errors          : {total['errors']}")
    logger.info(f"   ⏱  Total time      : {elapsed:.1f}s")
    logger.info("=" * 60)
    return total


def main():
    parser = argparse.ArgumentParser(description='Multi-keyword Reddit scraper')
    parser.add_argument('--keywords-list', nargs='+', default=None,
                        help='Override keyword list (space-separated)')
    parser.add_argument('--limit', type=int, default=50, help='Posts per keyword')
    parser.add_argument('--full-content', action='store_true')
    parser.add_argument('--headless', type=lambda v: v.lower() != 'false', default=True,
                        metavar='BOOL')
    parser.add_argument('--slow-mo', type=int, default=100)
    parser.add_argument('--niche-id', type=int, default=2)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    asyncio.run(run_all(args))


if __name__ == '__main__':
    main()
