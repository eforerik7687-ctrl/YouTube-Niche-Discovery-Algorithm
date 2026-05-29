# Channel & Niche Concepts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add channel-level concept ranking tooltip (4a) and restore Louvain for niche-level concept aggregation with JSON output (4b).

**Architecture:** Steps 1-3 existing pipeline unchanged. Step 4a modifies `export_network()` tooltip to use propagated concepts sorted by score. Step 4b restores Louvain community detection via `networkx.algorithms.community.louvain_communities()`, adds niche concept aggregation, and exports both levels to JSON.

**Tech Stack:** Python 3.10+, NetworkX 3.0+ (built-in `louvain_communities`), python-louvain dependency exists already

---

### Task 1: Restore Louvain Community Detection in community.py

**Files:**
- Modify: `src/analysis/community.py`
- Test: `tests/test_community.py`

- [ ] **Step 1: Write failing test for Louvain detection**

Read `tests/test_community.py` first to understand existing test patterns, then add:

```python
def test_detect_niches_returns_communities(detector, sample_similarities):
    """Louvain should partition graph into communities (niches)."""
    G = detector.build_channel_graph(sample_similarities)
    niches = detector.detect_niches(G)
    assert isinstance(niches, dict)
    assert all(isinstance(k, int) for k in niches.keys())  # niche_id → channels
    assert all(isinstance(v, list) for v in niches.values())
    all_channels = set()
    for ch_list in niches.values():
        all_channels.update(ch_list)
    assert len(all_channels) == len(set().union(*sample_similarities.keys()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/efore/youtube-niche-finder && python -m pytest tests/test_community.py::test_detect_niches_returns_communities -v 2>&1 | tail -20`
Expected: FAIL with "detect_niches not defined"

- [ ] **Step 3: Add `detect_niches()` method to CommunityDetector**

```python
def detect_niches(self, G: nx.Graph) -> Dict[int, List[str]]:
    """Partition channel graph into niches using Louvain community detection.

    Returns: {niche_id: [channel_name, ...]}
    """
    try:
        # networkx.algorithms.community.louvain_communities returns list of sets
        from networkx.algorithms.community import louvain_communities
        communities = louvain_communities(G, seed=42)
    except (ImportError, ModuleNotFoundError):
        # Fallback: try python-louvain package
        import community as community_louvain
        partition = community_louvain.best_partition(G)
        # Convert {node: community_id} → {community_id: [nodes]}
        niches: Dict[int, List[str]] = {}
        for node, cid in partition.items():
            niches.setdefault(cid, []).append(node)
        return niches

    niches: Dict[int, List[str]] = {}
    for cid, members in enumerate(communities):
        niches[cid] = sorted(members)
    return niches
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/efore/youtube-niche-finder && python -m pytest tests/test_community.py::test_detect_niches_returns_communities -v 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /c/Users/efore/youtube-niche-finder
git add src/analysis/community.py tests/test_community.py
git commit -m "feat: restore Louvain community detection as detect_niches()"
```

---

### Task 2: Add Niche Concept Aggregation Logic

**Files:**
- Modify: `src/analysis/community.py`

- [ ] **Step 1: Write failing test**

Add test in `tests/test_community.py`:

```python
def test_compute_niche_concepts_aggregates_correctly(detector):
    """Niche concepts should aggregate channel concepts with coverage and avg_score."""
    propagated = {
        "ChannelA": {"python": 1.5, "tutorial": 0.8},
        "ChannelB": {"python": 1.2, "coding": 0.9},
        "ChannelC": {"python": 0.6, "tutorial": 0.3},
    }
    niches = {0: ["ChannelA", "ChannelB", "ChannelC"]}
    result = detector.compute_niche_concepts(niches, propagated)
    assert 0 in result
    concepts = result[0]
    # python appears in 3/3 channels → coverage 1.0
    py = [c for c in concepts if c["concept"] == "python"][0]
    assert py["coverage"] == 1.0
    assert py["avg_score"] == pytest.approx((1.5 + 1.2 + 0.6) / 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/efore/youtube-niche-finder && python -m pytest tests/test_community.py::test_compute_niche_concepts_aggregates_correctly -v 2>&1 | tail -20`
Expected: FAIL

- [ ] **Step 3: Implement `compute_niche_concepts()`**

```python
@staticmethod
def compute_niche_concepts(
    niches: Dict[int, List[str]],
    propagated: Dict[str, Dict[str, float]],
    top_n: int = 20,
) -> Dict[int, List[Dict]]:
    """Aggregate channel concepts per niche.

    Each concept gets:
    - coverage: % of channels in niche that have this concept
    - avg_score: mean propagated score across channels that have it

    Returns: {niche_id: [{concept, coverage, avg_score}, ...]} sorted by coverage desc
    """
    result: Dict[int, List[Dict]] = {}
    for nid, channels in niches.items():
        concept_scores: Dict[str, List[float]] = {}
        for ch in channels:
            for concept, score in propagated.get(ch, {}).items():
                concept_scores.setdefault(concept, []).append(score)

        total = len(channels)
        ranked = []
        for concept, scores in concept_scores.items():
            ranked.append({
                "concept": concept,
                "coverage": round(len(scores) / total, 4),
                "avg_score": round(sum(scores) / len(scores), 4),
            })
        ranked.sort(key=lambda x: (-x["coverage"], -x["avg_score"]))
        result[nid] = ranked[:top_n]
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/efore/youtube-niche-finder && python -m pytest tests/test_community.py::test_compute_niche_concepts_aggregates_correctly -v 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /c/Users/efore/youtube-niche-finder
git add src/analysis/community.py tests/test_community.py
git commit -m "feat: add compute_niche_concepts() for niche-level concept aggregation"
```

---

### Task 3: Modify Tooltip to Show Concepts Sorted by Score

**Files:**
- Modify: `src/analysis/community.py` (export_network method)
- Test: `tests/test_community.py` (update existing test)

- [ ] **Step 1: Read current export_network()**

Read lines 36-52 of `src/analysis/community.py` to see current tooltip logic.

- [ ] **Step 2: Modify export_network() tooltip**

Replace lines 94-108 in export_network():

Old:
```python
# Get top-5 keywords for this channel
top5 = self.propagator.rank_keywords(propagated, channel, top_n=5)
...
kw_lines = "\n".join(f"  • {kw}: {score:.2f}" for kw, score in top5) if top5 else "  (none)"
tooltip_text = (
    f"{channel}\n{sep}\n"
    f"Top Keywords:\n{kw_lines}\n{sep}\n"
    ...
)
```

New:
```python
# Get top-5 concepts for this channel, sorted by score descending
channel_concepts = propagated.get(channel, {})
top5 = sorted(channel_concepts.items(), key=lambda x: -x[1])[:5]
...
conc_lines = "\n".join(f"  • {concept}: {score:.2f}" for concept, score in top5) if top5 else "  (none)"
tooltip_text = (
    f"{channel}\n{sep}\n"
    f"Top Concepts:\n{conc_lines}\n{sep}\n"
    ...
)
```

- [ ] **Step 3: Update test for tooltip format**

Update the existing `export_network` test to check for "Top Concepts:" instead of "Top Keywords:" in the HTML output.

- [ ] **Step 4: Run existing tests to verify**

Run: `cd /c/Users/efore/youtube-niche-finder && python -m pytest tests/test_community.py -v 2>&1 | tail -30`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /c/Users/efore/youtube-niche-finder
git add src/analysis/community.py tests/test_community.py
git commit -m "feat: change tooltip Keywords → Concepts, sort by score descending"
```

---

### Task 4: Add JSON Output for Channel & Niche Concepts

**Files:**
- Modify: `src/output/formatter.py`
- Modify: `src/cli.py`

- [ ] **Step 1: Read formatter.py and cli.py**

- [ ] **Step 2: Add `save_concepts()` to OutputFormatter**

In `src/output/formatter.py`:

```python
def save_concepts(
    self,
    channel_concepts: Dict[str, List[Dict]],
    niche_concepts: Dict[int, List[Dict]],
    filename: str = "concepts.json",
) -> str:
    """Export both channel-level and niche-level concepts to JSON.

    Args:
        channel_concepts: {channel_name: [{concept, score}, ...]}
        niche_concepts: {niche_id: [{concept, coverage, avg_score}, ...]}

    Returns: path to saved JSON file
    """
    output = {
        "channel_concepts": channel_concepts,
        "niche_concepts": niche_concepts,
    }
    path = self._resolve("concepts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return str(path)
```

- [ ] **Step 3: Wire into cli.py pipeline**

In `src/cli.py`, after the 3-mode discovery loop in `run_pipeline()`, add:

```python
# Step 6: Compute niche concepts
from src.analysis.community import CommunityDetector
detector = CommunityDetector(propagator)

all_channel_concepts = {}
for name, result in [("en", en_results), ("7lang", ml_results), ("7geo", geo_results)]:
    if result:
        G = detector.build_channel_graph(result.get("similarities", {}))
        if G.number_of_nodes() > 0:
            niches = detector.detect_niches(G)
            niche_conc = detector.compute_niche_concepts(niches, result["propagated"])
            # Channel concepts sorted by score
            ch_conc = {}
            for ch, concepts in result["propagated"].items():
                sorted_concepts = sorted(concepts.items(), key=lambda x: -x[1])
                ch_conc[ch] = [{"concept": c, "score": round(s, 4)} for c, s in sorted_concepts[:10]]
            all_channel_concepts[name] = ch_conc
            paths[f"concepts_{name}"] = formatter.save_concepts(ch_conc, niche_conc, f"concepts_{name}.json")
```

Note: `_run_discovery` currently returns graph/all_pairs paths. Need to also return `similarities` and `propagated` dicts in its return value.

- [ ] **Step 4: Update _run_discovery return value**

In `_run_discovery()`, change the return to include similarity data:

```python
return {
    "graph": graph_path,
    "all_pairs": pairs_path,
    "similarities": similarities,
    "propagated": propagated,
}
```

- [ ] **Step 5: Run tests to verify nothing broke**

Run: `cd /c/Users/efore/youtube-niche-finder && python -m pytest tests/ -v 2>&1 | tail -40`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /c/Users/efore/youtube-niche-finder
git add src/output/formatter.py src/cli.py
git commit -m "feat: add JSON output for channel_concepts and niche_concepts"
```

---

### Self-Review Checklist

1. **Spec coverage:** All requirements covered:
   - ✅ Tooltip shows Concepts sorted by score (Task 3)
   - ✅ Louvain restored (Task 1)
   - ✅ Niche concepts aggregated (Task 2)
   - ✅ JSON output for both 4a and 4b (Task 4)

2. **Placeholder scan:** No TBD, no empty steps, all code blocks filled with real implementation.

3. **Type consistency:** `detect_niches()` returns `Dict[int, List[str]]` (Task 1), `compute_niche_concepts()` returns `Dict[int, List[Dict]]` (Task 2), both consumed in cli.py (Task 4). `_run_discovery` return expanded to include `similarities` and `propagated` keys (Task 4).
