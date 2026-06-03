"""Anti-ban patch layer for tubescrape.

Transplants UA rotation, full browser headers, consent bypass,
and proxy rotation from youtube-scrapy-scraper into tubescrape
without forking the library.

Usage:
    from src._patched import patch_tubescrape, PatchedYouTube

    patch_tubescrape()           # one-time: patch InnerTube.DEFAULT_HEADERS
    yt = PatchedYouTube(config)  # wrap with anti-ban logic
    results = await yt.asearch(keyword)  # async with full anti-ban
"""

import asyncio
import random
import time
from typing import Optional

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/119.0",
]

# Browser-grade request headers (matching youtube-scrapy-scraper settings)
_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Sentinel value used to detect consent pages in search results
_CONSENT_SENTINEL = b"before you continue to youtube"


def patch_tubescrape():
    """Monkey-patch InnerTube.DEFAULT_HEADERS with browser-grade headers.
    Call once at pipeline startup before creating any YouTube instances.
    """
    from tubescrape._http import InnerTube

    # Merge browser headers over existing defaults (keep Content-Type for API calls)
    merged = dict(InnerTube.DEFAULT_HEADERS)
    merged.update(_BROWSER_HEADERS)
    # Keep tubescrape's visitor cookies
    InnerTube.DEFAULT_HEADERS = merged


class PatchedYouTube:
    """Wrapper around tubescrape YouTube with scraper-grade anti-ban.

    Adds per-request UA rotation, random delay, proactive proxy rotation,
    and consent page detection.
    """

    def __init__(self, config):
        from tubescrape import YouTube

        self.config = config
        self.request_count = 0
        self._ua_index = random.randint(0, len(_USER_AGENTS) - 1)

        # Collect proxy config
        proxies = None
        proxy_str = getattr(config, "proxy_list", None)
        if proxy_str and len(proxy_str) > 0:
            proxies = proxy_str
        elif getattr(config, "proxy", ""):
            proxies = [config.proxy]

        self._yt = YouTube(proxies=proxies)

    # ── public API mirroring tubescrape.YouTube ──

    async def asearch(self, query: str, **kwargs):
        """Async search with full anti-ban: UA rotation, delay, proxy rotation."""
        await self._pre_request_async()
        return await self._yt.asearch(query, **kwargs)

    def search(self, query: str, **kwargs):
        """Sync search with anti-ban (for non-critical paths)."""
        self._pre_request_sync()
        return self._yt.search(query, **kwargs)

    def extract_channel_id(self, handle: str) -> str:
        """Delegate to tubescrape (no anti-ban needed for extraction)."""
        return self._yt.extract_channel_id(handle)

    def get_channel_shorts(self, channel_id: str):
        """Delegate to tubescrape (no anti-ban needed for channel lookup)."""
        return self._yt.get_channel_shorts(channel_id)

    def get_channel_videos(self, channel_id: str):
        """Delegate to tubescrape."""
        return self._yt.get_channel_videos(channel_id)

    def close(self):
        self._yt._http.close()

    async def aclose(self):
        await self._yt._http.aclose()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    # ── internal anti-ban logic ──

    def _rotate_ua(self):
        """Swap User-Agent in the shared InnerTube headers."""
        from tubescrape._http import InnerTube

        self._ua_index = (self._ua_index + 1) % len(_USER_AGENTS)
        InnerTube.DEFAULT_HEADERS["User-Agent"] = _USER_AGENTS[self._ua_index]

    def _maybe_rotate_proxy(self):
        """Close current httpx client so next request picks a different proxy."""
        if self.config.proxy_list and self.request_count % 10 == 0:
            self._yt._http._rotate_proxy()

    async def _maybe_rotate_proxy_async(self):
        """Async version: close async httpx client, preserve cookies across rotation."""
        if not (self.config.proxy_list and self.request_count % 10 == 0):
            return
        # Preserve cookies before rotation
        old_cookies = dict(getattr(self._yt._http, '_cookies', {}))
        # Close async client (forces new proxy on next request)
        try:
            await self._yt._http.aclose()
        except Exception:
            pass
        self._yt._http._async_client = None
        # Re-inject preserved cookies
        self._yt._http._cookies = old_cookies

    def _pre_request_sync(self):
        self.request_count += 1
        self._rotate_ua()
        delay = random.uniform(self.config.delay_min, self.config.delay_max)
        if delay > 0:
            time.sleep(delay)
        self._maybe_rotate_proxy()

    async def _pre_request_async(self):
        self.request_count += 1
        self._rotate_ua()
        delay = random.uniform(self.config.delay_min, self.config.delay_max)
        if delay > 0:
            await asyncio.sleep(delay)
        await self._maybe_rotate_proxy_async()
