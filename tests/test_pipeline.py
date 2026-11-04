import csv, json, os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml
import tracker.run as run
from tracker.store import key_for

HOME = '<html><body><form action="/pretraga" method="get"><input type="search" name="q"></form></body></html>'

def cards(items):
    lis = "".join(f'<div class="product-item"><a href="/p/{slug}"><img src="/i/{slug}.jpg"><h3 class="product-name">{t}</h3></a>'
                  f'<span class="price-old">{o} KM</span><span class="price-new">{p} KM</span></div>' if o else
                  f'<div class="product-item"><a href="/p/{slug}"><img src="/i/{slug}.jpg"><h3 class="product-name">{t}</h3></a><span class="price-new">{p} KM</span></div>'
                  for slug, t, p, o in items)
    return f'<html><body><div class="grid">{lis}</div></body></html>'

WASHERS = [("gorenje-wnei84aps", "Gorenje veš mašina WNEI84APS 8kg", 579, 799), ("beko-b3wfu", "Beko mašina za veš B3WFU57215W 7kg", 529, None),
           ("bosch-wan28", "Bosch perilica rublja WAN28281BY 8kg", 749, 899), ("crijevo", "Crijevo za veš mašinu 1.5m", 19, None)]
DISH = [("beko-dvn", "Beko mašina za suđe DVN05320W", 599, 699), ("bosch-sms2", "Bosch mašina za suđe SMS2ITW08E", 829, None), ("tablete", "Finish tablete za mašinu za suđe", 35, None)]
SOFA = [("ugao-1", "Ugaona garnitura Alba na razvlačenje", 1190, 1490), ("ugao-2", "Ugaona garnitura Rio siva", 899, None), ("jastuk", "Jastuk za garnituru", 25, None)]

class FakeFetcher:
    def __init__(self, delay=0, timeout=0): pass
    def close(self): pass
    def get(self, url, render=False):
        if url.rstrip("/").endswith("domod.test") or url.endswith("jysk.test/"):
            return 200, url, HOME
        if "domod.test/pretraga?q=" in url:
            q = url.split("q=")[1].lower()
            if "ves" in q or "ve%c5%a1" in q or "perilica" in q: return 200, url, cards(WASHERS)
            if "su" in q or "posu" in q: return 200, url, cards(DISH)
            if "frizider" in q: return 200, url, cards(WASHERS[:3])
            return 200, url, cards([])
        if "jysk.test/pretraga?q=" in url:
            return 200, url, cards(SOFA)
        if "olx.test" in url:
            data = {"props": {"pageProps": {"data": [{"id": 9, "title": "Gorenje veš mašina WNEI84APS polovna", "price": 300},
                                                      {"id": 10, "title": "Veš mašina Candy CS 1072", "price": 220}]}}}
            return 200, url, f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'
        return 404, url, ""

def setup(tmp_path):
    os.chdir(tmp_path)
    src = Path(__file__).resolve().parents[1]
    Path("watchlist.yaml").write_text((src / "watchlist.yaml").read_text())
    Path("shops.yaml").write_text(yaml.safe_dump({"delay_seconds": 0, "shops": [
        {"id": "domod", "name": "Domod", "home": "https://domod.test", "kinds": ["appliances"]},
        {"id": "jysk", "name": "JYSK", "home": "https://jysk.test/", "kinds": ["furniture"]},
        {"id": "olx", "name": "OLX", "home": "https://olx.test", "search": "https://olx.test/pretraga?q={q}", "kinds": ["appliances", "furniture", "everything"],
         "marketplace": True, "url_template": "https://olx.test/artikal/{id}", "alerts": False}]}))

def test_pipeline(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    # a week of history: the Gorenje washer used to cost 699, the Beko dishwasher always 599
    gk, bk = key_for("https://domod.test/p/gorenje-wnei84aps"), key_for("https://domod.test/p/beko-dvn")
    Path("data").mkdir()
    with open("data/history.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["ts", "shop", "item", "key", "price", "old"])
        for d in range(8, 0, -1):
            day = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%dT10:00:00Z")
            w.writerow([day, "domod", "washer", gk, 699, 799]); w.writerow([day, "domod", "dishwasher", bk, 599, 699])
    sent = []
    monkeypatch.setattr(run.alerts, "send", lambda m: sent.append(m) or True)
    pushed = []
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.setattr(run.alerts.requests, "post", lambda url, data=None, headers=None, timeout=None: pushed.append((url, headers, data)) or type("R", (), {"ok": True})())
    assert run.main([]) == 0
    data = json.loads(Path("docs/data/products.json").read_text())
    titles = {p["t"]: p for p in data["products"]}
    assert "Crijevo za veš mašinu 1.5m" not in titles and "Finish tablete za mašinu za suđe" not in titles and "Jastuk za garnituru" not in titles
    g = titles["Gorenje veš mašina WNEI84APS 8kg"]
    assert g["p"] == 579 and g["low30"] and g["drop_pct"] > 15 and g["m"] == "WNEI84APS" and g["days"] == 9
    b = titles["Beko mašina za suđe DVN05320W"]
    assert b["inflated"] is True   # shop says "was 699" but we only ever saw 599
    assert titles["Ugaona garnitura Rio siva"]["i"] == "sofa" and titles["Ugaona garnitura Rio siva"]["s"] == "jysk"
    assert any(p["s"] == "olx" and p["p"] == 220 for p in data["products"])
    assert json.loads(Path("data/discovered.json").read_text())["domod"]["search"] == "https://domod.test/pretraga?q={q}"
    assert sent and "Real drop −17%, under your 600 KM target" in sent[0] and "WNEI84APS" in sent[0] and "olx.test" not in sent[0]
    assert any(h.get("Click") == "https://domod.test/p/gorenje-wnei84aps" and b"579 KM" in d for _, h, d in pushed), pushed
    # second run same prices: no repeat alerts
    sent.clear(); run.main([])
    assert not sent
