from datetime import datetime, timezone

import pytest

from src.analysis.metrics import MetricsCalculator
from src.collector.collector import YouTubeCollector
from src.config import Config
from src.models import VideoRecord


@pytest.fixture
def calculator():
    config = Config()
    collector = YouTubeCollector(config)
    return MetricsCalculator(collector)


def _v(title: str, kw: str, views: int, days_ago: int) -> VideoRecord:
    return VideoRecord(
        title=title,
        video_id=f"id_{hash(title)}",
        view_count=views,
        published=datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone.utc)
        - __import__("datetime").timedelta(days=days_ago),
        duration="10:00",
        channel="Test",
        keyword=kw,
    )


class TestCompute:
    def test_single_keyword_7d_only(self, calculator):
        """All views in 7d window -> high opportunity."""
        videos = [_v("title", "python", 100_000, days_ago=1)]
        stats = calculator.compute(videos)
        s = stats["python"]
        assert s.count_7d == 1
        assert s.views_7d == 100_000
        assert s.supply_growth > 0

    def test_high_supply_low_demand(self, calculator):
        """Many videos (supply) but low views -> high ratio -> low opp."""
        videos = [_v(f"title{i}", "python", 500, days_ago=1) for i in range(10)]
        videos += [_v("old high-view video", "python", 50_000, days_ago=10)]
        stats = calculator.compute(videos)
        s = stats["python"]
        # 10 recent / 11 total in 30d = ~0.909 supply_growth
        assert s.count_7d == 10
        assert s.count_30d == 11
        # Low recent demand relative to past -> high ratio
        assert s.supply_demand_ratio > 1.0

    def test_blue_ocean_signal(self, calculator):
        """Demand growing faster than supply -> low ratio -> high opp."""
        videos = [
            _v("hot topic 1", "python", 200_000, days_ago=1),
            _v("hot topic 2", "python", 150_000, days_ago=2),
            _v("old video", "python", 10_000, days_ago=10),
        ]
        stats = calculator.compute(videos)
        s = stats["python"]
        # supply: 2/3 = 0.667, demand: 350k/360k = 0.972, ratio = 0.667/0.972 = 0.686
        assert s.supply_demand_ratio < 1.0

    def test_multiple_keywords(self, calculator):
        videos = [
            _v("learn python fast", "python", 50_000, days_ago=1),
            _v("python tutorial", "python", 30_000, days_ago=30),
            _v("javascript basics", "javascript", 80_000, days_ago=1),
            _v("js tutorial", "javascript", 20_000, days_ago=60),
        ]
        stats = calculator.compute(videos)
        assert "python" in stats
        assert "javascript" in stats
        assert len(stats) == 2

    def test_empty_videos(self, calculator):
        stats = calculator.compute([])
        assert stats == {}

    def test_safe_divide_by_zero(self, calculator):
        result = calculator._safe_divide(10, 0)
        assert result == 0.0

    def test_safe_divide_normal(self, calculator):
        result = calculator._safe_divide(10, 5)
        assert result == 2.0
