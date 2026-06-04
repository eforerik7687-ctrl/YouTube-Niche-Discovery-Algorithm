"""Social Blade crawler — Playwright + real Chrome.

Extracts per channel:
- Total subs / views / videos
- Creator Statistics: 30-day subs Δ, 30-day views Δ
- Daily table: 14 days of views Δ, videos Δ per day
- Computes: 7d total views, 7d total videos

Usage:
    from src.socialblade.crawler import SocialBladeCrawler

    crawler = SocialBladeCrawler()
    data = crawler.scan_channels(["dream", "mrbeast", ...])
    # data = {handle: {total: {...}, stats_30d: {...}, daily: [...], periods: {...}}}
"""

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Channel handle → Social Blade URL
SB_URL = "https://socialblade.com/youtube/handle/{}"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


class SocialBladeCrawler:
    """Crawl Social Blade for channel statistics using Playwright + real Chrome."""

    def __init__(self, delay_range: tuple = (8, 16), cookies_path: Optional[str] = None):
        self.delay_min, self.delay_max = delay_range
        self.cookies_path = cookies_path
        self.results: Dict[str, Dict] = {}

    def scan_channels(self, channels: List[Dict]) -> Dict[str, Dict]:
        """Scan multiple channels.

        Args:
            channels: List of dicts with keys:
                      {handle: str} or {channel_id: str, channel_name: str}

        Returns:
            {channel_handle: {total: {...}, stats_30d: {...}, daily: [...], periods: {...}}}
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            # Inject anti-detection script
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

            # Load cookies if available
            if self.cookies_path and Path(self.cookies_path).exists():
                try:
                    cookies = json.loads(Path(self.cookies_path).read_text())
                    ctx.add_cookies(cookies)
                    logger.info(f"Loaded {len(cookies)} cookies from {self.cookies_path}")
                except Exception as e:
                    logger.warning(f"Failed to load cookies: {e}")

            page = ctx.new_page()

            for ch in channels:
                handle = ch.get("handle", "")
                if not handle and ch.get("channel_name"):
                    handle = ch["channel_name"].lower().replace(" ", "")
                if not handle:
                    handle = ch.get("channel_id", "")[:8]

                url = SB_URL.format(handle)
                logger.info(f"Crawling: {handle} ({url})")

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    # Wait for dynamic content (Social Blade needs ~10s to render)
                    time.sleep(random.uniform(max(self.delay_min, 10), max(self.delay_max, 14)))

                    result = self._extract_page(page, handle)
                    self.results[handle] = result

                    # Compute period totals
                    result["periods"] = self._compute_periods(
                        result.get("daily", []), result.get("summary")
                    )

                    logger.info(f"  → {result.get('total', {}).get('subs', '?')} subs, "
                                f"{result['periods'].get('views_7d', 0):,} views 7d")

                except Exception as e:
                    logger.error(f"Failed to crawl {handle}: {e}")
                    self.results[handle] = {"error": str(e)}

                # Random delay between channels
                if ch != channels[-1]:
                    delay = random.uniform(self.delay_min, self.delay_max)
                    time.sleep(delay)

            browser.close()

        return self.results

    def _extract_page(self, page, handle: str) -> Dict:
        """Extract all stats from a loaded Social Blade page."""
        body = page.evaluate("() => document.body.innerText")
        lines = [l.strip() for l in body.split("\n")]

        result = {}

        # ─── 1. Total stats ───
        total = {}
        for i, l in enumerate(lines):
            if l == "Subscribers":
                total["subs"] = self._clean_num(lines[i + 2].strip()) if i + 2 < len(lines) else ""
            elif l == "Views":
                total["views"] = self._clean_num(lines[i + 2].strip()) if i + 2 < len(lines) else ""
            elif l == "Videos":
                total["videos"] = self._clean_num(lines[i + 2].strip()) if i + 2 < len(lines) else ""
        result["total"] = total

        # ─── 2. Creator Statistics (30d) ───
        stats_30d = {}
        for i, l in enumerate(lines):
            if "Subscribers for the last 30 days" in l and i > 0:
                val = self._clean_num(lines[i - 1].strip())
                if val and not any(k in val for k in ["Subscriber", "View", "CREATOR"]):
                    stats_30d["subs_30d"] = val
            elif "Views for the last 30 days" in l and i > 0:
                val = self._clean_num(lines[i - 1].strip())
                if val and val not in ("0", "") and "View" not in val:
                    stats_30d["views_30d"] = val
        result["stats_30d"] = stats_30d

        # ─── 3. Daily table (14 days) ───
        daily = []
        for i, l in enumerate(lines):
            if re.match(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)20\d{2}-", l):
                parts = l.split("\t")
                if len(parts) >= 7:
                    daily.append({
                        "date": parts[0].lstrip("MonTueWedThuFriSatSun"),
                        "subs_delta": self._parse_int(parts[1]),
                        "total_subs": parts[2],
                        "views_delta": self._parse_int(parts[3]),
                        "total_views": parts[4],
                        "videos_delta": self._parse_int(parts[5]),
                        "total_videos": parts[6],
                    })
        result["daily"] = daily

        # ─── 4. Summary lines (Daily/Weekly/Last 30) ───
        summary = {}
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith("Last 30 Days") or s.startswith("Last 30 days"):
                parts = s.split("\t")
                if len(parts) >= 4:
                    summary["last_30d"] = {
                        "subs": self._parse_int(parts[1] if len(parts) > 1 else 0),
                        "views": self._parse_int(parts[2] if len(parts) > 2 else 0),
                        "videos": self._parse_int(parts[3] if len(parts) > 3 else 0),
                    }
        # Fallback: parse from stats_30d if summary line not found
        if "last_30d" not in summary and stats_30d:
            summary["last_30d"] = {
                "subs": self._parse_int(stats_30d.get("subs_30d", "0")),
                "views": self._parse_int(stats_30d.get("views_30d", "0")),
                "videos": 0,
            }
        result["summary"] = summary

        return result

    def _compute_periods(self, daily: List[Dict], summary: Dict = None) -> Dict:
        """Compute 7d (from daily rows) + 30d (from summary line)."""
        periods = {"views_7d": 0, "videos_7d": 0, "views_30d": 0, "videos_30d": 0}

        # 7d from daily table (last 7 rows = most recent)
        # daily is ordered oldest → newest, so [-7:] = most recent 7 days
        recent = daily[-7:]
        for row in recent:
            periods["views_7d"] += row.get("views_delta", 0)
            periods["videos_7d"] += row.get("videos_delta", 0)

        # 30d from summary line
        if summary and "last_30d" in summary:
            periods["views_30d"] = summary["last_30d"].get("views", 0)
            periods["videos_30d"] = summary["last_30d"].get("videos", 0)

        return periods

    @staticmethod
    def _clean_num(s: str) -> str:
        """Convert '34.4M', '6.9B', etc. to clean string."""
        return s.replace(",", "")

    @staticmethod
    def _parse_int(s) -> int:
        """Parse '13M', '6.9B', '1,099,213', '--' → int."""
        if isinstance(s, int):
            return s
        if not s or s == "--" or s == "-":
            return 0
        s = str(s).strip()
        multiplier = 1
        if s.upper().endswith("B"):
            multiplier = 1_000_000_000
            s = s[:-1]
        elif s.upper().endswith("M"):
            multiplier = 1_000_000
            s = s[:-1]
        elif s.upper().endswith("K"):
            multiplier = 1_000
            s = s[:-1]
        try:
            return int(float(s.replace(",", "")) * multiplier)
        except (ValueError, TypeError):
            return 0

    def export_json(self, output_path: str = "output/socialblade_data.json"):
        """Export results to JSON."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.results, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Exported: {path}")
        return str(path)


# ─── Quick test ───
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    crawler = SocialBladeCrawler()
    data = crawler.scan_channels([
        {"handle": "mrbeast"},
        {"handle": "dream"},
    ])
    for handle, d in data.items():
        p = d.get("periods", {})
        print(f"\n{handle}:")
        print(f"  Total: {d['total']}")
        print(f"  Summary 30d: {d.get('summary', {}).get('last_30d', {})}")
        print(f"  7d:   {p.get('views_7d', 0):,} views, {p.get('videos_7d', 0)} videos")
        print(f"  30d:  {p.get('views_30d', 0):,} views, {p.get('videos_30d', 0)} videos")
