from typing import Dict, List, Tuple

from src.config import Config


class KeywordPropagator:
    """Collaborative filtering keyword discovery via channel-neighbor propagation.

    Core concept:
    - A channel's "keywords" = search terms that return this channel in results
    - Two channels are "neighbors" if they share keywords (appear in same searches)
    - Keywords propagate from neighbor to neighbor weighted by channel similarity
    """

    def __init__(self, config: Config, yt=None):
        self.config = config
        self.yt = yt

    def discover(self, seed_keywords: List[str]) -> Dict[str, Dict[str, float]]:
        """Phase 1: Search each seed keyword x each modifier.

        Returns: {channel_name: {keyword: weight}}
        weight = 1.0 for appearing in any search for that keyword
        """
        if self.yt is None:
            raise RuntimeError(
                "YouTube client is required for discovery. "
                "Pass a YouTube instance to KeywordPropagator."
            )

        channel_keywords: Dict[str, Dict[str, float]] = {}

        for seed in seed_keywords:
            for modifier in self.config.search_modifiers:
                query = f"{seed} {modifier}"
                results = self.yt.search(
                    query,
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
                    # The search query itself is the keyword for this channel
                    channel_keywords[channel][query] = 1.0

        return channel_keywords

    def compute_similarity(
        self, channel_keywords: Dict[str, Dict[str, float]]
    ) -> Dict[Tuple[str, str], float]:
        """Phase 2: Cosine similarity between channel keyword vectors.

        Returns: {(channel_a, channel_b): similarity}
        Only pairs with similarity > 0 are included.
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
                if sim > 0:
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
