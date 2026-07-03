"""2captcha ile reCAPTCHA v2 cozumu (opsiyonel API key)."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.async_api import Page

from config import CAPTCHA_API_KEY, CAPTCHA_SERVICE
from core.log_bus import LOG_BUS

_SITEKEY_RE = re.compile(r"[?&]k=([^&]+)")


async def _extract_sitekey(page: Page) -> str | None:
    try:
        key = await page.evaluate(
            """
            () => {
              const el = document.querySelector('[data-sitekey]');
              if (el) return el.getAttribute('data-sitekey');
              for (const f of document.querySelectorAll('iframe[src*="recaptcha"]')) {
                const u = f.getAttribute('src') || '';
                const m = u.match(/[?&]k=([^&]+)/);
                if (m) return decodeURIComponent(m[1]);
              }
              return null;
            }
            """
        )
        if key:
            return str(key)
    except Exception:
        pass

    for frame in page.frames:
        url = frame.url or ""
        if "recaptcha" in url and "k=" in url:
            qs = parse_qs(urlparse(url).query)
            if "k" in qs:
                return qs["k"][0]
    return None


async def _inject_recaptcha_token(page: Page, token: str) -> None:
    await page.evaluate(
        """
        (token) => {
          const areas = document.querySelectorAll(
            '#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[id*="g-recaptcha"]'
          );
          areas.forEach((ta) => {
            ta.value = token;
            ta.innerHTML = token;
            ta.dispatchEvent(new Event('input', { bubbles: true }));
            ta.dispatchEvent(new Event('change', { bubbles: true }));
          });
          const cbName = document.querySelector('[data-callback]')?.getAttribute('data-callback');
          if (cbName && typeof window[cbName] === 'function') {
            window[cbName](token);
          }
          if (window.grecaptcha && typeof window.grecaptcha.getResponse === 'function') {
            try {
              const clients = window.___grecaptcha_cfg?.clients || {};
              for (const id of Object.keys(clients)) {
                const client = clients[id];
                const cb = client?.K?.K?.callback || client?.callback;
                if (typeof cb === 'function') cb(token);
              }
            } catch (e) {}
          }
        }
        """,
        token,
    )


async def _solve_2captcha(sitekey: str, pageurl: str, bot_id: int) -> str | None:
    if not CAPTCHA_API_KEY:
        return None

    base = "https://2captcha.com"
    async with httpx.AsyncClient(timeout=60) as client:
        LOG_BUS.emit("INFO", bot_id, "2captcha'ya gonderiliyor (otomatik cozum)...")
        r = await client.post(
            f"{base}/in.php",
            data={
                "key": CAPTCHA_API_KEY,
                "method": "userrecaptcha",
                "googlekey": sitekey,
                "pageurl": pageurl,
                "json": 1,
            },
        )
        data = r.json()
        if data.get("status") != 1:
            LOG_BUS.emit("ERROR", bot_id, f"2captcha gonderim hatasi: {data.get('request', data)}")
            return None

        req_id = data["request"]
        for i in range(40):
            await asyncio.sleep(5)
            poll = await client.get(
                f"{base}/res.php",
                params={"key": CAPTCHA_API_KEY, "action": "get", "id": req_id, "json": 1},
            )
            pdata = poll.json()
            if pdata.get("status") == 1:
                LOG_BUS.emit("SUCCESS", bot_id, "2captcha cozdu — token enjekte ediliyor")
                return str(pdata["request"])
            if pdata.get("request") != "CAPCHA_NOT_READY":
                LOG_BUS.emit("ERROR", bot_id, f"2captcha hata: {pdata.get('request')}")
                return None
            if i % 3 == 2:
                LOG_BUS.emit("INFO", bot_id, f"2captcha bekleniyor... ({(i + 1) * 5} sn)")

    LOG_BUS.emit("ERROR", bot_id, "2captcha zaman asimi")
    return None


async def try_auto_solve_recaptcha(page: Page, bot_id: int) -> bool:
    """API key varsa reCAPTCHA v2'yi otomatik cozmeyi dene."""
    if not CAPTCHA_API_KEY:
        return False
    if CAPTCHA_SERVICE not in ("2captcha", "auto", ""):
        LOG_BUS.emit("WARNING", bot_id, f"Desteklenmeyen captcha servisi: {CAPTCHA_SERVICE}")
        return False

    sitekey = await _extract_sitekey(page)
    if not sitekey:
        LOG_BUS.emit("WARNING", bot_id, "reCAPTCHA sitekey bulunamadi — elle cozun")
        return False

    token = await _solve_2captcha(sitekey, page.url, bot_id)
    if not token:
        return False

    await _inject_recaptcha_token(page, token)
    await asyncio.sleep(1.5)
    return True
