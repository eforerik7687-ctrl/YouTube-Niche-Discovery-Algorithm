"""Regenerate niche_wordcloud.html from cluster_report.json data."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def generate_wordcloud_html(niche_concepts, output_path):
    """Generate wordcloud HTML from cluster_report data.

    niche_concepts: {niche_id: {channel_count, keywords: [{keyword, coverage}, ...]}}
    """
    # Prepare data sorted by niche_id ascending (already ascending by channel count)
    data = []
    sorted_nids = sorted(niche_concepts.keys(), key=lambda nid: int(nid))

    for nid in sorted_nids:
        info = niche_concepts[nid]
        concepts = info["keywords"][:30]  # top 30
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
            "id": int(nid),
            "channel_count": info["channel_count"],
            "words": words,
        })

    niches_json = json.dumps(data, ensure_ascii=False)

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
    print(f"  OK {output_path} — {len(data)} niches")


def main():
    path = ROOT / "cluster_report.json"
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    niche_concepts = data["cluster_keywords"]

    # Generate from cluster_report data
    generate_wordcloud_html(niche_concepts, ROOT / "niche_wordcloud.html")


if __name__ == "__main__":
    main()
