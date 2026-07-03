from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx

from core.log_bus import LOG_BUS


async def _test_one(proxy: str, timeout: float = 8.0) -> tuple[str, bool, str]:
    proxy = proxy.strip()
    if not proxy:
        return proxy, False, "boş"
    try:
        async with httpx.AsyncClient(
            proxies=proxy,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            r = await client.get("https://www.trendyol.com/")
            ok = r.status_code < 500
            return proxy, ok, f"HTTP {r.status_code}"
    except Exception as exc:
        return proxy, False, str(exc)[:80]


def test_proxies(proxy_lines: str) -> list[dict]:
    """Proxy Doktoru — satır satır proxy testi."""
    lines = [ln.strip() for ln in proxy_lines.splitlines() if ln.strip()]
    if not lines:
        return []

    async def run_all():
        return await asyncio.gather(*[_test_one(p) for p in lines])

    results = asyncio.run(run_all())
    out = []
    for proxy, ok, msg in results:
        level = "SUCCESS" if ok else "WARNING"
        LOG_BUS.emit(level, 0, f"Proxy {'OK' if ok else 'FAIL'}: {proxy[:40]} — {msg}")
        out.append({"proxy": proxy, "ok": ok, "message": msg})
    return out


def normalize_proxy(line: str) -> str:
    """http://user:pass@host:port formatına yaklaştır."""
    line = line.strip()
    if not line:
        return ""
    if "://" in line:
        return line
    return f"http://{line}"
