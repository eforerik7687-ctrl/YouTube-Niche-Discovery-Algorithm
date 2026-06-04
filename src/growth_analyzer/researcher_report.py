"""Generate researcher_report.html from latest pipeline output."""
import json, re, sys, webbrowser
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

OUTPUT = Path("output/researcher_report.html")

def generate():
    # Load niche data from wordcloud (correct 1-based numbering)
    wc = Path("niche_wordcloud.html")
    if not wc.exists():
        print("No niche_wordcloud.html found. Run pipeline first.")
        return
    m = re.search(r'var niches = (\[.*?\]);', wc.read_text(encoding="utf-8"), re.DOTALL)
    if not m:
        print("No niche data in wordcloud file.")
        return
    niches = json.loads(m.group(1))

    # Load graph for all channel IDs + niche assignments
    graph_html = Path("graph_expanded.html")
    nodes = []
    if graph_html.exists():
        m2 = re.search(r'nodes = new vis\.DataSet\((\[.*?\])\s*\)', graph_html.read_text(encoding="utf-8"), re.DOTALL)
        if m2:
            nodes = json.loads(m2.group(1))

    # Build channel lookup: name -> channelId
    ch_id = {}
    for n in nodes:
        l, t = n.get('label',''), n.get('title','')
        cm = re.search(r'youtube\.com/channel/(UC\w+)', t)
        if l and cm:
            ch_id[l] = cm.group(1)

    def fmt(v):
        try: v = int(v)
        except: return str(v)
        if v >= 1e9: return f"{v/1e9:.1f}B"
        if v >= 1e6: return f"{v/1e6:.1f}M"
        if v >= 1e3: return f"{v/1e3:.0f}K"
        return str(v)

    def opp_cls(v):
        return 'opp-high' if v > 1.5 else 'opp-mid' if v > 1.0 else 'opp-low'

    # Build niche cards HTML
    niche_html = ''
    for n in niches:
        nid = n['id']
        kw = n.get('keyword', '')
        ch_count = n.get('channel_count', 0)
        total_views = n.get('total_views', 0)
        color = n.get('color', '#c8b8ff')
        desc = n.get('description', '')
        top_chs = n.get('top_channels', [])

        # Channel rows
        ch_rows = ''
        for ch in top_chs:
            cid = ch.get('channelId', '')
            url = f"https://www.youtube.com/channel/{cid}/shorts" if cid else f"https://www.youtube.com/@{ch.get('name','')}/shorts"
            ch_rows += f'''<div class="ch-row">
                <span class="ch-rank">{ch_rows.count('<div class="ch-row">') + 1}</span>
                <span class="ch-name"><a href="{url}" target="_blank">{ch['name']}</a></span>
                <span class="ch-subs">{ch.get('subs_display','')}</span>
            </div>\n'''

        # All channels from graph that belong to this niche
        niche_chs = []
        for n2 in nodes:
            label = n2.get('label','')
            title = n2.get('title','')
            nm = re.search(r'Niche (\d+)', title)
            if nm and int(nm.group(1)) == nid:
                cid = ch_id.get(label, '')
                url = f"https://www.youtube.com/channel/{cid}/shorts" if cid else f"https://www.youtube.com/@{label}/shorts"
                niche_chs.append((label, url))

        all_ch_rows = ''
        for i, (name, url) in enumerate(niche_chs[:50]):
            all_ch_rows += f'''<div class="ch-row">
                <span class="ch-rank">#{i+1}</span>
                <span class="ch-name"><a href="{url}" target="_blank">{name}</a></span>
            </div>\n'''
        if len(niche_chs) > 50:
            all_ch_rows += f'<div style="color:#8878b0;font-size:12px;padding:8px">... +{len(niche_chs)-50} more</div>'

        niche_html += f'''
        <div class="niche-card">
            <div class="niche-header">
                <span class="niche-title" style="color:{color}">Niche {nid}</span>
                <span class="niche-count">{ch_count} ch</span>
                <span class="niche-count">{fmt(total_views)} views</span>
                {f'<span class="niche-tag">{kw}</span>' if kw else ''}
            </div>
            {f'<div class="niche-desc">{desc}</div>' if desc else ''}
            <details>
                <summary>Top channels</summary>
                {ch_rows}
            </details>
            <details>
                <summary>All {len(niche_chs)} channels</summary>
                {all_ch_rows}
            </details>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Researcher Report</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0b0e1a;color:#e0d8ff;font-family:'Inter','Segoe UI',sans-serif;padding:32px}}
h1{{font-weight:500;font-size:22px;color:#c8b8ff;margin-bottom:4px}}
.subtitle{{color:#8878b0;font-size:14px;margin-bottom:24px}}
.summary{{display:flex;gap:20px;margin-bottom:24px;flex-wrap:wrap}}
.summary-card{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 20px;min-width:140px}}
.summary-card .num{{font-size:22px;font-weight:500;color:#c8b8ff}}
.summary-card .label{{font-size:11px;color:#8878b0;margin-top:2px}}
.niche-card{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:16px;margin-bottom:12px}}
.niche-header{{display:flex;align-items:baseline;gap:10px;margin-bottom:8px;flex-wrap:wrap}}
.niche-title{{font-weight:600;font-size:16px}}
.niche-count{{color:#8878b0;font-size:12px}}
.niche-tag{{font-size:11px;padding:2px 8px;border-radius:12px;background:rgba(255,255,255,0.06);color:#c8b8ff}}
.niche-desc{{font-size:13px;color:#a898c8;margin-bottom:10px;line-height:1.5}}
details{{margin-top:8px}}
summary{{cursor:pointer;font-size:13px;color:#8878b0;padding:4px 0}}
summary:hover{{color:#c8b8ff}}
.ch-row{{display:flex;align-items:center;padding:6px 8px;gap:8px;border-bottom:1px solid rgba(255,255,255,0.04)}}
.ch-row:hover{{background:rgba(255,255,255,0.03)}}
.ch-rank{{color:#8878b0;font-size:12px;width:28px;text-align:right}}
.ch-name{{flex:1}}
.ch-name a{{color:#c8b8ff;text-decoration:none;font-weight:500;font-size:13px}}
.ch-name a:hover{{color:#fff;text-decoration:underline}}
.ch-subs{{color:#8878b0;font-size:11px;min-width:80px;text-align:right}}
.result-links{{display:flex;gap:12px;margin-bottom:20px}}
.result-links a{{padding:8px 16px;background:rgba(200,184,255,0.06);border:1px solid rgba(200,184,255,0.12);border-radius:8px;color:#c8b8ff;text-decoration:none;font-size:13px}}
.result-links a:hover{{background:rgba(200,184,255,0.12)}}
</style></head><body>
<h1>Researcher Report</h1>
<p class="subtitle">Niche discovery results</div>
<div class="summary">
  <div class="summary-card"><div class="num">{len(niches)}</div><div class="label">Niches</div></div>
  <div class="summary-card"><div class="num">{sum(n.get('channel_count',0) for n in niches)}</div><div class="label">Channels</div></div>
</div>
<div class="result-links">
  <a href="graph_expanded.html" target="_blank">Network Graph</a>
  <a href="growth_report.html" target="_blank">Growth Analyzer</a>
</div>
{niche_html}
</body></html>'''

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Report: {OUTPUT}")
    webbrowser.open(str(OUTPUT.resolve()))

if __name__ == "__main__":
    generate()
