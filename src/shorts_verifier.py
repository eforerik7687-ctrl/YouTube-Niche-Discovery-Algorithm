"""yt-dlp Shorts verifier for YouTube channel analysis.

Verifies channels have Shorts content by fetching their /shorts tab via yt-dlp.
Uses --flat-playlist mode for speed (metadata only, no download).

Usage:
    from src.shorts_verifier import ShortsVerifier

    verifier = ShortsVerifier(max_workers=4)
    results = verifier.verify([
        {"name": "SpraySword", "id": "UCtAX3Vb0tKFcYsLyKDbUI9Q"},
    ])
    # returns: [{"channel_name": "SpraySword", "is_shorts_creator": True, ...}]
"""

import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ShortsVerifier:
    """Verify YouTube channels have Shorts content using yt-dlp."""

    def __init__(self, max_workers: int = 4, ytdlp_path: str = "yt-dlp",
                 timeout: int = 30, proxy: Optional[str] = None):
        """
        Args:
            max_workers: Number of concurrent yt-dlp processes.
            ytdlp_path: Path to yt-dlp binary, or "yt-dlp" if in PATH.
            timeout: Max seconds per channel before skipping.
            proxy: Optional proxy URL for all yt-dlp requests
                   (e.g. 'http://user:pass@host:port').
        """
        self.max_workers = max_workers
        self.ytdlp_path = ytdlp_path
        self.timeout = timeout
        self.proxy = proxy

    def verify(
        self,
        channels: List[Dict[str, str]],
    ) -> List[Dict]:
        """Verify which channels have Shorts.

        Args:
            channels: List of dicts with keys 'name' (channel name) and 'id' (channel_id).
                      Example: [{"name": "SpraySword", "id": "UCtAX3Vb0tKFcYsLyKDbUI9Q"}]

        Returns:
            List of dicts with keys:
                channel_name, channel_id, is_shorts_creator, shorts_count,
                total_shorts_views, error (if failed)
        """
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {
                executor.submit(self._fetch_shorts, ch["name"], ch["id"]): ch
                for ch in channels if ch.get("id")
            }

            for future in as_completed(future_map):
                ch = future_map[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append({
                        "channel_name": ch["name"],
                        "channel_id": ch.get("id", ""),
                        "is_shorts_creator": False,
                        "shorts_count": 0,
                        "total_shorts_views": 0,
                        "error": str(e),
                    })

        return results

    def _build_cmd(self) -> list:
        """Build yt-dlp command with anti-ban options."""
        cmd = [
            self.ytdlp_path,
            "--flat-playlist",
            "--dump-json",
            "--impersonate", "chrome",       # browser TLS fingerprint
            "--extractor-retries", "1",       # don't hammer on errors
            "--no-warnings",
        ]
        if self.proxy:
            cmd += ["--proxy", self.proxy]
        return cmd

    def _fetch_shorts(self, channel_name: str, channel_id: str) -> Dict:
        """Fetch Shorts metadata for a single channel via yt-dlp.

        Uses --flat-playlist --dump-json for lightweight metadata-only fetch.
        Anti-ban: --impersonate chrome + optional --proxy.
        """
        url = f"https://www.youtube.com/channel/{channel_id}/shorts"

        try:
            cmd = self._build_cmd() + [url]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "channel_name": channel_name,
                "channel_id": channel_id,
                "is_shorts_creator": False,
                "shorts_count": 0,
                "total_shorts_views": 0,
                "error": "timeout",
            }
        except FileNotFoundError:
            return {
                "channel_name": channel_name,
                "channel_id": channel_id,
                "is_shorts_creator": False,
                "shorts_count": 0,
                "total_shorts_views": 0,
                "error": "yt-dlp not found",
            }

        if result.returncode != 0 or not result.stdout:
            return {
                "channel_name": channel_name,
                "channel_id": channel_id,
                "is_shorts_creator": False,
                "shorts_count": 0,
                "total_shorts_views": 0,
                "error": result.stderr.strip() or "no output",
            }

        # Parse JSON lines output
        total_views = 0
        count = 0
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                count += 1
                views = data.get("view_count")
                if views is not None:
                    total_views += int(views)
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        return {
            "channel_name": channel_name,
            "channel_id": channel_id,
            "is_shorts_creator": count > 0,
            "shorts_count": count,
            "total_shorts_views": total_views,
            "error": None,
        }


def filter_shorts_channels(
    channel_keywords: Dict[str, Dict],
    shorts_results: List[Dict],
) -> Dict[str, Dict]:
    """Filter channel_keywords to only keep channels verified as Shorts creators.

    Args:
        channel_keywords: {channel_name: {keyword: weight}}
        shorts_results: Output from ShortsVerifier.verify()

    Returns:
        Filtered channel_keywords dict (only Shorts-creating channels).
    """
    short_channels = {r["channel_name"] for r in shorts_results if r.get("is_shorts_creator")}
    return {ch: kw for ch, kw in channel_keywords.items() if ch in short_channels}
