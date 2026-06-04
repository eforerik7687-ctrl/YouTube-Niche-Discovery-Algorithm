"""CLI entry point for YouTube Niche Finder pipeline."""

import argparse
import asyncio
import json
import math
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src._patched import patch_tubescrape, PatchedYouTube, _BROWSER_HEADERS, _USER_AGENTS
from src._token import get_po_token, inject_po_token
from src.config import Config
from src.analysis.propagator import KeywordPropagator
from src.analysis.community import CommunityDetector
from src.youtube_api import YouTubeAPI
from src.innertube import InnerTubeClient



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


async def filter_shorts_channels(
    channel_urls: Dict[str, str],
    config: Config,
    threshold: int = 3,
    max_concurrent: int = 20,
) -> set:
    """Check each channel's /shorts tab via httpx, reuse anti-ban headers from _patched.

    Uses richItemRenderer count in the HTML as signal:
      - > threshold = channel has Shorts content
      - <= threshold = empty / no Shorts tab

    Inherits anti-ban from _patched.py:
      - UA rotation (cyclic)
      - Browser-grade headers (Sec-Fetch-*, DNT, etc.)
      - Random delay (config.delay_min/max)
    """
    sem = asyncio.Semaphore(max_concurrent)
    ua_index = random.randint(0, len(_USER_AGENTS) - 1)
    request_count = 0
    shorts_set = set()

    print(f"  [shorts] Checking {len(channel_urls)} channels (threshold={threshold}, "
          f"concurrent={max_concurrent}, delay={config.delay_min}-{config.delay_max}s)")

    async def _check(ch_name: str, ch_url: str):
        nonlocal ua_index, request_count
        async with sem:
            # Anti-ban: random delay
            delay = random.uniform(config.delay_min, config.delay_max)
            if delay > 0:
                await asyncio.sleep(delay)

            # Anti-ban: cyclic UA rotation
            ua_index = (ua_index + 1) % len(_USER_AGENTS)
            request_count += 1

            headers = {
                **_BROWSER_HEADERS,
                "User-Agent": _USER_AGENTS[ua_index],
            }

            try:
                async with httpx.AsyncClient(
                    headers=headers,
                    follow_redirects=True,
                    timeout=15,
                ) as client:
                    resp = await client.get(f"{ch_url}/shorts")

                if resp.status_code == 200:
                    count = resp.text.count("richItemRenderer")
                    if count > threshold:
                        shorts_set.add(ch_name)
                    elif count > 0:
                        print(f"    [skip] {ch_name}: richItemRenderer={count} (<=threshold)")
            except Exception as exc:
                pass

    tasks = [_check(name, url) for name, url in channel_urls.items()]
    await asyncio.gather(*tasks)
    return shorts_set


async def _fetch_api_stats(
    api: YouTubeAPI,
    channel_keywords: Dict[str, Dict[str, float]],
    channel_urls: Dict[str, str],
) -> tuple:
    """Step A: channels.list → real stats + ch_to_cid mapping."""
    ch_to_cid: Dict[str, str] = {}
    channel_ids = []
    for ch_name, ch_url in channel_urls.items():
        if ch_name in channel_keywords:
            cid = ch_url.rstrip("/").split("/")[-1]
            ch_to_cid[ch_name] = cid
            channel_ids.append(cid)

    print()
    print("[pipeline] Fetching real channel statistics via YouTube API...")
    real_stats = await api.channels_list(channel_ids)
    print(f"  [API] Got stats for {len(real_stats)} channels ({len(channel_ids)} requested)")
    return real_stats, ch_to_cid


def _inject_views(
    channel_keywords: Dict[str, Dict[str, float]],
    real_stats: Dict[str, Dict],
    ch_to_cid: Dict[str, str],
) -> None:
    """Inject real viewCount into keyword vectors (log-scale normalized)."""
    view_counts = {}
    for ch_name in channel_keywords:
        cid = ch_to_cid.get(ch_name, "")
        vc = int(real_stats.get(cid, {}).get("viewCount", 0))
        view_counts[ch_name] = vc

    max_vc = max(view_counts.values()) if view_counts else 1
    for ch_name in channel_keywords:
        vc = view_counts.get(ch_name, 0)
        normalized = math.log10(vc + 1) / math.log10(max_vc + 1)
        channel_keywords[ch_name]["__views__"] = normalized
    print(f"  [views] Injected viewCount into keyword vectors (max={max_vc:,})")


def _strip_views(dicts: List[Dict]) -> None:
    """Remove __views__ synthetic keyword from all channel dicts."""
    for d in dicts:
        d.pop("__views__", None)


def _filter_channels(
    channel_keywords: Dict[str, Dict[str, float]],
    channel_data: Dict[str, Dict],
    clusters: Dict[int, List[str]],
    G: "nx.Graph",
    real_stats: Dict[str, Dict],
    ch_to_cid: Dict[str, str],
    min_views: int,
    min_niche_size: int,
    propagated: Dict[str, Dict[str, float]],
    detector: CommunityDetector,
) -> tuple:
    """Step D: views filter → niche size filter → renumber.

    Returns (channel_keywords, channel_data, clusters, G, cluster_kws).
    """
    # Filter 1: Keep only channels with >= min_views
    surviving = set()
    for ch_name in channel_keywords:
        cid = ch_to_cid.get(ch_name, "")
        vc = int(real_stats.get(cid, {}).get("viewCount", 0))
        if vc >= min_views:
            surviving.add(ch_name)

    old_ch_count = sum(len(m) for m in clusters.values())
    channel_keywords = {ch: kw for ch, kw in channel_keywords.items() if ch in surviving}
    channel_data = {ch: data for ch, data in channel_data.items() if ch in surviving}

    # Sync G: remove filtered-out nodes
    nodes_to_remove = [n for n in G.nodes() if n not in surviving]
    G.remove_nodes_from(nodes_to_remove)

    # Filter 2: Drop niches that fell below min_niche_size
    new_clusters = {}
    for nid, members in clusters.items():
        filtered = [ch for ch in members if ch in surviving]
        if len(filtered) >= min_niche_size:
            new_clusters[nid] = filtered
    clusters = new_clusters

    # Renumber niches by size ascending (smallest = 0)
    sorted_nids = sorted(clusters.keys(), key=lambda nid: len(clusters[nid]))
    remap = {old: new for new, old in enumerate(sorted_nids)}
    clusters = {remap[old]: members for old, members in clusters.items()}

    new_ch_count = sum(len(m) for m in clusters.values()) if clusters else 0
    print(f"  [filter] ViewCount > {min_views:,}: {old_ch_count} → {new_ch_count} channels, "
          f"{len(clusters)} niches (min {min_niche_size} ch/niche)")

    # Recompute niche concepts
    cluster_kws = detector.compute_niche_concepts(clusters, propagated) if clusters else {}

    return channel_keywords, channel_data, clusters, G, cluster_kws


async def _expand_step(
    api: YouTubeAPI | None,
    itube: InnerTubeClient | None,
    channel_keywords: Dict[str, Dict[str, float]],
    channel_data: Dict[str, Dict],
    clusters: Dict[int, List[str]],
    G: "nx.Graph",
    ch_to_cid: Dict[str, str],
    real_stats: Dict[str, Dict],
    channel_urls: Dict[str, str],
    propagated: Dict[str, Dict[str, float]],
    detector: CommunityDetector,
    max_expand: int = 50,
    config: Optional["Config"] = None,
) -> tuple:
    """Step E: InnerTube browse → related channels → vote assignment → G/data sync.

    Priority: InnerTubeClient (zero quota cost) > YouTubeAPI (100 quota/call, broken).
    Returns (clusters, channel_data, channel_keywords, channel_urls, G, cluster_kws).
    """
    if not itube and not api:
        print("  [expand] No API client available, skipping.")
        cluster_kws = detector.compute_niche_concepts(clusters, propagated)
        return clusters, channel_data, channel_keywords, channel_urls, G, cluster_kws

    from collections import defaultdict

    # Sort surviving channels by viewCount desc, optionally limit
    view_counts_local = {}
    for ch_name in channel_keywords:
        cid = ch_to_cid.get(ch_name, "")
        view_counts_local[ch_name] = int(real_stats.get(cid, {}).get("viewCount", 0))
    sorted_chs = sorted(view_counts_local.keys(), key=lambda ch: view_counts_local[ch], reverse=True)
    if max_expand is not None:
        sorted_chs = sorted_chs[:max_expand]

    print(f"  [expand] Expanding {len(sorted_chs)} channels by viewCount" +
          (f" (top {max_expand})" if max_expand else ""))
    print(f"  [expand] Source: {'InnerTube' if itube else 'YouTube API (legacy)'}")

    # Channel → niche mapping
    ch_to_niche = {}
    for nid, members in clusters.items():
        for ch in members:
            ch_to_niche[ch] = nid

    votes = defaultdict(lambda: defaultdict(int))
    new_ch_titles: Dict[str, str] = {}
    # Track which source channels found each new channel (for graph edges)
    new_ch_sources: Dict[str, set] = defaultdict(set)

    for ch_name in sorted_chs:
        cid = ch_to_cid.get(ch_name, "")
        if not cid:
            continue
        try:
            if itube:
                # InnerTube browse → related channels (zero quota cost)
                related = await itube.get_related_channels(cid)
                for ch in related:
                    new_id = ch["channelId"]
                    new_title = ch["title"]
                    if not new_id or not new_title:
                        continue
                    votes[new_id][ch_to_niche.get(ch_name, 0)] += 1
                    if new_id not in new_ch_titles:
                        new_ch_titles[new_id] = new_title
                    new_ch_sources[new_id].add(ch_name)
            elif api:
                # Legacy: YouTube Data API search.list (broken on most keys)
                related = await api.search_related(cid)
                for video in related:
                    new_id = video["channelId"]
                    new_title = video["channelTitle"]
                    votes[new_id][ch_to_niche.get(ch_name, 0)] += 1
                    if new_id not in new_ch_titles:
                        new_ch_titles[new_id] = new_title
                    new_ch_sources[new_id].add(ch_name)
        except Exception as exc:
            print(f"    [expand] Error expanding {ch_name}: {exc}")
            continue

    # ── Shorts filter: only keep expanded channels that produce Shorts ──
    if config and votes:
        new_urls = {}
        for new_id in votes:
            new_name = new_ch_titles.get(new_id, f"ch_{new_id[:8]}")
            new_urls[new_name] = f"https://www.youtube.com/channel/{new_id}"
        print(f"  [expand] Verifying {len(new_urls)} new channels for Shorts...")
        shorts_pass = await filter_shorts_channels(
            new_urls, config, threshold=3, max_concurrent=20,
        )
        before = len(votes)
        votes = {new_id: v for new_id, v in votes.items()
                 if new_ch_titles.get(new_id, f"ch_{new_id[:8]}") in shorts_pass}
        dropped = before - len(votes)
        if dropped:
            print(f"  [expand] Dropped {dropped} non-Shorts channels from expand results")

    # Assign via majority voting + sync all data structures
    total_new = 0
    for new_id, niche_votes in votes.items():
        winner = max(niche_votes, key=niche_votes.get)
        new_name = new_ch_titles.get(new_id, f"ch_{new_id[:8]}")
        clusters[winner].append(new_name)
        channel_urls[new_name] = f"https://www.youtube.com/channel/{new_id}"
        G.add_node(new_name)
        # Add edges to source channels (so new channels aren't isolated dots)
        for src_name in new_ch_sources.get(new_id, set()):
            if src_name in G:
                G.add_edge(new_name, src_name, weight=0.9)
        if new_name not in channel_keywords:
            channel_keywords[new_name] = {}
        if new_name not in channel_data:
            channel_data[new_name] = {
                "total_views": 0, "video_count": 0,
                "views_7d": 0, "views_30d": 0,
                "opportunity_score": 0,
                "supply_growth": 0, "demand_growth": 0,
            }
        total_new += 1

    print(f"  [expand] Added {total_new} new channels across {len(clusters)} niches")

    # Recompute niche concepts
    cluster_kws = detector.compute_niche_concepts(clusters, propagated)

    return clusters, channel_data, channel_keywords, channel_urls, G, cluster_kws


async def _discover_from_seeds(seeds: List[str], config) -> tuple:
    """Resolve seed channel handles → metadata keywords → add to pool.
    No related channels (YouTube doesn't expose them for Shorts creators).
    Channels get added directly to the keyword pool → cosine sim → Louvain."""
    from src.innertube import InnerTubeClient
    from collections import defaultdict

    itube = InnerTubeClient(
        delay_min=config.delay_min, delay_max=config.delay_max,
        proxy_list=getattr(config, "proxy_list", None) or [],
    )

    channel_keywords: Dict[str, Dict[str, float]] = {}
    channel_urls: Dict[str, str] = {}
    seen = set()

    for handle in seeds:
        # Resolve handle → channel ID
        cid = await itube.resolve_handle(handle)
        if not cid:
            print(f"  [seed] Could not resolve: {handle}")
            continue

        # Get channel metadata keywords (no related channels — YouTube doesn't support it for Shorts)
        meta = await itube.get_channel_metadata(cid)
        title = meta.get("title", "") or handle
        if not title or cid in seen:
            continue
        seen.add(cid)

        # Build keyword vector from metadata (keywords → topics → description fallback)
        kw_dict: Dict[str, float] = defaultdict(float)
        if meta.get("keywords"):
            for kw in meta["keywords"].split(","):
                kw = kw.strip().lower().strip('"').strip("'")
                if kw and len(kw) > 2 and kw not in ("minecraft", "gaming", "game"):
                    kw_dict[kw] += 1.0
        for topic in meta.get("topics", []):
            clean = topic.lower().replace("_", " ").replace("https://en.wikipedia.org/wiki/", "")
            if clean and len(clean) > 2:
                kw_dict[clean] = 0.8
        # Fallback: extract keywords from description
        if not kw_dict and meta.get("description"):
            desc = meta["description"].lower()
            words = desc.replace("\n", " ").replace(",", " ").replace(".", " ").split()
            for w in words:
                w = w.strip().strip('"')
                if len(w) > 3 and w not in ("minecraft", "gaming", "game", "this", "that", "with", "from"):
                    kw_dict[w] = 0.3

        channel_keywords[title] = dict(kw_dict)
        channel_urls[title] = f"https://www.youtube.com/channel/{cid}"

        print(f"  [seed] {title}: {len(kw_dict)} keywords (added to pool)")

    await itube.close()
    return channel_keywords, channel_urls


async def run_pipeline(keywords: List[str], config: Config | None = None,
                       seed_channels: List[str] = None) -> dict:
    """Run the YouTube Niche Finder pipeline.

    Pipeline flow:
      1. Expansion: fetch YouTube Search Suggestions (7 languages + 7 geos)
      2. Discover: find channels via merged 7+7 search suggestions
         (shorts_mode: append ' short', filter by views>=100k, duration<=60s)
      3. Cosine similarity + keyword propagation
      4. Louvain community detection + niche concept aggregation
      5. Export: graph, word cloud, cluster report
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

    _ALL_GEOS = ["US", "IN", "GB", "PH", "NG", "AU", "CA"]

    async with PatchedYouTube(config) as yt:
        propagator = KeywordPropagator(config, yt)
        print()
        print("[pipeline] Discovering (en × 7 geo)...")
        channel_keywords = await propagator.discover_async(keywords, geos=_ALL_GEOS)
        print(f"  [7geo] Found {len(channel_keywords)} channels")

    total_channels = len(channel_keywords)
    print(f"[pipeline] Total unique channels: {total_channels}")

    # ── Seed Channel Discovery (InnerTube browse) ──
    if seed_channels:
        print()
        print("[pipeline] Discovering from seed channels via InnerTube...")
        seed_kw, seed_urls = await _discover_from_seeds(seed_channels, config)
        channel_keywords.update(seed_kw)
        propagator.channel_urls.update(seed_urls)
        total_channels = len(channel_keywords)
        print(f"  [seed] Found {len(seed_kw)} channels from {len(seed_channels)} seeds")
        print(f"[pipeline] Total channels after merge: {total_channels}")

    if not channel_keywords:
        print("[pipeline] No channels found, skipping.")
        return {}

    # ── Shorts filter: skip if only seed channels (no keywords) ──
    only_seeds = seed_channels and not keywords
    if not only_seeds and channel_keywords:
        print()
        print("[pipeline] Verifying Shorts channels via /shorts URL check...")
        shorts_channels = await filter_shorts_channels(
            propagator.channel_urls, config,
            threshold=3, max_concurrent=20,
        )
        print(f"  [shorts] {len(shorts_channels)} / {len(propagator.channel_urls)} channels produce Shorts")
        channel_keywords = {
            ch: kw for ch, kw in channel_keywords.items()
            if ch in shorts_channels
        }
        print(f"  [shorts] Remaining channels after filter: {len(channel_keywords)}")
        if len(channel_keywords) < 10:
            print("[pipeline] Too few Shorts channels (<10), skipping.")
            return {}
    else:
        print("[pipeline] Seed channel mode: skipping Shorts filter")

    # ── Step A: YouTube API — channels.list (real stats) ──
    real_stats: Dict[str, Dict] = {}
    ch_to_cid: Dict[str, str] = {}
    if config.youtube_api_key:
        api = YouTubeAPI(config.youtube_api_key)
        real_stats, ch_to_cid = await _fetch_api_stats(api, channel_keywords, propagator.channel_urls)
        _inject_views(channel_keywords, real_stats, ch_to_cid)
    else:
        print()
        print("[pipeline] No YouTube API key — skipping real stats, using discovery data")

    # ── Step B: Cosine Similarity + Keyword Propagation ──
    print("[pipeline] Computing cosine similarity...")
    similarities = propagator.compute_similarity(channel_keywords, min_similarity=0.5)
    print(f"[pipeline] Found {len(similarities)} channel similarity pairs")

    propagated = propagator.propagate(channel_keywords, similarities)

    # Strip __views__ from keyword vectors (no longer needed, shouldn't pollute concepts)
    if config.youtube_api_key:
        _strip_views(propagated.values())
        _strip_views(channel_keywords.values())

    # ── Step C: Louvain Community Detection ──
    detector = CommunityDetector(propagator)
    G = detector.build_channel_graph(similarities)

    paths: Dict[str, str] = {}
    enriched_clusters = {}

    if G.number_of_nodes() > 0:
        # Build channel_data (pre-filter, for downstream use)
        channel_data = _build_channel_data(channel_keywords, propagator.channel_stats)

        # Louvain
        clusters = detector.detect_niches(G)
        sorted_nids = sorted(clusters.keys(), key=lambda nid: len(clusters[nid]))
        remap = {old: new for new, old in enumerate(sorted_nids)}
        clusters = {remap[old]: members for old, members in clusters.items()}
        cluster_kws = detector.compute_niche_concepts(clusters, propagated)

        # ── Step D: YouTube API — Filter by real viewCount ──
        if config.youtube_api_key and real_stats:
            print()
            channel_keywords, channel_data, clusters, G, cluster_kws = _filter_channels(
                channel_keywords, channel_data, clusters, G,
                real_stats, ch_to_cid,
                min_views=config.min_total_views, min_niche_size=1,
                propagated=propagated, detector=detector,
            )

            if not clusters:
                print("[pipeline] No channels surviving filter, skipping.")
                return {}

            # Export filtered graph (before expand)
            filtered_path = detector.export_network(
                G, channel_keywords,
                channel_data=channel_data,
                channel_urls=propagator.channel_urls,
                seed_keywords=keywords,
                niches=clusters,
                output_path=str(Path(config.output_dir) / "graph_filtered.html"),
            )
            paths["graph_filtered"] = filtered_path
            print(f"  [filter] Graph exported: {filtered_path}")

        # ── Step E: InnerTube browse → Expand All ──
        itube: "InnerTubeClient | None" = None
        if clusters:
            proxy_list = getattr(config, "proxy_list", None) or []
            itube = InnerTubeClient(
                delay_min=config.delay_min,
                delay_max=config.delay_max,
                proxy_list=proxy_list,
            )
            clusters, channel_data, channel_keywords, propagator.channel_urls, G, cluster_kws = await _expand_step(
                api if config.youtube_api_key else None,
                itube,
                channel_keywords, channel_data, clusters, G,
                ch_to_cid, real_stats, propagator.channel_urls,
                propagated, detector,
                max_expand=None,
                config=config,
            )
            await itube.close()

        # ── Post-expand: drop niches with < 10 channels OR total views >= 100M ──
        if clusters:
            min_channels = 10
            min_niche_views = 500_000_000
            before = len(clusters)
            new_clusters = {}
            for nid, members in clusters.items():
                total_views = 0
                for ch in members:
                    cid = ch_to_cid.get(ch, "")
                    if cid in real_stats:
                        total_views += int(real_stats[cid].get("viewCount", 0))
                if len(members) >= min_channels and total_views > min_niche_views:
                    new_clusters[nid] = members
                else:
                    reason = "channels" if len(members) < min_channels else "views"
                    print(f"  [cleanup] Dropped niche {nid}: {len(members)} ch, "
                          f"{total_views:,} views ({reason})")
            dropped = before - len(new_clusters)
            if dropped:
                kept = {ch for members in new_clusters.values() for ch in members}
                orphans = [n for n in G.nodes() if n not in kept]
                G.remove_nodes_from(orphans)

            # Sort by total views descending, number from 1
            sorted_nids = sorted(
                new_clusters.keys(),
                key=lambda nid: sum(
                    int(real_stats.get(ch_to_cid.get(ch, ""), {}).get("viewCount", 0))
                    for ch in new_clusters[nid] if ch_to_cid.get(ch, "") in real_stats
                ),
                reverse=True,
            )
            remap = {old: idx + 1 for idx, old in enumerate(sorted_nids)}
            clusters = {remap[old]: members for old, members in new_clusters.items()}
            cluster_kws = detector.compute_niche_concepts(clusters, propagated)
            print(f"  [cleanup] {len(clusters)} niches remain "
                  f"(min {min_channels} ch, min {min_niche_views:,} total views)")

        # ── Step F: Export ──
        # Override channel_data with real API stats if available
        if config.youtube_api_key and real_stats:
            for ch_name in channel_data:
                cid = ch_to_cid.get(ch_name, "")
                api_stats = real_stats.get(cid, {})
                if api_stats:
                    channel_data[ch_name].update({
                        "total_views": int(api_stats.get("viewCount", 0)),
                        "video_count": int(api_stats.get("videoCount", 0)),
                        "subscriber_count": int(api_stats.get("subscriberCount", 0)),
                    })
        graph_path = detector.export_network(
            G, channel_keywords,
            channel_data=channel_data,
            channel_urls=propagator.channel_urls,
            seed_keywords=keywords,
            niches=clusters,
            output_path=str(Path(config.output_dir) / "graph_expanded.html"),
        )
        paths["graph"] = graph_path

        # Word cloud per niche
        wordcloud_path = detector.export_niche_wordcloud(
            clusters, cluster_kws,
            output_path=str(Path(config.output_dir) / "niche_wordcloud.html"),
            channel_data=channel_data,
            real_stats=real_stats if config.youtube_api_key else None,
            ch_to_cid=ch_to_cid if config.youtube_api_key else None,
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
    paths["yt_keywords"] = "disabled (direct mode)"

    print(f"[pipeline] Done! Output:")
    for name, path in paths.items():
        if path:
            print(f"  {name}: {path}")

    # Cleanup API client
    try:
        await api.close()
    except (NameError, AttributeError):
        pass

    return paths


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Niche Finder - discover blue ocean niches"
    )
    parser.add_argument("keywords", nargs="*", help="Seed keywords to analyze")
    parser.add_argument("--seed-channels", "-sc", nargs="*", default=[],
                        help="Seed channel handles (e.g. @MrBeast @Tiaocraft)")
    parser.add_argument("--env", "-e", default=".env", help="Path to .env file")
    parser.add_argument("--output", "-o", default="output", help="Output directory")

    args = parser.parse_args()
    keywords = []
    for kw in args.keywords:
        keywords.extend(k.strip() for k in kw.split(",") if k.strip())

    seed_channels = []
    for sc in args.seed_channels:
        seed_channels.extend(s.strip() for s in sc.split(",") if s.strip())

    config = Config.from_env()
    config.output_dir = args.output
    config.raw_dir = f"{args.output}/raw"
    if keywords:
        asyncio.run(run_pipeline(keywords, config, seed_channels=seed_channels))
    elif seed_channels:
        asyncio.run(run_pipeline([], config, seed_channels=seed_channels))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
