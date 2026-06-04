"""Growth metrics — formulas only, no debugging.

Channel level:
  DGR = (7d_views / 7) / (30d_views / 30)   — demand growth rate
  SGR = (7d_videos / 7) / (30d_videos / 30)  — supply growth rate
  Opportunity = DGR / SGR                     — >1 = blue ocean

Niche level (aggregated across all channels in niche):
  Same formulas but sum views/videos first, then DGR/SGR.
"""

from typing import Dict, List


# ─── Channel level ─────────────────────────────────────────────────

def dgr(ch: Dict) -> float:
    """Demand Growth Rate = daily avg views(7d) / daily avg views(30d)."""
    v7 = _int(ch, "periods", "views_7d")
    v30 = _int(ch, "periods", "views_30d")
    if v30 <= 0:
        return 0.0
    return (v7 / 7) / (v30 / 30)


def sgr(ch: Dict) -> float:
    """Supply Growth Rate = daily avg videos(7d) / daily avg videos(30d)."""
    v7 = _int(ch, "periods", "videos_7d")
    v30 = _int(ch, "periods", "videos_30d")
    if v30 <= 0:
        return 0.0
    return (v7 / 7) / (v30 / 30)


def opportunity(ch: Dict) -> float:
    """Opportunity = DGR / SGR. >1 = demand growing faster than supply."""
    d = dgr(ch)
    s = sgr(ch)
    if s <= 0:
        return 0.0
    return d / s


# ─── Niche level (aggregated) ──────────────────────────────────────

def niche_dgr(channels: List[Dict]) -> float:
    """Aggregated Demand Growth Rate for a whole niche."""
    v7 = sum(_int(c, "periods", "views_7d") for c in channels)
    v30 = sum(_int(c, "periods", "views_30d") for c in channels)
    if v30 <= 0:
        return 0.0
    return (v7 / 7) / (v30 / 30)


def niche_sgr(channels: List[Dict]) -> float:
    """Aggregated Supply Growth Rate for a whole niche."""
    v7 = sum(_int(c, "periods", "videos_7d") for c in channels)
    v30 = sum(_int(c, "periods", "videos_30d") for c in channels)
    if v30 <= 0:
        return 0.0
    return (v7 / 7) / (v30 / 30)


def niche_opportunity(channels: List[Dict]) -> float:
    """Niche Opportunity = DGR / SGR."""
    d = niche_dgr(channels)
    s = niche_sgr(channels)
    if s <= 0:
        return 0.0
    return d / s


# ─── Compute all ───────────────────────────────────────────────────

def compute_channel(ch: Dict) -> Dict:
    """Compute all metrics for a single channel."""
    return {
        "dgr": round(dgr(ch), 4),
        "sgr": round(sgr(ch), 4),
        "opportunity": round(opportunity(ch), 4),
    }


def compute_aggregated(channels: List[Dict]) -> Dict:
    """Compute aggregated metrics for a group (niche)."""
    return {
        "dgr": round(niche_dgr(channels), 4),
        "sgr": round(niche_sgr(channels), 4),
        "opportunity": round(niche_opportunity(channels), 4),
        "total_views_7d": sum(_int(c, "periods", "views_7d") for c in channels),
        "total_views_30d": sum(_int(c, "periods", "views_30d") for c in channels),
        "total_videos_7d": sum(_int(c, "periods", "videos_7d") for c in channels),
        "total_videos_30d": sum(_int(c, "periods", "videos_30d") for c in channels),
    }


# ─── Helper ────────────────────────────────────────────────────────

def _int(data: Dict, *keys: str) -> int:
    try:
        val = data
        for k in keys:
            val = val.get(k, 0)
        return int(val) if val else 0
    except (TypeError, ValueError):
        return 0
