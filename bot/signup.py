"""Trendyol hesap kaydi — uyelik + e-posta dogrulama."""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import Page

from bot.captcha import captcha_visible, resolve_captcha
from bot.human import human_delay
from bot.login import is_logged_in
from bot.navigation import dismiss_overlays
from core.async_utils import should_stop
from core.log_bus import LOG_BUS
from services.temp_mail import EmailRejectedError, TempInbox, wait_verification_code

SIGNUP_URL = "https://www.trendyol.com/giris?cb=%2F"
MEMBERSHIP_URL = "https://www.trendyol.com/uyelik"


async def _fill_email(page: Page, email: str) -> bool:
    for label in (r"E-Posta \*", r"E-Posta", r"E-posta"):
        try:
            loc = page.get_by_role("textbox", name=re.compile(label, re.I)).first
            if await loc.is_visible(timeout=3000):
                await loc.click()
                await loc.fill(email)
                return True
        except Exception:
            continue
    try:
        loc = page.locator("input[type='email'], input[name='email']").first
        if await loc.is_visible(timeout=2000):
            await loc.fill(email)
            return True
    except Exception:
        pass
    return False


async def _email_rejected(page: Page) -> bool:
    try:
        body = (await page.inner_text("body")).lower()
        return (
            "e-posta adresi kullanılamaz" in body
            or "e-posta adresi kullanilamaz" in body
            or "başka bir e-posta" in body
            or "baska bir e-posta" in body
        )
    except Exception:
        return False


async def _click_devam_et(page: Page) -> bool:
    try:
        btn = page.get_by_role("button", name=re.compile(r"Devam\s*Et", re.I)).first
        if await btn.is_visible(timeout=2500):
            await btn.click()
            return True
    except Exception:
        pass
    return False


async def _on_membership_page(page: Page) -> bool:
    url = (page.url or "").lower()
    if "/uyelik" in url:
        return True
    try:
        return await page.get_by_role("heading", name=re.compile(r"Hesap\s*Olu", re.I)).is_visible(timeout=1500)
    except Exception:
        return False


async def _fill_signup_form(page: Page, password: str, bot_id: int) -> bool:
    try:
        pw = page.get_by_role("textbox", name=re.compile(r"^Şifre$|^Sifre$", re.I)).first
        if await pw.is_visible(timeout=4000):
            await pw.click()
            await pw.fill(password)
    except Exception:
        LOG_BUS.emit("ERROR", bot_id, "Kayit: sifre alani bulunamadi")
        return False

    # Cinsiyet (istege bagli) — Erkek sec
    try:
        gender = page.get_by_role("button", name=re.compile(r"^Erkek$", re.I)).first
        if await gender.is_visible(timeout=1000):
            await gender.click()
    except Exception:
        pass

    # Zorunlu onay kutulari
    try:
        boxes = page.locator("input[type='checkbox']")
        count = await boxes.count()
        for i in range(count):
            box = boxes.nth(i)
            try:
                if await box.is_visible(timeout=400) and not await box.is_checked():
                    await box.check(force=True)
            except Exception:
                try:
                    await box.click(force=True)
                except Exception:
                    pass
    except Exception:
        pass

    await human_delay(bot_id, 0.5, 1.0, speed=1.0)
    return True


async def _click_uye_ol(page: Page) -> bool:
    try:
        btn = page.get_by_role("button", name=re.compile(r"^Üye\s*Ol$|^Uye\s*Ol$", re.I)).first
        if await btn.is_visible(timeout=2000):
            if await btn.is_disabled():
                await asyncio.sleep(0.8)
            await btn.click()
            return True
    except Exception:
        pass
    return False


async def _verification_visible(page: Page) -> bool:
    try:
        if await page.get_by_text(re.compile(r"E-?posta\s*Do[gğ]rulama", re.I)).first.is_visible(timeout=800):
            return True
    except Exception:
        pass
    try:
        loc = page.get_by_role("textbox", name=re.compile(r"Do[gğ]rulama\s*Kodu", re.I))
        if await loc.count() > 0 and await loc.first.is_visible(timeout=800):
            return True
    except Exception:
        pass
    try:
        loc = page.locator("input[maxlength='1'], input[autocomplete='one-time-code']")
        if await loc.count() >= 4:
            return True
    except Exception:
        pass
    return False


async def _fill_verification_code(page: Page, code: str, bot_id: int) -> bool:
    code = re.sub(r"\D", "", code)[:6]
    if len(code) < 4:
        return False

    # Tek kutu
    try:
        loc = page.get_by_role("textbox", name=re.compile(r"Do[gğ]rulama\s*Kodu", re.I)).first
        if await loc.is_visible(timeout=3000):
            await loc.click()
            await loc.fill(code)
            LOG_BUS.emit("INFO", bot_id, f"Dogrulama kodu yazildi ({len(code)} hane)")
            return True
    except Exception:
        pass

    # OTP kutulari (6 ayri input)
    try:
        cells = page.locator("input[maxlength='1']")
        n = await cells.count()
        if n >= len(code):
            for i, ch in enumerate(code):
                await cells.nth(i).fill(ch)
            LOG_BUS.emit("INFO", bot_id, "Dogrulama kodu OTP kutularina yazildi")
            return True
    except Exception:
        pass

    try:
        loc = page.locator("input[autocomplete='one-time-code']").first
        if await loc.is_visible(timeout=1500):
            await loc.fill(code)
            return True
    except Exception:
        pass

    return False


async def _click_verify_continue(page: Page) -> bool:
    for name in (r"Devam\s*Et", r"^Gönder$|^Gonder$|^Onayla$"):
        try:
            btn = page.get_by_role("button", name=re.compile(name, re.I)).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                return True
        except Exception:
            continue
    return False


async def register_trendyol_account(
    page: Page,
    inbox: TempInbox,
    password: str,
    bot_id: int,
    *,
    speed: float = 1.0,
) -> bool:
    email = inbox.address
    LOG_BUS.emit("INFO", bot_id, f"Trendyol kayit: {email}")

    await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=60_000)
    await dismiss_overlays(page, bot_id)
    await human_delay(bot_id, 1.0, 1.8, speed=speed)

    if await captcha_visible(page):
        if not await resolve_captcha(page, bot_id):
            return False

    if not await _fill_email(page, email):
        LOG_BUS.emit("ERROR", bot_id, "E-posta alani bulunamadi")
        return False

    await human_delay(bot_id, 0.4, 0.8, speed=speed)
    if not await _click_devam_et(page):
        LOG_BUS.emit("ERROR", bot_id, "Devam Et bulunamadi")
        return False

    await asyncio.sleep(1.2)
    if await _email_rejected(page):
        LOG_BUS.emit("WARNING", bot_id, f"Trendyol maili reddetti: {email}")
        raise EmailRejectedError(email)

    LOG_BUS.emit("INFO", bot_id, "Uyelik formu bekleniyor...")
    for _ in range(30):
        if should_stop():
            return False
        if await _on_membership_page(page):
            break
        await asyncio.sleep(0.4)
    else:
        LOG_BUS.emit("ERROR", bot_id, "Uyelik sayfasi acilmadi")
        return False

    if not await _fill_signup_form(page, password, bot_id):
        return False

    if await captcha_visible(page):
        if not await resolve_captcha(page, bot_id):
            return False

    if not await _click_uye_ol(page):
        LOG_BUS.emit("ERROR", bot_id, "Uye Ol butonu tiklanamadi")
        return False

    LOG_BUS.emit("INFO", bot_id, "E-posta dogrulama ekrani bekleniyor...")
    for _ in range(40):
        if should_stop():
            return False
        if await _verification_visible(page) or await is_logged_in(page):
            break
        await asyncio.sleep(0.5)

    if await is_logged_in(page):
        LOG_BUS.emit("SUCCESS", bot_id, "Hesap olusturuldu (dogrulama gerekmedi)")
        return True

    if not await _verification_visible(page):
        LOG_BUS.emit("ERROR", bot_id, "Dogrulama ekrani acilmadi")
        return False

    code = await wait_verification_code(inbox, timeout_sec=180)
    if not code:
        LOG_BUS.emit(
            "WARNING",
            bot_id,
            "Kod gelmedi — tarayicida elle girip Devam Et'e basin (90 sn)",
        )
        for _ in range(45):
            if should_stop():
                return False
            if await is_logged_in(page):
                break
            await asyncio.sleep(2.0)
        return await is_logged_in(page)

    if not await _fill_verification_code(page, code, bot_id):
        LOG_BUS.emit("ERROR", bot_id, "Dogrulama kodu yazilamadi")
        return False

    await human_delay(bot_id, 0.4, 0.8, speed=speed)
    if not await _click_verify_continue(page):
        await page.keyboard.press("Enter")

    for _ in range(30):
        if should_stop():
            return False
        if await is_logged_in(page):
            LOG_BUS.emit("SUCCESS", bot_id, "Trendyol hesabi acildi")
            return True
        await asyncio.sleep(1.0)

    LOG_BUS.emit("ERROR", bot_id, "Dogrulama sonrasi oturum acilmadi")
    return False
