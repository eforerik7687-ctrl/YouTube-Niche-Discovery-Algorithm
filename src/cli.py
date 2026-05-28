"""CLI entry point for YouTube Niche Finder pipeline."""

import argparse
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tubescrape import YouTube

from src.config import Config
from src.collector.collector import YouTubeCollector
from src.analysis.metrics import MetricsCalculator
from src.analysis.propagator import KeywordPropagator
from src.analysis.community import CommunityDetector
from src.output.formatter import OutputFormatter


def _build_channel_data(
    videos: List,
    channel_keywords: Dict[str, Dict[str, float]],
) -> Dict[str, Dict]:
    """Build channel_data dict for graph export from collected videos."""
    channel_views = {}
    for v in videos:
        ch = v.channel
        channel_views[ch] = channel_views.get(ch, 0) + v.view_count
    channel_data = {}
    for ch, kws in channel_keywords.items():
        real_views = channel_views.get(ch, 0)
        proxy_size = real_views or len(kws) * 10000
        channel_data[ch] = {
            "total_views": proxy_size,
            "video_count": len(kws),
            "opportunity_score": 0,
            "supply_growth": 0,
            "demand_growth": 0,
        }
    return channel_data


def _run_discovery(
    keywords: List[str],
    config: Config,
    yt,
    label: str,
    languages: List[str] = None,
    geos: List[str] = None,
) -> dict:
    """Run propagator discover → similarity → propagate → export graphs."""
    propagator = KeywordPropagator(config, yt)
    channel_keywords = propagator.discover(keywords, languages=languages, geos=geos)
    print(f"[{label}] Found {len(channel_keywords)} channels")

    if not channel_keywords:
        print(f"[{label}] No channels found, skipping.")
        return {}

    similarities = propagator.compute_similarity(channel_keywords, min_similarity=0.5)
    print(f"[{label}] Found {len(similarities)} channel similarity pairs")

    propagated = propagator.propagate(channel_keywords, similarities)
    keywords_found = set()
    for ch_kws in propagated.values():
        keywords_found.update(ch_kws.keys())
    print(f"[{label}] Discovered {len(keywords_found)} unique keywords via propagation")

    detector = CommunityDetector(propagator)
    G = detector.build_channel_graph(similarities)

    if G.number_of_nodes() == 0:
        return {}

    channel_data = _build_channel_data([], channel_keywords)

    graph_path = detector.export_network(
        G, channel_keywords, propagated,
        channel_data=channel_data,
        channel_urls=propagator.channel_urls,
        seed_keywords=keywords,
        output_path=str(Path(config.output_dir) / f"graph_{label}.html"),
    )
    all_pair_path = detector.export_all_pairs(
        channel_keywords, propagated,
        channel_urls=propagator.channel_urls,
        seed_keywords=keywords,
        output_path=str(Path(config.output_dir) / f"all_pairs_{label}.html"),
    )

    return {
        "graph": graph_path,
        "all_pairs": all_pair_path,
        "similarities": similarities,
        "propagated": propagated,
    }


def run_pipeline(keywords: List[str], config: Config | None = None) -> dict:
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

    # Step 3: Save YouTube search suggestions for reference (3 modes)
    print("[pipeline] Fetching YouTube search suggestions (3 modes)...")
    import json

    _GEO7 = ["US", "IN", "GB", "PH", "NG", "AU", "CA"]
    yt_suggestions = {}
    for seed in keywords:
        en_kws = KeywordPropagator.fetch_suggestions(seed, languages=["en"])
        lang_kws = KeywordPropagator.fetch_suggestions(seed, languages=KeywordPropagator._SUGGESTION_LANGS)
        geo_kws = KeywordPropagator.fetch_suggestions(seed, geos=_GEO7)
        yt_suggestions[seed] = {
            "english": en_kws,
            "7lang": lang_kws,
            "7geo": geo_kws,
        }
        print(f"  [suggestions] {seed}: {len(en_kws)}en / {len(lang_kws)}lang / {len(geo_kws)}geo")

    suggestion_path = Path(config.output_dir) / "yt_keywords.json"
    suggestion_path.write_text(
        json.dumps(yt_suggestions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Saved to {suggestion_path}")

    # Step 4: Collaborative filtering (3 modes: en, 7lang, 7geo)
    with YouTube() as yt:
        print()
        print("[pipeline] 1/3 — English-only...")
        en_results = _run_discovery(keywords, config, yt, "en", languages=["en"])

        print()
        print("[pipeline] 2/3 — 7-language...")
        ml_results = _run_discovery(keywords, config, yt, "7lang", languages=KeywordPropagator._SUGGESTION_LANGS)

        print()
        print("[pipeline] 3/3 — 7-geography...")
        geo_results = _run_discovery(keywords, config, yt, "7geo", geos=_GEO7)

    # Step 4b: Compute niche concepts for each mode
    from src.analysis.community import CommunityDetector
    niche_results = {}
    for name, result in [("en", en_results), ("7lang", ml_results), ("7geo", geo_results)]:
        if result and result.get("similarities"):
            detector = CommunityDetector(KeywordPropagator(config))
            G = detector.build_channel_graph(result["similarities"])
            if G.number_of_nodes() > 0:
                niches = detector.detect_niches(G)
                niche_conc = detector.compute_niche_concepts(niches, result["propagated"])
                # Channel concepts sorted by score descending
                ch_conc = {}
                for ch, concepts in result["propagated"].items():
                    sorted_concepts = sorted(concepts.items(), key=lambda x: -x[1])
                    ch_conc[ch] = [{"concept": c, "score": round(s, 4)} for c, s in sorted_concepts[:10]]
                niche_results[name] = {
                    "channel_concepts": ch_conc,
                    "niche_concepts": niche_conc,
                    "niche_count": len(niches),
                }
                paths[f"concepts_{name}"] = formatter.save_concepts(ch_conc, niche_conc, f"concepts_{name}.json")

    # Step 5: Export metrics
    formatter = OutputFormatter(config.output_dir)
    kw_path = formatter.save_keywords(stats, {})
    edge_path = formatter.save_edges([])
    video_path = formatter.save_videos(videos)

    paths = {
        "keywords": kw_path,
        "edges": edge_path,
        "videos": video_path,
    }
    for name, result in [("en", en_results), ("7lang", ml_results), ("7geo", geo_results)]:
        if result:
            paths[f"graph_{name}"] = result["graph"]
            paths[f"all_pairs_{name}"] = result["all_pairs"]
    paths["yt_keywords"] = str(suggestion_path)

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
