"""One tracker run: search every shop for every watched item, record prices, publish data for the app, send alerts.

    python -m tracker.run            # normal run (what the GitHub schedule does)
    python -m tracker.run --shop olx # only one shop, handy when tuning
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import yaml

from . import alerts
from .deals import analyse, today_str
from .discover import discover
from .extract import extract
from .fetch import Fetcher
from .prices import model_code, norm
from .store import (CATALOG, append_history, daily_series, key_for, load_json, save_json)

DISCOVERED = Path("data/discovered.json")
OUT = Path("docs/data")


def load_config():
    shops_cfg = yaml.safe_load(Path("shops.yaml").read_text(encoding="utf-8"))
    watch = yaml.safe_load(Path("watchlist.yaml").read_text(encoding="utf-8"))
    extra_path = Path("watch_extra.yaml")
    if extra_path.exists():
        extra = yaml.safe_load(extra_path.read_text(encoding="utf-8")) or {}
        watch["items"] = watch["items"] + (extra.get("items") or [])
    return shops_cfg, watch


def accepts(title: str, price: float, item: dict, common_exclude: list[str], marketplace: bool) -> bool:
    t = norm(title)
    must = [norm(m) for m in item.get("must_any") or []]
    if must and not any(m in t for m in must):
        return False
    if item.get("match_all_words"):
        words = [w for w in norm(item["queries"][0]).split() if len(w) >= 3]
        if not all(w in t for w in words):
            return False
    for ex in list(common_exclude) + list(item.get("exclude") or []):
        if norm(ex) in t:
            return False
    floor = item.get("min_price") or 0
    if marketplace:
        floor *= 0.35  # used items on OLX can be far cheaper
    return price >= floor


def crawl(shops_cfg, watch, only_shop=None):
    f = Fetcher(delay=shops_cfg.get("delay_seconds", 1.5))
    disc = load_json(DISCOVERED, {})
    now = datetime.now(timezone.utc)
    found: dict[str, dict] = {}
    status: dict[str, dict] = {}
    common_ex = watch.get("common_exclude") or []
    try:
        for shop in shops_cfg["shops"]:
            if only_shop and shop["id"] != only_shop:
                continue
            sid = shop["id"]
            st = {"name": shop["name"], "ok": False, "count": 0, "requests": 0, "errors": 0, "method": None}
            template = shop.get("search") or (disc.get(sid) or {}).get("search")
            render = bool(shop.get("render") or (disc.get(sid) or {}).get("render"))
            last_try = (disc.get(sid) or {}).get("at", "")
            if not template and last_try < (now - timedelta(hours=20)).isoformat():
                d = discover(f, shop["home"], render=render)
                if not d["search"] and not render:
                    d2 = discover(f, shop["home"], render=True)
                    if d2.get("search") and d2["count"] > d["count"]:
                        d, render = d2, True
                d.update(at=now.isoformat(), render=render)
                disc[sid] = {k: d.get(k) for k in ("search", "count", "method", "render", "at", "home_status", "error")}
                template = d["search"]
            if not template:
                st["note"] = "search page not found yet"
                status[sid] = st
                print(f"[{sid}] skipped: no search page found", flush=True)
                continue
            kinds = set(shop.get("kinds") or ["everything"])
            for item in watch["items"]:
                item_kinds = set(item.get("kinds") or ["everything"])
                if not (kinds & item_kinds or "everything" in kinds):
                    continue
                for q in item["queries"]:
                    url = template.replace("{q}", quote_plus(q))
                    code, final, text = f.get(url, render=render)
                    st["requests"] += 1
                    if code == 0 or code >= 400:
                        st["errors"] += 1
                        continue
                    prods, rep = extract(text, final, shop.get("selectors"), shop.get("url_template"))
                    st["method"] = st["method"] or rep.get("used")
                    for p in prods:
                        if not accepts(p.title, p.price, item, common_ex, bool(shop.get("marketplace"))):
                            continue
                        k = key_for(p.url)
                        if k in found:
                            continue
                        found[k] = {"k": k, "t": p.title, "u": p.url, "img": p.image, "s": sid, "i": item["id"],
                                    "p": round(p.price, 2), "o": round(p.old_price, 2) if p.old_price else None,
                                    "m": model_code(p.title)}
                        st["count"] += 1
            st["ok"] = st["count"] > 0
            status[sid] = st
            print(f"[{sid}] {st['count']} products from {st['requests']} searches ({st['errors']} errors) via {st['method']}", flush=True)
            if st["count"] == 0 and not shop.get("search") and sid in disc:
                disc[sid]["search"] = None  # rediscover next time
    finally:
        f.close()
        save_json(DISCOVERED, disc)
    return found, status


def publish(found, status, shops_cfg, watch, first_run: bool):
    today = today_str()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    append_history([{"ts": ts, "shop": p["s"], "item": p["i"], "key": k, "price": p["p"], "old": p["o"] or ""} for k, p in found.items()])
    catalog = load_json(CATALOG, {})
    for k, p in found.items():
        c = catalog.get(k) or {"first_seen": today}
        c.update(t=p["t"], u=p["u"], img=p["img"], s=p["s"], i=p["i"], m=p["m"], last_seen=today)
        catalog[k] = c
    save_json(CATALOG, catalog, compact=True)

    series = daily_series(120)
    products = []
    for k, p in found.items():
        a = analyse(series.get(k, []), p["p"], p["o"], today)
        hist = series.get(k, [])[-60:]
        products.append(p | a | {"fs": catalog[k]["first_seen"], "h": [[d[5:], v] for d, v in hist]})
    products.sort(key=lambda x: (x["i"], x["p"]))

    items = {it["id"]: it for it in watch["items"]}
    shops = {s["id"]: s for s in shops_cfg["shops"]}
    data = {
        "generated": ts,
        "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "items": [{"id": it["id"], "name": it["name"], "target": it.get("max_price")} for it in watch["items"]],
        "shops": [{"id": sid, "name": st["name"], "ok": st["ok"], "count": st["count"], "note": st.get("note")} for sid, st in status.items()],
        "products": products,
    }
    save_json(OUT / "products.json", data, compact=True)

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    app_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" if "/" in repo else ""
    picks = alerts.pick_alerts(products, items, shops)
    msg = alerts.format_message(picks, items, shops, app_url, first_run, len(products))
    if msg and alerts.send(msg):
        print(f"Telegram: sent {len(picks)} alerts")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop")
    args = ap.parse_args(argv)
    t0 = time.time()
    shops_cfg, watch = load_config()
    first_run = not Path("data/history.csv").exists()
    found, status = crawl(shops_cfg, watch, args.shop)
    data = publish(found, status, shops_cfg, watch, first_run)
    print(f"Done: {len(data['products'])} products from {sum(1 for s in status.values() if s['ok'])}/{len(status)} shops in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
