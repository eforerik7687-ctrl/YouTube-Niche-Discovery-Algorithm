from unittest.mock import MagicMock

import pytest

from src.analysis.community import CommunityDetector
from src.analysis.propagator import KeywordPropagator
from src.config import Config


@pytest.fixture
def propagator():
    config = Config()
    return KeywordPropagator(config, MagicMock())


@pytest.fixture
def detector(propagator):
    return CommunityDetector(propagator)


@pytest.fixture
def sample_similarities():
    return {
        ("ChannelA", "ChannelB"): 0.8,
        ("ChannelB", "ChannelC"): 0.7,
        ("ChannelC", "ChannelA"): 0.6,
        ("ChannelD", "ChannelE"): 0.9,
    }


class TestBuildChannelGraph:
    def test_builds_from_similarities(self, detector):
        similarities = {
            ("ChannelA", "ChannelB"): 0.5,
            ("ChannelB", "ChannelC"): 0.3,
        }
        G = detector.build_channel_graph(similarities)
        assert G.number_of_nodes() == 3
        assert G.number_of_edges() == 2
        assert G.has_edge("ChannelA", "ChannelB")
        assert abs(G["ChannelA"]["ChannelB"]["weight"] - 0.5) < 0.001

    def test_empty_similarities(self, detector):
        G = detector.build_channel_graph({})
        assert G.number_of_nodes() == 0
        assert G.number_of_edges() == 0


class TestExportNetwork:
    def test_returns_path(self, detector, tmp_path):
        G = detector.build_channel_graph({
            ("ChannelA", "ChannelB"): 0.5,
        })
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0},
            "ChannelB": {"javascript tutorial": 1.0},
        }
        propagated = dict(channel_keywords)

        output = tmp_path / "graph.html"
        path = detector.export_network(
            G, channel_keywords, propagated,
            output_path=str(output),
        )
        assert path == str(output)
        assert output.exists()
        content = output.read_text()
        assert "ChannelA" in content
        assert "network" in content.lower()


class TestDetectNiches:
    def test_detect_niches_returns_communities(self, detector, sample_similarities):
        """Louvain should partition graph into communities (niches)."""
        G = detector.build_channel_graph(sample_similarities)
        niches = detector.detect_niches(G)
        assert isinstance(niches, dict)
        assert all(isinstance(k, int) for k in niches.keys())
        assert all(isinstance(v, list) for v in niches.values())
        # Verify all channels are covered
        all_channels = set()
        for ch_list in niches.values():
            all_channels.update(ch_list)
        assert len(all_channels) == 5  # ChannelA-E
        # Verify A-B-C form one community (they're a triangle)
        for nid, members in niches.items():
            members_set = set(members)
            if "ChannelA" in members_set:
                assert "ChannelB" in members_set
                assert "ChannelC" in members_set
            if "ChannelD" in members_set:
                assert "ChannelE" in members_set

    def test_detect_niches_empty_graph(self, detector):
        """Empty graph should return empty dict."""
        from networkx import Graph
        G = Graph()
        niches = detector.detect_niches(G)
        assert niches == {}


class TestComputeNicheConcepts:
    def test_compute_niche_concepts_aggregates_correctly(self, detector):
        """Niche concepts should aggregate channel concepts with coverage."""
        propagated = {
            "ChannelA": {"python": 1.5, "tutorial": 0.8},
            "ChannelB": {"python": 1.2, "coding": 0.9},
            "ChannelC": {"python": 0.6, "tutorial": 0.3},
        }
        niches = {0: ["ChannelA", "ChannelB", "ChannelC"]}
        result = detector.compute_niche_concepts(niches, propagated)
        assert 0 in result
        concepts = result[0]
        py = [c for c in concepts if c["concept"] == "python"][0]
        assert py["coverage"] == 1.0
        assert "avg_score" not in py

    def test_compute_niche_concepts_empty_niche(self, detector):
        """Empty niche should return empty list."""
        result = detector.compute_niche_concepts({}, {})
        assert result == {}

    def test_compute_niche_concepts_top_n_limits(self, detector):
        """top_n parameter should limit number of concepts returned."""
        propagated = {f"Ch{i}": {f"c{j}": 1.0 for j in range(10)} for i in range(5)}
        niches = {0: list(propagated.keys())}
        result = detector.compute_niche_concepts(niches, propagated, top_n=3)
        assert len(result[0]) <= 3
