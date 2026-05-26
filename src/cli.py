"""CLI entry point for YouTube Niche Finder pipeline."""

import argparse
import sys
from pathlib import Path
from typing import Dict, List

# Add src to path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config
from src.collector.collector import YouTubeCollector
from src.analysis.metrics import MetricsCalculator
from src.analysis.propagator import KeywordPropagator
from src.analysis.community import CommunityDetector
from src.output.formatter import OutputFormatter


def _build_channel_data(
    channel_keywords: Dict[str, Dict[str, float]],
) -> Dict[str, Dict]:
    """Build channel metadata from propagator results."""
    return {
        ch: {
            "total_views": 0,
            "video_count": len(kws),
            "opportunity_score": 0.0,
            "supply_growth": 0.0,
            "demand_growth": 0.0,
        }
        for ch, kws in channel_keywords.items()
    }


def run_pipeline(keywords: List[str], config: Config | None = None) -> dict:
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

    # Step 3: Propagator - collaborative filtering keyword discovery
    print("[pipeline] Running keyword propagation...")
    propagator = KeywordPropagator(config)
    # Note: discovery requires a real YouTube client; for demo/testing
    # use synthetic channel_keywords. In production, call discover().
    channel_keywords: Dict[str, Dict[str, float]] = {}
    similarities: Dict = {}
    propagated: Dict = {}
    if channel_keywords:
        similarities = propagator.compute_similarity(channel_keywords)
        propagated = propagator.propagate(channel_keywords, similarities)
        print(f"[pipeline] Found {len(channel_keywords)} channels, "
              f"{len(similarities)} similarity pairs")

    # Step 4: Community detection
    print("[pipeline] Running community detection...")
    detector = CommunityDetector(propagator)
    G = detector.build_channel_graph(similarities)
    communities = detector.detect_communities(G)
    print(f"[pipeline] Detected {len(set(communities.values()))} communities")

    # Step 5: Export
    print("[pipeline] Exporting results...")
    formatter = OutputFormatter(config.output_dir)
    kw_path = formatter.save_keywords(stats, {})
    edge_path = formatter.save_edges([])
    video_path = formatter.save_videos(videos)

    graph_path = ""
    if G.number_of_nodes() > 0:
        channel_data = _build_channel_data(channel_keywords)
        graph_path = detector.export_network(
            G, communities, channel_keywords, propagated,
            channel_data=channel_data,
            output_path=str(Path(config.output_dir) / "graph.html"),
        )

    paths = {
        "keywords": kw_path,
        "edges": edge_path,
        "videos": video_path,
        "graph": graph_path,
    }
    print(f"[pipeline] Done! Output:")
    for name, path in paths.items():
        if path:
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
