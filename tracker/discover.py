"""Find a shop's search URL automatically: read its search form, then try common URL patterns."""
from __future__ import annotations

from urllib.parse import urljoin, urlencode, quote_plus

from bs4 import BeautifulSoup

from .extract import extract

SEARCH_NAMES = ("q", "s", "search", "query", "term", "keyword", "keywords", "pretraga", "searchTerm",
                "search_query", "text", "k", "kljucna_rijec", "filter_name", "phrase")
COMMON_PATTERNS = (
    "/pretraga?q={q}", "/search?q={q}", "/?s={q}&post_type=product", "/pretraga?term={q}",
    "/catalogsearch/result/?q={q}", "/search?controller=search&s={q}", "/pretraga?search={q}",
    "/proizvodi?search={q}", "/shop?search={q}", "/index.php?route=product/search&search={q}",
    "/search?search_query={q}", "/pretraga/{q}", "/search/{q}",
)
TEST_QUERY = "frizider"


def form_templates(html: str, base: str) -> list[str]:
    out = []
    soup = BeautifulSoup(html, "lxml")
    for form in soup.find_all("form"):
        if (form.get("method") or "get").lower() != "get":
            continue
        inp = None
        for i in form.find_all("input"):
            name = i.get("name") or ""
            if (i.get("type") or "").lower() == "search" or name in SEARCH_NAMES:
                inp = i
                break
        if not inp or not inp.get("name"):
            continue
        params = {}
        for h in form.find_all("input", type="hidden"):
            if h.get("name") and h.get("value") is not None and len(h.get("value")) < 60:
                params[h["name"]] = h["value"]
        action = urljoin(base, form.get("action") or base)
        qs = urlencode(params)
        sep = "&" if "?" in action else "?"
        out.append(f"{action}{sep}{qs + '&' if qs else ''}{inp['name']}={{q}}")
    return list(dict.fromkeys(out))


def discover(fetcher, home: str, render: bool = False, max_tries: int = 9) -> dict:
    """Returns {'search': template|None, 'count': n, 'method': str, 'tried': [...], 'home_status': int}."""
    status, final, html = fetcher.get(home, render=render)
    result = {"home_status": status, "home_final": final, "search": None, "count": 0, "method": None, "tried": []}
    if status == 0 or status >= 400:
        result["error"] = html[:200] if status == 0 else f"HTTP {status}"
        return result
    base = final
    cands = form_templates(html, base) + [urljoin(base, p.split("{q}")[0]) + "{q}" + p.split("{q}")[1] for p in COMMON_PATTERNS]
    cands = list(dict.fromkeys(cands))[:max_tries]
    for tpl in cands:
        url = tpl.replace("{q}", quote_plus(TEST_QUERY))
        st, fin, text = fetcher.get(url, render=render)
        prods, rep = ([], {}) if st == 0 or st >= 400 else extract(text, fin)
        result["tried"].append({"template": tpl, "status": st, "products": len(prods), "method": rep.get("used")})
        if len(prods) > result["count"]:
            result.update(search=tpl, count=len(prods), method=rep.get("used"))
        if len(prods) >= 8:
            break
    return result
