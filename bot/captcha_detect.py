"""reCAPTCHA gorunurluk tespiti."""

from __future__ import annotations

import re

from playwright.async_api import Frame, Page

_CAPTCHA_FRAME = re.compile(r"recaptcha|google\.com/recaptcha", re.I)
_CAPTCHA_TEXT = re.compile(
    r"recaptcha|robot\s*olmad|robot\s*degil|guvenlik\s*dogrul|captcha|"
    r"ben\s*robot\s*degilim|i\s*'?m\s*not\s*a\s*robot|turnstile",
    re.I,
)

_CAPTCHA_SELECTORS = (
    "iframe[src*='recaptcha']",
    "iframe[title*='reCAPTCHA' i]",
    "iframe[name*='recaptcha' i]",
    ".g-recaptcha",
    "[class*='recaptcha']",
    "#captcha",
    "[data-sitekey]",
    "iframe[src*='challenges.cloudflare.com']",
)


async def captcha_token_present(page: Page) -> bool:
    try:
        return bool(
            await page.evaluate(
                """
                () => {
                  const areas = document.querySelectorAll(
                    '#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[id*="g-recaptcha"]'
                  );
                  for (const ta of areas) {
                    if (ta.value && ta.value.length > 20) return true;
                  }
                  return false;
                }
                """
            )
        )
    except Exception:
        return False


async def recaptcha_checkbox_checked(page: Page) -> bool:
    """Anchor iframe'de tik isareti var mi."""
    try:
        anchor = page.frame_locator('iframe[src*="recaptcha/api2/anchor"], iframe[src*="recaptcha/enterprise/anchor"]').first
        box = anchor.locator("#recaptcha-anchor")
        if await box.get_attribute("aria-checked", timeout=1500) == "true":
            return True
        if await box.evaluate("el => el.classList.contains('recaptcha-checkbox-checked')"):
            return True
    except Exception:
        pass

    for frame in page.frames:
        url = frame.url or ""
        if "recaptcha" not in url or "anchor" not in url:
            continue
        try:
            cb = frame.locator("#recaptcha-anchor")
            if await cb.count() == 0:
                continue
            if await cb.get_attribute("aria-checked") == "true":
                return True
        except Exception:
            continue
    return False


async def captcha_solved(page: Page) -> bool:
    """Checkbox tikli veya gecerli token + form hazir."""
    if await recaptcha_checkbox_checked(page):
        return True
    if await captcha_token_present(page):
        return True
    return False


async def signup_captcha_ready(page: Page) -> bool:
    """Kayit formu icin captcha gercekten cozulmus mu (buton aktif veya checkbox)."""
    if await recaptcha_checkbox_checked(page):
        return True
    try:
        ready = await page.evaluate(
            """
            () => {
              const btns = Array.from(document.querySelectorAll('button, input[type=submit]'));
              for (const b of btns) {
                const t = (b.innerText || b.value || '').toLowerCase();
                if (!/üye\\s*ol|uye\\s*ol|kay[iı]t/.test(t)) continue;
                if (!b.disabled && b.offsetParent !== null) return true;
              }
              const areas = document.querySelectorAll(
                '#g-recaptcha-response, textarea[name="g-recaptcha-response"]'
              );
              for (const ta of areas) {
                if (ta.value && ta.value.length > 20) {
                  const form = ta.closest('form');
                  if (form) {
                    const submit = form.querySelector('button:not([disabled]), input[type=submit]:not([disabled])');
                    if (submit) return true;
                  }
                }
              }
              return false;
            }
            """
        )
        return bool(ready)
    except Exception:
        return await captcha_token_present(page)


async def reset_recaptcha_widget(page: Page) -> bool:
    """Basarisiz Uye Ol sonrasi Google widget'i gorsel olarak sifirlaniyor
    (kutucuk bosaliyor) ama biz eski token/callback'i tekrar enjekte
    edersek sunucu kabul etmiyor — widget'i grecaptcha.reset() ile
    GERCEKTEN sifirlayip taze bir challenge baslatmak gerekiyor."""
    try:
        return bool(
            await page.evaluate(
                """
                () => {
                  const gr = window.grecaptcha?.enterprise || window.grecaptcha;
                  if (!gr || typeof gr.reset !== 'function') return false;
                  const cfg = window.___grecaptcha_cfg;
                  try {
                    if (cfg && cfg.clients) {
                      for (const id of Object.keys(cfg.clients)) {
                        try { gr.reset(Number(id)); } catch (e) {}
                      }
                    } else {
                      gr.reset();
                    }
                    return true;
                  } catch (e) {
                    return false;
                  }
                }
                """
            )
        )
    except Exception:
        return False


async def clear_recaptcha_tokens(page: Page) -> None:
    """Eski/stale token temizle — yeni captcha cozumunden once."""
    try:
        await page.evaluate(
            """
            () => {
              document.querySelectorAll(
                '#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[id*="g-recaptcha"]'
              ).forEach((el) => { el.value = ''; el.innerHTML = ''; });
            }
            """
        )
    except Exception:
        pass


async def is_recaptcha_enterprise(page: Page) -> bool:
    try:
        return bool(
            await page.evaluate(
                """
                () => {
                  if (window.grecaptcha && window.grecaptcha.enterprise) return true;
                  for (const f of document.querySelectorAll('iframe[src*="recaptcha"]')) {
                    if ((f.src || '').includes('enterprise')) return true;
                  }
                  return false;
                }
                """
            )
        )
    except Exception:
        return False


async def _frame_has_captcha(frame: Frame) -> bool:
    try:
        if _CAPTCHA_FRAME.search(frame.url or ""):
            return True
    except Exception:
        pass
    try:
        title = await frame.title()
        if title and _CAPTCHA_FRAME.search(title):
            return True
    except Exception:
        pass
    return False


async def captcha_visible(page: Page) -> bool:
    if await captcha_solved(page):
        return False

    for sel in _CAPTCHA_SELECTORS:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible(timeout=400):
                return True
        except Exception:
            continue

    try:
        for frame in page.frames:
            if await _frame_has_captcha(frame):
                return True
    except Exception:
        pass

    try:
        body = await page.inner_text("body")
        if _CAPTCHA_TEXT.search(body):
            return True
    except Exception:
        pass

    return False
