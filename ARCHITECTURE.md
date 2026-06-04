# Niche Research Analyzer — Architecture

> 兩套 pipeline：**Niche Researcher**（找利基）+ **Growth Analyzer**（分析成長）

---

## 目錄

1. [System Overview](#1-system-overview)
2. [Niche Researcher Pipeline](#2-niche-researcher-pipeline)
3. [Growth Analyzer Pipeline](#3-growth-analyzer-pipeline)
4. [File Structure](#4-file-structure)
5. [Data Flow](#5-data-flow)
6. [Formulas](#6-formulas)
7. [Anti-Ban Measures](#7-anti-ban-measures)
8. [API Quota](#8-api-quota)
9. [Filters](#9-filters)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   NICHE RESEARCHER                          │
│  keywords / seed channels → 7geo discovery                  │
│  → Shorts filter → cosine similarity → Louvain              │
│  → filter → InnerTube expand → cleanup → export             │
│                                                             │
│  輸出: graph_expanded.html, niche_wordcloud.html,           │
│        cluster_report.json, socialblade_data.json           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   GROWTH ANALYZER                            │
│  Social Blade crawl → DGR/SGR/Opportunity                    │
│  → Niche Level + Channel Level 排名表                       │
│                                                             │
│  輸出: growth_report.html, researcher_report.html            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Niche Researcher Pipeline

### Step 0: Discovery

**Keywords Mode:**
```
Input:  "minecraft animation", "roblox"
Process: YouTube Search Suggestions × 7 geos (US/IN/GB/PH/NG/AU/CA)
         每個地區對每個關鍵字產生 ~30 建議關鍵字
         搜尋每個建議關鍵字 → 收集 channels + keywords
Output: {channel_name: {keyword: weight, ...}}
Cost:   0 quota (不是 YouTube Data API)
Time:   ~5s per keyword × 7 geo
```

**Seed Channels Mode:**
```
Input:  @Ayahitoo, @RealBacon
Process: InnerTube search → resolve handle to channel ID
         InnerTube browse → metadata keywords + topics + description
         Add to keyword pool (no related channels)
         Keywords isolated from propagation
Cost:   0 quota (InnerTube internal API)
Time:   ~5s per seed
```

### Step 1: Shorts Filter

```
Input:  {channel_name: url}
Process: HTTP GET {url}/shorts → count richItemRenderer
         threshold: > 3 = Shorts channel
         concurrent: 20, anti-ban: UA rotation + random delay
Output: filtered channel_keywords
Time:   ~1s per channel
```

### Step A: YouTube Data API — channels.list

```
Input:  channel IDs (up to 50 per call)
Process: GET youtube/v3/channels?part=statistics&id=...
         batch 50 IDs per call
         Inject __views__ into keyword vectors (log-scale)
Output: real_stats {channel_id: {viewCount, subscriberCount, videoCount}}
Cost:   1 unit per call (~17 units for 800 channels)
```

### Step B: Cosine Similarity

```
Input:  channel_keywords dict
Process: 兩兩餘弦相似度計算
         threshold: ≥ 0.5
Output: {(ch_a, ch_b): similarity} + channel graph edges
```

### Step C: Keyword Propagation

```
Input:  channel_keywords + similarities
Process: 每個 channel 吸收 neighbor keywords（weighted merge）
         移除 __views__ synthetic keyword
         移除 seed channel keywords from other channels
Output: propagated keyword vectors
```

### Step D: Louvain Community Detection

```
Input:  channel graph
Process: Louvain algorithm → natural community division
         compute_niche_concepts (top 20 keywords by coverage %)
Output: clusters {niche_id: [channel_names]}
```

### Step E: ViewCount Filter

```
Input:  clusters + real_stats
Process: Remove channels with viewCount < 10,000,000
         Remove empty niches (min_niche_size = 1)
Output: filtered clusters
```

### Step F: InnerTube Expand

```
Input:  filtered clusters (all channels)
Process: 每個 channel → InnerTube browse → related channels
         New channels → Shorts verification (richItemRenderer > 3)
         Majority voting → assign to existing niche
         Add edges in graph (no orphan nodes)
Output: expanded clusters
Cost:   0 quota
Time:   ~2.5s per channel
```

### Step G: Post-Expand Cleanup

```
Input:  expanded clusters
Process: Remove niches with < 10 channels OR < 500M total views
         Renumber: 1-based, sort by total views descending
Output: final clusters
```

### Step H: Export

```
1. graph_expanded.html    — Pyvis interactive channel graph
2. niche_wordcloud.html   — Niche Report (keyword + description + top 3)
3. cluster_report.json     — Structured data
4. niche_data_for_llm.json — LLM description generation data
```

---

## 3. Growth Analyzer Pipeline

### Input

```
Researcher output:
  - socialblade_data.json (from Social Blade crawl)
  - graph_expanded.html (for channel → niche mapping)
  - niche_wordcloud.html (for niche names/colors)
```

### Process

**Social Blade Crawl** (`src/growth_analyzer/socialblade.py`):
```
Playwright + real Chrome → socialblade.com/youtube/handle/{handle}
Extract:
  - Total subs / views / videos (always available)
  - Last 30 Days summary: subs, views, videos
  - Daily table: 14 rows of views_delta / videos_delta per day
  - Bonus: Creator Statistics 30d (when available)

Anti-ban: real Chrome (channel='chrome'), UA rotation, 8-12s delay
Cost: 0 (no API key needed)
```

**Metrics Computation** (`src/growth_analyzer/metrics.py`):
```
Channel Level:
  Views GR = (views_7d / 7) / (views_30d / 30)
  Video GR = (videos_7d / 7) / (videos_30d / 30)
  Opportunity = Views GR / Video GR

Niche Level (aggregated):
  Same formulas, sum all channels in niche first
```

### Output

```
growth_report.html      — Niche Level + Channel Level tables (sorted by Opp)
researcher_report.html  — Niche cards with all channels
```

---

## 4. File Structure

```
youtube-niche-finder/
├── app.py                          # Flask desktop app (optional)
├── src/
│   ├── cli.py                      # Pipeline orchestrator
│   ├── config.py                   # Config (.env loader)
│   ├── innertube.py                # InnerTube API client + anti-ban
│   ├── youtube_api.py              # YouTube Data API v3 wrapper
│   ├── _patched.py                 # tubescrape anti-ban patch
│   ├── _token.py                   # PO Token extraction (Playwright)
│   ├── models.py                   # Data models
│   ├── shorts_verifier.py          # Shorts verification
│   ├── analysis/
│   │   ├── propagator.py           # Keyword propagation + similarity
│   │   └── community.py            # Louvain + graph export + niche report
│   ├── growth_analyzer/
│   │   ├── __init__.py
│   │   ├── socialblade.py          # Social Blade crawler (Playwright)
│   │   ├── metrics.py              # DGR/SGR/Opportunity formulas
│   │   ├── report.py               # Growth Analyzer HTML report
│   │   └── researcher_report.py    # Researcher HTML report
│   ├── socialblade/                # (deprecated, moved to growth_analyzer)
│   └── collector/
│       └── collector.py            # tubescrape collection
├── templates/                      # Flask web templates
├── output/                         # Generated output files
├── .env                            # API keys
├── dashboard.html                  # GitHub Pages dashboard
├── sb_cookies.json                 # Social Blade session cookies
├── socialblade_data.json           # Crawled Social Blade data
├── create_shortcut.py              # Desktop shortcut creator
└── start.bat                       # Desktop launcher
```

---

## 5. Data Flow

```
Keywords / Seeds
     │
     ▼
[7geo Discovery] ────→ channel_keywords {name: {keyword: weight}}
     │
     ▼
[Shorts Filter] ────→ filtered channels
     │
     ▼
[API channels.list] ──→ real_stats + __views__ injection
     │
     ▼
[Cosine Similarity] ──→ similarities {(a,b): score}
     │
     ▼
[Propagation] ──────→ propagated {name: {keyword: weight}}
     │
     ▼
[Louvain] ───────────→ clusters {niche_id: [names]}
     │
     ▼
[ViewCount Filter] ──→ filtered clusters
     │
     ▼
[InnerTube Expand] ──→ expanded clusters (+Shorts verify)
     │
     ▼
[Post-Cleanup] ──────→ final clusters (1-based, views desc)
     │
     ▼
[Export] ────────────→ graph_expanded.html
                       niche_wordcloud.html
                       cluster_report.json
                       socialblade_data.json
                            │
                            ▼
                   [Growth Analyzer]
                       Social Blade crawl
                       → DGR/SGR/Opportunity
                       → growth_report.html
```

---

## 6. Formulas

### Channel Level

| Metric | Formula | Data Source | Meaning |
|--------|---------|-------------|---------|
| Views GR | `(views_7d / 7) / (views_30d / 30)` | Social Blade daily table / summary | >1 = demand accelerating |
| Video GR | `(videos_7d / 7) / (videos_30d / 30)` | Social Blade daily table / summary | >1 = supply accelerating |
| Opportunity | `Views GR / Video GR` | Computed | **>1 = blue ocean** (demand > supply) |

### Niche Level (Aggregated)

```
Niche Views GR = (sum views_7d / 7) / (sum views_30d / 30)
Niche Video GR = (sum videos_7d / 7) / (sum videos_30d / 30)
Niche Opportunity = Niche Views GR / Niche Video GR
```

---

## 7. Anti-Ban Measures

| Layer | Method | Applied To |
|-------|--------|------------|
| UA rotation | 8 browser-grade UAs, cycled per request | InnerTube, Shorts check, Social Blade |
| Random delay | 0.5-2.5s (adjustable) | All HTTP requests |
| Proxy rotation | Every 10 requests (optional) | InnerTube |
| Retry | 429/5xx: 3 attempts, exp. backoff | InnerTube |
| Browser headers | Sec-Fetch-*, DNT, Accept-Language | All HTTP requests |
| PO Token | Playwright extraction | tubescrape InnerTube |
| Real Chrome | `channel='chrome'` not headless Chromium | Social Blade |
| Webdriver hide | `navigator.webdriver = undefined` | Social Blade |
| Batch processing | 10 channels at a time, save after each | Social Blade |

---

## 8. API Quota

| Component | Quota Cost | Limits |
|-----------|-----------|--------|
| YouTube Data API channels.list | 1 unit/call (50 IDs) | 10,000 units/day |
| YouTube Search Suggestions | 0 units | None |
| InnerTube browse | 0 units | None (YouTube internal API) |
| Social Blade crawl | 0 units | None (Playwright + Chrome) |

**Typical run: ~17 units / 10,000 daily (< 0.2%)**

---

## 9. Filters

```
Sequential filter chain:

1. Shorts Filter        → richItemRenderer > 3
2. ViewCount Filter     → viewCount >= 10,000,000
3. Expand Shorts Filter → richItemRenderer > 3 (new channels)
4. Post-Cleanup         → channels >= 10 AND total views > 500M
```

## 10. Pipeline 時間

| Channels | Expand 模式 | 總時間 |
|---------|-------------|-------|
| ~300 (3 kw) | Top 50 | ~12 min |
| ~800 (6 kw) | Top 50 | ~15 min |
| ~800 (6 kw) | All | ~30 min |
| ~2000 (8 kw) | Top 100 | ~40 min |

---

*Last updated: 2026-06-05*
