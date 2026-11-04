"""Price and text helpers for Bosnian shop pages (KM / BAM, comma decimals)."""
from __future__ import annotations

import re
import unicodedata

# 1.299,00 KM | 1 299,00 KM | 1299 KM | KM 1.299,00 | 849,90KM | 1.299 BAM | 1,299.00 KM
_NUM = r"(\d{1,3}(?:[.\s  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
PRICE_RE = re.compile(
    rf"(?:{_NUM}(?:,-{{1,2}})?\s*(?:KM|BAM|kn|K\.M\.)(?![a-zA-Z]))|(?:\b(?:KM|BAM)\s*{_NUM})", re.IGNORECASE
)
# installment / per-month prices that must never be read as the product price
INSTALL_BEFORE = re.compile(r"(\brat[ae]?\b|\brata:|na\s*\d+\s*rata|\d+\s*x\s*$|mjese[cč]na|mese[cč]na|u[sš]ted[aie]\w*|popust\w*|save[sd]?|you save|dostava|po[sš]tarina)[^\d]{0,14}$", re.I)
INSTALL_AFTER = re.compile(r"^\s*(/\s*mj|mjese[cč]no|mese[cč]no|mj\.|x\s*\d+)", re.I)


def parse_number(raw: str) -> float | None:
    """Turn '1.299,00' / '1 299,00' / '1299' / '1,299.00' into 1299.0."""
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", " ").replace(" ", " ")
    s = re.sub(r"[^\d.,\s]", "", s).strip()
    if not s:
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        # whichever comes last is the decimal separator
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + "." + tail if len(tail) in (1, 2) else s.replace(",", "")
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if len(tail) == 3:  # thousands separator
            s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if 0 < v < 1_000_000 else None


def find_prices(text: str) -> list[float]:
    """All KM prices in a piece of text, in order, skipping installment amounts."""
    out: list[float] = []
    if not text:
        return out
    for m in PRICE_RE.finditer(text):
        if INSTALL_BEFORE.search(text[max(0, m.start() - 22): m.start()]) or INSTALL_AFTER.search(text[m.end(): m.end() + 14]):
            continue
        v = parse_number(m.group(1) or m.group(2))
        if v is not None:
            out.append(v)
    return out


def norm(text: str) -> str:
    """Lowercase, strip diacritics (š->s, č->c, đ->d), collapse spaces."""
    if not text:
        return ""
    t = text.replace("đ", "d").replace("Đ", "D")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


_MODEL_RE = re.compile(r"\b(?=[A-Z0-9/\-]*\d)(?=[A-Z0-9/\-]*[A-Z])[A-Z0-9][A-Z0-9/\-]{4,19}\b")
_NOT_MODELS = {"1400RPM", "1200RPM", "1000RPM", "SMART", "4K", "UHD", "QLED", "OLED", "LED"}


def model_code(title: str) -> str | None:
    """Best guess at the manufacturer model code in a product title (e.g. WAN28281BY)."""
    if not title:
        return None
    cands = []
    for m in _MODEL_RE.finditer(title.upper()):
        tok = m.group(0).strip("-/")
        if tok in _NOT_MODELS or re.fullmatch(r"\d+(KG|L|CM|W|RPM|OBR|HZ)?", tok):
            continue
        if re.fullmatch(r"\d{2,3}\"?", tok):
            continue
        letters = sum(c.isalpha() for c in tok)
        digits = sum(c.isdigit() for c in tok)
        if letters >= 1 and digits >= 2 and len(tok) >= 6:
            cands.append(tok)
    if not cands:
        return None
    return max(cands, key=len).replace("/", "")


_SPEC_CUT = re.compile(r"\s(?:Boja|Brend i model proizvoda|Dimenzije(?: proizvoda)?|Dodatne karakteristike|Broj obrtaja|Broj programa|"
                       r"Audio|Energetski razred|Kapacitet|Garancija)\s*:.*$", re.I)


def clean_title(title: str) -> str:
    """Drop shop noise from a product title: spec lists, hashtags, embedded prices, 'Akcija' prefixes."""
    t = re.sub(r"#\S+", " ", title or "")
    t = _SPEC_CUT.sub("", t)
    t = PRICE_RE.sub(" ", t)
    t = re.sub(r"^\s*(akcija|novo|sni[zž]eno|top ponuda)\s*[:!-]?\s+", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -–|,;:")
    return t or (title or "").strip()
