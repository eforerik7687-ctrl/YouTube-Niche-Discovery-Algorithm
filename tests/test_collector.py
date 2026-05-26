import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.collector.collector import YouTubeCollector
from src.config import Config
from src.models import VideoRecord


FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def config():
    return Config(max_results_per_keyword=50)


@pytest.fixture
def sample_videos():
    path = FIXTURE_DIR / "sample_search.json"
    data = json.loads(path.read_text())
    return [
        VideoRecord(
            title=v["title"],
            video_id=v["id"],
            view_count=v["view_count"],
            published=datetime.fromisoformat(v["published"]).replace(tzinfo=timezone.utc),
            duration=v["duration"],
            channel=v["channel"],
            keyword=v["keyword"],
        )
        for v in data["videos"]
    ]


class TestFilterByWindow:
    def test_7d_window(self, config, sample_videos):
        collector = YouTubeCollector(config)
        recent = collector.filter_by_window(sample_videos, days=7)
        assert all(
            v.published >= datetime.now(timezone.utc) - timedelta(days=7)
            for v in recent
        )

    def test_30d_window(self, config, sample_videos):
        collector = YouTubeCollector(config)
        recent = collector.filter_by_window(sample_videos, days=30)
        assert len(recent) > 0

    def test_365d_window_includes_all(self, config, sample_videos):
        collector = YouTubeCollector(config)
        all_vids = collector.filter_by_window(sample_videos, days=365)
        assert len(all_vids) >= len(sample_videos) - 1


class TestParsePublished:
    def test_days_ago(self, config):
        collector = YouTubeCollector(config)
        result = collector._parse_published("3 days ago")
        assert result is not None
        expected = datetime.now(timezone.utc) - timedelta(days=3)
        assert abs((result - expected).total_seconds()) < 10

    def test_hours_ago(self, config):
        collector = YouTubeCollector(config)
        result = collector._parse_published("5 hours ago")
        assert result is not None

    def test_months_ago(self, config):
        collector = YouTubeCollector(config)
        result = collector._parse_published("2 months ago")
        assert result is not None

    def test_none_input(self, config):
        collector = YouTubeCollector(config)
        assert collector._parse_published("") is None
        assert collector._parse_published(None) is None

    def test_live_stream_text(self, config):
        collector = YouTubeCollector(config)
        assert collector._parse_published("Streamed 1 day ago") is not None
