import json
import random
import re
import time
from typing import Dict, List, Optional, Tuple

import httpx

from src.config import Config


class KeywordPropagator:
    """Collaborative filtering keyword discovery via channel-neighbor propagation.

    Core concept:
    - A channel's "keywords" = search terms that return this channel in results
    - Keywords are discovered naturally via YouTube Search Suggestions API,
      NOT via hardcoded human-picked modifiers
    - Two channels are "neighbors" if they share keywords (appear in same searches)
    - Keywords propagate from neighbor to neighbor weighted by channel similarity
    """

    # Default languages (used when languages= is not passed to discover)
    _SUGGESTION_LANGS = ["en", "hi", "es", "pt", "ar", "ru", "ko"]
    # Default geographies (used when geos= is not passed)
    _SUGGESTION_GEOS = ["US", "IN", "GB", "PH", "NG", "AU", "CA"]

    @staticmethod
    def _parse_view_count(value) -> int:
        """Parse YouTube view count string like '3,791,034 views' or None."""
        if value is None:
            return 0
        text = str(value).lower().replace(",", "")
        match = re.search(r"([\d.]+)\s*([kmb]?)", text)
        if not match:
            return 0
        num = float(match.group(1))
        suffix = match.group(2)
        multipliers = {"k": 1000, "m": 1000000, "b": 1000000000}
        return int(num * multipliers.get(suffix, 1))

    def __init__(self, config: Config, yt=None):
        self.config = config
        self.yt = yt
        self.channel_urls: Dict[str, str] = {}
        self.channel_stats: Dict[str, Dict] = {}  # {channel: total_views, video_count}

    @staticmethod
    def _build_hl_gl_pairs(
        languages: Optional[List[str]] = None,
        geos: Optional[List[str]] = None,
    ) -> List[Tuple[str, str]]:
        """Build (hl, gl) parameter pairs for the suggestions API.

        - languages + no geo: one pair per language, gl=US
        - geos + no language: one pair per geo, hl=en
        - both: cross product (language × geo)
        - neither: defaults to [("en", "US")]
        """
        if languages and geos:
            return [(hl, gl) for hl in languages for gl in geos]
        if languages:
            return [(hl, "US") for hl in languages]
        if geos:
            return [("en", gl) for gl in geos]
        return [("en", "US")]

    @staticmethod
    def fetch_suggestions(
        keyword: str,
        languages: Optional[List[str]] = None,
        geos: Optional[List[str]] = None,
    ) -> List[str]:
        """Fetch YouTube search suggestions using hl and gl parameters."""
        pairs = KeywordPropagator._build_hl_gl_pairs(languages, geos)
        all_suggestions: set = set()
        for hl, gl in pairs:
            try:
                r = httpx.get(
                    "http://suggestqueries.google.com/complete/search",
                    params={"client": "youtube", "ds": "yt", "q": keyword, "hl": hl, "gl": gl},
                    timeout=5,
                )
                data = r.text
                m = re.search(r"\[.*\]", data)
                parsed = json.loads(m.group())
                for item in parsed[1]:
                    all_suggestions.add(item[0])
            except Exception:
                continue
            time.sleep(random.uniform(0.05, 0.2))

        if not all_suggestions:
            return [keyword]
        return list(all_suggestions)

    def discover(
        self,
        seed_keywords: List[str],
        languages: Optional[List[str]] = None,
        geos: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, float]]:
        """Discover channels and their keywords using YouTube search suggestions.

        For each seed keyword:
          1. Fetch YouTube search suggestions using hl and gl parameters
          2. Search each suggestion on YouTube
          3. Record which channels appear in results for each suggestion

        Args:
            seed_keywords: List of seed keywords to discover from.
            languages: Language (hl) codes. With gl=US when geos is None.
            geos: Geography (gl) codes. With hl=en when languages is None.
                  If both provided, uses cross product (each language × each geo).

        Returns: {channel_name: {keyword: weight}}
        Populates self.channel_urls with {channel_name: https://youtube.com/channel/UC...}
        """
        if self.yt is None:
            raise RuntimeError(
                "YouTube client is required for discovery. "
                "Pass a YouTube instance to KeywordPropagator."
            )

        channel_keywords: Dict[str, Dict[str, float]] = {}

        # Determine mode for display label
        if geos and not languages:
            label = f"{len(geos)}geo"
        elif languages == ["en"] and not geos:
            label = "en"
        elif languages:
            label = f"{len(languages)}lang"
        else:
            label = "default"

        for seed in seed_keywords:
            suggestions = KeywordPropagator.fetch_suggestions(seed, languages, geos)
            print(f"  [{label}] {seed}: {len(suggestions)} related keywords")

            for suggestion in suggestions:
                # Anti-ban: random delay before each search (looks like human behavior)
                delay = random.uniform(self.config.delay_min, self.config.delay_max)
                time.sleep(delay)

                results = self.yt.search(
                    suggestion,
                    max_results=self.config.max_results_per_keyword,
                    sort_by=self.config.sort_by,
                    type="video",
                )
                for video in results.videos:
                    channel = getattr(video, "channel", "") or ""
                    if not channel:
                        continue
                    if channel not in channel_keywords:
                        channel_keywords[channel] = {}
                    # Capture channel URL from YouTube API
                    if channel not in self.channel_urls:
                        cid = getattr(video, "channel_id", "") or ""
                        if cid:
                            self.channel_urls[channel] = f"https://www.youtube.com/channel/{cid}"
                    # Accumulate channel stats from discovered videos
                    if channel not in self.channel_stats:
                        self.channel_stats[channel] = {"total_views": 0, "video_count": 0}
                    view_count = getattr(video, "view_count", None)
                    if view_count is not None:
                        try:
                            self.channel_stats[channel]["total_views"] += KeywordPropagator._parse_view_count(view_count)
                        except (ValueError, TypeError):
                            pass
                    self.channel_stats[channel]["video_count"] += 1
                    # The suggestion itself is the keyword (YouTube's judgment)
                    channel_keywords[channel][suggestion] = 1.0

        return channel_keywords

    def compute_similarity(
        self,
        channel_keywords: Dict[str, Dict[str, float]],
        min_similarity: float = 0.0,
    ) -> Dict[Tuple[str, str], float]:
        """Phase 2: Cosine similarity between channel keyword vectors.

        Args:
            channel_keywords: {channel: {keyword: weight}}
            min_similarity: Only return pairs with similarity > this threshold.
                            Default 0.0 returns all positive similarities.
                            Use 0.5 to filter out weakly related channels.

        Returns: {(channel_a, channel_b): similarity}
        """
        channels = list(channel_keywords.keys())
        all_keywords = sorted({
            kw for kw_dict in channel_keywords.values()
            for kw in kw_dict
        })

        # Build vectors for each channel
        vectors: Dict[str, List[float]] = {}
        for ch in channels:
            vec = [channel_keywords[ch].get(kw, 0.0) for kw in all_keywords]
            vectors[ch] = vec

        similarities: Dict[Tuple[str, str], float] = {}
        for i in range(len(channels)):
            for j in range(i + 1, len(channels)):
                ch_a, ch_b = channels[i], channels[j]
                sim = self._cosine(vectors[ch_a], vectors[ch_b])
                if sim > min_similarity:
                    similarities[(ch_a, ch_b)] = sim

        return similarities

    def propagate(
        self,
        channel_keywords: Dict[str, Dict[str, float]],
        similarities: Dict[Tuple[str, str], float],
    ) -> Dict[str, Dict[str, float]]:
        """Phase 3: Propagate keywords from neighbors weighted by similarity.

        New keyword score = sum of (neighbor_similarity x neighbor_keyword_weight)
        Only propagates keywords the channel does not already have.

        Returns: {channel: {keyword: final_score}}
        """
        propagated: Dict[str, Dict[str, float]] = {}
        for ch in channel_keywords:
            propagated[ch] = dict(channel_keywords[ch])

        for (ch_a, ch_b), sim in similarities.items():
            # Propagate from ch_a to ch_b
            for kw, weight in channel_keywords[ch_a].items():
                if kw not in channel_keywords[ch_b]:
                    propagated[ch_b][kw] = (
                        propagated[ch_b].get(kw, 0) + sim * weight
                    )
            # Propagate from ch_b to ch_a
            for kw, weight in channel_keywords[ch_b].items():
                if kw not in channel_keywords[ch_a]:
                    propagated[ch_a][kw] = (
                        propagated[ch_a].get(kw, 0) + sim * weight
                    )

        return propagated

    def rank_keywords(
        self,
        propagated: Dict[str, Dict[str, float]],
        channel: str,
        top_n: int = 50,
    ) -> List[Tuple[str, float]]:
        """Return top N (keyword, score) pairs for a channel."""
        if channel not in propagated:
            return []
        sorted_kws = sorted(
            propagated[channel].items(), key=lambda x: x[1], reverse=True
        )
        return sorted_kws[:top_n]

    @staticmethod
    def _cosine(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = sum(a * a for a in vec_a) ** 0.5
        mag_b = sum(b * b for b in vec_b) ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
