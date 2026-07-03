"""Gecici e-posta — Trendyol uyumlu (tempmail.lol oncelikli)."""

from __future__ import annotations

import asyncio
import os
import random
import re
import string
from dataclasses import dataclass
from typing import Protocol

import httpx
from playwright.async_api import Page

from core.log_bus import LOG_BUS

_CODE_PATTERNS = (
    re.compile(r"dogrulama\s*kodu[^\d]{0,40}(\d{6})", re.I),
    re.compile(r"verification\s*code[^\d]{0,40}(\d{6})", re.I),
    re.compile(r"\b(\d{6})\b"),
)

# Trendyol'un reddettigi bilinen domainler
TRENDYOL_BLOCKED_DOMAINS = (
    "web-library.net",
    "guerrillamail",
    "maildrop.cc",
    "mail.tm",
    "10minutemail",
    "yopmail.com",
    "sharklasers.com",
)

# Trendyol'da genelde kabul goren domainler (tempmail.lol agi)
PREFERRED_DOMAINS = (
    "tempmail.lol",
    "icodetensor.com",
)


@dataclass
class TempInbox:
    address: str
    provider: str
    token: str = ""
    password: str = ""
    mail_password: str = ""


class EmailRejectedError(Exception):
    """Trendyol e-posta adresini reddetti."""


def domain_of(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


def is_blocked_domain(email: str) -> bool:
    dom = domain_of(email)
    return any(b in dom for b in TRENDYOL_BLOCKED_DOMAINS)


def domain_score(email: str) -> int:
    dom = domain_of(email)
    if is_blocked_domain(email):
        return -100
    for i, pref in enumerate(PREFERRED_DOMAINS):
        if dom.endswith(pref) or pref in dom:
            return 100 - i
    return 10


def _extract_code(text: str) -> str | None:
    for pat in _CODE_PATTERNS:
        m = pat.search(text or "")
        if m:
            return m.group(1)
    return None


class MailProvider(Protocol):
    async def wait_code(self, inbox: TempInbox, *, timeout_sec: int = 180) -> str | None: ...


class TempMailLolFetcher:
    BASE = "https://api.tempmail.lol/v2/inbox"

    async def wait_code(self, inbox: TempInbox, *, timeout_sec: int = 180) -> str | None:
        if not inbox.token:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            for _ in range(max(1, timeout_sec // 4)):
                r = await client.get(self.BASE, params={"token": inbox.token})
                if r.status_code != 200:
                    await asyncio.sleep(4)
                    continue
                data = r.json()
                for mail in data.get("emails", []):
                    blob = " ".join(
                        str(mail.get(k, "") or "")
                        for k in ("from", "to", "subject", "body", "html")
                    )
                    if "trendyol" not in blob.lower() and _extract_code(blob) is None:
                        continue
                    code = _extract_code(blob)
                    if code:
                        return code
                await asyncio.sleep(4)
        return None


async def _read_tempmail_storage(page: Page) -> tuple[str, str]:
    address = await page.evaluate("localStorage.getItem('address') || ''")
    token = await page.evaluate("localStorage.getItem('address_token') || ''")
    return str(address), str(token)


async def _click_tempmail_reset(page: Page) -> None:
    await page.evaluate(
        """
        () => {
          const el = Array.from(document.querySelectorAll('div'))
            .find(n => (n.innerText || '').trim() === 'Reset');
          if (el) el.click();
        }
        """
    )


async def create_temp_inbox_browser(page: Page, *, max_reset: int = 15) -> TempInbox:
    """
    tempmail.lol sitesinden gercek inbox (TR'de API create kapali, site calisiyor).
    Reset ile tempmail.lol / icodetensor domaini aranir.
    """
    LOG_BUS.emit("INFO", 0, "Temp mail aciliyor (tempmail.lol)...")
    await page.goto("https://tempmail.lol/en/", wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(2.5)

    from bot.captcha import resolve_captcha

    if await resolve_captcha(page, 0, label="TempMail reCAPTCHA"):
        pass

    best: TempInbox | None = None
    best_score = -999

    for attempt in range(max_reset):
        address, token = await _read_tempmail_storage(page)
        if address and token and not is_blocked_domain(address):
            score = domain_score(address)
            inbox = TempInbox(address=address, provider="tempmail.lol", token=token)
            if score >= 100:
                LOG_BUS.emit("INFO", 0, f"Temp mail: {address} (tercih edilen domain)")
                return inbox
            if score > best_score:
                best_score = score
                best = inbox

        if attempt < max_reset - 1:
            await _click_tempmail_reset(page)
            await asyncio.sleep(2.0)

    if best:
        LOG_BUS.emit("INFO", 0, f"Temp mail: {best.address} (yedek domain)")
        return best

    raise RuntimeError(
        "Uygun temp mail bulunamadi — tempmail.lol sitesini kontrol edin veya TEMPMAIL_API_KEY deneyin"
    )


async def create_temp_inbox_api_key() -> TempInbox | None:
    """TempMail Plus/Ultra API key varsa (TR bypass)."""
    api_key = os.environ.get("TEMPMAIL_API_KEY", "").strip()
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        r = await client.post(
            "https://api.tempmail.lol/v2/inbox/create",
            json={"prefix": "ty" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))},
        )
        if r.status_code != 201:
            LOG_BUS.emit("WARNING", 0, f"TempMail API: {r.text[:120]}")
            return None
        data = r.json()
        return TempInbox(
            address=data["address"],
            provider="tempmail.lol-api",
            token=data["token"],
        )


async def create_temp_inbox(page: Page | None = None) -> TempInbox:
    api_inbox = await create_temp_inbox_api_key()
    if api_inbox and not is_blocked_domain(api_inbox.address):
        LOG_BUS.emit("INFO", 0, f"Temp mail (API): {api_inbox.address}")
        return api_inbox

    if page is None:
        raise RuntimeError("Temp mail icin Playwright sayfasi gerekli (tempmail.lol)")

    return await create_temp_inbox_browser(page)


async def wait_verification_code(inbox: TempInbox, *, timeout_sec: int = 180) -> str | None:
    fetcher = TempMailLolFetcher()
    LOG_BUS.emit("INFO", 0, f"Dogrulama maili bekleniyor ({inbox.address})...")
    code = await fetcher.wait_code(inbox, timeout_sec=timeout_sec)
    if code:
        LOG_BUS.emit("SUCCESS", 0, f"Dogrulama kodu alindi: {code}")
    else:
        LOG_BUS.emit("ERROR", 0, "Dogrulama kodu gelmedi (timeout)")
    return code
