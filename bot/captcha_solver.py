"""2captcha ile reCAPTCHA v2 cozumu (opsiyonel API key)."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.async_api import Page

from bot.captcha_detect import captcha_solved, clear_recaptcha_tokens, is_recaptcha_enterprise, signup_captcha_ready
from config import CAPSOLVER_API_KEY, CAPTCHA_API_KEY, CAPTCHA_SERVICE
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


async def _inject_recaptcha_token(page: Page, token: str) -> dict:
    """Token + gercek widget callback'ini tetikle (Enterprise dahil).

    Google'in ic ___grecaptcha_cfg.clients yapisi minify/obfuscate edilmis
    oldugu icin rastgele fonksiyon cagirmak yerine 'sitekey' + 'size'
    ozelligine sahip gercek widget nesnesini bulup onun callback'ini
    cagiriyoruz — bilinen en guvenilir yontem budur.
    """
    return await page.evaluate(
        """
        (token) => {
          const setToken = (el) => {
            el.value = token;
            el.innerHTML = token;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          };
          document.querySelectorAll(
            '#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[id*="g-recaptcha"]'
          ).forEach(setToken);

          const fire = (fn) => {
            if (typeof fn === 'function') {
              try { fn(token); return true; } catch (e) { return false; }
            }
            return false;
          };

          let fired = 0;
          let clientsFound = 0;

          document.querySelectorAll('[data-callback]').forEach((el) => {
            const name = el.getAttribute('data-callback');
            if (name && window[name]) {
              if (fire(window[name])) fired++;
            }
          });

          const cfg = window.___grecaptcha_cfg;
          if (cfg && cfg.clients) {
            const clients = Object.entries(cfg.clients);
            clientsFound = clients.length;
            for (const [, client] of clients) {
              const topLevels = Object.values(client).filter(
                (v) => v && typeof v === 'object'
              );
              for (const toplevel of topLevels) {
                const entries = Object.values(toplevel).filter(
                  (v) => v && typeof v === 'object'
                );
                for (const sublevel of entries) {
                  if (!('sitekey' in sublevel) && !('size' in sublevel)) continue;
                  const cbKey = Object.keys(sublevel).find(
                    (k) => typeof sublevel[k] === 'function'
                  );
                  if (cbKey && fire(sublevel[cbKey])) fired++;
                }
              }
            }
          }

          const gr = window.grecaptcha?.enterprise || window.grecaptcha;
          if (gr && typeof gr.getResponse === 'function' && cfg && cfg.clients) {
            for (const id of Object.keys(cfg.clients)) {
              try {
                if (typeof gr.execute === 'function') gr.execute(Number(id));
              } catch (e) {}
            }
          }

          return { clientsFound, fired };
        }
        """,
        token,
    )


async def _solve_2captcha(
    sitekey: str,
    pageurl: str,
    bot_id: int,
    *,
    enterprise: bool = False,
) -> str | None:
    if not CAPTCHA_API_KEY:
        return None

    base = "https://2captcha.com"
    payload = {
        "key": CAPTCHA_API_KEY,
        "method": "userrecaptcha",
        "googlekey": sitekey,
        "pageurl": pageurl,
        "json": 1,
    }
    if enterprise:
        payload["enterprise"] = 1

    async with httpx.AsyncClient(timeout=60) as client:
        kind = "Enterprise" if enterprise else "v2"
        LOG_BUS.emit("INFO", bot_id, f"2captcha'ya gonderiliyor (reCAPTCHA {kind})...")
        r = await client.post(f"{base}/in.php", data=payload)
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


async def _solve_capsolver(
    sitekey: str,
    pageurl: str,
    bot_id: int,
    *,
    enterprise: bool = False,
) -> str | None:
    if not CAPSOLVER_API_KEY:
        return None

    base = "https://api.capsolver.com"
    task_type = "ReCaptchaV2EnterpriseTaskProxyLess" if enterprise else "ReCaptchaV2TaskProxyLess"
    payload = {
        "clientKey": CAPSOLVER_API_KEY,
        "task": {
            "type": task_type,
            "websiteURL": pageurl,
            "websiteKey": sitekey,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        kind = "Enterprise" if enterprise else "v2"
        LOG_BUS.emit("INFO", bot_id, f"CapSolver'a gonderiliyor (reCAPTCHA {kind})...")
        try:
            r = await client.post(f"{base}/createTask", json=payload)
            data = r.json()
        except Exception as exc:
            LOG_BUS.emit("ERROR", bot_id, f"CapSolver hata: {exc}")
            return None

        if data.get("errorId"):
            LOG_BUS.emit(
                "ERROR",
                bot_id,
                f"CapSolver gonderim hatasi: {data.get('errorCode')} {data.get('errorDescription', '')}",
            )
            return None

        task_id = data.get("taskId")
        if not task_id:
            LOG_BUS.emit("ERROR", bot_id, f"CapSolver hata: taskId alinamadi ({data})")
            return None

        for i in range(60):
            await asyncio.sleep(3)
            try:
                poll = await client.post(
                    f"{base}/getTaskResult",
                    json={"clientKey": CAPSOLVER_API_KEY, "taskId": task_id},
                )
                pdata = poll.json()
            except Exception as exc:
                LOG_BUS.emit("ERROR", bot_id, f"CapSolver hata: {exc}")
                return None

            if pdata.get("errorId"):
                LOG_BUS.emit(
                    "ERROR",
                    bot_id,
                    f"CapSolver hata: {pdata.get('errorCode')} {pdata.get('errorDescription', '')}",
                )
                return None

            status = pdata.get("status")
            if status == "ready":
                token = pdata.get("solution", {}).get("gRecaptchaResponse")
                if not token:
                    LOG_BUS.emit("ERROR", bot_id, f"CapSolver hata: token bos ({pdata})")
                    return None
                LOG_BUS.emit("SUCCESS", bot_id, "CapSolver cozdu — token enjekte ediliyor")
                return str(token)
            if status != "processing":
                LOG_BUS.emit("ERROR", bot_id, f"CapSolver hata: beklenmeyen durum ({status})")
                return None
            if i % 3 == 2:
                LOG_BUS.emit("INFO", bot_id, f"CapSolver bekleniyor... ({(i + 1) * 3} sn)")

    LOG_BUS.emit("ERROR", bot_id, "CapSolver zaman asimi")
    return None


async def try_auto_solve_recaptcha(page: Page, bot_id: int) -> bool:
    """API key varsa reCAPTCHA v2/Enterprise otomatik coz.

    Servis secimi: CAPTCHA_SERVICE == "capsolver" -> sadece CapSolver.
    CAPTCHA_SERVICE == "2captcha" -> sadece 2captcha (geriye donuk uyumluluk).
    "auto"/bos -> CAPSOLVER_API_KEY doluysa CapSolver birincil (daha hizli),
    basarisiz olursa CAPTCHA_API_KEY (2captcha) varsa ona fallback.
    """
    if not CAPTCHA_API_KEY and not CAPSOLVER_API_KEY:
        return False
    if CAPTCHA_SERVICE not in ("2captcha", "capsolver", "auto", ""):
        LOG_BUS.emit("WARNING", bot_id, f"Desteklenmeyen captcha servisi: {CAPTCHA_SERVICE}")
        return False

    sitekey = await _extract_sitekey(page)
    if not sitekey:
        LOG_BUS.emit("WARNING", bot_id, "reCAPTCHA sitekey bulunamadi — elle cozun")
        return False

    enterprise = await is_recaptcha_enterprise(page)
    if enterprise:
        LOG_BUS.emit("INFO", bot_id, "reCAPTCHA Enterprise algilandi")

    use_capsolver_first = CAPTCHA_SERVICE == "capsolver" or (
        CAPTCHA_SERVICE in ("auto", "") and CAPSOLVER_API_KEY
    )

    token = None
    used_service = ""
    if use_capsolver_first and CAPSOLVER_API_KEY:
        token = await _solve_capsolver(sitekey, page.url, bot_id, enterprise=enterprise)
        used_service = "CapSolver"
        if not token and CAPTCHA_SERVICE == "auto" and CAPTCHA_API_KEY:
            LOG_BUS.emit("WARNING", bot_id, "CapSolver basarisiz — 2captcha'ya dusuluyor")
            token = await _solve_2captcha(sitekey, page.url, bot_id, enterprise=enterprise)
            used_service = "2captcha"
    elif CAPTCHA_SERVICE == "2captcha" and CAPTCHA_API_KEY:
        token = await _solve_2captcha(sitekey, page.url, bot_id, enterprise=enterprise)
        used_service = "2captcha"
    elif CAPTCHA_API_KEY:
        token = await _solve_2captcha(sitekey, page.url, bot_id, enterprise=enterprise)
        used_service = "2captcha"

    if not token:
        return False

    diag = await _inject_recaptcha_token(page, token)
    LOG_BUS.emit(
        "INFO",
        bot_id,
        f"Callback taramasi: {diag.get('clientsFound', 0)} widget, {diag.get('fired', 0)} tetiklendi",
    )
    for _ in range(12):
        await asyncio.sleep(0.5)
        if await signup_captcha_ready(page) or await captcha_solved(page):
            LOG_BUS.emit("SUCCESS", bot_id, f"{used_service} token sayfada dogrulandi")
            return True

    LOG_BUS.emit("WARNING", bot_id, "Token enjekte edildi ama form hazir degil — callback tekrar deneniyor")
    diag2 = await _inject_recaptcha_token(page, token)
    LOG_BUS.emit(
        "INFO",
        bot_id,
        f"Callback taramasi 2: {diag2.get('clientsFound', 0)} widget, {diag2.get('fired', 0)} tetiklendi",
    )
    await asyncio.sleep(2.0)
    if await signup_captcha_ready(page) or await captcha_solved(page):
        LOG_BUS.emit("SUCCESS", bot_id, f"{used_service} token (2. deneme) dogrulandi")
        return True

    LOG_BUS.emit("WARNING", bot_id, "Token enjekte edildi ama captcha hala acik — callback tetiklenmedi")
    return False
