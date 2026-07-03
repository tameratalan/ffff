"""reCAPTCHA — ucretsiz Buster, elle cozum, opsiyonel 2captcha."""

from __future__ import annotations

import asyncio

from playwright.async_api import Page

from bot.captcha_buster import buster_available, try_buster_solve
from bot.captcha_detect import captcha_token_present, captcha_visible
from bot.captcha_solver import try_auto_solve_recaptcha
from config import CAPTCHA_API_KEY
from core.async_utils import should_stop
from core.log_bus import LOG_BUS


async def _focus_browser(page: Page, bot_id: int, *, manual: bool = False) -> None:
    try:
        await page.bring_to_front()
    except Exception:
        pass
    if manual:
        LOG_BUS.emit(
            "WARNING",
            bot_id,
            ">>> CAPTCHA: Chrome'da kutucugu isaretleyin (veya Buster bekleyin) <<<",
        )


async def wait_for_captcha_manual(
    page: Page,
    bot_id: int,
    *,
    timeout_sec: int = 300,
    label: str = "reCAPTCHA",
) -> bool:
    if not await captcha_visible(page):
        return True

    await _focus_browser(page, bot_id, manual=True)
    LOG_BUS.emit(
        "WARNING",
        bot_id,
        f"{label} — elle cozun (max {timeout_sec // 60} dk) veya Buster bitsin",
    )

    elapsed = 0
    poll = 2.0
    while elapsed < timeout_sec:
        if should_stop():
            return False
        if not await captcha_visible(page) or await captcha_token_present(page):
            LOG_BUS.emit("SUCCESS", bot_id, f"{label} tamamlandi")
            await asyncio.sleep(1.0)
            return True
        if elapsed > 0 and elapsed % 30 == 0:
            LOG_BUS.emit("INFO", bot_id, f"{label} bekleniyor... ({timeout_sec - elapsed} sn)")
        await asyncio.sleep(poll)
        elapsed += int(poll)

    LOG_BUS.emit("ERROR", bot_id, f"{label} zaman asimi")
    return False


async def resolve_captcha(
    page: Page,
    bot_id: int,
    *,
    timeout_sec: int = 300,
    label: str = "reCAPTCHA",
) -> bool:
    if not await captcha_visible(page):
        return True

    await _focus_browser(page, bot_id)

    if buster_available():
        if await try_buster_solve(page, bot_id):
            if not await captcha_visible(page) or await captcha_token_present(page):
                return True
    else:
        LOG_BUS.emit("INFO", bot_id, "Ucretsiz otomasyon: setup_buster.bat calistirin")

    if CAPTCHA_API_KEY:
        LOG_BUS.emit("INFO", bot_id, "2captcha deneniyor (ucretli yedek)...")
        if await try_auto_solve_recaptcha(page, bot_id):
            await asyncio.sleep(1.0)
            if not await captcha_visible(page) or await captcha_token_present(page):
                return True

    return await wait_for_captcha_manual(page, bot_id, timeout_sec=timeout_sec, label=label)


wait_for_captcha = resolve_captcha
