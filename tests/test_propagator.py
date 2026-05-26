from unittest.mock import MagicMock

import pytest

from src.analysis.propagator import KeywordPropagator
from src.config import Config


@pytest.fixture
def config():
    return Config(search_modifiers=["tutorial", "review"])


@pytest.fixture
def propagator(config):
    yt = MagicMock()
    return KeywordPropagator(config, yt)


class TestComputeSimilarity:
    def test_identical_channels(self, propagator):
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0, "python review": 1.0},
            "ChannelB": {"python tutorial": 1.0, "python review": 1.0},
        }
        sim = propagator.compute_similarity(channel_keywords)
        assert len(sim) == 1
        assert abs(sim[("ChannelA", "ChannelB")] - 1.0) < 0.001

    def test_orthogonal_channels(self, propagator):
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0},
            "ChannelB": {"javascript tutorial": 1.0},
        }
        sim = propagator.compute_similarity(channel_keywords)
        assert len(sim) == 0

    def test_partial_overlap(self, propagator):
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0, "python review": 1.0},
            "ChannelB": {"python tutorial": 1.0, "javascript review": 1.0},
        }
        sim = propagator.compute_similarity(channel_keywords)
        assert len(sim) == 1
        # cosine([1,1], [1,1]) would be 1.0 but here:
        # vec_a = [1, 1, 0] (python tutorial, python review, javascript review)
        # vec_b = [1, 0, 1]
        # dot = 1, mag_a = sqrt(2), mag_b = sqrt(2) => 0.5
        assert abs(sim[("ChannelA", "ChannelB")] - 0.5) < 0.001

    def test_three_channels(self, propagator):
        channel_keywords = {
            "ChA": {"kw1": 1.0, "kw2": 1.0},
            "ChB": {"kw1": 1.0, "kw3": 1.0},
            "ChC": {"kw4": 1.0, "kw5": 1.0},
        }
        sim = propagator.compute_similarity(channel_keywords)
        assert ("ChA", "ChB") in sim
        assert ("ChA", "ChC") not in sim
        assert ("ChB", "ChC") not in sim


class TestPropagate:
    def test_propagates_new_keywords(self, propagator):
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0},
            "ChannelB": {"javascript tutorial": 1.0},
        }
        sim = {("ChannelA", "ChannelB"): 0.5}
        result = propagator.propagate(channel_keywords, sim)
        # ChannelB gets "python tutorial" with score 0.5
        assert "python tutorial" in result["ChannelB"]
        assert abs(result["ChannelB"]["python tutorial"] - 0.5) < 0.001
        # ChannelA gets "javascript tutorial" with score 0.5
        assert "javascript tutorial" in result["ChannelA"]
        assert abs(result["ChannelA"]["javascript tutorial"] - 0.5) < 0.001

    def test_preserves_own_keywords(self, propagator):
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0, "python review": 1.0},
        }
        result = propagator.propagate(channel_keywords, {})
        assert result["ChannelA"]["python tutorial"] == 1.0
        assert result["ChannelA"]["python review"] == 1.0

    def test_no_similarity_no_propagation(self, propagator):
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0},
            "ChannelB": {"javascript tutorial": 1.0},
        }
        result = propagator.propagate(channel_keywords, {})
        assert "python tutorial" not in result["ChannelB"]
        assert "javascript tutorial" not in result["ChannelA"]

    def test_does_not_overwrite_existing(self, propagator):
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0},
            "ChannelB": {"python tutorial": 1.0, "javascript tutorial": 1.0},
        }
        sim = {("ChannelA", "ChannelB"): 0.8}
        result = propagator.propagate(channel_keywords, sim)
        # ChannelA should get "javascript tutorial" (new), but its own
        # "python tutorial" should remain at 1.0
        assert result["ChannelA"]["python tutorial"] == 1.0
        assert "javascript tutorial" in result["ChannelA"]
        # ChannelB's values remain unchanged (already has python tutorial)
        assert result["ChannelB"]["python tutorial"] == 1.0


class TestRankKeywords:
    def test_returns_top_n(self, propagator):
        propagated = {
            "ChannelA": {
                "python": 10.0, "tutorial": 5.0, "beginner": 2.0, "advanced": 1.0,
            },
        }
        ranked = propagator.rank_keywords(propagated, "ChannelA", top_n=2)
        assert len(ranked) == 2
        assert ranked[0] == ("python", 10.0)
        assert ranked[1] == ("tutorial", 5.0)

    def test_unknown_channel(self, propagator):
        ranked = propagator.rank_keywords({}, "Unknown", top_n=5)
        assert ranked == []

    def test_returns_all_when_less_than_top_n(self, propagator):
        propagated = {"Ch": {"kw1": 1.0, "kw2": 2.0}}
        ranked = propagator.rank_keywords(propagated, "Ch", top_n=10)
        assert len(ranked) == 2
