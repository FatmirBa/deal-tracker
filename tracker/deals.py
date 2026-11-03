"""Turn price history into honest deal signals.

- low30:    today's price is at or below the lowest price we saw in the previous 30 days
- drop:     cheaper than the last different price we recorded
- inflated: the shop shows a "was" price we never saw it charge in the last 30 days
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def analyse(series: list[tuple[str, float]], price: float, claimed_old: float | None, today: str) -> dict:
    before = [(d, p) for d, p in series if d < today]
    last30 = [p for d, p in before if d >= (datetime.fromisoformat(today) - timedelta(days=30)).strftime("%Y-%m-%d")]
    days_tracked = len({d for d, _ in series})
    prev = before[-1][1] if before else None
    out = {
        "days": days_tracked,
        "prev": prev,
        "lo30": min(last30) if last30 else None,
        "hi30": max(last30) if last30 else None,
        "lo_all": min([p for _, p in series] + [price]),
        "drop_pct": round((prev - price) / prev * 100, 1) if prev and price < prev else 0.0,
        "low30": bool(last30) and days_tracked >= 3 and price <= min(last30),
        "inflated": False,
    }
    if claimed_old and claimed_old > price and days_tracked >= 7 and out["hi30"] is not None:
        out["inflated"] = out["hi30"] < claimed_old * 0.93
    return out


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
