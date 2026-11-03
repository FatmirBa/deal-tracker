"""Generic product extraction from a shop's listing/search page.

Tries, in order of reliability:
  1. Shop-specific CSS selectors (from shops.yaml), when configured
  2. JSON-LD (schema.org Product / ItemList / Offer)
  3. Embedded app state (__NEXT_DATA__, __NUXT__, JSON API responses)
  4. Repeating "product card" pattern in the HTML with a KM price inside
and keeps whichever source yields the most priced products.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .prices import find_prices, parse_number

OLD_HINT = re.compile(r"old|regular|stara|before|was|prev|line-through|strike|crossed|precrt|redovn|mpc", re.I)
NEW_HINT = re.compile(r"\b(new|sale|special|akcij|current|final|actual|discount|price--now|now)\b", re.I)
TITLE_HINT = re.compile(r"title|name|naziv|naslov|product-link", re.I)
TITLE_KEYS = ("name", "title", "naziv", "productName", "product_name", "label")
PRICE_KEYS = ("price", "salePrice", "sale_price", "finalPrice", "final_price", "special_price", "cijena",
              "akcijska_cijena", "current_price", "priceWithVat", "price_with_vat", "amount", "value", "display_price")
OLD_KEYS = ("regularPrice", "regular_price", "oldPrice", "old_price", "listPrice", "list_price", "originalPrice",
            "original_price", "stara_cijena", "price_before", "priceBefore", "mpc")
URL_KEYS = ("url", "link", "href", "permalink", "slug", "path", "canonical_url", "productUrl")
IMG_KEYS = ("image", "img", "thumbnail", "imageUrl", "image_url", "picture", "photo", "thumb")


@dataclass
class Product:
    title: str
    price: float
    url: str
    old_price: float | None = None
    image: str | None = None
    source: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


# ---------------------------------------------------------------- helpers
def _abs(base: str, href: str | None) -> str | None:
    if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
        return None
    return urljoin(base, href)


def _img(el: Tag, base: str) -> str | None:
    img = el.find("img")
    if not img:
        return None
    for attr in ("data-src", "data-lazy-src", "data-original", "data-srcset", "srcset", "src"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return _abs(base, v.split(",")[0].split(" ")[0])
    return None


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if 0 < v < 1_000_000 else None
    if isinstance(v, str):
        ps = find_prices(v)
        return ps[0] if ps else parse_number(v)
    if isinstance(v, dict):
        for k in ("amount", "value", "price", "raw"):
            if k in v:
                return _num(v[k])
    return None


# ---------------------------------------------------------------- 1. selectors
def from_selectors(soup: BeautifulSoup, base: str, sel: dict) -> list[Product]:
    out = []
    for card in soup.select(sel["card"]):
        t_el = card.select_one(sel.get("title", "a")) if sel.get("title") else None
        title = _clean(t_el.get_text(" ") if t_el else "") or _clean((card.find("img") or {}).get("alt", "") if card.find("img") else "")
        link_el = card.select_one(sel["link"]) if sel.get("link") else (t_el if t_el and t_el.name == "a" else card.find("a", href=True))
        url = _abs(base, link_el.get("href") if link_el else None)
        p_el = card.select_one(sel["price"]) if sel.get("price") else None
        prices = find_prices(p_el.get_text(" ")) if p_el else find_prices(card.get_text(" "))
        if not prices and p_el is not None:
            v = parse_number(p_el.get_text(" "))
            prices = [v] if v else []
        o_el = card.select_one(sel["old_price"]) if sel.get("old_price") else None
        old = None
        if o_el is not None:
            ops = find_prices(o_el.get_text(" ")) or [parse_number(o_el.get_text(" "))]
            old = ops[0] if ops and ops[0] else None
        if title and url and prices:
            price = min(prices) if not p_el else prices[0]
            out.append(Product(title, price, url, old if old and old > price else None, _img(card, base), "selectors"))
    return out


# ---------------------------------------------------------------- 2. JSON-LD
def from_jsonld(soup: BeautifulSoup, base: str) -> list[Product]:
    out = []

    def handle(node):
        if isinstance(node, list):
            for n in node:
                handle(n)
            return
        if not isinstance(node, dict):
            return
        typ = node.get("@type")
        typ = " ".join(typ) if isinstance(typ, list) else str(typ or "")
        if "@graph" in node:
            handle(node["@graph"])
        if "ItemList" in typ:
            for el in node.get("itemListElement", []) or []:
                handle(el.get("item", el) if isinstance(el, dict) else el)
        if "Product" in typ:
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = _num(offers.get("price") or offers.get("lowPrice") or (offers.get("priceSpecification") or {}).get("price"))
            title = _clean(node.get("name", ""))
            url = _abs(base, node.get("url") or offers.get("url"))
            img = node.get("image")
            if isinstance(img, list):
                img = img[0] if img else None
            if isinstance(img, dict):
                img = img.get("url")
            if title and price and url:
                out.append(Product(title, price, url, None, _abs(base, img) if isinstance(img, str) else None, "jsonld"))

    for s in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            handle(json.loads(s.string or s.get_text() or "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


# ---------------------------------------------------------------- 3. embedded state / JSON APIs
def _walk_products(obj, base: str, url_template: str | None, found: list, depth=0):
    if depth > 14:
        return
    if isinstance(obj, list):
        for x in obj:
            _walk_products(x, base, url_template, found, depth + 1)
        return
    if not isinstance(obj, dict):
        return
    title = next((obj[k] for k in TITLE_KEYS if isinstance(obj.get(k), str) and len(obj[k].strip()) >= 6), None)
    price = None
    for k in PRICE_KEYS:
        if k in obj:
            price = _num(obj[k])
            if price:
                break
    if title and price:
        url = None
        for k in URL_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v:
                url = _abs(base, v if v.startswith(("http", "/")) else "/" + v)
                break
        if not url and url_template:
            try:
                url = url_template.format(**{k: v for k, v in obj.items() if isinstance(v, (str, int))})
            except (KeyError, IndexError):
                url = None
        old = next((_num(obj[k]) for k in OLD_KEYS if k in obj and _num(obj[k])), None)
        img = None
        for k in IMG_KEYS:
            v = obj.get(k)
            if isinstance(v, list) and v:
                v = v[0]
            if isinstance(v, dict):
                v = v.get("url") or v.get("src")
            if isinstance(v, str) and v:
                img = _abs(base, v)
                break
        if url:
            found.append(Product(_clean(title), price, url, old if old and old > price else None, img, "embedded"))
    for v in obj.values():
        if isinstance(v, (dict, list)):
            _walk_products(v, base, url_template, found, depth + 1)


def from_embedded(text: str, soup: BeautifulSoup | None, base: str, url_template: str | None = None) -> list[Product]:
    blobs = []
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            blobs.append(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    if soup is not None:
        for s in soup.find_all("script"):
            raw = s.string or ""
            if not raw or len(raw) < 50:
                continue
            if s.get("type", "").lower() in ("application/json",) or s.get("id") in ("__NEXT_DATA__", "__NUXT_DATA__"):
                try:
                    blobs.append(json.loads(raw))
                    continue
                except json.JSONDecodeError:
                    pass
            m = re.search(r"(?:window\.__[A-Z_]+__|__INITIAL_STATE__|__PRELOADED_STATE__)\s*=\s*(\{.*\})\s*;?\s*$", raw, re.S)
            if m:
                try:
                    blobs.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    pass
    found: list[Product] = []
    for b in blobs:
        _walk_products(b, base, url_template, found)
    return found


# ---------------------------------------------------------------- 4. repeating product cards
def _signature(el: Tag) -> tuple:
    cls = el.get("class") or []
    cls = [c for c in cls if not re.search(r"\d", c)][:3]
    return (el.name, tuple(sorted(cls)))


def _card_product(card: Tag, base: str) -> Product | None:
    text = card.get_text(" ")
    prices = find_prices(text)
    if not prices:
        return None
    links = [a for a in card.find_all("a", href=True) if _abs(base, a["href"])]
    if not links:
        return None
    # title: an element hinting "title/name", else the longest link text, else image alt
    title = ""
    hinted = card.find(lambda t: isinstance(t, Tag) and t.name in ("h1", "h2", "h3", "h4", "h5", "a", "div", "span", "p")
                       and TITLE_HINT.search(" ".join(t.get("class") or []) + " " + (t.get("itemprop") or "")))
    if hinted:
        title = _clean(hinted.get_text(" "))
    if len(title) < 6:
        title = max((_clean(a.get_text(" ")) for a in links), key=len, default="")
    if len(title) < 6 and card.find("img"):
        title = _clean(card.find("img").get("alt", ""))
    if len(title) < 6 or len(title) > 300 or find_prices(title) and len(title) < 25:
        return None
    link = next((a for a in links if _clean(a.get_text(" ")) == title), None) or links[0]
    url = _abs(base, link["href"])

    old = None
    for el in card.find_all(["del", "s", "strike"]) + card.find_all(class_=OLD_HINT):
        ps = find_prices(el.get_text(" "))
        if ps:
            old = max(ps)
            break
    price = None
    for el in card.find_all(class_=NEW_HINT):
        ps = find_prices(el.get_text(" "))
        if ps:
            price = min(ps)
            break
    if price is None:
        cand = [p for p in prices if old is None or p < old] or prices
        price = min(cand)
    if old is None and len(set(prices)) >= 2 and max(prices) > price * 1.02:
        old = max(prices)
    return Product(title, price, url, old if old and old > price * 1.005 else None, _img(card, base), "cards")


def from_cards(soup: BeautifulSoup, base: str) -> list[Product]:
    for junk in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        junk.decompose()
    best: list[Product] = []
    by_parent: dict[int, dict[tuple, list[Tag]]] = defaultdict(lambda: defaultdict(list))
    parents = {}
    for el in soup.find_all(["li", "div", "article", "section", "a", "tr"]):
        p = el.parent
        if p is None:
            continue
        by_parent[id(p)][_signature(el)].append(el)
        parents[id(p)] = p
    groups = []
    for pid, sigs in by_parent.items():
        for sig, els in sigs.items():
            if len(els) >= 3:
                groups.append(els)
    for els in groups:
        prods = [p for p in (_card_product(e, base) for e in els) if p]
        if len(prods) >= 3 and len(prods) >= 0.5 * len(els) and len(prods) > len(best):
            best = prods
    return best


# ---------------------------------------------------------------- entry point
def dedupe(products: list[Product]) -> list[Product]:
    seen, out = set(), []
    for p in products:
        key = p.url.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def extract(text: str, base: str, selectors: dict | None = None, url_template: str | None = None) -> tuple[list[Product], dict]:
    """Return (products, report) where report says how many each method found."""
    report = {}
    is_json = text.lstrip().startswith(("{", "["))
    soup = None if is_json else BeautifulSoup(text, "lxml")
    results = {}
    if selectors and soup is not None:
        results["selectors"] = dedupe(from_selectors(soup, base, selectors))
    if soup is not None:
        results["jsonld"] = dedupe(from_jsonld(soup, base))
    results["embedded"] = dedupe(from_embedded(text, soup, base, url_template))
    if soup is not None:
        results["cards"] = dedupe(from_cards(BeautifulSoup(text, "lxml"), base))
    for k, v in results.items():
        report[k] = len(v)
    if selectors and results.get("selectors"):
        return results["selectors"], report | {"used": "selectors"}
    best_key = max(results, key=lambda k: len(results[k]), default=None)
    if not best_key or not results[best_key]:
        return [], report | {"used": None}
    return results[best_key], report | {"used": best_key}
