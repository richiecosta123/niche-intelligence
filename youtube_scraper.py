"""
YouTube scraper for the niche intelligence platform.
- Transcripts via youtube-transcript-api (no auth needed)
- Video metadata, comments, and search via YouTube Data API v3
- Saves to raw_source_data with source_type='youtube'
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import psycopg2
import requests
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


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


def save_video(conn, video: dict, niche_id: int):
    stats = video.get('stats', {})
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO raw_source_data
                (niche_id, source_type, source_url, source_id, title,
                 content, author, score, engagement_metrics, raw_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            niche_id,
            'youtube',
            video['source_url'],
            video['content']['video_id'],
            video['content']['title'][:500],
            video['content'].get('transcript', '') or video['content'].get('description', ''),
            video['content']['channel'],
            int(stats.get('likes', 0)),
            json.dumps({
                'views': stats.get('views', 0),
                'likes': stats.get('likes', 0),
                'comments_count': stats.get('comments_count', 0),
            }),
            json.dumps(video),
        ))
    conn.commit()


# ─── YouTube API helpers ───────────────────────────────────────────────────────

def build_youtube_client():
    api_key = os.getenv('YOUTUBE_API_KEY')
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY not set in .env")
    return build('youtube', 'v3', developerKey=api_key)


def search_videos(youtube, query: str, limit: int) -> list[str]:
    """Return video IDs from a search query."""
    video_ids = []
    next_page_token = None

    while len(video_ids) < limit:
        batch = min(50, limit - len(video_ids))
        params = {
            'q': query,
            'type': 'video',
            'part': 'id',
            'maxResults': batch,
            'relevanceLanguage': 'en',
        }
        if next_page_token:
            params['pageToken'] = next_page_token

        response = youtube.search().list(**params).execute()
        for item in response.get('items', []):
            video_ids.append(item['id']['videoId'])

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return video_ids[:limit]


def get_channel_videos(youtube, channel_name: str, limit: int) -> list[str]:
    """Return video IDs from a channel search."""
    # First find the channel
    channel_resp = youtube.search().list(
        q=channel_name,
        type='channel',
        part='id',
        maxResults=1,
    ).execute()

    items = channel_resp.get('items', [])
    if not items:
        logger.warning(f"⚠️  Channel not found: {channel_name}")
        return []

    channel_id = items[0]['id']['channelId']
    logger.info(f"📺 Found channel ID: {channel_id}")

    video_ids = []
    next_page_token = None

    while len(video_ids) < limit:
        batch = min(50, limit - len(video_ids))
        params = {
            'channelId': channel_id,
            'type': 'video',
            'part': 'id',
            'order': 'viewCount',
            'maxResults': batch,
        }
        if next_page_token:
            params['pageToken'] = next_page_token

        response = youtube.search().list(**params).execute()
        for item in response.get('items', []):
            video_ids.append(item['id']['videoId'])

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return video_ids[:limit]


def get_video_details(youtube, video_ids: list[str]) -> dict[str, dict]:
    """Fetch snippet + statistics for up to 50 video IDs at once."""
    details = {}
    # API allows max 50 per request
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        response = youtube.videos().list(
            id=','.join(batch),
            part='snippet,statistics',
        ).execute()
        for item in response.get('items', []):
            details[item['id']] = item
    return details


def get_top_comments(youtube, video_id: str, limit: int = 20) -> list[dict]:
    """Fetch top comments sorted by relevance."""
    comments = []
    try:
        response = youtube.commentThreads().list(
            videoId=video_id,
            part='snippet',
            order='relevance',
            maxResults=min(limit, 100),
            textFormat='plainText',
        ).execute()
        for item in response.get('items', []):
            top = item['snippet']['topLevelComment']['snippet']
            comments.append({
                'author': top.get('authorDisplayName', ''),
                'text': top.get('textDisplay', '')[:600],
                'likes': int(top.get('likeCount', 0)),
            })
    except HttpError as e:
        if e.resp.status == 403:
            logger.debug(f"    Comments disabled for {video_id}")
        else:
            logger.warning(f"    ⚠️  Comments error for {video_id}: {e}")
    return comments


def get_transcript(video_id: str) -> str:
    """Fetch transcript using yt-dlp."""
    try:
        import yt_dlp

        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'skip_download': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Try manual subtitles first
            subs = info.get('subtitles', {}).get('en', [])
            if not subs:
                # Fall back to auto-generated
                subs = info.get('automatic_captions', {}).get('en', [])

            if subs and len(subs) > 0:
                # Get the subtitle URL
                sub_url = subs[0].get('url')
                if sub_url:
                    # Fetch the subtitle content
                    response = requests.get(sub_url, timeout=10)
                    if response.status_code == 200:
                        # Parse JSON3 format
                        data = response.json()
                        # Extract text from events
                        text_parts = []
                        for event in data.get('events', []):
                            if 'segs' in event:
                                for seg in event['segs']:
                                    if 'utf8' in seg:
                                        text_parts.append(seg['utf8'])
                        return ' '.join(text_parts)

        return ''
    except:
        return ''


def analyze_channel(channel_name: str, niche_id: int):
    """Analyze a YouTube channel's quality metrics."""
    import yt_dlp
    from datetime import datetime, timezone

    logger.info(f"📊 Analyzing channel: {channel_name}")

    try:
        # Search for channel
        logger.info("🔍 Fetching channel metadata...")
        search_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            search_result = ydl.extract_info(f"ytsearch1:{channel_name}", download=False)
            if not search_result or 'entries' not in search_result:
                logger.error("❌ Channel not found")
                return

            # Get channel URL from first result
            channel_url = search_result['entries'][0]['channel_url']

            # Get channel info (fast - extract_flat)
            channel_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': 'in_playlist',
            }

            with yt_dlp.YoutubeDL(channel_opts) as ydl:
                # Fetch main channel page for full video count
                info = ydl.extract_info(channel_url, download=False)

                subscriber_count = info.get('channel_follower_count', 0)
                total_videos = info.get('playlist_count', 0)
                logger.info(f"✅ Found: {subscriber_count:,} subscribers, {total_videos:,} videos")

                # Get recent 10 videos for engagement calculation
                entries = info.get('entries', [])[:10]
                view_counts = []
                comment_counts = []

                logger.info(f"📈 Calculating engagement from {len(entries)} recent videos...")

                # Fetch full info for 10 videos to get views/comments
                video_opts = {'quiet': True, 'no_warnings': True}
                with yt_dlp.YoutubeDL(video_opts) as video_ydl:
                    for idx, entry in enumerate(entries):
                        logger.info(f"   [{idx+1}/{len(entries)}] Processing video...")
                        try:
                            video_info = video_ydl.extract_info(f"https://youtube.com/watch?v={entry['id']}", download=False)
                            if 'view_count' in video_info:
                                view_counts.append(video_info['view_count'])
                            if 'comment_count' in video_info:
                                comment_counts.append(video_info['comment_count'])
                        except:
                            pass

                avg_views = sum(view_counts) // len(view_counts) if view_counts else 0
                avg_comments = sum(comment_counts) // len(comment_counts) if comment_counts else 0
                engagement_ratio = (avg_comments / avg_views) if avg_views > 0 else 0
                logger.info(f"✅ Engagement calculated: {avg_views:,} avg views, {avg_comments:,} avg comments")
                recent_videos = entries

                # Authority score (0-100)
                authority_score = 0

                if subscriber_count >= 1000000: authority_score += 40
                elif subscriber_count >= 500000: authority_score += 30
                elif subscriber_count >= 100000: authority_score += 20
                elif subscriber_count >= 10000: authority_score += 10

                if total_videos >= 1000: authority_score += 20
                elif total_videos >= 500: authority_score += 15
                elif total_videos >= 100: authority_score += 10

                if engagement_ratio >= 0.01: authority_score += 40
                elif engagement_ratio >= 0.005: authority_score += 30
                elif engagement_ratio >= 0.001: authority_score += 20
                elif avg_comments >= 100: authority_score += 10

                # Recommendation
                if authority_score >= 70:
                    tier = "TIER 1: High Priority"
                    cadence = "Weekly scraping recommended"
                    video_limit = 20
                elif authority_score >= 40:
                    tier = "TIER 2: Medium Priority"
                    cadence = "Monthly scraping recommended"
                    video_limit = 10
                else:
                    tier = "TIER 3: Low Priority"
                    cadence = "One-time scrape only"
                    video_limit = 5

                # Display results
                print("\n" + "="*70)
                print(f"📺 CHANNEL ANALYSIS: {info.get('channel', channel_name)}")
                print("="*70)
                print(f"\n🔢 METRICS:")
                print(f"   Subscribers: {subscriber_count:,}")
                print(f"   Total Videos: {total_videos:,}")
                print(f"   Avg Views/Video: {avg_views:,}")
                print(f"   Avg Comments/Video: {avg_comments:,}")
                print(f"   Engagement Rate: {engagement_ratio*100:.2f}%")
                print(f"   Recent Videos Analyzed: {len(recent_videos)}")

                print(f"\n⭐ AUTHORITY SCORE: {authority_score}/100")

                print(f"\n🎯 RECOMMENDATION:")
                print(f"   {tier}")
                print(f"   {cadence}")
                print(f"   Suggested limit: {video_limit} videos per scrape")

                print(f"\n📋 SAMPLE COMMAND:")
                print(f'   python3 youtube_scraper.py --niche-id=2 --channel="{channel_name}" --limit={video_limit}')
                print("="*70 + "\n")

                # Save to database
                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO youtube_channels
                        (niche_id, channel_name, channel_id, channel_url,
                         subscriber_count, total_videos, avg_views,
                         avg_comments, engagement_ratio,
                         authority_score, tier, recommended_limit, scrape_cadence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        niche_id,
                        info.get('channel'),
                        info.get('channel_id'),
                        channel_url,
                        subscriber_count,
                        total_videos,
                        avg_views,
                        round(avg_comments),
                        round(engagement_ratio, 6),
                        authority_score,
                        tier.split(':')[0].strip(),
                        video_limit,
                        cadence.split()[0].lower()
                    ))
                conn.commit()
                conn.close()
                logger.info("✅ Channel analysis saved to database")

                return {
                    'channel': info.get('channel'),
                    'subscribers': subscriber_count,
                    'total_videos': total_videos,
                    'avg_views': avg_views,
                    'avg_comments': avg_comments,
                    'engagement_ratio': engagement_ratio,
                    'authority_score': authority_score,
                    'tier': tier,
                    'recommended_limit': video_limit
                }

    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}")
        return None


# ─── Main scraper ─────────────────────────────────────────────────────────────

def scrape_youtube(args) -> dict:
    niche_id: int = args.niche_id
    limit: int = args.limit
    fetch_comments: bool = not args.no_comments

    stats = {'new': 0, 'duplicates': 0, 'errors': 0}

    try:
        conn = get_db_connection()
        logger.info("✅ Database connected")
    except Exception as exc:
        logger.error(f"❌ DB connection failed: {exc}")
        return stats

    try:
        youtube = build_youtube_client()
        logger.info("✅ YouTube API client ready")
    except Exception as exc:
        logger.error(f"❌ YouTube API init failed: {exc}")
        conn.close()
        return stats

    # ── Collect video IDs ──────────────────────────────────────────────────────
    video_ids: list[str] = []

    if args.search:
        logger.info(f"🔍 Searching YouTube: \"{args.search}\"")
        try:
            video_ids = search_videos(youtube, args.search, limit)
            logger.info(f"   Found {len(video_ids)} videos")
        except HttpError as e:
            logger.error(f"❌ Search failed: {e}")

    if args.channel:
        logger.info(f"📺 Fetching videos from channel: \"{args.channel}\"")
        try:
            channel_ids = get_channel_videos(youtube, args.channel, limit)
            # Merge, dedupe, respect limit
            seen = set(video_ids)
            for vid in channel_ids:
                if vid not in seen and len(video_ids) < limit:
                    video_ids.append(vid)
                    seen.add(vid)
            logger.info(f"   Total unique videos: {len(video_ids)}")
        except HttpError as e:
            logger.error(f"❌ Channel fetch failed: {e}")

    if not video_ids:
        logger.error("❌ No videos found. Provide --search or --channel.")
        conn.close()
        return stats

    # ── Fetch metadata for all video IDs ──────────────────────────────────────
    logger.info(f"📋 Fetching metadata for {len(video_ids)} videos...")
    try:
        details_map = get_video_details(youtube, video_ids)
    except HttpError as e:
        logger.error(f"❌ Metadata fetch failed: {e}")
        conn.close()
        return stats

    # ── Process each video ────────────────────────────────────────────────────
    for i, video_id in enumerate(video_ids, 1):
        source_url = f"https://youtube.com/watch?v={video_id}"
        title_short = video_id  # fallback before we have metadata

        try:
            if is_duplicate(conn, source_url):
                logger.info(f"⏭️  [{i}/{len(video_ids)}] Duplicate — skipping {video_id}")
                stats['duplicates'] += 1
                continue

            detail = details_map.get(video_id)
            if not detail:
                logger.warning(f"⚠️  [{i}/{len(video_ids)}] No metadata for {video_id} — skipping")
                stats['errors'] += 1
                continue

            snippet = detail.get('snippet', {})
            statistics = detail.get('statistics', {})

            title_short = snippet.get('title', video_id)[:60]
            logger.info(f"🎬 [{i}/{len(video_ids)}] {title_short}")

            # Transcript
            logger.info("    📝 Fetching transcript...")
            transcript = get_transcript(video_id)
            if transcript:
                logger.info(f"    ✅ Transcript: {len(transcript)} chars")
            else:
                logger.info("    ℹ️  No transcript available")

            # Comments
            top_comments = []
            if fetch_comments:
                logger.info("    💬 Fetching comments...")
                top_comments = get_top_comments(youtube, video_id)
                logger.info(f"    ✅ {len(top_comments)} comments")

            video_stats = {
                'views': int(statistics.get('viewCount', 0)),
                'likes': int(statistics.get('likeCount', 0)),
                'comments_count': int(statistics.get('commentCount', 0)),
            }

            record = {
                'source_url': source_url,
                'content': {
                    'video_id': video_id,
                    'title': snippet.get('title', ''),
                    'channel': snippet.get('channelTitle', ''),
                    'description': snippet.get('description', '')[:2000],
                    'published_at': snippet.get('publishedAt', ''),
                    'transcript': transcript,
                    'top_comments': top_comments,
                    'stats': video_stats,
                },
                'scraped_at': datetime.now(timezone.utc).isoformat(),
            }

            save_video(conn, record, niche_id)
            logger.info(
                f"    ✅ Saved — 👁 {video_stats['views']:,}  "
                f"👍 {video_stats['likes']:,}  "
                f"💬 {video_stats['comments_count']:,}"
            )
            stats['new'] += 1

        except HttpError as e:
            logger.error(f"❌ [{i}/{len(video_ids)}] API error for {video_id}: {e}")
            stats['errors'] += 1
        except Exception as exc:
            logger.error(f"❌ [{i}/{len(video_ids)}] Error processing {video_id}: {exc}")
            stats['errors'] += 1

    conn.close()

    logger.info(
        f"\n📊 Done — "
        f"{stats['new']} new | "
        f"{stats['duplicates']} duplicates | "
        f"{stats['errors']} errors"
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='YouTube scraper for niche intelligence platform')
    parser.add_argument('--niche-id', type=int, help='Niche ID to tag records with (not needed for --analyze-channel)')
    parser.add_argument('--search', help='Search query for YouTube videos')
    parser.add_argument('--channel', help='Channel name to scrape top videos from')
    parser.add_argument('--limit', type=int, default=20, help='Max videos to collect (default 20)')
    parser.add_argument('--no-comments', action='store_true', help='Skip fetching comments')
    parser.add_argument('--analyze-channel', help='Analyze channel quality metrics without scraping')
    args = parser.parse_args()

    if args.analyze_channel:
        if not args.niche_id:
            parser.error("--niche-id is required for --analyze-channel")
        analyze_channel(args.analyze_channel, args.niche_id)
        return

    if not args.niche_id:
        parser.error("--niche-id is required for scraping")

    if not args.search and not args.channel:
        parser.error("Provide at least one of --search or --channel")

    scrape_youtube(args)


if __name__ == '__main__':
    main()
