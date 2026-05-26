from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


@dataclass
class VideoRecord:
    """Raw video data from YouTube search result."""
    title: str
    video_id: str
    view_count: int
    published: datetime
    duration: str
    channel: str
    keyword: str  # the search keyword that found this video

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "VideoRecord":
        d["published"] = datetime.fromisoformat(d["published"])
        return cls(**d)


@dataclass
class KeywordStats:
    """Aggregated statistics and computed metrics for a single keyword."""
    keyword: str
    # Time window counts
    count_7d: int = 0
    count_30d: int = 0
    count_365d: int = 0
    # Time window views
    views_7d: int = 0
    views_30d: int = 0
    views_365d: int = 0
    # Derived metrics (computed)
    supply_growth: float = 0.0
    demand_growth: float = 0.0
    supply_demand_ratio: float = 0.0
    opportunity_score: float = 0.0
    total_views: int = 0
    # Co-occurrence
    co_keywords: List[str] = field(default_factory=list)


@dataclass
class CooccurrenceEdge:
    """Co-occurrence relationship between two keywords."""
    source: str
    target: str
    weight: int  # number of videos where both keywords appear


@dataclass
class ChannelNode:
    """Channel-level data for Pyvis network visualization."""
    name: str
    total_views: int = 0
    video_count: int = 0
    top_keywords: List[str] = field(default_factory=list)
    community_id: int = 0
    opportunity_score: float = 0.0
    supply_growth: float = 0.0
    demand_growth: float = 0.0
    supply_demand_ratio: float = 0.0
