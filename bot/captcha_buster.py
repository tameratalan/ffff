"""Buster — ucretsiz reCAPTCHA (sesli challenge, acik kaynak)."""

from __future__ import annotations

import asyncio

from playwright.async_api import Page

from bot.captcha_detect import captcha_token_present, captcha_visible
from config import BUSTER_EXTENSION_DIR
from core.log_bus import LOG_BUS


def buster_available() -> bool:
    return (BUSTER_EXTENSION_DIR / "manifest.json").is_file()


async def _click_recaptcha_checkbox(page: Page) -> None:
    try:
        anchor = page.frame_locator('iframe[src*="recaptcha/api2/anchor"]').first
        box = anchor.locator("#recaptcha-anchor, .recaptcha-checkbox-border")
        if await box.is_visible(timeout=2500):
            await box.click()
            await asyncio.sleep(2.0)
            return
    except Exception:
        pass

    for frame in page.frames:
        url = frame.url or ""
        if "recaptcha/api2/anchor" not in url and "recaptcha/enterprise/anchor" not in url:
            continue
        try:
            cb = frame.locator("#recaptcha-anchor")
            if await cb.is_visible(timeout=1500):
                await cb.click()
                await asyncio.sleep(2.0)
                return
        except Exception:
            continue


async def _click_buster_button(page: Page) -> bool:
    try:
        bframe = page.frame_locator('iframe[src*="recaptcha/api2/bframe"]').first
        btn = bframe.locator("#solver-button")
        if await btn.is_visible(timeout=1500):
            await btn.click()
            return True
    except Exception:
        pass

    try:
        btn = page.locator("#solver-button").first
        if await btn.is_visible(timeout=1000):
            await btn.click()
            return True
    except Exception:
        pass
    return False


async def try_buster_solve(page: Page, bot_id: int, *, wait_sec: int = 45) -> bool:
    """
    Buster extension yuklu ve headed modda calisir.
    reCAPTCHA checkbox + #solver-button (sesli cozum).
    """
    if not buster_available():
        return False

    LOG_BUS.emit("INFO", bot_id, "Buster (ucretsiz) deneniyor...")

    await _click_recaptcha_checkbox(page)
    await asyncio.sleep(1.5)

    if await captcha_token_present(page):
        LOG_BUS.emit("SUCCESS", bot_id, "reCAPTCHA gecti (tek tik)")
        return True

    if not await _click_buster_button(page):
        LOG_BUS.emit("INFO", bot_id, "Buster butonu henuz yok — challenge bekleniyor")
        await asyncio.sleep(2.0)
        if not await _click_buster_button(page):
            return False

    LOG_BUS.emit("INFO", bot_id, "Buster sesli cozum calisiyor (biraz bekleyin)...")

    elapsed = 0
    while elapsed < wait_sec:
        if await captcha_token_present(page):
            LOG_BUS.emit("SUCCESS", bot_id, "Buster ile cozuldu (ucretsiz)")
            return True
        if not await captcha_visible(page):
            return True
        await asyncio.sleep(2.0)
        elapsed += 2
        if elapsed in (10, 20, 30):
            await _click_buster_button(page)

    return await captcha_token_present(page)
