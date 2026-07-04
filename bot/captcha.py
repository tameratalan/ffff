"""reCAPTCHA — ucretsiz Buster, 2captcha, elle cozum."""

from __future__ import annotations

import asyncio

from playwright.async_api import Page

from bot.captcha_buster import buster_available, try_buster_solve
from bot.captcha_detect import (
    captcha_solved,
    captcha_token_present,
    captcha_visible,
    clear_recaptcha_tokens,
    signup_captcha_ready,
)
from bot.captcha_solver import try_auto_solve_recaptcha
from config import CAPSOLVER_API_KEY, CAPTCHA_API_KEY, CAPTCHA_SERVICE
from core.async_utils import should_stop
from core.log_bus import LOG_BUS

# Herhangi bir ucretli captcha API key'i (CapSolver ve/veya 2captcha) tanimli mi.
_HAS_PAID_CAPTCHA_KEY = bool(CAPSOLVER_API_KEY or CAPTCHA_API_KEY)
_PAID_SERVICE_LABEL = (
    "CapSolver"
    if (CAPTCHA_SERVICE == "capsolver" or (CAPTCHA_SERVICE in ("auto", "") and CAPSOLVER_API_KEY))
    else "2captcha"
)


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
        f"{label} — elle cozun (max {timeout_sec // 60} dk) veya Buster bekleyin",
    )

    elapsed = 0
    poll = 2.0
    while elapsed < timeout_sec:
        if should_stop():
            return False
        if await captcha_solved(page) or not await captcha_visible(page):
            LOG_BUS.emit("SUCCESS", bot_id, f"{label} tamamlandi")
            await asyncio.sleep(1.0)
            return True
        if elapsed > 0 and elapsed % 30 == 0:
            LOG_BUS.emit("INFO", bot_id, f"{label} bekleniyor... ({timeout_sec - elapsed} sn)")
        await asyncio.sleep(poll)
        elapsed += int(poll)

    LOG_BUS.emit("ERROR", bot_id, f"{label} zaman asimi")
    return False


async def _try_paid_service(page: Page, bot_id: int, *, attempts: int = 2) -> bool:
    """CapSolver ve/veya 2captcha ile coz — hangisinin kullanildigi
    try_auto_solve_recaptcha icinde CAPTCHA_SERVICE/mevcut key'lere gore secilir."""
    if not _HAS_PAID_CAPTCHA_KEY:
        return False
    for i in range(attempts):
        LOG_BUS.emit("INFO", bot_id, f"{_PAID_SERVICE_LABEL} deneniyor ({i + 1}/{attempts})...")
        if await try_auto_solve_recaptcha(page, bot_id):
            await asyncio.sleep(1.0)
            if await signup_captcha_ready(page) or await captcha_solved(page):
                return True
        await asyncio.sleep(1.5)
    return False


# Geriye donuk uyumluluk (eski adiyla cagiranlar icin).
_try_2captcha = _try_paid_service


async def resolve_captcha(
    page: Page,
    bot_id: int,
    *,
    timeout_sec: int = 300,
    label: str = "reCAPTCHA",
    force: bool = False,
) -> bool:
    """force=True: signup_captcha_ready sadece butonun aktif/pasif olup
    olmadigina bakiyor, token'in GECERLI oldugunu garanti etmiyor — sunucu
    hatasi sonrasi eski/gecersiz token ile tekrar tiklamamak icin bu
    kisayollari atlayip her zaman taze coz."""
    if not force:
        if await signup_captcha_ready(page):
            return True
        if not await captcha_visible(page):
            return True

    await clear_recaptcha_tokens(page)
    await _focus_browser(page, bot_id)

    # Ucretli servis (CapSolver/2captcha) once — kayit formunda daha guvenilir
    if _HAS_PAID_CAPTCHA_KEY and await _try_paid_service(page, bot_id):
        return await signup_captcha_ready(page) or await captcha_solved(page)

    if buster_available():
        if await try_buster_solve(page, bot_id, wait_sec=60):
            await asyncio.sleep(0.8)
            if await signup_captcha_ready(page) or await captcha_solved(page) or not await captcha_visible(page):
                LOG_BUS.emit("SUCCESS", bot_id, "Buster ile captcha gecildi")
                return True
    else:
        LOG_BUS.emit("INFO", bot_id, "Buster yok — setup_buster.bat ile kurulabilir")

    # Buster yetmediyse ucretli servis tekrar
    await clear_recaptcha_tokens(page)
    if _HAS_PAID_CAPTCHA_KEY and await _try_paid_service(page, bot_id, attempts=1):
        return await signup_captcha_ready(page) or await captcha_solved(page)

    return await wait_for_captcha_manual(page, bot_id, timeout_sec=timeout_sec, label=label)


async def ensure_captcha_before_action(page: Page, bot_id: int, *, label: str = "reCAPTCHA") -> bool:
    """Form gondermeden once captcha cozulmus mu — her seferinde yeniden coz."""
    for attempt in range(3):
        if await signup_captcha_ready(page):
            return True
        if await captcha_visible(page) or await captcha_token_present(page):
            LOG_BUS.emit("INFO", bot_id, f"Captcha cozuluyor ({attempt + 1}/3)...")
            await clear_recaptcha_tokens(page)
            if not await resolve_captcha(page, bot_id, label=label):
                return False
            await asyncio.sleep(1.0)
            if await signup_captcha_ready(page):
                return True
        elif not await captcha_visible(page):
            return True
        LOG_BUS.emit("WARNING", bot_id, "Captcha hala acik — tekrar denenecek")
        await asyncio.sleep(1.5)

    ok = await signup_captcha_ready(page) or not await captcha_visible(page)
    if not ok:
        LOG_BUS.emit("ERROR", bot_id, "Captcha cozulemedi — Uye Ol devre disi kalabilir")
    return ok


wait_for_captcha = resolve_captcha
