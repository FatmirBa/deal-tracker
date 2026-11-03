"""Price history (append-only CSV) and product catalog (JSON) kept in the repo's data/ folder."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path("data")
HISTORY = DATA / "history.csv"
CATALOG = DATA / "catalog.json"
FIELDS = ["ts", "shop", "item", "key", "price", "old"]


def key_for(url: str) -> str:
    return hashlib.sha1(url.split("#")[0].rstrip("/").encode()).hexdigest()[:12]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(obj, ensure_ascii=False, indent=1)
    path.write_text(txt, encoding="utf-8")


def append_history(rows: list[dict]):
    DATA.mkdir(exist_ok=True)
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def daily_series(days: int = 120) -> dict[str, list[tuple[str, float]]]:
    """key -> [(YYYY-MM-DD, lowest price that day)], oldest first, limited to the last `days` days."""
    if not HISTORY.exists():
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    per: dict[str, dict[str, float]] = defaultdict(dict)
    with HISTORY.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = r["ts"][:10]
            if d < cutoff:
                continue
            try:
                p = float(r["price"])
            except (TypeError, ValueError):
                continue
            cur = per[r["key"]].get(d)
            per[r["key"]][d] = p if cur is None else min(cur, p)
    return {k: sorted(v.items()) for k, v in per.items()}
