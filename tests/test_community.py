from unittest.mock import MagicMock

import pytest

from src.analysis.community import CommunityDetector
from src.analysis.propagator import KeywordPropagator
from src.config import Config


@pytest.fixture
def propagator():
    config = Config(search_modifiers=["tutorial", "review"])
    return KeywordPropagator(config, MagicMock())


@pytest.fixture
def detector(propagator):
    return CommunityDetector(propagator)


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


class TestDetectCommunities:
    def test_basic_clustering(self, detector):
        G = detector.build_channel_graph({
            ("ChA", "ChB"): 0.9,
            ("ChB", "ChC"): 0.8,
            ("ChD", "ChE"): 0.7,
        })
        communities = detector.detect_communities(G)
        assert len(communities) == 5
        # ChA, ChB, ChC should be in one community; ChD, ChE in another
        assert communities["ChA"] == communities["ChB"]
        assert communities["ChD"] == communities["ChE"]

    def test_no_edges(self, detector):
        G = nx_module = pytest.importorskip("networkx").Graph()
        G.add_node("solo")
        communities = detector.detect_communities(G)
        assert communities == {"solo": 0}


class TestExportNetwork:
    def test_returns_path(self, detector, tmp_path):
        G = detector.build_channel_graph({
            ("ChannelA", "ChannelB"): 0.5,
        })
        communities = {"ChannelA": 0, "ChannelB": 1}
        channel_keywords = {
            "ChannelA": {"python tutorial": 1.0},
            "ChannelB": {"javascript tutorial": 1.0},
        }
        propagated = dict(channel_keywords)

        output = tmp_path / "graph.html"
        path = detector.export_network(
            G, communities, channel_keywords, propagated,
            output_path=str(output),
        )
        assert path == str(output)
        assert output.exists()
        content = output.read_text()
        assert "ChannelA" in content
        assert "network" in content.lower()
