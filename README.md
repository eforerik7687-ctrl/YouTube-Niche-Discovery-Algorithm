# YouTube Niche Discovery Researcher

Discover blue-ocean YouTube niches via keyword co-occurrence networks and Louvain community detection.

## How it works

1. **Keyword Expansion** — YouTube Search Suggestions API (7 languages × 7 geographies)
2. **Channel Matrix** — Search all expanded keywords, build channel×keyword matrix
3. **Cosine Similarity** — Connect channels with similarity > 0.5
4. **Community Detection** — Louvain algorithm finds natural niche clusters
5. **Keyword Coverage** — Each niche's defining keywords ranked by channel coverage

## Quick Start

```bash
pip install -r requirements.txt
python src/cli.py minecraft -o output
```

Open `output/niche_wordcloud.html` and `output/graph_7plus7.html` in your browser.

## Configuration

Copy `.env.example` to `.env` and adjust:
- `SEED_KEYWORDS` — comma-separated seed keywords
- `DELAY_MIN` / `DELAY_MAX` — random delay between searches (anti-ban)
- `PROXY_LIST` — comma-separated proxies for IP rotation

## Outputs

- `niche_wordcloud.html` — 2×2 grid word clouds per niche (4 per scroll page)
- `graph_7plus7.html` — interactive Pyvis network graph
- `cluster_report.json` — structured niche data (channel_count, keywords, coverage)
