from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv
import os

load_dotenv()


@dataclass
class Config:
    # Time windows in days
    recent_window: int = 7
    medium_window: int = 30
    past_window: int = 365

    # Search config
    max_results_per_keyword: int = 200
    sort_by: str = "upload_date"

    # Output paths
    output_dir: str = "output"
    raw_dir: str = "output/raw"

    # Proxy (optional)
    proxy: str = ""

    # Seed keywords
    seed_keywords: List[str] = field(default_factory=list)

    # Search modifiers for KeywordPropagator
    search_modifiers: List[str] = field(default_factory=lambda: [
        "tutorial", "vs", "best", "review", "beginner", "advanced",
        "top", "how to", "guide", "course", "2026",
    ])

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            recent_window=int(os.getenv("RECENT_WINDOW", "7")),
            medium_window=int(os.getenv("MEDIUM_WINDOW", "30")),
            past_window=int(os.getenv("PAST_WINDOW", "365")),
            max_results_per_keyword=int(os.getenv("MAX_RESULTS_PER_KEYWORD", "200")),
            sort_by=os.getenv("SORT_BY", "upload_date"),
            proxy=os.getenv("PROXY", ""),
            seed_keywords=[
                kw.strip()
                for kw in os.getenv("SEED_KEYWORDS", "").split(",")
                if kw.strip()
            ],
            output_dir=os.getenv("OUTPUT_DIR", "output"),
            raw_dir=os.getenv("RAW_DIR", "output/raw"),
        )
