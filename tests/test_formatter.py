import json
from datetime import datetime

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
                published=datetime(2026, 5, 20),
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
