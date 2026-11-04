"""Map every shop: find its search page, test extraction, save real pages for tuning.

    python -m tracker.probe [--out probe] [--render]
Writes probe/report.json (+ a readable probe/REPORT.md) and probe/<shop>.html samples.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import yaml

from .discover import discover
from .extract import extract
from .fetch import Fetcher

SAMPLE_QUERY = "veš mašina"
EXTRA_URLS = {
    "olx_api": "https://olx.ba/api/search?q=" + quote_plus("ves masina"),
    "olx_search": "https://olx.ba/pretraga?q=" + quote_plus("veš mašina"),
}


def slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", urlparse(url).netloc.replace("www.", ""))[:40].strip("_")


def probe_pages(out: Path):
    """Save the first category page per shop and item, plus what extraction makes of it (for tuning parsers)."""
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(Path("shops.yaml").read_text(encoding="utf-8"))
    f = Fetcher(delay=1.2)
    lines = []
    try:
        for shop in cfg["shops"]:
            for item, urls in (shop.get("pages") or {}).items():
                code, final, text = f.get(urls[0], render=bool(shop.get("render")))
                (out / f"{shop['id']}_{item}.html").write_text(text[:900_000], encoding="utf-8")
                prods, rep = extract(text, final, shop.get("selectors"), shop.get("url_template"))
                lines.append(f"## {shop['id']} / {item}: HTTP {code}, {len(prods)} products via {rep}")
                lines += [f"- {p.price} (old {p.old_price}) {p.title[:80]}" for p in prods[:6]]
                print(lines[-min(len(lines), 7):][0], flush=True)
    finally:
        f.close()
    (out / "PAGES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def probe_targets(out: Path, path: Path):
    """For each candidate: robots.txt, listing pages (plain, then headless if needed), search discovery."""
    out.mkdir(parents=True, exist_ok=True)
    targets = yaml.safe_load(path.read_text(encoding="utf-8"))["targets"]
    f = Fetcher(delay=1.2)
    lines, report = [], {}
    try:
        for t in targets:
            tid, home = t["id"], t["home"]
            entry = {"home": home, "pages": []}
            rc, _, robots = f.get(home.rstrip("/") + "/robots.txt")
            entry["robots_disallow_all"] = bool(rc == 200 and re.search(r"(?im)^user-agent:\s*\*\s*$(?:\n(?!user-agent).*)*?\n\s*disallow:\s*/\s*$", robots))
            for i, url in enumerate(t["urls"]):
                best = None
                for render in (False, True):
                    code, final, text = f.get(url, render=render)
                    prods, rep = ([], {}) if code == 0 or code >= 400 else extract(text, final)
                    if best is None or len(prods) > best[1]:
                        best = (render, len(prods), code, rep, prods, text)
                    if len(prods) >= 5:
                        break
                render, n, code, rep, prods, text = best
                (out / f"{tid}_{i}.html").write_text(text[:900_000], encoding="utf-8")
                entry["pages"].append({"url": url, "status": code, "render": render, "count": n, "method": rep.get("used"),
                                       "sample": [{"t": p.title[:80], "p": p.price, "o": p.old_price, "img": bool(p.image)} for p in prods[:6]]})
                lines.append(f"## {tid} [{url}] HTTP {code}, {n} products via {rep.get('used')}{' (headless)' if render else ''}")
                lines += [f"- {p.price} (old {p.old_price}) {p.title[:80]}" for p in prods[:5]]
            d = discover(f, home, max_tries=6)
            entry["search"] = d.get("search")
            entry["search_count"] = d.get("count")
            lines.append(f"   search: {d.get('search')} ({d.get('count')} products); robots blocks all: {entry['robots_disallow_all']}")
            report[tid] = entry
            print("\n".join(lines[-8:]), flush=True)
    finally:
        f.close()
    (out / "targets.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "TARGETS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="probe")
    ap.add_argument("--render", action="store_true", help="also try headless Chromium for shops that fail")
    ap.add_argument("--pages", action="store_true", help="only fetch each shop's configured category pages and save them")
    ap.add_argument("--targets", help="YAML file of candidate shops with listing URLs to test")
    args = ap.parse_args(argv)
    if args.pages:
        return probe_pages(Path(args.out))
    if args.targets:
        return probe_targets(Path(args.out), Path(args.targets))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(Path("shops.yaml").read_text(encoding="utf-8"))
    targets = [(s["id"], s["home"], s.get("search")) for s in cfg["shops"]] + [(slug(u), u, None) for u in cfg.get("candidates", [])]
    f = Fetcher(delay=1.2)
    report = {}
    try:
        for sid, home, known in targets:
            print(f"== {sid} ({home})", flush=True)
            entry = {"home": home}
            if known:
                entry["search"], entry["render"] = known, False
            else:
                d = discover(f, home)
                entry.update(d, render=False)
                if not d["search"] and args.render and d.get("home_status", 0) and d["home_status"] < 400:
                    d2 = discover(f, home, render=True, max_tries=5)
                    if d2.get("search"):
                        entry.update(d2, render=True)
            if entry.get("search"):
                url = entry["search"].replace("{q}", quote_plus(SAMPLE_QUERY))
                code, final, text = f.get(url, render=entry.get("render", False))
                prods, rep = extract(text, final, None, next((s.get("url_template") for s in cfg["shops"] if s["id"] == sid), None))
                entry["sample"] = {"url": url, "status": code, "report": rep,
                                   "products": [{"title": p.title[:90], "price": p.price, "old": p.old_price, "url": p.url} for p in prods[:8]]}
                (out / f"{sid}.html").write_text(text[:600_000], encoding="utf-8")
            else:
                code, final, text = f.get(home)
                if code:
                    (out / f"{sid}_home.html").write_text(text[:600_000], encoding="utf-8")
            report[sid] = entry
            print(json.dumps({k: entry.get(k) for k in ("search", "count", "method", "home_status", "error")}, ensure_ascii=False), flush=True)
        for name, url in EXTRA_URLS.items():
            code, final, text = f.get(url)
            (out / f"{name}.txt").write_text(f"{code} {final}\n\n{text[:400_000]}", encoding="utf-8")
    finally:
        f.close()
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["| shop | home | search template | products | method | sample |", "|---|---|---|---|---|---|"]
    for sid, e in report.items():
        s = (e.get("sample") or {}).get("products") or []
        first = f"{s[0]['title'][:40]} — {s[0]['price']}" if s else ""
        lines.append(f"| {sid} | {e.get('home_status', '')} | {e.get('search') or '—'} | {len(s)} | {(e.get('sample') or {}).get('report', {}).get('used') or e.get('method') or ''} | {first} |")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
