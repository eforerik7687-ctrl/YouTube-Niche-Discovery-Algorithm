import json
from pathlib import Path
from typing import Dict, List

from src.models import CooccurrenceEdge, KeywordStats, VideoRecord


class OutputFormatter:
    """Export analysis results to JSON for frontend consumption."""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "raw").mkdir(exist_ok=True)

    def save_videos(self, videos: List[VideoRecord], filename: str = "raw/videos.json"):
        path = self.output_dir / filename
        path.write_text(
            json.dumps([v.to_dict() for v in videos], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(path)

    def save_keywords(
        self,
        stats: Dict[str, KeywordStats],
        communities: Dict[str, int],
        filename: str = "keywords.json",
    ):
        """Export keyword stats with community assignments for frontend table."""
        items = []
        for kw, s in stats.items():
            items.append({
                "keyword": kw,
                "community_id": communities.get(kw, 0),
                "count_7d": s.count_7d,
                "count_30d": s.count_30d,
                "count_365d": s.count_365d,
                "views_7d": s.views_7d,
                "views_30d": s.views_30d,
                "views_365d": s.views_365d,
                "supply_growth": s.supply_growth,
                "demand_growth": s.demand_growth,
                "supply_demand_ratio": s.supply_demand_ratio,
                "opportunity_score": s.opportunity_score,
                "total_views": s.total_views,
            })

        # Sort by opportunity_score descending
        items.sort(key=lambda x: x["opportunity_score"], reverse=True)

        path = self.output_dir / filename
        path.write_text(
            json.dumps(items, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(path)

    def save_concepts(
        self,
        channel_concepts: Dict[str, List[Dict]],
        niche_concepts: Dict[int, List[Dict]],
        filename: str = "concepts.json",
    ) -> str:
        """Export both channel-level and niche-level concepts to JSON.

        Args:
            channel_concepts: {channel_name: [{concept, score}, ...]}
            niche_concepts: {niche_id: [{concept, coverage, avg_score}, ...]}

        Returns: path to saved JSON file
        """
        output = {
            "channel_concepts": channel_concepts,
            "niche_concepts": niche_concepts,
        }
        path = self.output_dir / filename
        path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(path)

    def save_edges(
        self,
        edges: List[CooccurrenceEdge],
        filename: str = "edges.json",
    ):
        path = self.output_dir / filename
        path.write_text(
            json.dumps(
                [{"source": e.source, "target": e.target, "weight": e.weight}
                 for e in edges],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return str(path)
