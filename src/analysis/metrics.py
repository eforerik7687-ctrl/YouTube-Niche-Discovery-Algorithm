from typing import Dict, List

from src.collector.collector import YouTubeCollector
from src.models import KeywordStats, VideoRecord


class MetricsCalculator:
    """Compute four key metrics per keyword across time windows."""

    def __init__(self, collector: YouTubeCollector):
        self.collector = collector

    def compute(self, videos: List[VideoRecord]) -> Dict[str, KeywordStats]:
        """Compute keyword stats from a list of videos.

        Groups by keyword, counts/sums across 7d/30d/365d windows,
        then derives growth rates and opportunity score.
        """
        # Phase 1: aggregate raw counts and views
        raw: Dict[str, dict] = {}
        for v in videos:
            kw = v.keyword
            if kw not in raw:
                raw[kw] = {
                    "count_7d": 0, "count_30d": 0, "count_365d": 0,
                    "views_7d": 0, "views_30d": 0, "views_365d": 0,
                }

            is_7d = bool(self.collector.filter_by_window([v], days=7))
            is_30d = bool(self.collector.filter_by_window([v], days=30))
            is_365d = bool(self.collector.filter_by_window([v], days=365))

            if is_7d:
                raw[kw]["count_7d"] += 1
                raw[kw]["views_7d"] += v.view_count
            if is_30d:
                raw[kw]["count_30d"] += 1
                raw[kw]["views_30d"] += v.view_count
            if is_365d:
                raw[kw]["count_365d"] += 1
                raw[kw]["views_365d"] += v.view_count

        # Phase 2: compute derived metrics
        stats: Dict[str, KeywordStats] = {}
        for kw, r in raw.items():
            supply = self._safe_divide(r["count_7d"], r["count_30d"])
            demand = self._safe_divide(r["views_7d"], r["views_30d"])
            ratio = self._safe_divide(supply, demand)
            opp = self._safe_divide(r["views_7d"], ratio)

            stats[kw] = KeywordStats(
                keyword=kw,
                count_7d=r["count_7d"],
                count_30d=r["count_30d"],
                count_365d=r["count_365d"],
                views_7d=r["views_7d"],
                views_30d=r["views_30d"],
                views_365d=r["views_365d"],
                supply_growth=round(supply, 4),
                demand_growth=round(demand, 4),
                supply_demand_ratio=round(ratio, 4),
                opportunity_score=round(opp, 2),
                total_views=r["views_365d"],
            )

        return stats

    @staticmethod
    def _safe_divide(a: float | int, b: float | int) -> float:
        """Return a/b, or 0.0 if b is 0."""
        if b == 0:
            return 0.0
        return a / b
