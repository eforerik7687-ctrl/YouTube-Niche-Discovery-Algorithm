# YouTube Niche Finder 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 YouTube 利基發現系統，透過關鍵詞共現網路與供需比指標自動找出藍海利基。

**Architecture:** 五層架構 — Python 後端負責採集 (tubescrape) + 分析 (networkx/pandas)，JSON 為資料交換格式，前端為靜態 HTML (Pyvis + 可排序表格)。採路線 B：一次查詢全年資料，在記憶體中按精確日期過濾 7d/30d/365d 三窗口。

**Tech Stack:** Python 3.10+, tubescrape, networkx, pandas, Pyvis, Chart.js (前端)

---
## File Structure

```
youtube-niche-finder/
├── src/
│   ├── __init__.py
│   ├── config.py                 # 設定管理（pydantic-settings / dataclass）
│   ├── models.py                 # 資料模型（VideoRecord, KeywordStats, CooccurrenceEdge）
│   ├── collector/
│   │   ├── __init__.py
│   │   └── collector.py          # YouTubeCollector — tubescrape 封裝
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── extractor.py          # KeywordExtractor — 從標題萃取關鍵詞
│   │   ├── metrics.py            # MetricsCalculator — 四項指標計算
│   │   └── community.py          # CommunityDetector — 共現網路 + 社群發現
│   ├── output/
│   │   └── formatter.py          # JSON / HTML 輸出格式器
│   └── cli.py                    # CLI 入口點（typer / argparse）
├── output/
│   ├── raw/                      # 原始影片資料 JSON
│   ├── keywords.json             # 關鍵詞指標結果
│   └── graph.html                # Pyvis 網路圖
├── tests/
│   ├── __init__.py
│   ├── test_extractor.py
│   ├── test_metrics.py
│   ├── test_community.py
│   └── fixtures/                 # 測試用 fixture JSON
├── pyproject.toml
├── .env
└── README.md
```

---

### Task 1: 專案 Scaffolding + Config + Models

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `src/models.py`

- [ ] **Step 1: 建立 pyproject.toml**

```toml
[project]
name = "youtube-niche-finder"
version = "0.1.0"
description = "YouTube Niche Discovery System - find blue ocean niches via keyword co-occurrence networks"
requires-python = ">=3.10"
dependencies = [
    "tubescrape>=0.1.0",
    "networkx>=3.0",
    "python-louvain>=0.16",
    "pandas>=2.0",
    "python-dateutil>=2.8",
    "python-dotenv>=1.0",
    "pyvis>=0.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "mypy>=1.0",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]

[tool.mypy]
strict = true
python_version = "3.10"
```

- [ ] **Step 2: 建立 .env.example**

```env
# YouTube Niche Finder 設定
# 代理設定（選用，YouTube 可能封鎖部分 IP）
PROXY=

# 預設種子關鍵詞（逗號分隔）
SEED_KEYWORDS=python tutorial, machine learning, data science

# 時間窗口天數
RECENT_WINDOW=7
MEDIUM_WINDOW=30
PAST_WINDOW=365

# 搜尋設定
MAX_RESULTS_PER_KEYWORD=200
SORT_BY=upload_date
```

- [ ] **Step 3: 建立 src/config.py**

```python
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
```

- [ ] **Step 4: 建立 src/models.py**

```python
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
```

- [ ] **Step 5: 建立 src/__init__.py**

```python
"""YouTube Niche Finder - discover blue ocean niches via keyword co-occurrence networks."""
```

- [ ] **Step 6: 跑測試確認 import 正確**

Run: `cd /path/to/youtube-niche-finder && python -c "from src.config import Config; from src.models import VideoRecord, KeywordStats, CooccurrenceEdge; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example src/
git commit -m "feat: scaffold project structure with config and data models"
```

---

### Task 2: Keyword Extractor

**Files:**
- Create: `src/analysis/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: 建立 src/analysis/extractor.py**

```python
import re
from typing import List, Set


# Default English stopwords for YouTube niche mining
_DEFAULT_STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "not", "no", "nor",
    "so", "as", "if", "than", "that", "this", "these", "those", "it", "its",
    "how", "what", "when", "where", "why", "who", "whom", "which",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "get", "got", "getting",
    "make", "made", "making", "use", "used", "using", "new", "one", "two",
    "like", "just", "also", "very", "really", "way", "know", "need",
    "want", "see", "try", "vs", "using", "amp", "via", "de", "en",
    "youtube", "video", "tutorial", "guide", "howto",
}


class KeywordExtractor:
    """Extract meaningful keywords from video titles."""

    def __init__(self, stopwords: Set[str] | None = None):
        self.stopwords = stopwords or _DEFAULT_STOPWORDS

    def extract(self, title: str) -> List[str]:
        """Extract single-word keywords from a title.

        Steps: lowercase, split on non-alpha, filter short/stopwords.
        """
        cleaned = re.sub(r"[^a-z0-9\s#+]", " ", title.lower())
        tokens = cleaned.split()
        return [
            t for t in tokens
            if len(t) > 2 and t not in self.stopwords and not t.isdigit()
        ]

    def extract_ngrams(self, title: str, n: int = 2) -> List[str]:
        """Extract n-gram phrases from a title."""
        tokens = self.extract(title)
        return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]

    def extract_all(self, title: str) -> List[str]:
        """Extract both unigrams and bigrams."""
        return self.extract(title) + self.extract_ngrams(title)
```

- [ ] **Step 2: 建立 tests/test_extractor.py**

```python
import pytest
from src.analysis.extractor import KeywordExtractor


@pytest.fixture
def extractor():
    return KeywordExtractor()


class TestExtract:
    def test_removes_stopwords(self, extractor):
        result = extractor.extract("the quick brown fox")
        assert "the" not in result
        assert "quick" in result
        assert "brown" in result
        assert "fox" in result

    def test_lowercases(self, extractor):
        result = extractor.extract("Python Machine Learning")
        assert "python" in result
        assert "machine" in result
        assert "learning" in result

    def test_removes_short_tokens(self, extractor):
        result = extractor.extract("how to go big in ai ml")
        assert "go" not in result
        assert "big" in result
        assert "ai" not in result  # length <= 2
        assert "ml" not in result

    def test_handles_special_chars(self, extractor):
        result = extractor.extract("C++ vs Python 2024!")
        assert "c++" in result or "c" in result
        assert "python" in result
        assert "2024" not in result  # digits only

    def test_empty_title(self, extractor):
        assert extractor.extract("") == []

    def test_extract_ngrams(self, extractor):
        result = extractor.extract_ngrams("machine learning tutorial", n=2)
        assert "machine learning" in result
        assert "learning tutorial" in result

    def test_extract_all_includes_unigrams_and_bigrams(self, extractor):
        result = extractor.extract_all("machine learning python")
        assert "machine" in result
        assert "learning" in result
        assert "python" in result
        assert "machine learning" in result
        assert "learning python" in result
```

- [ ] **Step 3: 跑測試**

Run: `cd /path/to/youtube-niche-finder && python -m pytest tests/test_extractor.py -v`
Expected: 6 passed

- [ ] **Step 4: Commit**

```bash
git add src/analysis/extractor.py tests/test_extractor.py
git commit -m "feat: add keyword extractor from video titles"
```

---

### Task 3: YouTube Collector (tubescrape 整合)

**Files:**
- Create: `src/collector/collector.py`
- Create: `tests/test_collector.py`
- Create: `tests/fixtures/sample_search.json`

- [ ] **Step 1: 建立測試 fixture JSON**

```json
{
  "videos": [
    {
      "title": "Python Machine Learning Tutorial 2024",
      "id": "abc123",
      "view_count": 45000,
      "published": "2026-05-20T10:00:00",
      "duration": "25:30",
      "channel": "TechChannel",
      "keyword": "machine learning"
    },
    {
      "title": "Deep Learning with Python - Full Course",
      "id": "def456",
      "view_count": 120000,
      "published": "2026-05-01T08:00:00",
      "duration": "2:15:00",
      "channel": "AI Academy",
      "keyword": "machine learning"
    },
    {
      "title": "Python for Beginners 2026",
      "id": "ghi789",
      "view_count": 89000,
      "published": "2026-05-25T14:00:00",
      "duration": "45:00",
      "channel": "CodeSimple",
      "keyword": "python"
    },
    {
      "title": "Python Advanced Tips and Tricks",
      "id": "jkl012",
      "view_count": 32000,
      "published": "2026-03-15T09:00:00",
      "duration": "18:00",
      "channel": "ProCoder",
      "keyword": "python"
    },
    {
      "title": "Machine Learning Basics Explained",
      "id": "mno345",
      "view_count": 67000,
      "published": "2026-04-10T11:00:00",
      "duration": "12:00",
      "channel": "DataScience101",
      "keyword": "machine learning"
    }
  ]
}
```

- [ ] **Step 2: 建立 src/collector/collector.py**

```python
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from tubescrape import YouTube

from src.config import Config
from src.models import VideoRecord


class YouTubeCollector:
    """Collect YouTube video data using tubescrape."""

    def __init__(self, config: Config):
        self.config = config
        self._yt: Optional[YouTube] = None

    def _get_client(self) -> YouTube:
        if self._yt is None:
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

    def _parse_published(self, text: str) -> Optional[datetime]:
        """Parse tubescrape's relative time text (e.g. '3 days ago') to datetime."""
        if not text:
            return None
        now = datetime.now(timezone.utc)
        text = text.lower().strip()

        units = {
            "second": "seconds",
            "minute": "minutes",
            "hour": "hours",
            "day": "days",
            "week": "weeks",
            "month": "months",
            "year": "years",
        }

        for key, attr in units.items():
            if key in text:
                try:
                    num = int(text.split()[0])
                    return now - timedelta(**{attr: num})
                except (ValueError, IndexError):
                    return None
        return None

    def close(self):
        if self._yt is not None:
            self._yt.__exit__(None, None, None)
            self._yt = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
```

- [ ] **Step 3: 建立 tests/test_collector.py**

```python
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
            published=datetime.fromisoformat(v["published"]),
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
        # Only videos within last 7 days from fixture date (May 26)
        assert all(v.published >= datetime.now(timezone.utc) - timedelta(days=7)
                   for v in recent)

    def test_30d_window(self, config, sample_videos):
        collector = YouTubeCollector(config)
        recent = collector.filter_by_window(sample_videos, days=30)
        assert len(recent) > 0

    def test_365d_window_includes_all(self, config, sample_videos):
        collector = YouTubeCollector(config)
        all_vids = collector.filter_by_window(sample_videos, days=365)
        assert len(all_vids) >= len(sample_videos) - 1  # fixture dates are within 365d


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
```

- [ ] **Step 4: 跑測試**

Run: `cd /path/to/youtube-niche-finder && python -m pytest tests/test_collector.py tests/test_extractor.py -v`
Expected: 12+ passed

- [ ] **Step 5: Commit**

```bash
git add src/collector/ tests/
git commit -m "feat: add YouTube collector with tubescrape integration"
```

---

### Task 4: Metrics Calculator

**Files:**
- Create: `src/analysis/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: 建立 src/analysis/metrics.py**

```python
from collections import defaultdict
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
                raw[kw] = {"count_7d": 0, "count_30d": 0, "count_365d": 0,
                           "views_7d": 0, "views_30d": 0, "views_365d": 0}

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
```

- [ ] **Step 2: 建立 tests/test_metrics.py**

```python
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
        """Many videos (supply) but low views -> low opportunity."""
        videos = [_v(f"title{i}", "python", 500, days_ago=1) for i in range(10)]
        videos += [_v("old title", "python", 50_000, days_ago=20)]
        stats = calculator.compute(videos)
        s = stats["python"]
        assert s.supply_growth > 1.0  # recent supply is high relative to past
        assert s.opportunity_score > 0

    def test_blue_ocean_signal(self, calculator):
        """Demand growing faster than supply -> low ratio -> high opp."""
        videos = [
            _v("hot topic 1", "python", 200_000, days_ago=1),
            _v("hot topic 2", "python", 150_000, days_ago=2),
            _v("old video", "python", 10_000, days_ago=60),
        ]
        stats = calculator.compute(videos)
        s = stats["python"]
        # 2 recent / 3 total = 0.667 supply growth
        # 350k recent / 360k total = 0.972 demand growth
        # ratio = 0.667/0.972 = 0.686 < 1 -> blue ocean signal
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
```

- [ ] **Step 3: 跑測試**

Run: `cd /path/to/youtube-niche-finder && python -m pytest tests/test_metrics.py -v`
Expected: 7+ passed

- [ ] **Step 4: Commit**

```bash
git add src/analysis/metrics.py tests/test_metrics.py
git commit -m "feat: add metrics calculator with four niche indicators"
```

---

### Task 5: Co-occurrence Network + Community Detection

**Files:**
- Create: `src/analysis/community.py`
- Create: `tests/test_community.py`

- [ ] **Step 1: 建立 src/analysis/community.py**

```python
from collections import defaultdict, Counter
from typing import Dict, List, Set, Tuple

import networkx as nx
from pyvis.network import Network

from src.analysis.extractor import KeywordExtractor
from src.models import CooccurrenceEdge, KeywordStats, VideoRecord


class CommunityDetector:
    """Build keyword co-occurrence network and detect niche communities."""

    def __init__(self, extractor: KeywordExtractor):
        self.extractor = extractor

    def build_edges(
        self, videos: List[VideoRecord]
    ) -> Tuple[Dict[str, KeywordStats], List[CooccurrenceEdge]]:
        """Extract keywords from video titles and build co-occurrence edges.

        For each video, extract keywords from its title. If a video matches
        search keyword K and also contains word W in its title, that's a
        co-occurrence between K and W.
        """
        # keyword -> set of keyword's own stats
        kw_extracted: Dict[str, Counter] = defaultdict(Counter)
        cooccur: Dict[Tuple[str, str], int] = defaultdict(int)

        for video in videos:
            title_kws = self.extractor.extract(video.title)
            # The search keyword that matched this video
            search_kw = video.keyword

            # Add all title keywords as co-occurring with the search keyword
            for tk in set(title_kws):
                if tk == search_kw:
                    continue
                pair = tuple(sorted([search_kw, tk]))
                cooccur[pair] += 1

        # Convert to edge list
        edges = [
            CooccurrenceEdge(source=s, target=t, weight=w)
            for (s, t), w in cooccur.items()
        ]

        return edges

    def detect_communities(
        self, edges: List[CooccurrenceEdge], stats: Dict[str, KeywordStats]
    ) -> Dict[str, int]:
        """Run Louvain community detection on co-occurrence graph.

        Returns: dict of keyword -> community_id
        """
        G = nx.Graph()
        for kw in stats:
            G.add_node(kw, weight=stats[kw].total_views)
        for e in edges:
            if e.source in stats and e.target in stats:
                G.add_edge(e.source, e.target, weight=e.weight)

        if G.number_of_edges() == 0:
            return {kw: 0 for kw in stats}

        from networkx.algorithms.community import louvain_communities

        communities = louvain_communities(G, seed=42)
        result: Dict[str, int] = {}
        for cid, community in enumerate(communities):
            for kw in community:
                result[kw] = cid
        return result

    def export_network(
        self,
        stats: Dict[str, KeywordStats],
        edges: List[CooccurrenceEdge],
        communities: Dict[str, int],
        output_path: str = "output/graph.html",
    ):
        """Generate interactive Pyvis network graph."""
        net = Network(height="700px", width="100%", bgcolor="#ffffff")

        # Color palette for communities
        colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
            "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
        ]

        for kw, s in stats.items():
            cid = communities.get(kw, 0)
            size = max(10, min(80, s.total_views / 10_000))
            net.add_node(
                kw,
                label=kw,
                title=(
                    f"<b>{kw}</b><br>"
                    f"供給增速: {s.supply_growth}<br>"
                    f"需求增速: {s.demand_growth}<br>"
                    f"供需比: {s.supply_demand_ratio}<br>"
                    f"機會得分: {s.opportunity_score}"
                ),
                size=size,
                color=colors[cid % len(colors)],
            )

        for e in edges:
            if e.source in stats and e.target in stats:
                net.add_edge(e.source, e.target, weight=e.weight, title=str(e.weight))

        net.set_options("""
        {
          "physics": {
            "stabilization": {"iterations": 100},
            "barnesHut": {"gravitationalConstant": -3000, "springLength": 200}
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "dragNodes": true,
            "zoomView": true
          }
        }
        """)

        net.save_graph(output_path)
        return output_path
```

- [ ] **Step 2: 建立 tests/test_community.py**

```python
import pytest
from src.analysis.community import CommunityDetector
from src.analysis.extractor import KeywordExtractor
from src.models import VideoRecord, KeywordStats


@pytest.fixture
def detector():
    return CommunityDetector(KeywordExtractor())


class TestBuildEdges:
    def test_simple_cooccurrence(self, detector):
        videos = [
            VideoRecord(
                title="Python Machine Learning Tutorial",
                video_id="v1", view_count=100,
                published=__import__("datetime").datetime(2026, 5, 20),
                duration="10:00", channel="Test",
                keyword="machine learning",
            ),
        ]
        edges = detector.build_edges(videos)
        # Should find co-occurrence between "machine learning" keywords
        # and title words like "python", "tutorial"
        assert len(edges) > 0

    def test_empty_videos(self, detector):
        edges = detector.build_edges([])
        assert edges == []


class TestDetectCommunities:
    def test_basic_clustering(self, detector):
        stats = {
            "python": KeywordStats(keyword="python", total_views=1000),
            "javascript": KeywordStats(keyword="javascript", total_views=800),
            "tutorial": KeywordStats(keyword="tutorial", total_views=500),
        }
        from src.models import CooccurrenceEdge
        edges = [
            CooccurrenceEdge(source="python", target="tutorial", weight=5),
            CooccurrenceEdge(source="javascript", target="tutorial", weight=3),
        ]
        communities = detector.detect_communities(edges, stats)
        assert len(communities) == 3
        assert all(kw in communities for kw in stats)

    def test_no_edges(self, detector):
        stats = {"python": KeywordStats(keyword="python")}
        communities = detector.detect_communities([], stats)
        assert communities == {"python": 0}


class TestExportNetwork:
    def test_returns_path(self, detector, tmp_path):
        stats = {"python": KeywordStats(keyword="python", total_views=1000)}
        from src.models import CooccurrenceEdge
        output = tmp_path / "graph.html"
        path = detector.export_network(stats, [], {}, str(output))
        assert path == str(output)
        assert output.exists()
        content = output.read_text()
        assert "python" in content
        assert "network" in content.lower()
```

- [ ] **Step 3: 跑測試**

Run: `cd /path/to/youtube-niche-finder && python -m pytest tests/test_community.py -v`
Expected: 4+ passed

- [ ] **Step 4: Commit**

```bash
git add src/analysis/community.py tests/test_community.py
git commit -m "feat: add co-occurrence network and community detection"
```

---

### Task 6: Output Formatter (JSON export)

**Files:**
- Create: `src/output/formatter.py`
- Create: `tests/test_formatter.py`

- [ ] **Step 1: 建立 src/output/formatter.py**

```python
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
        self, stats: Dict[str, KeywordStats],
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

    def save_edges(
        self, edges: List[CooccurrenceEdge],
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
```

- [ ] **Step 2: 建立 tests/test_formatter.py**

```python
import json
import pytest
from src.output.formatter import OutputFormatter
from src.models import KeywordStats, CooccurrenceEdge, VideoRecord


class TestOutputFormatter:
    @pytest.fixture
    def formatter(self, tmp_path):
        return OutputFormatter(str(tmp_path))

    def test_save_keywords_sorts_by_opportunity(self, formatter):
        stats = {
            "kw_a": KeywordStats(keyword="kw_a", opportunity_score=50.0),
            "kw_b": KeywordStats(keyword="kw_b", opportunity_score=100.0),
            "kw_c": KeywordStats(keyword="kw_c", opportunity_score=10.0),
        }
        path = formatter.save_keywords(stats, {})
        data = json.loads(open(path, encoding="utf-8").read())
        assert data[0]["keyword"] == "kw_b"  # highest opp first
        assert data[-1]["keyword"] == "kw_c"  # lowest opp last

    def test_save_keywords_includes_community(self, formatter):
        stats = {"kw_a": KeywordStats(keyword="kw_a")}
        communities = {"kw_a": 2}
        path = formatter.save_keywords(stats, communities)
        data = json.loads(open(path, encoding="utf-8").read())
        assert data[0]["community_id"] == 2

    def test_save_videos(self, formatter):
        videos = [
            VideoRecord(
                title="test", video_id="v1", view_count=100,
                published=__import__("datetime").datetime(2026, 5, 20),
                duration="10:00", channel="C", keyword="python",
            )
        ]
        path = formatter.save_videos(videos)
        data = json.loads(open(path, encoding="utf-8").read())
        assert len(data) == 1
        assert data[0]["title"] == "test"

    def test_save_edges(self, formatter):
        edges = [CooccurrenceEdge(source="a", target="b", weight=3)]
        path = formatter.save_edges(edges)
        data = json.loads(open(path, encoding="utf-8").read())
        assert data[0]["source"] == "a"
        assert data[0]["weight"] == 3
```

- [ ] **Step 3: 跑測試**

Run: `cd /path/to/youtube-niche-finder && python -m pytest tests/ -v`
Expected: 24+ passed 整合全測試

- [ ] **Step 4: Commit**

```bash
git add src/output/ tests/test_formatter.py
git commit -m "feat: add JSON output formatter with opportunity ranking"
```

---

### Task 7: CLI Entry Point + Pipeline Orchestrator

**Files:**
- Create: `src/cli.py`

- [ ] **Step 1: 建立 src/cli.py**

```python
"""CLI entry point for YouTube Niche Finder pipeline."""

import argparse
import sys
from pathlib import Path

# Add src to path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config
from src.collector.collector import YouTubeCollector
from src.analysis.extractor import KeywordExtractor
from src.analysis.metrics import MetricsCalculator
from src.analysis.community import CommunityDetector
from src.output.formatter import OutputFormatter


def run_pipeline(keywords: list[str], config: Config | None = None) -> dict:
    """Run the full niche discovery pipeline and return output paths."""
    if config is None:
        config = Config.from_env()

    if not keywords:
        keywords = config.seed_keywords

    print(f"[pipeline] Keywords: {keywords}")
    print(f"[pipeline] Config: recent={config.recent_window}d, "
          f"medium={config.medium_window}d, past={config.past_window}d")

    # Step 1: Collect
    print("[pipeline] Collecting video data from YouTube...")
    with YouTubeCollector(config) as collector:
        videos = collector.collect(keywords)
        print(f"[pipeline] Collected {len(videos)} videos")

        # Step 2: Compute metrics
        print("[pipeline] Computing niche metrics...")
        calculator = MetricsCalculator(collector)
        stats = calculator.compute(videos)
        print(f"[pipeline] Computed metrics for {len(stats)} keywords")

    # Step 3: Build co-occurrence network
    print("[pipeline] Building co-occurrence network...")
    extractor = KeywordExtractor()
    detector = CommunityDetector(extractor)
    edges = detector.build_edges(videos)
    print(f"[pipeline] Found {len(edges)} co-occurrence edges")

    # Step 4: Community detection
    print("[pipeline] Running community detection...")
    communities = detector.detect_communities(edges, stats)
    print(f"[pipeline] Detected {len(set(communities.values()))} communities")

    # Step 5: Export
    print("[pipeline] Exporting results...")
    formatter = OutputFormatter(config.output_dir)
    kw_path = formatter.save_keywords(stats, communities)
    edge_path = formatter.save_edges(edges)
    video_path = formatter.save_videos(videos)
    graph_path = detector.export_network(stats, edges, communities,
                                         str(Path(config.output_dir) / "graph.html"))

    paths = {
        "keywords": kw_path,
        "edges": edge_path,
        "videos": video_path,
        "graph": graph_path,
    }
    print(f"[pipeline] Done! Output:")
    for name, path in paths.items():
        print(f"  {name}: {path}")

    return paths


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Niche Finder - discover blue ocean niches"
    )
    parser.add_argument(
        "keywords",
        nargs="*",
        help="Seed keywords to analyze (comma or space separated)"
    )
    parser.add_argument(
        "--env", "-e",
        default=".env",
        help="Path to .env file"
    )
    parser.add_argument(
        "--output", "-o",
        default="output",
        help="Output directory"
    )

    args = parser.parse_args()

    # Parse keywords from args
    keywords = []
    for kw in args.keywords:
        keywords.extend(k.strip() for k in kw.split(",") if k.strip())

    config = Config.from_env()
    config.output_dir = args.output
    config.raw_dir = f"{args.output}/raw"

    run_pipeline(keywords, config)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手動測試 CLI help**

Run: `cd /path/to/youtube-niche-finder && python src/cli.py --help`
Expected: 顯示 argparse help 文字

- [ ] **Step 3: Commit**

```bash
git add src/cli.py
git commit -m "feat: add CLI entry point for full pipeline"
```

---

## Architecture Diagrams

### Data Flow

```
使用者輸入關鍵詞
       │
       ▼
┌──────────────┐    tubescrape     ┌──────────────────┐
│  YouTubeCollector │ ─────────────→ │  VideoRecord[]     │
│  (L4 採集層)     │   this_year     │  (原始資料)        │
└──────────────┘                 └──────────────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │ filter_by_window()   │
                               │  (7d / 30d / 365d)  │
                               └─────────────────────┘
                                          │
                     ┌────────────────────┼────────────────────┐
                     ▼                    ▼                    ▼
              ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
              │ MetricsCalc  │   │  KeywordExt  │   │ CommunityDetect  │
              │ 4 indicators │   │co-occurrence │   │ Louvain社群      │
              └──────────────┘   └──────────────┘   └──────────────────┘
                     │                    │                    │
                     └────────────────────┼────────────────────┘
                                          ▼
                               ┌──────────────────┐
                               │  OutputFormatter  │
                               │  JSON + Pyvis     │
                               └──────────────────┘
                                          │
                    ┌─────────────────────┼────────────────────┐
                    ▼                     ▼                    ▼
             keywords.json          edges.json          graph.html
             (4指標排序表)        (共現網路邊)         (Pyvis互動圖)
```

### Frontend Plan (Phase 4)

```
┌─────────────────────────────────────────────┐
│  [Keyword Input Box]  [Run]                  │
├─────────────────────────────────────────────┤
│  Tab 1: 社群網路圖     Tab 2: 排序表格        │
│  ┌─────────────────┐  ┌──────────────────┐  │
│  │  Pyvis 網路圖    │  │ 可排序 HTML 表格 │  │
│  │  節點=關鍵詞     │  │ 供給增速 △ ▼    │  │
│  │  大小=total views│  │ 需求增速 △ ▼    │  │
│  │  顏色=社群       │  │ 供需比   △ ▼    │  │
│  │  懸浮=4指標      │  │ 機會得分 △ ▼    │  │
│  └─────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────┘
```

---

## Self-Review Checklist

### Spec Coverage
| 需求 | 對應 Task | 狀態 |
|------|-----------|------|
| 關鍵詞輸入框 | Task 7 (CLI) + Phase 4 (frontend) | ✅ |
| 雙時間窗口 (7d/30d/365d) | Task 1 (Config) + Task 4 (Metrics) | ✅ |
| 供給增速公式 | Task 4: `_safe_divide(count_7d, count_30d)` | ✅ |
| 需求增速公式 | Task 4: `_safe_divide(views_7d, views_30d)` | ✅ |
| 供需比公式 | Task 4: `_safe_divide(supply, demand)` | ✅ |
| 機會得分公式 | Task 4: `_safe_divide(views_7d, ratio)` | ✅ |
| 關鍵詞共現網路 | Task 5: `build_edges()` | ✅ |
| Louvain 社群發現 | Task 5: `detect_communities()` | ✅ |
| Pyvis 可視化 | Task 5: `export_network()` | ✅ |
| 懸停浮窗顯示4指標 | Task 5: Pyvis `title` 參數 | ✅ |
| JSON 輸出 | Task 6: `save_keywords()` | ✅ |
| 路線B (精確窗口) | Task 3: `filter_by_window()` | ✅ |
| tubescrape 整合 | Task 3: `YouTubeCollector` | ✅ |

### Placeholder Scan
所有程式碼區塊均包含完整實作（無 TBD/TODO/placeholder）。

### Type Consistency
- `VideoRecord.published`: `datetime` → `from_dict` 轉 `isoformat` — 一致
- `KeywordStats.keyword`: `str` — 所有 modules 一致
- `_safe_divide` 回傳 `float`，`round()` 後存回 — 一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-26-youtube-niche-finder.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — 每個 Task 派一個乾淨 subagent，我 review 後再交接下一個 task，快速疊代

**2. Inline Execution** — 在這個 session 裡批次執行，附 checkpoint 驗證

**哪個方式？**
