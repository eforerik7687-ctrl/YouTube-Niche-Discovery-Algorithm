import json as json_mod
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
            return niches

        niches: Dict[int, List[str]] = {}
        for cid, members in enumerate(communities):
            niches[cid] = sorted(members)
        return niches

    def export_network(
        self,
        G: nx.Graph,
        channel_keywords: Dict[str, Dict[str, float]],
        propagated: Dict[str, Dict[str, float]],
        channel_data: Optional[Dict[str, Dict]] = None,
        channel_urls: Optional[Dict[str, str]] = None,
        seed_keywords: Optional[List[str]] = None,
        output_path: str = "output/graph.html",
    ) -> str:
        """Generate interactive Pyvis network graph with channels as nodes.

        Node size = channel total views (from channel_data)
        Node color = dominant seed keyword per channel
        Hover tooltip = top-5 keywords + 4 metrics
        Click node = open YouTube channel (exact URL if known, else search)
        """
        net = Network(height="700px", width="100%", bgcolor="#ffffff")

        # Colors per seed keyword
        seed_colors = [
            "#FF6B6B",  # Red
            "#4ECDC4",  # Teal
            "#45B7D1",  # Blue
            "#DDA0DD",  # Plum
            "#F7DC6F",  # Gold
        ]
        seeds = seed_keywords or []

        # For each channel, determine dominant seed
        def _dominant_seed(ch: str) -> int:
            """Return index of seed that contributes most score to this channel."""
            kws = propagated.get(ch, {})
            if not kws or not seeds:
                return 0
            scores = [0] * len(seeds)
            for kw, score in kws.items():
                kw_lower = kw.lower()
                # Match longest seed first (handles "steal a brianrot")
                best_idx = -1
                best_len = -1
                for i, s in enumerate(seeds):
                    if kw_lower.startswith(s.lower()) and len(s) > best_len:
                        best_idx = i
                        best_len = len(s)
                if best_idx >= 0:
                    scores[best_idx] += score
            # Tie → first seed wins
            max_score = max(scores)
            return scores.index(max_score) if max_score > 0 else 0

        if channel_data is None:
            channel_data = {}

        for channel in G.nodes():
            sid = _dominant_seed(channel)
            data = channel_data.get(channel, {})

            # Get top-5 keywords for this channel
            top5 = self.propagator.rank_keywords(propagated, channel, top_n=5)

            total_views = data.get("total_views", 0)
            size = max(10, min(80, total_views / 10_000))

            sep = "─" * 20
            kw_lines = "\n".join(f"  • {kw}: {score:.2f}" for kw, score in top5) if top5 else "  (none)"
            tooltip_text = (
                f"{channel}\n{sep}\n"
                f"Top Keywords:\n{kw_lines}\n{sep}\n"
                f"Views: {total_views:,}\n"
                f"Videos: {data.get('video_count', 0)}\n"
                f"Opportunity: {data.get('opportunity_score', 0):.2f}\n"
                f"Supply: {data.get('supply_growth', 0):.4f}  |  Demand: {data.get('demand_growth', 0):.4f}"
            )
            net.add_node(
                channel,
                label=channel,
                title=tooltip_text,
                size=size,
                color=seed_colors[sid % len(seed_colors)],
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

        # Build legend: count channels per seed
        seed_counts: Dict[int, int] = {}
        for ch in G.nodes():
            sid = _dominant_seed(ch)
            seed_counts[sid] = seed_counts.get(sid, 0) + 1

        legend_rows = "".join(
            f'<div class="legend-row"><span class="legend-dot" style="background:{seed_colors[sid % len(seed_colors)]}"></span>'
            f'<span class="legend-label">{seeds[sid] if sid < len(seeds) else "?"}</span><span class="legend-count">{seed_counts.get(sid, 0)}</span></div>'
            for sid in sorted(seed_counts.keys())
        )

        # Post-processing: physics freeze + click-to-channel + legend
        html = Path(output_path).read_text(encoding="utf-8")
        import json
        url_json = json.dumps(channel_urls or {}, ensure_ascii=False)

        inject = f"""
<style>
.legend-container {{
  position: fixed; bottom: 20px; right: 20px; z-index: 999;
  background: rgba(15, 15, 30, 0.85); backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,0.1); border-radius: 10px;
  padding: 14px 18px; font-family: 'Segoe UI', sans-serif; font-size: 13px;
  min-width: 180px; box-shadow: 0 4px 20px rgba(0,0,0,0.4);
}}
.legend-title {{
  color: #aaa; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
  margin-bottom: 8px; font-weight: 600;
}}
.legend-row {{
  display: flex; align-items: center; gap: 8px; padding: 2px 0;
  transition: opacity 0.15s;
}}
.legend-row:hover {{ opacity: 0.7; cursor: pointer; }}
.legend-dot {{
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
  border: 1px solid rgba(255,255,255,0.15);
}}
.legend-label {{ color: #ddd; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.legend-count {{ color: #666; font-size: 11px; }}
</style>
<div class="legend-container" id="legend">
  <div class="legend-title" id="legend-handle" style="cursor:grab; user-select:none">↕ Niche Communities</div>
  {legend_rows}
</div>
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
// Draggable legend
(function() {{
  var legend = document.getElementById('legend');
  var handle = document.getElementById('legend-handle');
  var ox = 0, oy = 0, fx = 0, fy = 0;
  handle.addEventListener('mousedown', function(e) {{
    e.preventDefault();
    ox = e.clientX - fx;
    oy = e.clientY - fy;
    handle.style.cursor = 'grabbing';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }});
  function onMove(e) {{
    fx = e.clientX - ox;
    fy = e.clientY - oy;
    legend.style.left = fx + 'px';
    legend.style.right = 'auto';
    legend.style.bottom = 'auto';
    legend.style.top = fy + 'px';
  }}
  function onUp() {{
    handle.style.cursor = 'grab';
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  }}
}})();
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
