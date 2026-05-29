import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

try:
    from tubescrape import YouTube
except ImportError:
    YouTube = None  # type: ignore

from src.config import Config
from src.models import VideoRecord


class YouTubeCollector:
    """Collect YouTube video data using tubescrape."""

    def __init__(self, config: Config):
        self.config = config
        self._yt: Optional["YouTube"] = None

    def _get_client(self):
        if self._yt is None:
            if YouTube is None:
                raise ImportError(
                    "tubescrape is not installed. Install it with: pip install tubescrape"
                )
            kwargs = {}
            if self.config.proxy:
                kwargs["proxy"] = self.config.proxy
            self._yt = YouTube(**kwargs)
        return self._yt

    def collect(self, keywords: List[str]) -> List[VideoRecord]:
        """Search YouTube for each keyword, collect all matching videos."""
        records: List[VideoRecord] = []
        yt = self._get_client()

        for keyword in keywords:
            results = yt.search(
                keyword,
                max_results=self.config.max_results_per_keyword,
                sort_by=self.config.sort_by,
                type="video",
                upload_date="this_year",
            )
            for video in results.videos:
                title_lower = video.title.lower()
                if "livestream" in title_lower:
                    continue
                published = self._parse_published(video.published_text)
                records.append(
                    VideoRecord(
                        title=video.title,
                        video_id=self._extract_video_id(video.url),
                        view_count=self._parse_view_count(video.view_count),
                        published=published or datetime.now(timezone.utc),
                        duration=video.duration or "",
                        channel=video.channel or "",
                        channel_url=getattr(video, "channel_url", "") or "",
                        keyword=keyword,
                    )
                )
        return records

    @staticmethod
    def _is_short(duration: str) -> bool:
        """Return True if duration is under 60 seconds (YouTube Shorts)."""
        if not duration:
            return False
        total = 0
        parts = str(duration).split(":")
        if len(parts) == 3:  # H:MM:SS
            total = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:  # M:SS
            total = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:  # seconds
            total = int(parts[0])
        return total <= 60

    def filter_by_window(
        self, videos: List[VideoRecord], days: int
    ) -> List[VideoRecord]:
        """Filter videos published within the last N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [v for v in videos if v.published >= cutoff]

    @staticmethod
    def _parse_view_count(value) -> int:
        """Parse view count from various YouTube formats."""
        if value is None:
            return 0
        text = str(value).lower().replace(",", "")
        # Extract the first number (with optional decimal)
        match = re.search(r"([\d.]+)\s*([kmb]?)", text)
        if not match:
            return 0
        num = float(match.group(1))
        suffix = match.group(2)
        multipliers = {"k": 1000, "m": 1000000, "b": 1000000000}
        return int(num * multipliers.get(suffix, 1))

    @staticmethod
    def _extract_video_id(url: str) -> str:
        """Extract video ID from YouTube URL."""
        if not url:
            return ""
        match = re.search(r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})", url)
        return match.group(1) if match else url

    def _parse_published(self, text: Optional[str]) -> Optional[datetime]:
        """Parse tubescrape's relative time text (e.g. '3 days ago') to datetime."""
        if not text:
            return None
        now = datetime.now(timezone.utc)
        text = text.lower().strip()

        multipliers = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
            "week": 604800,
            "month": 2592000,   # 30 days
            "year": 31536000,   # 365 days
        }

        for keyword, total_seconds in multipliers.items():
            if keyword in text:
                match = re.search(r"(\d+)", text)
                if match:
                    num = int(match.group(1))
                    return now - timedelta(seconds=num * total_seconds)
        return None

    def close(self):
        if self._yt is not None:
            self._yt.__exit__(None, None, None)
            self._yt = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
