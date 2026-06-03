"""Renumber niches in all rendered files from descending->ascending by channel count.
Also add niche number to graph_7plus7.html tooltips (which were missing it).

Usage: cd youtube-niche-finder && python scripts/renumber_niches.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def compute_mapping():
    """Read cluster_report.json, return old->new niche ID mapping (ascending)."""
    path = ROOT / "cluster_report.json"
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    niches = data["cluster_keywords"]
    # Sort by channel_count ascending (smallest = 0)
    sorted_old_ids = sorted(niches.keys(), key=lambda nid: niches[nid]["channel_count"])
    mapping = {int(old): new for new, old in enumerate(sorted_old_ids)}
    return mapping, data


def update_cluster_report(mapping, data):
    """Rewrite cluster_report.json with new niche IDs."""
    old_niches = data["cluster_keywords"]
    new_niches = {}
    for old_id, info in old_niches.items():
        new_id = str(mapping[int(old_id)])
        new_niches[new_id] = info
    data["cluster_keywords"] = new_niches
    path = ROOT / "cluster_report.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  OK {path.name} -- renumbered {len(mapping)} niches")


def update_docs_cluster_report(mapping):
    """Update docs/cluster_report.json if exists."""
    path = ROOT / "docs" / "cluster_report.json"
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    old_niches = data["cluster_keywords"]
    new_niches = {}
    for old_id, info in old_niches.items():
        new_id = str(mapping[int(old_id)])
        new_niches[new_id] = info
    data["cluster_keywords"] = new_niches
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  OK docs/{path.name} -- renumbered {len(mapping)} niches")


def niche_color(nid, total):
    """Compute HSL color for a niche ID, matching community.py logic."""
    hue = (nid * 360 / total) % 360
    sat = 70 + (nid % 3) * 10
    lit = 50 + (nid % 5) * 5
    return f"hsl({hue},{sat}%,{lit}%)"


def parse_niche_from_color(hsl_str, total):
    """Given an HSL string, determine which niche ID it belongs to (old numbering)."""
    m = re.match(r'hsl\(([\d.]+),(\d+)%,(\d+)%\)', hsl_str)
    if not m:
        return None
    hue = float(m.group(1))
    sat = int(m.group(2))
    lit = int(m.group(3))
    tolerance = 0.5
    for nid in range(total):
        expected_hue = (nid * 360 / total) % 360
        expected_sat = 70 + (nid % 3) * 10
        expected_lit = 50 + (nid % 5) * 5
        hue_diff = min(abs(hue - expected_hue), abs(hue - (expected_hue - 360)),
                       abs(hue - (expected_hue + 360)))
        if hue_diff < tolerance and sat == expected_sat and lit == expected_lit:
            return nid
    return None


def _build_color_to_old_nid(nodes_data):
    """Build mapping from color string -> old niche ID (descending by count)."""
    color_counts = {}
    for n in nodes_data:
        c = n.get("color", "")
        if c:
            color_counts[c] = color_counts.get(c, 0) + 1

    # Sort by count descending = old Niche 0 (biggest), Niche 1, ...
    sorted_colors = sorted(color_counts.items(), key=lambda x: -x[1])
    return {color: nid for nid, (color, _) in enumerate(sorted_colors)}


def update_graph_html(mapping):
    """Update graph_7plus7.html: renumber colors + add niche to tooltips."""
    path = ROOT / "graph_7plus7.html"
    if not path.exists():
        print(f"  SKIP {path.name} not found")
        return
    html = path.read_text(encoding="utf-8")

    # Find the nodes DataSet JSON
    nodes_match = re.search(r'nodes\s*=\s*new\s+vis\.DataSet\((\[.*?\])\)', html, re.DOTALL)
    if not nodes_match:
        print("  SKIP could not find nodes DataSet in graph HTML")
        return

    try:
        nodes_data = json.loads(nodes_match.group(1))
    except json.JSONDecodeError as e:
        print(f"  FAIL JSON parse: {e}")
        return

    if not nodes_data:
        print("  FAIL empty nodes data")
        return

    # Build color -> old niche ID mapping (by counting)
    color_to_old = _build_color_to_old_nid(nodes_data)
    old_total = len(color_to_old)
    new_total = len(mapping)
    print(f"  Graph: {old_total} old niches -> {new_total} new niches")

    updated_count = 0
    for node in nodes_data:
        old_color = node.get("color", "")
        if not old_color:
            continue
        old_nid = color_to_old.get(old_color)
        if old_nid is None:
            continue
        new_nid = mapping.get(old_nid)
        if new_nid is None:
            continue

        # Update color
        node["color"] = niche_color(new_nid, new_total)

        # Add/update niche number in tooltip
        old_title = node.get("title", "")
        sep = "─" * 20  # box-drawing horizontal line

        if "Niche" in old_title:
            new_title = re.sub(r'Niche \d+', f'Niche {new_nid}', old_title)
        else:
            # Old tooltip format: "channel\n────\nKeywords:\n...\n────\nViews:..."
            # Insert "Niche X" after first line
            lines = old_title.split("\n")
            first_line = lines[0]
            rest = "\n".join(lines[1:]) if len(lines) > 1 else ""
            new_title = f"{first_line}\nNiche {new_nid}\n{rest}".rstrip("\n")

        node["title"] = new_title
        updated_count += 1

    # Serialize back
    new_nodes_json = json.dumps(nodes_data, ensure_ascii=False)

    old_str = nodes_match.group(0)
    new_str = f"nodes = new vis.DataSet({new_nodes_json})"
    html = html.replace(old_str, new_str, 1)

    path.write_text(html, encoding="utf-8")
    print(f"  OK {path.name} -- updated {updated_count}/{len(nodes_data)} nodes")


def update_niche_wordcloud(mapping):
    """Update niche_wordcloud.html -- renumber the JS data array and display."""
    path = ROOT / "niche_wordcloud.html"
    if not path.exists():
        return
    html = path.read_text(encoding="utf-8")

    pattern = r'var niches\s*=\s*(\[.*?\]);'
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        print(f"  SKIP could not find niches data in {path.name}")
        return

    try:
        niches_data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"  FAIL JSON parse in {path.name}: {e}")
        return

    for item in niches_data:
        old_id = item.get("id")
        new_id = mapping.get(old_id)
        if new_id is not None:
            item["id"] = new_id

    # Re-sort by new ID (ascending by size)
    niches_data.sort(key=lambda x: x["id"])

    new_json = json.dumps(niches_data, ensure_ascii=False)
    html = html.replace(match.group(0), f"var niches = {new_json};", 1)

    path.write_text(html, encoding="utf-8")
    print(f"  OK {path.name} -- renumbered {len(niches_data)} niches, resorted")


def _guess_total_colors(color_set):
    """Try to determine the total number of niches by matching HSL patterns.
    The formula: hue = nid * 360 / total, sat = 70 + nid%3*10, lit = 50 + nid%5*5.
    """
    for total in range(58, 68):  # try totals around 61
        matched = 0
        for color in color_set:
            m = re.match(r'hsl\(([\d.]+),(\d+)%,(\d+)%\)', color)
            if not m:
                continue
            hue = float(m.group(1))
            sat = int(m.group(2))
            lit = int(m.group(3))
            for nid in range(total):
                expected_hue = (nid * 360 / total) % 360
                expected_sat = 70 + (nid % 3) * 10
                expected_lit = 50 + (nid % 5) * 5
                hue_diff = min(abs(hue - expected_hue), abs(hue - (expected_hue - 360)),
                              abs(hue - (expected_hue + 360)))
                if hue_diff < 1.0 and sat == expected_sat and lit == expected_lit:
                    matched += 1
                    break
        # If all colors match, we found the right total
        if matched == len(color_set):
            return total
    return max(len(color_set), 61)


def compute_mapping_from_graph(graph_path):
    """Read the graph HTML and determine old niche sizes from node colors.
    Then create old->new mapping (ascending order).

    Strategy: sort colors by node count descending.
    Old niche 0 = biggest (descending from code).
    Map to ascending: new niche 0 = smallest.
    """
    html = Path(graph_path).read_text(encoding="utf-8")
    m = re.search(r'nodes\s*=\s*new\s+vis\.DataSet\((\[.*?\])\)', html, re.DOTALL)
    if not m:
        return None
    nodes = json.loads(m.group(1))

    # Count nodes per color, sorted descending = old niche IDs
    color_counts_list = sorted(
        ((n.get("color", ""), sum(1 for n2 in nodes if n2.get("color", "") == n.get("color", "")))
         for n in nodes if n.get("color")),
        key=lambda x: -x[1]
    )
    # Deduplicate
    seen = set()
    unique_colors = []
    for c, cnt in color_counts_list:
        if c not in seen:
            seen.add(c)
            unique_colors.append((c, cnt))

    # In the old descending scheme: first color = biggest = Niche 0, etc.
    # Build old_niche_id -> old_size mapping
    old_sizes = {nid: cnt for nid, (c, cnt) in enumerate(unique_colors)}
    total = len(old_sizes)

    # Create ascending mapping: smallest niche = 0
    sorted_nids = sorted(old_sizes.keys(), key=lambda nid: old_sizes[nid])
    mapping = {nid: new_id for new_id, nid in enumerate(sorted_nids)}

    print(f"  -> {total} niches, sorted by count (ascending)")
    for nid in sorted_nids[:3]:
        print(f"    Old Niche {nid} ({old_sizes[nid]} nodes) -> New Niche {mapping[nid]}")
    print(f"    ...")
    for nid in sorted_nids[-3:]:
        print(f"    Old Niche {nid} ({old_sizes[nid]} nodes) -> New Niche {mapping[nid]}")
    return mapping


def main():
    # Use graph file to determine the actual old niche layout
    print("Analyzing graph HTML for niche distribution...")
    mapping = compute_mapping_from_graph(ROOT / "graph_7plus7.html")
    if mapping is None:
        print("Could not determine mapping from graph, falling back to cluster_report")
        mapping, _ = compute_mapping()

    print()
    print("Updating rendered files...")

    update_niche_wordcloud(mapping)

    print()
    print("Updating graph HTML (color + tooltips)...")
    update_graph_html(mapping)

    print()
    print("All done.")


if __name__ == "__main__":
    main()
