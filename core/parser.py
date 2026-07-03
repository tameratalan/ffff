from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote_plus, urlparse


PRODUCT_ID_RE = re.compile(r"-p-(\d+)", re.I)
BARE_ID_RE = re.compile(r"^\d{6,12}$")
_QUERY_ID_KEYS = ("contentId", "productId", "productMainId", "listingId")

@dataclass
class ParsedTarget:
    raw: str
    product_id: str | None = None
    product_url: str | None = None
    search_keyword: str | None = None

    @property
    def is_direct_url(self) -> bool:
        return bool(self.product_url)


def parse_target(raw: str, default_keyword: str = "") -> ParsedTarget:
    """
    Akıllı veri çözme: link, ürün ID veya arama kelimesi.

    Örnekler:
        https://www.trendyol.com/...-p-123456
        123456789
        spor ayakkabı erkek
    """
    text = (raw or "").strip()
    if not text:
        return ParsedTarget(raw="", search_keyword=default_keyword or None)

    if text.startswith("http"):
        pid = primary_product_id(text)
        return ParsedTarget(
            raw=text,
            product_id=pid,
            product_url=text.split("?")[0],
            search_keyword=default_keyword or None,
        )

    if BARE_ID_RE.match(text):
        url = f"https://www.trendyol.com/x-p-{text}"
        return ParsedTarget(
            raw=text,
            product_id=text,
            product_url=url,
            search_keyword=default_keyword or None,
        )

    return ParsedTarget(raw=text, search_keyword=text)


def parse_all_product_ids(text: str) -> list[str]:
    """URL/path/query icindeki tum olasi Trendyol urun ID'leri."""
    raw = (text or "").strip()
    if not raw:
        return []

    ids: list[str] = []
    for m in PRODUCT_ID_RE.finditer(raw):
        ids.append(m.group(1))

    if raw.startswith("http"):
        q = parse_qs(urlparse(raw).query)
        for key in _QUERY_ID_KEYS:
            val = (q.get(key) or [None])[0]
            if val and str(val).isdigit():
                ids.append(str(val))

    if BARE_ID_RE.match(raw):
        ids.append(raw)

    return list(dict.fromkeys(ids))


def primary_product_id(text: str) -> str | None:
    ids = parse_all_product_ids(text)
    return ids[0] if ids else None


def canonical_product_url(url: str) -> str:
    """Slug 404 verirse x-p-ID formati genelde calisir."""
    pid = primary_product_id(url)
    if pid:
        return f"https://www.trendyol.com/x-p-{pid}"
    return (url or "").strip().split("?")[0].split("#")[0]


def build_search_url(keyword: str, page: int = 1) -> str:
    q = quote_plus(keyword.strip())
    if page <= 1:
        return f"https://www.trendyol.com/sr?q={q}"
    return f"https://www.trendyol.com/sr?q={q}&pi={page}"


def href_matches_product(href: str, product_id: str | list[str]) -> bool:
    ids = [product_id] if isinstance(product_id, str) else list(product_id)
    ids = [i for i in ids if i]
    if not href or not ids:
        return False

    hid = extract_product_id(href)
    if hid and hid in ids:
        return True

    for pid in ids:
        if re.search(rf"-p-{re.escape(pid)}(?!\d)", href, re.I):
            return True
    return False


def extract_product_id(href: str) -> str | None:
    m = PRODUCT_ID_RE.search(href or "")
    return m.group(1) if m else None
