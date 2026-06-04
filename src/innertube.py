"""InnerTube API client — YouTube internal browse endpoint.

Uses youtube.com/youtubei/v1/browse (the same API YouTube.com calls)
instead of the public Data API. Zero quota cost, works with web client key.

Provides channel-related-channels extraction for pipeline expand step.
"""

import asyncio
import json
import logging
import random
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Web client key — embedded in youtube.com, public by design
INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/browse"
CLIENT_VERSION = "2.20250101.00.00"
CLIENT_NAME = "WEB"

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]

_BASE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.youtube.com",
    "Referer": "https://www.youtube.com/",
    "X-YouTube-Client-Name": str(CLIENT_NAME),
    "X-YouTube-Client-Version": CLIENT_VERSION,
}


class InnerTubeError(Exception):
    """Bare exception for InnerTube API errors (non-recoverable)."""
    pass


class InnerTubeClient:
    """InnerTube browse client with built-in anti-ban measures.

    Features:
        - Per-request UA rotation
        - Random delay between requests
        - Proxy rotation (via config.proxy_list)
        - PO Token injection (from get_po_token)
        - Retry on transient errors
    """

    def __init__(
        self,
        delay_min: float = 0.8,
        delay_max: float = 2.5,
        proxy_list: Optional[List[str]] = None,
        po_token: Optional[str] = None,
    ):
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True)
        self._ua_index = random.randint(0, len(_USER_AGENTS) - 1)
        self.request_count = 0
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.proxy_list = proxy_list or []
        self._proxy_index = 0
        self.po_token = po_token

    # ── public API ──────────────────────────────────────────────────

    async def get_related_channels(
        self, channel_id: str, max_retries: int = 2
    ) -> List[Dict[str, Any]]:
        """Fetch related channels for a given channel via InnerTube browse.

        Returns list of dicts with keys:
            channelId, title, subscriberCount, videoCount, thumbnail
        """
        data = await self._browse_channel(channel_id, max_retries)
        return self._extract_related_channels(data)

    async def close(self):
        await self._client.aclose()

    # ── InnerTube browse call ───────────────────────────────────────

    async def _browse_channel(
        self, channel_id: str, max_retries: int = 2
    ) -> Dict[str, Any]:
        """POST to youtubei/v1/browse with anti-ban pre/post.

        Retries on 429 / 5xx up to max_retries times with exponential backoff.
        """
        last_error = None

        for attempt in range(max_retries + 1):
            # Anti-ban: pre-request
            await self._pre_request()
            ua = _USER_AGENTS[self._ua_index]

            payload = {
                "context": {
                    "client": {
                        "clientName": CLIENT_NAME,
                        "clientVersion": CLIENT_VERSION,
                        "hl": "en",
                        "gl": "US",
                    },
                    "user": {"lockedSafetyMode": False},
                    "request": {"useSsl": True},
                },
                "browseId": channel_id,
            }

            # Inject PO Token if available
            if self.po_token:
                payload["context"]["client"]["visitorData"] = self.po_token

            headers = dict(_BASE_HEADERS)
            headers["User-Agent"] = ua

            try:
                resp = await self._client.post(
                    INNERTUBE_URL,
                    params={"key": INNERTUBE_API_KEY},
                    json=payload,
                    headers=headers,
                )

                if resp.status_code == 429:
                    logger.warning(
                        f"[InnerTube] 429 for {channel_id} "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    last_error = f"HTTP 429: rate limited"
                    await asyncio.sleep(2.0 ** (attempt + 1))
                    self._rotate_proxy()
                    continue

                if resp.status_code >= 500:
                    logger.warning(
                        f"[InnerTube] {resp.status_code} for {channel_id} "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    last_error = f"HTTP {resp.status_code}"
                    await asyncio.sleep(2.0 ** (attempt + 1))
                    continue

                data = resp.json()

                # Check for API-level errors
                if "error" in data:
                    err_msg = data["error"].get("message", "unknown")
                    logger.warning(
                        f"[InnerTube] API error for {channel_id}: {err_msg}"
                    )
                    last_error = err_msg
                    if attempt < max_retries:
                        await asyncio.sleep(2.0 ** (attempt + 1))
                        continue
                    return {"error": err_msg, "items": []}

                return data

            except httpx.TimeoutException:
                logger.warning(
                    f"[InnerTube] timeout for {channel_id} "
                    f"(attempt {attempt + 1}/{max_retries + 1})"
                )
                last_error = "timeout"
                if attempt < max_retries:
                    await asyncio.sleep(2.0 ** (attempt + 1))
                    continue

            except httpx.HTTPError as exc:
                logger.warning(
                    f"[InnerTube] HTTP error for {channel_id}: {exc}"
                )
                last_error = str(exc)
                if attempt < max_retries:
                    await asyncio.sleep(2.0 ** (attempt + 1))
                    continue

            except json.JSONDecodeError as exc:
                logger.warning(
                    f"[InnerTube] JSON decode error for {channel_id}: {exc}"
                )
                last_error = str(exc)
                if attempt < max_retries:
                    await asyncio.sleep(2.0 ** (attempt + 1))
                    continue

            # If we get here, request succeeded — no need to retry
            break

        if last_error:
            logger.error(
                f"[InnerTube] All {max_retries + 1} attempts failed for "
                f"{channel_id}: {last_error}"
            )

        return {"error": last_error or "unknown", "items": []}

    # ── response parser ─────────────────────────────────────────────

    def _extract_related_channels(
        self, data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Walk InnerTube browse response to find related channels.

        Searches all shelf renderers in all tabs for gridChannelRenderer.
        Returns deduplicated list sorted by subscriber count (desc).
        """
        if "error" in data or not data.get("contents"):
            return []

        seen_ids: set = set()
        channels: List[Dict[str, Any]] = []

        try:
            tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        except (KeyError, TypeError):
            return []

        for tab in tabs:
            tr = tab.get("tabRenderer", {}) or tab.get("expandableTabRenderer", {})
            section_list = (
                tr.get("content", {})
                .get("sectionListRenderer", {})
                .get("contents", [])
            )

            for section in section_list:
                items = (
                    section.get("itemSectionRenderer", {}).get("contents", [])
                )
                for item in items:
                    shelf = item.get("shelfRenderer", {})
                    if not shelf:
                        continue

                    horiz = (
                        shelf.get("content", {})
                        .get("horizontalListRenderer", {})
                    )
                    if not horiz:
                        continue

                    for grid_item in horiz.get("items", []):
                        gr = grid_item.get("gridChannelRenderer", {})
                        if not gr:
                            continue

                        ch_id = gr.get("channelId", "")
                        if not ch_id or ch_id in seen_ids:
                            continue
                        seen_ids.add(ch_id)

                        # Extract subscriber count as integer
                        subs_text = gr.get("subscriberCountText", {}).get(
                            "simpleText", ""
                        )
                        subscriber_count = self._parse_sub_count(subs_text)

                        title = (
                            gr.get("title", {}).get("simpleText", "")
                            or ""
                        )

                        vid_count_text = ""
                        vcr = gr.get("videoCountText", {})
                        if "runs" in vcr:
                            vid_count_text = "".join(
                                r.get("text", "") for r in vcr["runs"]
                            )
                        elif "simpleText" in vcr:
                            vid_count_text = vcr["simpleText"]

                        thumbnail = ""
                        thumbs = gr.get("thumbnail", {}).get(
                            "thumbnails", []
                        )
                        if thumbs:
                            thumbnail = thumbs[-1].get("url", "")

                        channels.append({
                            "channelId": ch_id,
                            "title": title,
                            "subscriberCount": subscriber_count,
                            "subscriberText": subs_text,
                            "videoCountText": vid_count_text,
                            "thumbnail": thumbnail,
                        })

        # Sort by subscriber count descending
        channels.sort(key=lambda c: c["subscriberCount"], reverse=True)
        return channels

    @staticmethod
    def _parse_sub_count(text: str) -> int:
        """Parse subscriber text like '1.2M subscribers' → 1200000."""
        text = text.replace("subscribers", "").replace("subscriber", "").strip()
        if not text:
            return 0
        try:
            multiplier = 1
            if "K" in text.upper():
                multiplier = 1000
                text = text.upper().replace("K", "")
            elif "M" in text.upper():
                multiplier = 1_000_000
                text = text.upper().replace("M", "")
            elif "B" in text.upper():
                multiplier = 1_000_000_000
                text = text.upper().replace("B", "")
            return int(float(text) * multiplier)
        except (ValueError, IndexError):
            return 0

    # ── anti-ban helpers ────────────────────────────────────────────

    async def _pre_request(self):
        """Run before each request: rotate UA, delay, rotate proxy."""
        self.request_count += 1
        self._rotate_ua()
        await self._random_delay()
        await self._maybe_rotate_proxy()

    def _rotate_ua(self):
        """Cycle through user agents."""
        self._ua_index = (self._ua_index + 1) % len(_USER_AGENTS)

    async def _random_delay(self):
        """Sleep random time between delay_min and delay_max."""
        delay = random.uniform(self.delay_min, self.delay_max)
        await asyncio.sleep(delay)

    async def _maybe_rotate_proxy(self):
        """Rotate proxy every 10 requests if proxy_list is configured."""
        if not self.proxy_list or self.request_count % 10 != 0:
            return
        self._rotate_proxy()

    def _rotate_proxy(self):
        """Close and recreate client to pick up new proxy."""
        if not self.proxy_list:
            return
        self._proxy_index = (self._proxy_index + 1) % len(self.proxy_list)
        proxy_url = self.proxy_list[self._proxy_index]
        logger.info(f"[InnerTube] rotating to proxy {proxy_url}")
        # Close old client and create new one with proxy
        transport = httpx.AsyncHTTPTransport(
            proxy=proxy_url,
            retries=1,
        )
        new_client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            transport=transport,
        )
        old_client = self._client
        self._client = new_client
        # Schedule old client close
        asyncio.get_event_loop().create_task(self._safe_close(old_client))

    @staticmethod
    async def _safe_close(client: httpx.AsyncClient):
        try:
            await client.aclose()
        except Exception:
            pass
