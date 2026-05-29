import json as json_mod
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx
from pyvis.network import Network

from src.analysis.propagator import KeywordPropagator
from src.models import ChannelNode


class CommunityDetector:
    """Build channel similarity network and export interactive graphs.

    Uses KeywordPropagator results to build a channel-level graph where:
    - Nodes = channels
    - Edges = cosine similarity between channel keyword vectors
    - Visual clusters emerge naturally from Barnes-Hut physics
    """

    def __init__(self, propagator: KeywordPropagator):
        self.propagator = propagator

    def build_channel_graph(
        self,
        similarities: Dict[Tuple[str, str], float],
    ) -> nx.Graph:
        """Build a NetworkX graph from propagator similarity results."""
        G = nx.Graph()
        for (ch_a, ch_b), sim in similarities.items():
            G.add_node(ch_a)
            G.add_node(ch_b)
            G.add_edge(ch_a, ch_b, weight=sim)
        return G

    def detect_niches(self, G: nx.Graph) -> Dict[int, List[str]]:
        """Partition channel graph into niches using Louvain community detection.

        Returns: {niche_id: [channel_name, ...]}
        """
        try:
            from networkx.algorithms.community import louvain_communities

            communities = louvain_communities(G, seed=42)
        except (ImportError, ModuleNotFoundError):
            import community as community_louvain

            partition = community_louvain.best_partition(G)
            niches: Dict[int, List[str]] = {}
            for node, cid in partition.items():
                niches.setdefault(cid, []).append(node)
            for cid in sorted(niches.keys()):
                niches[cid] = sorted(niches[cid])
            return niches

        niches: Dict[int, List[str]] = {}
        for cid, members in enumerate(communities):
            niches[cid] = sorted(members)
        return niches

    @staticmethod
    def compute_niche_concepts(
        niches: Dict[int, List[str]],
        propagated: Dict[str, Dict[str, float]],
        top_n: int = 20,
    ) -> Dict[int, List[Dict]]:
        """Aggregate propagated keywords per niche (with induction from neighbors).

        Each keyword gets:
        - coverage: % of channels in niche that have this keyword

        Returns: {niche_id: [{keyword, coverage}, ...]} sorted by coverage desc
        """
        result: Dict[int, List[Dict]] = {}
        for nid, channels in niches.items():
            kw_counts: Dict[str, int] = {}
            for ch in channels:
                for kw in propagated.get(ch, {}):
                    kw_counts[kw] = kw_counts.get(kw, 0) + 1

            total = len(channels)
            ranked = []
            for kw, count in kw_counts.items():
                ranked.append({
                    "keyword": kw,
                    "coverage": round(count / total, 4),
                })
            ranked.sort(key=lambda x: -x["coverage"])
            result[nid] = ranked[:top_n]
        return result

    def export_niche_wordcloud(
        self,
        niches: Dict[int, List[str]],
        niche_concepts: Dict[int, List[Dict]],
        output_path: str = "output/niche_wordcloud.html",
        concepts_per_niche: int = 30,
    ) -> str:
        """Generate interactive HTML with canvas-based word cloud per niche sorted descending by channel count."""
        # Prepare JSON data for client-side rendering
        data = []
        sorted_nids = sorted(
            niches.keys(),
            key=lambda nid: len(niches[nid]),
            reverse=True,  # descending by channel count
        )
        for nid in sorted_nids:
            concepts = niche_concepts.get(nid, [])[:concepts_per_niche]
            if not concepts:
                continue
            max_coverage = max(c["coverage"] for c in concepts) or 1
            words = []
            for c in concepts:
                weight = c["coverage"] / max_coverage
                words.append({
                    "text": c["keyword"],
                    "weight": round(weight, 4),
                    "coverage": c["coverage"],
                })
            data.append({
                "id": nid,
                "channel_count": len(niches[nid]),
                "words": words,
            })

        niches_json = json_mod.dumps(data, ensure_ascii=False)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Niche Keywords Word Clouds</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    color: #fff;
    padding: 40px 20px;
    min-height: 100vh;
}}
h1 {{
    text-align: center;
    font-weight: 500;
    font-size: 28px;
    letter-spacing: -0.3px;
    color: #e0d8ff;
    margin-bottom: 6px;
}}
.subtitle {{
    text-align: center;
    color: #8878b0;
    font-size: 14px;
    margin-bottom: 32px;
}}
.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    max-width: 1200px;
    margin: 0 auto;
}}
.niche-card {{
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 14px 16px 8px;
    backdrop-filter: blur(8px);
}}
.niche-header {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 6px;
}}
.niche-title {{
    font-weight: 500;
    font-size: 15px;
    color: #c8b8ff;
}}
.niche-count {{
    color: #8878b0;
    font-size: 12px;
    font-weight: 400;
}}
canvas {{
    display: block;
    width: 100%;
    height: 200px;
    border-radius: 10px;
    background: linear-gradient(135deg, #1a1740, #2d2860);
}}
.no-concepts {{
    text-align: center;
    color: #665;
    padding: 40px;
    font-style: italic;
}}
</style>
</head>
<body>
<h1>Niche Keywords</h1>
<p class="subtitle">Each niche&rsquo;s defining keywords &mdash; word size reflects coverage</p>
<div id="container" class="grid"></div>

<script>
(function() {{
    var niches = {niches_json};
    var container = document.getElementById('container');

    if (niches.length === 0) {{
        container.innerHTML = '<div class="no-concepts">No niche concepts found.</div>';
        return;
    }}

    niches.forEach(function(niche) {{
        var card = document.createElement('div');
        card.className = 'niche-card';

        var header = document.createElement('div');
        header.className = 'niche-header';
        header.innerHTML = '<span class="niche-title">Niche ' + niche.id + '</span><span class="niche-count">' + niche.channel_count + ' channels</span>';
        card.appendChild(header);

        var canvas = document.createElement('canvas');
        canvas.width = 860;
        canvas.height = 280;
        card.appendChild(canvas);

        container.appendChild(card);
        drawWordCloud(canvas, niche.words);
    }});

    // Pagination: 4 per page
    var cards = container.getElementsByClassName('niche-card');
    var pageSize = 4, page = 0, totalPages = Math.ceil(cards.length / pageSize);
    function showPage(p){{page = Math.max(0, Math.min(p, totalPages - 1));for (var i = 0; i < cards.length; i++)cards[i].style.display = (i >= page * pageSize && i < (page + 1) * pageSize) ? '' : 'none';pgText.textContent = (page + 1) + ' / ' + totalPages;}}
    var nav = document.createElement('div');nav.style.cssText = 'text-align:center;margin-bottom:24px;';
    var prevBtn = document.createElement('button');prevBtn.textContent = '← Previous';prevBtn.style.cssText = 'background:rgba(255,255,255,0.1);color:#c8b8ff;border:1px solid rgba(255,255,255,0.2);border-radius:8px;padding:8px 20px;font-size:14px;cursor:pointer;margin:0 8px;';prevBtn.onclick = function(){{ showPage(page - 1); }};
    var nextBtn = document.createElement('button');nextBtn.textContent = 'Next →';nextBtn.style.cssText = prevBtn.style.cssText;nextBtn.onclick = function(){{ showPage(page + 1); }};
    var pgText = document.createElement('span');pgText.style.cssText = 'color:#8878b0;font-size:14px;margin:0 12px;';
    nav.appendChild(prevBtn);nav.appendChild(pgText);nav.appendChild(nextBtn);
    container.parentNode.insertBefore(nav, container);
    showPage(0);

    function drawWordCloud(canvas, words) {{
        var ctx = canvas.getContext('2d');
        var cx = canvas.width / 2;
        var cy = canvas.height / 2;

        if (!words || words.length === 0) return;

        var maxWeight = 0;
        for (var i = 0; i < words.length; i++) {{
            if (words[i].weight > maxWeight) maxWeight = words[i].weight;
        }}
        if (maxWeight === 0) maxWeight = 1;

        var bgGrad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
        bgGrad.addColorStop(0, '#1a1740');
        bgGrad.addColorStop(1, '#2d2860');
        ctx.fillStyle = bgGrad;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        words.sort(function(a, b) {{ return b.weight - a.weight; }});

        var placed = [];
        var step = 0.15;
        var maxAngle = Math.PI * 30;

        for (var wi = 0; wi < words.length; wi++) {{
            var word = words[wi];
            var ratio = word.weight / maxWeight;
            var fontSize = 14 + ratio * 42;
            ctx.font = (ratio > 0.3 ? 'bold ' : '') + fontSize + 'px "Segoe UI", "Arial", sans-serif';
            var tw = ctx.measureText(word.text).width;
            var th = fontSize * 1.3;

            var placedFlag = false;
            for (var angle = 0; angle < maxAngle; angle += step) {{
                var radius = angle * 2.5;
                var x = cx + radius * Math.cos(angle) - tw / 2;
                var y = cy + radius * Math.sin(angle) - th / 2;

                if (x < 5 || y < 5 || x + tw > canvas.width - 5 || y + th > canvas.height - 5) continue;

                var overlap = false;
                for (var p = 0; p < placed.length; p++) {{
                    if (x < placed[p].x + placed[p].w && x + tw > placed[p].x &&
                        y < placed[p].y + placed[p].h && y + th > placed[p].y) {{
                        overlap = true;
                        break;
                    }}
                }}

                if (!overlap) {{
                    placed.push({{ x: x, y: y, w: tw, h: th }});
                    ctx.fillStyle = 'rgba(255, 255, 255, ' + (0.5 + 0.5 * ratio).toFixed(2) + ')';
                    ctx.fillText(word.text, x, y + fontSize - 2);
                    placedFlag = true;
                    break;
                }}
            }}

            if (!placedFlag) {{
                for (var att = 0; att < 50; att++) {{
                    var rx = 20 + Math.random() * (canvas.width - 40 - tw);
                    var ry = 20 + Math.random() * (canvas.height - 40 - th);
                    var hit = false;
                    for (var p = 0; p < placed.length; p++) {{
                        if (rx < placed[p].x + placed[p].w && rx + tw > placed[p].x &&
                            ry < placed[p].y + placed[p].h && ry + th > placed[p].y) {{
                            hit = true;
                            break;
                        }}
                    }}
                    if (!hit) {{
                        placed.push({{ x: rx, y: ry, w: tw, h: th }});
                        ctx.fillStyle = 'rgba(255, 255, 255, ' + (0.5 + 0.5 * ratio).toFixed(2) + ')';
                        ctx.fillText(word.text, rx, ry + fontSize - 2);
                        break;
                    }}
                }}
            }}
        }}
    }}
}})();
</script>
</body>
</html>"""
        Path(output_path).write_text(html, encoding="utf-8")
        return output_path

    def export_network(
        self,
        G: nx.Graph,
        channel_keywords: Dict[str, Dict[str, float]],
        channel_data: Optional[Dict[str, Dict]] = None,
        channel_urls: Optional[Dict[str, str]] = None,
        seed_keywords: Optional[List[str]] = None,
        niches: Optional[Dict[int, List[str]]] = None,
        output_path: str = "output/graph.html",
    ) -> str:
        """Generate interactive Pyvis network graph with channels as nodes.

        Node size = channel total views (from channel_data)
        Node color = niche (Louvain community), distinct per cluster
        Hover tooltip = top-5 keywords + views/videos
        Click node = open YouTube channel (exact URL if known, else search)
        """
        net = Network(height="700px", width="100%", bgcolor="#ffffff")

        # Build channel→niche_id lookup
        ch_to_niche: Dict[str, int] = {}
        if niches:
            for nid, members in niches.items():
                for ch in members:
                    ch_to_niche[ch] = nid

        # Generate up to 80 distinct colors using HSL spread
        niche_colors = []
        num_colors = max(len(niches) if niches else 5, 5)
        for i in range(num_colors):
            hue = (i * 360 / num_colors) % 360
            sat = 70 + (i % 3) * 10  # vary saturation 70-90
            lit = 50 + (i % 5) * 5   # vary lightness 50-70
            niche_colors.append(f"hsl({hue},{sat}%,{lit}%)")

        # For each channel, determine dominant seed by counting keyword matches
        def _dominant_seed(ch: str) -> int:
            """Return index of seed that most keywords relate to."""
            kws = channel_keywords.get(ch, {})
            if not kws or not seeds:
                return 0
            scores = [0] * len(seeds)
            for kw in kws:
                kw_lower = kw.lower()
                best_idx = -1
                best_len = -1
                for i, s in enumerate(seeds):
                    if kw_lower.startswith(s.lower()) and len(s) > best_len:
                        best_idx = i
                        best_len = len(s)
                if best_idx >= 0:
                    scores[best_idx] += 1
            max_score = max(scores)
            return scores.index(max_score) if max_score > 0 else 0

        if channel_data is None:
            channel_data = {}

        for channel in G.nodes():
            nid = ch_to_niche.get(channel, 0)
            data = channel_data.get(channel, {})

            # Get top-5 real keywords for this channel
            channel_kws = channel_keywords.get(channel, {})
            top5 = sorted(channel_kws.items(), key=lambda x: -x[1])[:5]

            total_views = data.get("total_views", 0)
            video_count = data.get("video_count", 0)
            # Log10 scale: 0→4, 1K→9, 10K→11, 100K→13, 1M→15, 10M→17, 100M→19
            size = max(4, min(19, 4 + int(math.log10(total_views + 1) * 1.9)))

            sep = "─" * 20
            kw_lines = "\n".join(f"  • {kw}" for kw, _ in top5) if top5 else "  (none)"
            tooltip_text = (
                f"{channel}\n{sep}\n"
                f"Niche {nid}\n{sep}\n"
                f"Keywords:\n{kw_lines}\n{sep}\n"
                f"Views: {total_views:,}\n"
                f"Videos: {video_count}"
            )
            net.add_node(
                channel,
                label=channel,
                title=tooltip_text,
                size=size,
                color=niche_colors[nid % len(niche_colors)],
            )

        for ch_a, ch_b, edge_data in G.edges(data=True):
            sim = edge_data.get("weight", 0)
            net.add_edge(ch_a, ch_b, weight=sim, title=f"Similarity: {sim:.3f}")

        net.set_options("""
        {
          "physics": {
            "stabilization": {"iterations": 50},
            "barnesHut": {
              "gravitationalConstant": -800,
              "centralGravity": 0.3,
              "springLength": 95,
              "springConstant": 0.04,
              "damping": 0.09
            },
            "maxVelocity": 5,
            "minVelocity": 0.1,
            "solver": "barnesHut"
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 200,
            "dragNodes": true,
            "zoomView": true,
            "hideEdgesOnDrag": true,
            "hideEdgesOnZoom": true,
            "navigationButtons": true
          },
          "edges": {
            "smooth": {"enabled": false}
          }
        }
        """)

        net.save_graph(output_path)

        # Post-processing: physics freeze + click-to-channel
        html = Path(output_path).read_text(encoding="utf-8")
        import json
        url_json = json.dumps(channel_urls or {}, ensure_ascii=False)

        inject = f"""
<style>
/* no legend — niche shown in tooltip */
</style>
<script type="text/javascript">
network.once("stabilized", function() {{
  network.setOptions({{ physics: {{ enabled: false }} }});
}});
var channelUrls = {url_json};
network.on("click", function(params) {{
  if (params.nodes.length > 0) {{
    var url = channelUrls[params.nodes[0]];
    if (url) window.open(url, '_blank');
  }}
}});
</script></body>"""
        html = html.replace("</body>", inject)
        Path(output_path).write_text(html, encoding="utf-8")
        return output_path

    def export_all_pairs(
        self,
        channel_keywords: Dict[str, Dict[str, float]],
        propagated: Dict[str, Dict[str, float]],
        channel_urls: Optional[Dict[str, str]] = None,
        seed_keywords: Optional[List[str]] = None,
        output_path: str = "output/all_pairs.html",
    ) -> str:
        """Export an adjacency matrix showing ALL channel×channel similarities.
        White cell = zero similarity, colored = positive. Hover to inspect.
        """
        seeds = seed_keywords or []
        channels = sorted(channel_keywords.keys())
        all_kws = sorted({kw for d in channel_keywords.values() for kw in d})
        vectors = {ch: [channel_keywords[ch].get(kw, 0.0) for kw in all_kws] for ch in channels}

        N = len(channels)
        matrix = [[0.0]*N for _ in range(N)]
        connected = [0]*N
        for i in range(N):
            for j in range(i+1, N):
                s = self.propagator._cosine(vectors[channels[i]], vectors[channels[j]])
                matrix[i][j] = s
                matrix[j][i] = s
                if s > 0:
                    connected[i] += 1
                    connected[j] += 1

        def _seed_idx(ch: str) -> int:
            kws = propagated.get(ch, channel_keywords.get(ch, {}))
            if not kws or not seeds:
                return 0
            scores = [0]*len(seeds)
            for kw in kws:
                kwl = kw.lower()
                best, bl = -1, -1
                for si, s in enumerate(seeds):
                    if kwl.startswith(s.lower()) and len(s) > bl:
                        best, bl = si, len(s)
                if best >= 0:
                    scores[best] += 1
            ms = max(scores)
            return scores.index(ms) if ms > 0 else 0

        seed_colors = ["#FF6B6B","#4ECDC4","#45B7D1","#DDA0DD","#F7DC6F"]
        max_sim = max(max(r) for r in matrix) if any(any(r > 0 for r in row) for row in matrix) else 1
        cell = 6
        w = N * cell

        rows = ""
        for i, ch in enumerate(channels):
            c = seed_colors[_seed_idx(ch) % len(seed_colors)]
            rows += f'<div class="row"><span class="ch-name" style="color:{c}">{ch}</span><span class="ch-stat">{len(channel_keywords[ch])} kw | {connected[i]} edges</span></div>\n'

        sc = {}
        for ch in channels:
            si = _seed_idx(ch)
            sc[si] = sc.get(si, 0) + 1
        leg = ""
        for si in sorted(sc):
            lbl = seeds[si] if si < len(seeds) else "?"
            leg += f'<span style="display:inline-block;width:10px;height:10px;background:{seed_colors[si%len(seed_colors)]};border-radius:50%;margin:0 4px 0 12px;vertical-align:middle"></span>{lbl}({sc[si]})'

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>All Pairs</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0b0e1a;color:#ccc;font-family:'Segoe UI',sans-serif;padding:20px}}
h1{{font-size:16px;margin-bottom:4px;color:#fff}}
.stats{{color:#888;font-size:12px;margin-bottom:12px}}
.legend{{font-size:12px;margin-bottom:12px;color:#aaa}}
.wrap{{display:flex;gap:16px;flex-wrap:wrap}}
canvas{{display:block;border-radius:4px}}
.side{{flex:1;min-width:260px;max-height:85vh;overflow-y:auto;font-size:11px}}
.side::-webkit-scrollbar{{width:5px}}
.side::-webkit-scrollbar-thumb{{background:#333;border-radius:3px}}
.row{{display:flex;justify-content:space-between;padding:2px 6px;border-bottom:1px solid rgba(255,255,255,0.03);cursor:default}}
.row:hover{{background:rgba(255,255,255,0.05)}}
.ch-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}}
.ch-stat{{color:#555;margin-left:6px;white-space:nowrap}}
#tip{{position:fixed;background:rgba(0,0,0,0.92);color:#fff;padding:6px 10px;border-radius:6px;font-size:12px;pointer-events:none;display:none;z-index:999;border:1px solid rgba(255,255,255,0.1);max-width:400px}}
.highlight{{background:rgba(255,255,255,0.08)!important}}
</style></head><body>
<h1>All Pairs — {N} channels</h1>
<div class="stats">{N*(N-1)//2:,} pairs | {sum(connected)//2:,} positive ({sum(connected)//2/(N*(N-1)/2)*100:.1f}%) | avg {sum(connected)/N:.1f} edges/ch | {sum(1 for c in connected if c==0)} zero-sim channels</div>
<div class="legend">{leg}</div>
<div class="wrap">
<div><canvas id="m" width="{w}" height="{w}"></canvas></div>
<div class="side" id="side">{rows}</div>
</div>
<div id="tip"></div>
<script>
var N={N}, ch={json_mod.dumps(channels, ensure_ascii=False)};
var m={json_mod.dumps(matrix)}, con={json_mod.dumps(connected)};
var cell={cell}, maxSim={max_sim};
var cvs=document.getElementById('m'), ctx=cvs.getContext('2d');
var tip=document.getElementById('tip'), side=document.getElementById('side');
var rows=side.getElementsByClassName('row');
// Draw matrix
for(var i=0;i<N;i++){{
  for(var j=0;j<N;j++){{
    var v=m[i][j];
    ctx.fillStyle=v>0?'rgb('+Math.round(255-v/maxSim*200)+',60,'+Math.round(100+v/maxSim*155)+')':'rgba(200,200,200,'+(i===j?'.15':'.04')+')';
    ctx.fillRect(j*cell,i*cell,cell,cell);
  }}
}}
cvs.addEventListener('mousemove',function(e){{
  var r=cvs.getBoundingClientRect();
  var x=Math.floor((e.clientX-r.left)/cell), y=Math.floor((e.clientY-r.top)/cell);
  if(x<0||x>=N||y<0||y>=N){{tip.style.display='none';return}}
  var v=m[y][x];
  tip.innerHTML='<b>'+ch[y]+'</b> vs <b>'+ch[x]+'</b>: sim='+(v>0?v.toFixed(4):'0.0000')+'<br>edges: '+con[y]+' | '+con[x];
  tip.style.display='block'; tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY-8)+'px';
  for(var k=0;k<rows.length;k++)rows[k].classList.toggle('highlight',k===y||k===x);
}});
cvs.addEventListener('mouseleave',function(){{tip.style.display='none';for(var k=0;k<rows.length;k++)rows[k].classList.remove('highlight')}});
cvs.addEventListener('click',function(e){{
  var r=cvs.getBoundingClientRect();
  var x=Math.floor((e.clientX-r.left)/cell), y=Math.floor((e.clientY-r.top)/cell);
  if(x>=0&&x<N&&y>=0&&y<N) window.open('https://www.youtube.com/results?search_query='+encodeURIComponent(ch[y])+' '+encodeURIComponent(ch[x]),'_blank');
}});
</script></body></html>"""
        Path(output_path).write_text(html, encoding="utf-8")
        return output_path
