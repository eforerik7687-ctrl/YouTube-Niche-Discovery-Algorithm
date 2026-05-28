import json
from datetime import datetime
from pathlib import Path

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


class TestSaveConcepts:
    def test_saves_json_with_correct_structure(self, tmp_path):
        from src.output.formatter import OutputFormatter
        formatter = OutputFormatter(str(tmp_path))
        ch_conc = {"ChannelA": [{"concept": "python", "score": 1.5}]}
        niche_conc = {0: [{"concept": "python", "coverage": 1.0, "avg_score": 1.5}]}
        path = formatter.save_concepts(ch_conc, niche_conc)
        import json
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert "channel_concepts" in data
        assert "niche_concepts" in data
        assert data["channel_concepts"]["ChannelA"][0]["concept"] == "python"

    def test_saves_empty_concepts(self, tmp_path):
        from src.output.formatter import OutputFormatter
        formatter = OutputFormatter(str(tmp_path))
        path = formatter.save_concepts({}, {})
        import json
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["channel_concepts"] == {}
        assert data["niche_concepts"] == {}
