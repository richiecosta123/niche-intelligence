"""
Gmail scraper: searches inbox for newsletter emails matching a query, extracts
article URLs from each email body, and seeds them as source_type='newsletter_pending'
in raw_source_data — the same pipeline entry point as seed_newsletter_urls (MCP tool)
and magazine_discovery_scraper.py.

OAuth2 flow:
  - Credentials JSON from Google Cloud Console → path in GMAIL_CREDENTIALS_PATH (.env)
  - Token cached at GMAIL_TOKEN_PATH (.env, default ~/.gmail_token.json)
  - First run with no token opens a browser tab for the user to authorise; token is
    saved and reused automatically on subsequent runs.
"""

import argparse
import base64
import json
import logging
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from landing_page_scraper import normalize_url

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

URL_RE = re.compile(r'https?://[^\s<>"\'()\[\]{}]+')

# Paths and domains that indicate tracking/utility links rather than articles
SKIP_PATH_RE = re.compile(
    r'/(unsubscribe|optout|opt-out|manage|preferences|click|track|redirect|pixel|open|beacon)',
    re.IGNORECASE,
)
SKIP_DOMAIN_RE = re.compile(
    r'('
    r'twitter\.com/intent|facebook\.com/share|linkedin\.com/share'
    r'|t\.co/|bit\.ly/|mailchimp\.com|list-manage\.com'
    r'|constantcontact\.com|sendgrid\.net|mailgun\.org'
    r'|googletagmanager\.com|google-analytics\.com'
    r')',
    re.IGNORECASE,
)


# ─── Gmail auth ───────────────────────────────────────────────────────────────

def get_gmail_service():
    credentials_path = os.getenv('GMAIL_CREDENTIALS_PATH')
    if not credentials_path:
        raise ValueError(
            "GMAIL_CREDENTIALS_PATH not set in .env — "
            "download credentials.json from Google Cloud Console and set the path."
        )

    token_path = os.getenv('GMAIL_TOKEN_PATH', os.path.expanduser('~/.gmail_token.json'))

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as fh:
            fh.write(creds.to_json())
        logger.info(f"OAuth token saved to {token_path}")

    return build('gmail', 'v1', credentials=creds)


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.getenv('NEON_DB_URL')
    if not db_url:
        raise ValueError("NEON_DB_URL not set in .env")
    return psycopg2.connect(db_url)


def get_existing_urls(conn, niche_id: int) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_url FROM raw_source_data WHERE niche_id = %s AND source_url IS NOT NULL",
            (niche_id,),
        )
        return {normalize_url(r[0]).rstrip('/') for r in cur.fetchall() if r[0]}


def save_pending(conn, niche_id: int, url: str, sender: str, subject: str, date: str):
    metrics = {
        'sender': sender,
        'subject': subject,
        'date': date,
        'discovery_method': 'gmail_scraper',
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_source_data (niche_id, source_type, source_url, title, engagement_metrics)
            VALUES (%s, 'newsletter_pending', %s, %s, %s)
            """,
            (niche_id, url, (subject or '')[:500] or None, json.dumps(metrics)),
        )
    conn.commit()


# ─── Email body parsing ───────────────────────────────────────────────────────

def _decode_body(data: str) -> str:
    """base64url-decode a Gmail message body data field."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')


def _extract_parts(payload: dict) -> tuple[str, str]:
    """Recursively walk a Gmail message payload and return (text_body, html_body)."""
    text_body = ''
    html_body = ''

    mime_type = payload.get('mimeType', '')
    body_data = payload.get('body', {}).get('data', '')

    if mime_type == 'text/plain' and body_data:
        text_body = _decode_body(body_data)
    elif mime_type == 'text/html' and body_data:
        html_body = _decode_body(body_data)

    for part in payload.get('parts', []):
        t, h = _extract_parts(part)
        text_body += t
        html_body += h

    return text_body, html_body


class _TagStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []

    def handle_data(self, data: str):
        self._pieces.append(data)

    def get_text(self) -> str:
        return ' '.join(self._pieces)


def _strip_html(html: str) -> str:
    p = _TagStripper()
    p.feed(html)
    return p.get_text()


# ─── URL extraction and filtering ─────────────────────────────────────────────

def _extract_raw_urls(text: str) -> list[str]:
    raw = URL_RE.findall(text)
    cleaned = []
    for url in raw:
        url = url.rstrip('.,;:!?)"\'>')
        cleaned.append(url)
    return cleaned


def is_article_url(url: str) -> bool:
    """Return True if the URL looks like an article link rather than a tracking/utility URL."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    # Must have at least one non-empty path segment (not just a domain root)
    parts = [p for p in parsed.path.split('/') if p]
    if not parts:
        return False
    if SKIP_PATH_RE.search(parsed.path):
        return False
    if SKIP_DOMAIN_RE.search(url):
        return False
    return True


# ─── Main ─────────────────────────────────────────────────────────────────────

def scrape(niche_id: int, query: str, limit: int, test: bool):
    service = get_gmail_service()

    mode = " [TEST MODE — no DB writes]" if test else ""
    logger.info(f"📧 Gmail scraper for niche {niche_id}{mode}")
    logger.info(f"   Query: {query!r} | Limit: {limit}")

    conn = None
    existing: set[str] = set()
    if not test:
        conn = get_db_connection()
        existing = get_existing_urls(conn, niche_id)

    stats = {'emails': 0, 'urls_found': 0, 'new': 0, 'duplicates': 0}

    response = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=limit,
    ).execute()

    messages = response.get('messages', [])
    logger.info(f"   Matched {len(messages)} email(s)")

    for msg_ref in messages:
        msg_data = service.users().messages().get(
            userId='me',
            id=msg_ref['id'],
            format='full',
        ).execute()
        stats['emails'] += 1

        headers = {h['name']: h['value'] for h in msg_data['payload'].get('headers', [])}
        sender = headers.get('From', '')
        subject = headers.get('Subject', '')
        date = headers.get('Date', '')

        text_body, html_body = _extract_parts(msg_data['payload'])

        # Prefer plaintext; fall back to tag-stripped HTML
        source_text = text_body.strip() if text_body.strip() else _strip_html(html_body)
        raw_urls = _extract_raw_urls(source_text)

        seen_in_email: set[str] = set()
        for raw_url in raw_urls:
            url = normalize_url(raw_url).rstrip('/')
            if url in seen_in_email or not is_article_url(url):
                continue
            seen_in_email.add(url)
            stats['urls_found'] += 1

            if url in existing:
                stats['duplicates'] += 1
                logger.debug(f"  ⏭️  Skip (exists): {url}")
                continue

            existing.add(url)
            stats['new'] += 1

            if test:
                logger.info(f"  🆕 [TEST] {url}")
                logger.info(f"       From: {sender[:70]}")
                logger.info(f"       Subj: {subject[:70]}")
            else:
                save_pending(conn, niche_id, url, sender, subject, date)
                logger.info(f"  ✅ Saved: {url}")

    if conn:
        conn.close()

    logger.info(
        f"\n📊 Done{mode}: {stats['emails']} emails | "
        f"{stats['urls_found']} URLs found | "
        f"{stats['new']} new | {stats['duplicates']} duplicates"
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Gmail newsletter scraper')
    parser.add_argument('--niche-id', type=int, required=True)
    parser.add_argument(
        '--query', type=str, default='label:apex-intel newer_than:7d',
        help='Gmail search query (default: "label:apex-intel newer_than:7d")',
    )
    parser.add_argument('--limit', type=int, default=50,
                        help='Max emails to process (default: 50)')
    parser.add_argument('--test', action='store_true',
                        help='Print discovered URLs without DB writes')
    args = parser.parse_args()

    scrape(
        niche_id=args.niche_id,
        query=args.query,
        limit=args.limit,
        test=args.test,
    )
