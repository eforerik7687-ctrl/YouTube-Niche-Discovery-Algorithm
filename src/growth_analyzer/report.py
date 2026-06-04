"""Generate growth_analyzer_report.html from Social Blade data."""
import json, re, sys, webbrowser
from pathlib import Path
from collections import defaultdict, Counter
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.growth_analyzer.metrics import compute_channel, compute_aggregated

def parse_subs(v):
    if not v: return 0
    v = str(v).upper().replace(',','')
    if 'B' in v: return int(float(v.replace('B','')) * 1e9)
    if 'M' in v: return int(float(v.replace('M','')) * 1e6)
    if 'K' in v: return int(float(v.replace('K','')) * 1e3)
    try: return int(float(v))
    except: return 0

OUTPUT = Path("output/growth_report.html")

def generate(sb_path="socialblade_data.json"):
    sb_data = json.loads(Path(sb_path).read_text())

    # Load channel → niche mapping from pipeline export (exact, no guessing)
    ch_to_niche = {}
    cn_file = Path("output/channel_to_niche.json")
    if cn_file.exists():
        ch_to_niche = json.loads(cn_file.read_text())
    # Fallback: try repo root
    if not ch_to_niche:
        cn_file = Path("channel_to_niche.json")
        if cn_file.exists():
            ch_to_niche = json.loads(cn_file.read_text())

    # Load niche metadata from wordcloud
    niche_meta = {}
    wc = Path("niche_wordcloud.html")
    if wc.exists():
        m = re.search(r'var niches = (\[.*?\]);', wc.read_text(encoding="utf-8"), re.DOTALL)
        if m:
            for n in json.loads(m.group(1)):
                niche_meta[n['id']] = n

    # Load graph for channelId lookup (fallback)
    graph_html = Path("graph_expanded.html").read_text(encoding="utf-8")
    match = re.search(r'nodes = new vis\.DataSet\((\[.*?\])\s*\)', graph_html, re.DOTALL)
    nodes = json.loads(match.group(1)) if match else []
    ch_id_lookup = {}
    for n in nodes:
        l, t = n.get('label',''), n.get('title','')
        cm = re.search(r'youtube\.com/channel/(UC\w+)', t)
        if l and cm:
            ch_id_lookup[l] = cm.group(1)

    # Channel level
    channels = []
    for handle, raw in sb_data.items():
        if not raw.get('total',{}).get('subs'): continue
        m = compute_channel(raw)
        views_30d = max(0, raw.get('periods',{}).get('views_30d',0))
        videos_30d = max(0, raw.get('periods',{}).get('videos_30d',0))
        if views_30d == 0 and raw.get('daily'):
            views_30d = max(0, sum(r.get('views_delta',0) for r in raw['daily']))
        if videos_30d == 0 and raw.get('daily'):
            videos_30d = max(0, sum(r.get('videos_delta',0) for r in raw['daily']))

        # Find channel name + niche from channel_to_niche.json
        name = handle
        niche_id = 0
        # Try exact match first, then case-insensitive
        if handle in ch_to_niche:
            niche_id = ch_to_niche[handle]
            name = handle
        else:
            for cname, cnid in ch_to_niche.items():
                if cname.lower().replace(' ','') == handle:
                    name = cname
                    niche_id = cnid
                    break
        # Last resort: search in graph nodes
        if niche_id == 0:
            for n in nodes:
                nl = n.get('label','').lower().replace(' ','')
                if nl == handle:
                    name = n['label']
                    break

        channels.append({
            'name': name,
            'niche_id': niche_id,
            'channelId': ch_id_lookup.get(name, ''),
            'subs': parse_subs(raw.get('total',{}).get('subs',0)),
            'views_7d': max(0, raw.get('periods',{}).get('views_7d',0)),
            'views_30d': views_30d,
            'videos_7d': max(0, raw.get('periods',{}).get('videos_7d',0)),
            'videos_30d': videos_30d,
            'dgr': m['dgr'], 'sgr': m['sgr'], 'opportunity': m['opportunity'],
        })
    channels.sort(key=lambda c: -c['opportunity'])

    # Niche level (aggregate from processed channel data)
    niche_raw = defaultdict(list)
    for c in channels:
        niche_raw[c['niche_id']].append(c)
    niche_scores = []
    for nid, raws in niche_raw.items():
        agg7v = sum(r.get('views_7d', 0) for r in raws)
        agg7vid = sum(r.get('videos_7d', 0) for r in raws)
        agg30v = sum(r.get('views_30d', 0) for r in raws)
        agg30vid = sum(r.get('videos_30d', 0) for r in raws)
        nd = (agg7v/7) / (agg30v/30) if agg30v > 0 else 0
        ns = (agg7vid/7) / (agg30vid/30) if agg30vid > 0 else 0
        nopp = nd / ns if ns > 0 else 0
        meta = niche_meta.get(nid, {})
        niche_scores.append({
            'id': nid,
            'keyword': meta.get('keyword',''),
            'color': meta.get('color','#c8b8ff'),
            'count': len(raws),
            'dgr': nd, 'sgr': ns, 'opportunity': nopp,
            'views_30d': agg30v,
            'videos_30d': agg30vid,
        })
    niche_scores.sort(key=lambda n: -n['opportunity'])

    # Build HTML
    def fmt(v):
        try: v = int(v)
        except: return str(v)
        if v >= 1e9: return f"{v/1e9:.1f}B"
        if v >= 1e6: return f"{v/1e6:.1f}M"
        if v >= 1e3: return f"{v/1e3:.0f}K"
        return str(v)
    def opp_cls(v):
        return 'opp-high' if v > 1.5 else 'opp-mid' if v > 1.0 else 'opp-low'

    ch_rows = ''
    for c in channels[:100]:
        url = f"https://www.youtube.com/channel/{c['channelId']}/shorts" if c['channelId'] else f"https://www.youtube.com/@{c['name']}/shorts"
        ch_rows += f'''<tr><td><a href="{url}" target="_blank">{c['name']}</a></td>
        <td><span style="color:{niche_meta.get(c['niche_id'],{}).get('color','#c8b8ff')}">Niche {c['niche_id']}</span></td>
        <td>{fmt(c['subs'])}</td><td>{fmt(c['views_30d'])}</td><td>{c['videos_30d']}</td>
        <td>{c['dgr']:.2f}</td><td>{c['sgr']:.2f}</td>
        <td class="{opp_cls(c['opportunity'])}">{c['opportunity']:.2f}</td></tr>\n'''

    n_rows = ''
    for n in niche_scores:
        n_rows += f'''<tr><td><span style="color:{n['color']}">Niche {n['id']}</span></td>
        <td>{n['count']}</td><td>{fmt(n['views_30d'])}</td><td>{n['videos_30d']}</td>
        <td>{n['dgr']:.2f}</td><td>{n['sgr']:.2f}</td>
        <td class="{opp_cls(n['opportunity'])}">{n['opportunity']:.2f}</td></tr>\n'''

    html = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Growth Analyzer Report</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0b0e1a;color:#e0d8ff;font-family:'Inter','Segoe UI',sans-serif;padding:32px}}
h1{{font-weight:500;font-size:22px;color:#c8b8ff;margin-bottom:4px}}
.subtitle{{color:#8878b0;font-size:13px;margin-bottom:24px}}
h2{{font-size:16px;font-weight:500;color:#c8b8ff;margin:24px 0 12px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:32px}}
th{{text-align:left;padding:10px 12px;color:#8878b0;font-weight:400;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid rgba(255,255,255,0.08)}}
td{{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.04)}}
tr:hover td{{background:rgba(255,255,255,0.03)}}
td a{{color:#c8b8ff;text-decoration:none;font-weight:500}}
td a:hover{{color:#fff;text-decoration:underline}}
.opp-high{{color:#60ff60}} .opp-mid{{color:#c8ff60}} .opp-low{{color:#ffc060}}
.summary{{display:flex;gap:20px;margin-bottom:24px;flex-wrap:wrap}}
.summary-card{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 20px;min-width:140px}}
.summary-card .num{{font-size:22px;font-weight:500;color:#c8b8ff}}
.summary-card .label{{font-size:11px;color:#8878b0;margin-top:2px}}
</style></head><body>
<h1>Growth Analyzer Report</h1>
<p class="subtitle">Views GR = (7d_views/7)/(30d_views/30) | SGR = (7d_videos/7)/(30d_videos/30) | Opportunity = Views GR/SGR</p>
<div class="summary">
  <div class="summary-card"><div class="num">{len(channels)}</div><div class="label">Channels</div></div>
  <div class="summary-card"><div class="num">{len(niche_scores)}</div><div class="label">Niches</div></div>
</div>
<h2>Niche Level <span style="font-size:12px;color:#8878b0;font-weight:400">(sorted by Opportunity)</span></h2>
<table><thead><tr><th>Niche</th><th>Ch</th><th>Views 30d</th><th>Videos 30d</th><th>Views GR</th><th>SGR</th><th>Opportunity</th></tr></thead>
<tbody>{n_rows}</tbody></table>
<h2>Channel Level <span style="font-size:12px;color:#8878b0;font-weight:400">(sorted by Opportunity, top 100)</span></h2>
<table><thead><tr><th>Channel</th><th>Niche</th><th>Subs</th><th>Views 30d</th><th>Videos 30d</th><th>Views GR</th><th>SGR</th><th>Opportunity</th></tr></thead>
<tbody>{ch_rows}</tbody></table>
</body></html>'''
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Report: {OUTPUT}")
    webbrowser.open(str(OUTPUT.resolve()))

if __name__ == "__main__":
    generate()
