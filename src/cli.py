"""CLI entry point for YouTube Niche Finder pipeline."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src._patched import patch_tubescrape, PatchedYouTube
from src._token import get_po_token, inject_po_token
from src.config import Config
from src.analysis.propagator import KeywordPropagator
from src.analysis.community import CommunityDetector

_ALL_LANGS = ["en", "hi", "es", "pt", "ar", "ru", "ko"]
_ALL_GEOS = ["US", "IN", "GB", "PH", "NG", "AU", "CA"]


def _build_channel_data(
    channel_keywords: Dict[str, Dict[str, float]],
    channel_stats: Optional[Dict[str, Dict]] = None,
) -> Dict[str, Dict]:
    """Build channel_data dict for graph export from discovery stats."""
    if channel_stats is None:
        channel_stats = {}

    channel_data = {}
    for ch, kws in channel_keywords.items():
        stats = channel_stats.get(ch, {})
        merge_views = stats.get("total_views", 0)
        merge_videos = stats.get("video_count", 0)

        # Last resort if both are 0
        if merge_views == 0 and merge_videos == 0:
            merge_views = len(kws) * 10000
            merge_videos = len(kws)

        channel_data[ch] = {
            "total_views": merge_views,
            "video_count": merge_videos,
            "views_7d": stats.get("views_7d", 0),
            "views_30d": stats.get("views_30d", 0),
            "opportunity_score": 0,
            "supply_growth": 0,
            "demand_growth": 0,
        }
    return channel_data


async def run_pipeline(keywords: List[str], config: Config | None = None) -> dict:
    """Run the YouTube Niche Finder pipeline.

    Pipeline flow:
      1. Expansion: fetch YouTube Search Suggestions (7 languages + 7 geos)
      2. Discover: find channels via merged 7+7 search suggestions
         (shorts_mode: append ' short', filter by views>=100k, duration<=60s)
      3. Cosine similarity + keyword propagation
      4. Louvain community detection + niche concept aggregation
      5. Export: graph, word cloud, cluster report, channel_stats
    """
    if config is None:
        config = Config.from_env()
    if not keywords:
        keywords = config.seed_keywords

    print(f"[pipeline] Keywords: {keywords}")

    # Apply anti-ban patch to tubescrape (UA rotation, browser headers, etc.)
    patch_tubescrape()
    print("[pipeline] Anti-ban patch applied (UA rotation, browser headers, proxy rotation)")

    # Extract and inject PO Token via Playwright (legitimate browser fingerprint)
    if config.po_token_enabled:
        print("[pipeline] Extracting PO Token via Playwright...")
        proxy_for_browser = config.proxy_list[0] if config.proxy_list else None
        token = get_po_token(proxy=proxy_for_browser, timeout=config.po_token_timeout)
        if token:
            inject_po_token(token)
            print(f"[pipeline] PO Token injected ({token[:20]}...)")
        else:
            print("[pipeline] PO Token not available, continuing without it")

    # Step 1: Fetch suggestions (7 languages + 7 geos)
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

    # Step 2: 7+7 merged discovery — two async passes, merged channel_keywords
    async with PatchedYouTube(config) as yt:
        propagator = KeywordPropagator(config, yt)
        print()
        print("[pipeline] 7+7 — Discovering (7 languages × US)...")
        kw_lang = await propagator.discover_async(keywords, languages=_ALL_LANGS)
        print(f"  [7+7] Language pass: {len(kw_lang)} channels")

        print()
        print("[pipeline] 7+7 — Discovering (en × 7 geos)...")
        kw_geo = await propagator.discover_async(keywords, geos=_ALL_GEOS)
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

    if not channel_keywords:
        print("[pipeline] No channels found, skipping.")
        return {}

    # Step 3: Similarity + Propagation (keyword induction for niche concept)
    print("[pipeline] Computing cosine similarity...")
    similarities = propagator.compute_similarity(channel_keywords, min_similarity=0.5)
    print(f"[pipeline] Found {len(similarities)} channel similarity pairs")

    propagated = propagator.propagate(channel_keywords, similarities)

    # Step 4: Community detection + cluster keywords
    detector = CommunityDetector(propagator)
    G = detector.build_channel_graph(similarities)

    paths: Dict[str, str] = {}

    # Step 5: Export
    enriched_clusters = {}

    if G.number_of_nodes() > 0:
        channel_data = _build_channel_data(channel_keywords, propagator.channel_stats)

        # Cluster keywords (Louvain communities → keyword aggregation)
        clusters = detector.detect_niches(G)
        # Renumber niches by size ascending (smallest = 0)
        sorted_nids = sorted(clusters.keys(), key=lambda nid: len(clusters[nid]))
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
    paths["yt_keywords"] = str(suggestion_path)

    # Save channel_stats.json for external analysis
    stats_path = Path(config.output_dir) / "channel_stats.json"
    stats_path.write_text(
        json.dumps(propagator.channel_stats, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths["channel_stats"] = str(stats_path)

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
    asyncio.run(run_pipeline(keywords, config))


if __name__ == "__main__":
    main()
