# Niche Research Analyzer

YouTube Shorts 藍海利基發現 + 成長分析工具。

## Quick Start

```bash
# Researcher — 找利基
python src/cli.py "minecraft animation" "roblox" -o output

# 看結果
open output/niche_wordcloud.html
open output/graph_expanded.html

# Growth Analyzer — 分析成長
python src/growth_analyzer/report.py
open output/growth_report.html
```

## Documentation

完整架構說明 → **[ARCHITECTURE.md](ARCHITECTURE.md)**
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
