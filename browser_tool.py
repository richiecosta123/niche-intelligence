"""
General-purpose headless browser tool using Playwright.
Renders a URL, waits for JS, and returns page content as JSON to stdout.
"""

import argparse
import asyncio
import json
import random
import sys

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
]


async def browse(url: str, wait_for: str | None) -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1280, 'height': 900},
            java_script_enabled=True,
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=15_000)

            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=10_000)
                except PlaywrightTimeoutError:
                    pass  # best-effort — extract whatever loaded

            title = await page.title() or ''

            # All visible text from body
            text_content = ''
            try:
                body = await page.query_selector('body')
                if body:
                    text_content = (await body.inner_text()).strip()
            except Exception:
                pass

            # All links
            links: list[dict] = []
            try:
                a_els = await page.query_selector_all('a[href]')
                for el in a_els[:100]:
                    href = (await el.get_attribute('href') or '').strip()
                    text = (await el.inner_text()).strip()[:100]
                    if href:
                        links.append({'href': href, 'text': text})
            except Exception:
                pass

            return {'url': url, 'title': title, 'text_content': text_content, 'links': links}

        except PlaywrightTimeoutError:
            return {'url': url, 'title': '', 'text_content': '', 'links': [], 'error': 'Page load timed out'}
        except Exception as exc:
            return {'url': url, 'title': '', 'text_content': '', 'links': [], 'error': str(exc)}
        finally:
            await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Headless browser tool')
    parser.add_argument('--url', required=True)
    parser.add_argument('--wait-for', default=None, dest='wait_for')
    args = parser.parse_args()

    result = asyncio.run(browse(url=args.url, wait_for=args.wait_for))
    print(json.dumps(result))
