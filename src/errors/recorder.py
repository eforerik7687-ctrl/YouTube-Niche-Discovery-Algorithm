import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ErrorRecorder:
    """Record 429/403 errors from YouTube API calls to output/errors.jsonl.

    Uses append-only JSON Lines format. Each line is one error event.
    """

    def __init__(self, output_dir: str = "output"):
        self.path = Path(output_dir) / "errors.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, error_type: str, source: str, keyword: str, detail: str = ""):
        """Append one error record."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": error_type,
            "source": source,
            "keyword": keyword,
            "detail": detail,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def recent_count(self, error_type: Optional[str] = None, minutes: int = 5) -> int:
        """Count errors recorded in the last N minutes."""
        if not self.path.exists():
            return 0
        cutoff_ts = datetime.now(timezone.utc).timestamp() - minutes * 60
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                    if ts < cutoff_ts:
                        continue
                    if error_type and entry.get("error_type") != error_type:
                        continue
                    count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        return count

    def summary(self) -> dict:
        """Return aggregated counts of recorded errors."""
        counts = {"429": 0, "403": 0}
        if not self.path.exists():
            return {"total": 0, **counts}
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    et = entry.get("error_type", "")
                    if et in counts:
                        counts[et] += 1
                except json.JSONDecodeError:
                    continue
        return {"total": sum(counts.values()), **counts}

    def classify_error(self, exc: Exception) -> Optional[str]:
        """Inspect an exception and return '429', '403', or None."""
        msg = str(exc).lower()
        code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if code in (429, 403):
            return str(code)
        for pattern in ("429", "too many requests", "rate limit"):
            if pattern in msg:
                return "429"
        for pattern in ("403", "forbidden", "access denied"):
            if pattern in msg:
                return "403"
        return None

    def print_summary(self) -> str:
        """Print a human-readable summary of errors."""
        s = self.summary()
        parts = [f"Total errors: {s['total']}"]
        if s["429"]:
            parts.append(f"429 (Rate limited): {s['429']}")
        if s["403"]:
            parts.append(f"403 (Forbidden): {s['403']}")
        return " | ".join(parts)
