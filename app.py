"""Niche Researcher + Growth Analyzer — Flask desktop app."""
import asyncio
import csv
import json
import os
import sys
import threading
import time
from pathlib import Path
from queue import Queue
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__)
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ─── Helpers ───────────────────────────────────────────────────────

def send_event(q, type, **kwargs):
    q.put({"type": type, **kwargs})

def stream_from_queue(q):
    while True:
        msg = q.get()
        if msg is None:
            break
        yield f"data: {json.dumps(msg)}\n\n"

def load_niche_report():
    """Load the latest niche data from wordcloud HTML."""
    import re
    path = OUTPUT_DIR / "niche_wordcloud.html"
    if not path.exists():
        path = Path("niche_wordcloud.html")
    if not path.exists():
        return None

    html = path.read_text(encoding="utf-8")
    match = re.search(r"var niches = (\[.*?\]);", html, re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(1))


# ─── Researcher ────────────────────────────────────────────────────

def run_pipeline_thread(keywords, seeds, q):
    """Run pipeline in background thread, sending progress events."""
    import asyncio
    from src.cli import run_pipeline
    from src.config import Config
    import sys

    send_event(q, type="progress", text="Starting pipeline...\n", pct=5)

    async def run():
        config = Config.from_env()
        config.output_dir = "output"

        # Patch the print function to capture output
        original_print = __builtins__.print
        captured_lines = []

        def patched_print(*args, **kwargs):
            text = " ".join(str(a) for a in args) + "\n"
            captured_lines.append(text)
            pct = min(95, 5 + len(captured_lines) * 2)
            send_event(q, type="progress", text=text, pct=pct)
            original_print(*args, **kwargs)

        __builtins__.print = patched_print

        try:
            result = await run_pipeline(keywords, config, seed_channels=seeds)
            __builtins__.print = original_print

            # Build niche data for display
            niches_json = load_niche_report()
            graph_file = str(result.get("graph", "")).replace("\\", "/")
            wc_file = str(result.get("wordcloud", "")).replace("\\", "/")

            # Save channel list for analyzer
            _save_channels_for_analyzer(result)

            send_event(q, type="done", data={
                "niches": niches_json or [],
                "graph": graph_file,
                "wordcloud": wc_file,
            })
        except Exception as e:
            __builtins__.print = original_print
            send_event(q, type="error", text=str(e))

    asyncio.run(run())

def _save_channels_for_analyzer(result):
    """Extract channel list from pipeline result for analyzer."""
    # Channels are best extracted from graph_expanded.html
    graph_path = result.get("graph", "")
    if graph_path:
        import re
        html = Path(graph_path).read_text(encoding="utf-8")
        match = re.search(r"nodes = new vis\.DataSet\((\[.*?\])\s*\)", html, re.DOTALL)
        if match:
            nodes = json.loads(match.group(1))
            channels = []
            for n in nodes:
                title = n.get("title", "")
                label = n.get("label", "")
                niche_m = re.search(r"Niche (\d+)", title)
                channelId_m = re.search(r"youtube\.com/channel/(UC\w+)", title)
                channels.append({
                    "name": label,
                    "niche_id": int(niche_m.group(1)) if niche_m else 0,
                    "channelId": channelId_m.group(1) if channelId_m else "",
                })
            Path("output/channels_for_analyzer.json").write_text(
                json.dumps(channels, indent=2), encoding="utf-8")


# ─── Analyzer ──────────────────────────────────────────────────────

def run_analyzer_thread(q):
    """Social Blade crawl + metrics computation."""
    from src.growth_analyzer.metrics import compute_channel, compute_aggregated
    import csv, json

    send_event(q, type="progress", text="Loading channels from Researcher...\n", pct=5)

    # Load channels from researcher output
    channels_file = Path("output/channels_for_analyzer.json")
    if not channels_file.exists():
        send_event(q, type="error", text="No researcher data found. Run Researcher first.")
        return

    channels = json.loads(channels_file.read_text())
    if not channels:
        send_event(q, type="error", text="No channels found in researcher data.")
        return

    send_event(q, type="progress", text=f"Found {len(channels)} channels. Starting Social Blade crawl...\n", pct=10)

    # Social Blade crawl
    from src.growth_analyzer.socialblade import SocialBladeCrawler
    crawl_data = {}
    handles_data = []

    for ch in channels:
        handle = ch["name"].lower().replace(" ", "").replace("'", "").replace(".", "")
        handle = "".join(c for c in handle if ord(c) < 128)
        handles_data.append({"handle": handle, "name": ch["name"], "niche_id": ch["niche_id"], "channelId": ch.get("channelId", "")})

    # Save handles for crawl
    handles_file = Path("output/sb_handles.json")
    handles_file.write_text(json.dumps(handles_data, indent=2), encoding="utf-8")

    send_event(q, type="progress", text=f"Crawling {len(handles_data)} channels via Social Blade...\n", pct=15)

    # Crawl in batches
    crawler = SocialBladeCrawler(delay_range=(8, 12))
    total = len(handles_data)

    for i in range(0, total, 10):
        batch = handles_data[i:i+10]
        batch_data = crawler.scan_channels(batch)
        crawl_data.update(batch_data)

        pct = 15 + int((i + len(batch)) / total * 55)
        send_event(q, type="progress", text=f"  Crawled {min(i+10, total)}/{total} channels...\n", pct=pct)

    send_event(q, type="progress", text="Computing metrics...\n", pct=75)

    # Build metrics
    # Channel-level
    channel_metrics = []
    for ch in handles_data:
        raw = crawl_data.get(ch["handle"], {})
        if not raw.get("total", {}).get("subs"):
            continue
        m = compute_channel(raw)
        channel_metrics.append({
            "name": ch["name"],
            "channelId": ch.get("channelId", ""),
            "niche_id": ch["niche_id"],
            "subs": raw.get("total", {}).get("subs", 0),
            "views_30d": raw.get("periods", {}).get("views_30d", 0),
            "videos_30d": raw.get("periods", {}).get("videos_30d", 0),
            "dgr": m["dgr"],
            "sgr": m["sgr"],
            "opportunity": m["opportunity"],
        })

    # Niche-level (aggregated)
    from collections import defaultdict
    niche_channels = defaultdict(list)
    for ch in channel_metrics:
        niche_channels[ch["niche_id"]].append(ch)

    # Load niche metadata from report
    niche_report = load_niche_report() or []
    niche_meta = {n["id"]: n for n in niche_report}

    niche_metrics = []
    for nid, chs in niche_channels.items():
        meta = niche_meta.get(nid, {})
        raw_chs = [crawl_data.get(h["handle"], {}) for h in handles_data if h["niche_id"] == nid and crawl_data.get(h["handle"], {}).get("total", {}).get("subs")]
        agg = compute_aggregated(raw_chs)
        niche_metrics.append({
            "id": nid,
            "keyword": meta.get("keyword", ""),
            "color": meta.get("color", "#8878b0"),
            "channel_count": len(chs),
            "views_30d": agg["total_views_30d"],
            "videos_30d": agg["total_videos_30d"],
            "dgr": agg["dgr"],
            "sgr": agg["sgr"],
            "opportunity": agg["opportunity"],
        })

    send_event(q, type="progress", text="Done!\n", pct=100)
    send_event(q, type="done", data={
        "niches": sorted(niche_metrics, key=lambda x: -x["opportunity"]),
        "channels": sorted(channel_metrics, key=lambda x: -x["opportunity"]),
    })


# ─── Flask Routes ──────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("researcher.html", active="researcher")

@app.route("/analyzer")
def analyzer():
    return render_template("analyzer.html", active="analyzer")

@app.route("/api/run_pipeline")
def api_run_pipeline():
    keywords = json.loads(request.args.get("keywords", "[]"))
    seeds = json.loads(request.args.get("seeds", "[]"))
    q = Queue()
    t = threading.Thread(target=run_pipeline_thread, args=(keywords, seeds, q), daemon=True)
    t.start()
    return Response(stream_from_queue(q), mimetype="text/event-stream")

@app.route("/api/run_analyzer")
def api_run_analyzer():
    q = Queue()
    t = threading.Thread(target=run_analyzer_thread, args=(q,), daemon=True)
    t.start()
    return Response(stream_from_queue(q), mimetype="text/event-stream")

@app.route("/niche/<int:nid>")
def niche_detail(nid):
    niches = load_niche_report()
    if not niches:
        return "No data"
    niche = None
    for n in niches:
        if n["id"] == nid:
            niche = n
            break
    if not niche:
        return "Niche not found"

    # Load all channels from graph
    import re
    graph_path = Path("output/graph_expanded.html")
    if not graph_path.exists():
        graph_path = Path("graph_expanded.html")

    if graph_path.exists():
        html = graph_path.read_text(encoding="utf-8")
        match = re.search(r"nodes = new vis\.DataSet\((\[.*?\])\s*\)", html, re.DOTALL)
        if match:
            nodes = json.loads(match.group(1))
            # Filter by niche from title field
            channels = []
            for n in nodes:
                title = n.get("title", "")
                label = n.get("label", "")
                niche_m = re.search(r"(\d+)\s*ch", title)
                if not niche_m:
                    continue
                # Extract color to match niche
                channelId_m = re.search(r"youtube\.com/channel/(UC\w+)", title)
                subs_m = re.search(r"([\d.]+[BMK]?)\s*subs", title, re.IGNORECASE)
                channels.append({
                    "name": label,
                    "channelId": channelId_m.group(1) if channelId_m else "",
                    "subs_display": subs_m.group(1) if subs_m else "",
                })
            channels.sort(key=lambda c: _parse_subs(c["subs_display"]), reverse=True)
            return render_template("niche_detail.html", niche=niche, channels=channels)

    return render_template("niche_detail.html", niche=niche, channels=[])

@app.route("/file/<path:filename>")
def serve_file(filename):
    return send_from_directory("output", filename)

def _parse_subs(s):
    try:
        if "M" in s: return int(float(s.replace("M","")) * 1_000_000)
        if "K" in s: return int(float(s.replace("K","")) * 1_000)
        return int(s)
    except: return 0


# ─── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import threading
    import time

    flask_ready = threading.Event()
    def start_flask():
        app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1.5)  # Wait for Flask to start

    try:
        import webview
        webview.create_window(
            "Niche Research Analyzer",
            "http://127.0.0.1:5000",
            width=1400,
            height=900,
            resizable=True,
            icon="niche_icon.ico",
            min_size=(900, 600),
        )
        webview.start()
    except ImportError:
        import webbrowser
        print("PyWebView not installed. Opening in browser instead.")
        print("Install with: pip install pywebview")
        webbrowser.open("http://127.0.0.1:5000")
        input("Press Enter to stop...")
