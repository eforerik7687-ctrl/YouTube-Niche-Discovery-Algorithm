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

    # Single proxy (optional)
    proxy: str = ""
    # Proxy rotation list (comma-separated in env)
    proxy_list: List[str] = field(default_factory=list)

    # Anti-ban: random delay range in seconds before each yt.search()
    delay_min: float = 0.0
    delay_max: float = 0.0
    # Anti-ban: jitter for SuggestQueries calls
    suggest_delay_min: float = 0.1
    suggest_delay_max: float = 0.5

    # Seed keywords
    seed_keywords: List[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Config":
        proxy_str = os.getenv("PROXY_LIST", "")
        proxy_list = [p.strip() for p in proxy_str.split(",") if p.strip()]
        return cls(
            recent_window=int(os.getenv("RECENT_WINDOW", "7")),
            medium_window=int(os.getenv("MEDIUM_WINDOW", "30")),
            past_window=int(os.getenv("PAST_WINDOW", "365")),
            max_results_per_keyword=int(os.getenv("MAX_RESULTS_PER_KEYWORD", "200")),
            sort_by=os.getenv("SORT_BY", "upload_date"),
            proxy=os.getenv("PROXY", ""),
            proxy_list=proxy_list,
            delay_min=float(os.getenv("DELAY_MIN", "0.5")),
            delay_max=float(os.getenv("DELAY_MAX", "2.0")),
            suggest_delay_min=float(os.getenv("SUGGEST_DELAY_MIN", "0.1")),
            suggest_delay_max=float(os.getenv("SUGGEST_DELAY_MAX", "0.5")),
            seed_keywords=[
                kw.strip()
                for kw in os.getenv("SEED_KEYWORDS", "").split(",")
                if kw.strip()
            ],
            output_dir=os.getenv("OUTPUT_DIR", "output"),
            raw_dir=os.getenv("RAW_DIR", "output/raw"),
        )
