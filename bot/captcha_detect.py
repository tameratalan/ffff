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
                  const ta = document.querySelector(
                    '#g-recaptcha-response, textarea[name="g-recaptcha-response"]'
                  );
                  return !!(ta && ta.value && ta.value.length > 20);
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
    if await captcha_token_present(page):
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
