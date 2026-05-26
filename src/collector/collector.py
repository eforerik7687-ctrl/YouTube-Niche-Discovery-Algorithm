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
        """Search YouTube for each keyword, collecting this_year data."""
        records: List[VideoRecord] = []
        yt = self._get_client()

        for keyword in keywords:
            results = yt.search(
                keyword,
                max_results=self.config.max_results_per_keyword,
                sort_by=self.config.sort_by,
                type="video",
            )
            for video in results.videos:
                published = self._parse_published(video.published_text)
                records.append(
                    VideoRecord(
                        title=video.title,
                        video_id=video.id,
                        view_count=video.view_count,
                        published=published or datetime.now(timezone.utc),
                        duration=video.duration or "",
                        channel=getattr(video, "channel", "") or "",
                        keyword=keyword,
                    )
                )
        return records

    def filter_by_window(
        self, videos: List[VideoRecord], days: int
    ) -> List[VideoRecord]:
        """Filter videos published within the last N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [v for v in videos if v.published >= cutoff]

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
