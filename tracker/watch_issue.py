"""Add or remove a watch from a GitHub issue (created by the app's "Watch something" button).

Issue title "Watch: <what>" (issue form fills the body) or "Unwatch: <what>".
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from .prices import norm

EXTRA = Path("watch_extra.yaml")
KINDS = {"appliances": ["appliances"], "furniture": ["furniture"], "anything": ["everything"]}


def field(body: str, label_start: str) -> str:
    m = re.search(rf"###\s*{label_start}[^\n]*\n+(.*?)(?=\n###|\Z)", body or "", re.S | re.I)
    v = (m.group(1).strip() if m else "")
    return "" if v in ("_No response_", "None") else v


def main(title: str, body: str) -> str:
    data = yaml.safe_load(EXTRA.read_text(encoding="utf-8")) if EXTRA.exists() else None
    data = data or {"items": []}
    t = title.strip()
    if t.lower().startswith("unwatch:"):
        what = norm(t.split(":", 1)[1])
        before = len(data["items"])
        data["items"] = [i for i in data["items"] if norm(i["name"]) != what and i["id"] != what.replace(" ", "-")]
        EXTRA.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return f"Removed {before - len(data['items'])} watch(es) for '{what}'."
    what = field(body, "What") or t.split(":", 1)[-1].strip()
    if not what:
        return "Couldn't read what to watch. Edit the issue title to 'Watch: <product>'."
    price_raw = field(body, "Max price")
    max_price = float(re.sub(r"[^\d.]", "", price_raw.replace(",", "."))) if re.search(r"\d", price_raw) else None
    kind = field(body, "Where").lower()
    kinds = next((v for k, v in KINDS.items() if k in kind), ["everything"])
    min_raw = field(body, "Ignore under")
    min_price = float(re.sub(r"[^\d.]", "", min_raw.replace(",", "."))) if re.search(r"\d", min_raw) else 0
    iid = re.sub(r"[^a-z0-9]+", "-", norm(what)).strip("-")[:40]
    data["items"] = [i for i in data["items"] if i["id"] != iid]
    item = {"id": iid, "name": what, "kinds": kinds, "queries": [what], "match_all_words": True, "min_price": min_price}
    if max_price:
        item["max_price"] = max_price
    data["items"].append(item)
    EXTRA.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    target = f" with a {max_price:.0f} KM target" if max_price else ""
    return f"Now watching **{what}**{target}. Prices appear in the app after the next run (starting now)."


if __name__ == "__main__":
    print(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
