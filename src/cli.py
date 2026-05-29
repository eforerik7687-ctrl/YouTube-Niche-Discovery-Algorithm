"""CLI entry point for YouTube Niche Finder pipeline."""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tubescrape import YouTube

from src.config import Config
from src.collector.collector import YouTubeCollector
from src.analysis.metrics import MetricsCalculator
from src.analysis.propagator import KeywordPropagator
from src.analysis.community import CommunityDetector
from src.output.formatter import OutputFormatter

_ALL_LANGS = ["en", "hi", "es", "pt", "ar", "ru", "ko"]
_ALL_GEOS = ["US", "IN", "GB", "PH", "NG", "AU", "CA"]


def _build_channel_data(
    videos: List,
    channel_keywords: Dict[str, Dict[str, float]],
    channel_stats: Optional[Dict[str, Dict]] = None,
) -> Dict[str, Dict]:
    """Build channel_data dict for graph export from videos + discovery stats.

    Merges seed (Step 1) and discovery (Step 4) stats, taking the max
    of each so that seed's 1-2 videos don't override discovery's 20+.
    """
    # Seed stats (Step 1)
    seed_views = {}
    seed_videos = {}
    for v in videos:
        ch = v.channel
        seed_views[ch] = seed_views.get(ch, 0) + v.view_count
        seed_videos[ch] = seed_videos.get(ch, 0) + 1

    if channel_stats is None:
        channel_stats = {}

    channel_data = {}
    for ch, kws in channel_keywords.items():
        # Merge seed + discovery, take max of each
        merge_views = seed_views.get(ch, 0)
        merge_videos = seed_videos.get(ch, 0)
        if ch in channel_stats:
            merge_views = max(merge_views, channel_stats[ch].get("total_views", 0))
            merge_videos = max(merge_videos, channel_stats[ch].get("video_count", 0))

        # Last resort if both are 0
        if merge_views == 0 and merge_videos == 0:
            merge_views = len(kws) * 10000
            merge_videos = len(kws)

        channel_data[ch] = {
            "total_views": merge_views,
            "video_count": merge_videos,
            "opportunity_score": 0,
            "supply_growth": 0,
            "demand_growth": 0,
        }
    return channel_data


def run_pipeline(keywords: List[str], config: Config | None = None) -> dict:
    """Run the YouTube Niche Finder pipeline with 7+7 merged discovery.

    Pipeline flow:
      1. Collect videos for seed keywords
      2. Compute niche metrics (supply/demand/opportunity)
      3. Fetch YouTube Search Suggestions (7 languages + 7 geos)
      4. Discover channels via merged 7+7 search suggestions
      5. Cosine similarity + keyword propagation
      6. Louvain community detection + niche concept aggregation
      7. Export single graph, all-pairs matrix, concepts, word cloud
    """
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

    if not videos:
        print("[pipeline] No videos collected, skipping analysis.")
        return {}

    # Step 2: Compute metrics per seed keyword
    print("[pipeline] Computing niche metrics...")
    calculator = MetricsCalculator(collector)
    stats = calculator.compute(videos)
    print(f"[pipeline] Computed metrics for {len(stats)} seed keywords")

    # Step 3: Fetch suggestions (7 languages + 7 geos)
    print("[pipeline] Fetching YouTube search suggestions (7+7)...")
    yt_suggestions = {}
    for seed in keywords:
        lang_kws = KeywordPropagator.fetch_suggestions(seed, languages=_ALL_LANGS)
        geo_kws = KeywordPropagator.fetch_suggestions(seed, geos=_ALL_GEOS)
        yt_suggestions[seed] = {
            "7lang": lang_kws,
            "7geo": geo_kws,
        }
        total = len(lang_kws) + len(geo_kws)
        print(f"  [suggestions] {seed}: {len(lang_kws)}lang + {len(geo_kws)}geo = {total}")

    suggestion_path = Path(config.output_dir) / "yt_keywords.json"
    suggestion_path.write_text(
        json.dumps(yt_suggestions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Saved to {suggestion_path}")

    # Step 4: 7+7 merged discovery — two passes, merged channel_keywords
    with YouTube() as yt:
        propagator = KeywordPropagator(config, yt)
        print()
        print("[pipeline] 7+7 — Discovering (7 languages × US)...")
        kw_lang = propagator.discover(keywords, languages=_ALL_LANGS)
        print(f"  [7+7] Language pass: {len(kw_lang)} channels")

        print()
        print("[pipeline] 7+7 — Discovering (en × 7 geos)...")
        kw_geo = propagator.discover(keywords, geos=_ALL_GEOS)
        print(f"  [7+7] Geo pass: {len(kw_geo)} channels")

        # Merge: union keywords per channel
        channel_keywords: Dict[str, Dict[str, float]] = dict(kw_lang)
        for ch, kws in kw_geo.items():
            existing = channel_keywords.get(ch, {})
            channel_keywords[ch] = {**existing, **kws}

    total_channels = len(channel_keywords)
    print(f"[pipeline] 7+7 — Total unique channels: {total_channels}")

    if not channel_keywords:
        print("[pipeline] No channels found, skipping.")
        return {}

    # Step 5: Similarity + Propagation (keyword induction for niche concept)
    print("[pipeline] Computing cosine similarity...")
    similarities = propagator.compute_similarity(channel_keywords, min_similarity=0.5)
    print(f"[pipeline] Found {len(similarities)} channel similarity pairs")

    propagated = propagator.propagate(channel_keywords, similarities)

    # Step 6: Community detection + cluster keywords
    detector = CommunityDetector(propagator)
    G = detector.build_channel_graph(similarities)

    formatter = OutputFormatter(config.output_dir)
    paths: Dict[str, str] = {}

    # Step 7: Export cluster keyword report + raw videos
    enriched_clusters = {}

    if G.number_of_nodes() > 0:
        channel_data = _build_channel_data(videos, channel_keywords, propagator.channel_stats)

        # Cluster keywords (Louvain communities → keyword aggregation)
        clusters = detector.detect_niches(G)
        # Renumber niches by size descending (biggest = 0)
        sorted_nids = sorted(clusters.keys(), key=lambda nid: -len(clusters[nid]))
        remap = {old: new for new, old in enumerate(sorted_nids)}
        clusters = {remap[old]: members for old, members in clusters.items()}
        cluster_kws = detector.compute_niche_concepts(clusters, propagated)

        # Export graph with niche-based colors
        graph_path = detector.export_network(
            G, channel_keywords,
            channel_data=channel_data,
            channel_urls=propagator.channel_urls,
            seed_keywords=keywords,
            niches=clusters,
            output_path=str(Path(config.output_dir) / "graph_7plus7.html"),
        )
        paths["graph"] = graph_path

        # Word cloud per niche
        wordcloud_path = detector.export_niche_wordcloud(
            clusters, cluster_kws,
            output_path=str(Path(config.output_dir) / "niche_wordcloud.html"),
        )
        paths["wordcloud"] = wordcloud_path

        # Populate enriched_clusters
        for nid, keywords in cluster_kws.items():
            enriched_clusters[str(nid)] = {
                "channel_count": len(clusters[nid]),
                "keywords": keywords,
            }
    else:
        clusters = {}
        cluster_kws = {}
    concept_report = {
        "cluster_keywords": enriched_clusters,
    }
    report_path = Path(config.output_dir) / "cluster_report.json"
    report_path.write_text(
        json.dumps(concept_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths["cluster_report"] = str(report_path)

    video_path = formatter.save_videos(videos)
    paths.update({
        "videos": video_path,
        "yt_keywords": str(suggestion_path),
    })

    print(f"[pipeline] Done! Output:")
    for name, path in paths.items():
        if path:
            print(f"  {name}: {path}")

    return paths


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Niche Finder - discover blue ocean niches"
    )
    parser.add_argument("keywords", nargs="*", help="Seed keywords to analyze")
    parser.add_argument("--env", "-e", default=".env", help="Path to .env file")
    parser.add_argument("--output", "-o", default="output", help="Output directory")

    args = parser.parse_args()
    keywords = []
    for kw in args.keywords:
        keywords.extend(k.strip() for k in kw.split(",") if k.strip())

    config = Config.from_env()
    config.output_dir = args.output
    config.raw_dir = f"{args.output}/raw"
    run_pipeline(keywords, config)


if __name__ == "__main__":
    main()
