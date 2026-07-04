"""Gecici e-posta — Trendyol uyumlu (tempmail.lol oncelikli)."""

from __future__ import annotations

import asyncio
import html as html_lib
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
    re.compile(r"do[gğ]rulama\s*kod(?:u|unuz)?\s*[:\-]?\s*(\d{4,8})", re.I),
    re.compile(r"verification\s*code\s*[:\-]?\s*(\d{4,8})", re.I),
    re.compile(r"kodunuz\s*[:\-]?\s*(\d{4,8})", re.I),
    re.compile(r"\bkod\s*[:\-]?\s*(\d{4,8})\b", re.I),
    # son care: yakinlarinda anahtar kelime olmasa da izole 6 haneli sayi
    # (hex renk / url / telefon gibi seylere bitismemeli — asagida filtrelenir)
    re.compile(r"(?<![#/:.\-%\d])\b(\d{6})\b(?![\d%])"),
)

_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>.*?</style>", re.I | re.S)
_SCRIPT_BLOCK_RE = re.compile(r"<script[^>]*>.*?</script>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _visible_text(raw: str) -> str:
    """HTML mailden CSS/script/etiketleri temizleyip goze gorunen metni cikar.

    Onemli: e-posta sablonlarindaki style="color:#767676" gibi hex renk
    kodlari 6 haneli sayi oldugu icin dogrulama kodu ile karisabiliyordu —
    bu yuzden stil/etiket temizligi + hex renk filtreleme sart.
    """
    text = raw or ""
    text = _STYLE_BLOCK_RE.sub(" ", text)
    text = _SCRIPT_BLOCK_RE.sub(" ", text)
    text = _HEX_COLOR_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

_LINK_PATTERNS = (
    re.compile(
        r'href=["\'](https?://[^"\']*(?:trendyol\.com|ty\.gl)[^"\']*(?:dogrul|verify|confirm|activation|uyelik|register)[^"\']*)["\']',
        re.I,
    ),
    re.compile(
        r"(https?://(?:www\.)?trendyol\.com[^\s\"'<>]+(?:dogrul|verify|confirm|activation|token|code)[^\s\"'<>]*)",
        re.I,
    ),
    re.compile(r"(https?://(?:www\.)?trendyol\.com/[^\s\"'<>]{10,200})", re.I),
    re.compile(r"(https?://ty\.gl/[^\s\"'<>]+)", re.I),
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


@dataclass
class VerificationResult:
    code: str | None = None
    link: str | None = None


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


def _clean_link(url: str) -> str:
    url = url.replace("&amp;", "&").strip().rstrip(".,;)\"'")
    if url.endswith(">"):
        url = url[:-1]
    return url


def _extract_verification_link(text: str) -> str | None:
    blob = text or ""
    for pat in _LINK_PATTERNS:
        m = pat.search(blob)
        if m:
            link = _clean_link(m.group(1))
            if "trendyol" in link.lower() or "ty.gl" in link.lower():
                return link
    return None


def _extract_code(text: str) -> str | None:
    """Goze gorunen e-posta metninden dogrulama kodunu cikar.

    `text` cagiran tarafindan zaten _visible_text() ile temizlenmis olmali
    (CSS/hex renk/etiket icermemeli), aksi halde yanlis pozitif riski var.
    """
    blob = text or ""
    for pat in _CODE_PATTERNS[:4]:
        m = pat.search(blob)
        if m:
            return m.group(1)

    if re.search(r"dogrulama|do[gğ]rula|verification|onay|kod", blob, re.I):
        m = _CODE_PATTERNS[4].search(blob)
        if m:
            code = m.group(1)
            if len(set(code)) > 1:
                return code
    return None


def _parse_verification_mail(blob: str) -> VerificationResult:
    link = _extract_verification_link(blob)
    code = None if link else _extract_code(_visible_text(blob))
    return VerificationResult(code=code, link=link)


class MailProvider(Protocol):
    async def wait_verification(
        self, inbox: TempInbox, *, timeout_sec: int = 180,
    ) -> VerificationResult | None: ...


class TempMailLolFetcher:
    BASE = "https://api.tempmail.lol/v2/inbox"

    async def wait_verification(
        self, inbox: TempInbox, *, timeout_sec: int = 180,
    ) -> VerificationResult | None:
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
                    # "from"/"to" adres alanlari dogrulama kodu/link icermez —
                    # sadece gurultu ekleyip yanlis pozitife yol acabilirler.
                    content_blob = " ".join(
                        str(mail.get(k, "") or "") for k in ("subject", "body", "html")
                    )
                    low = (str(mail.get("subject", "")) + " " + content_blob).lower()
                    visible = _visible_text(content_blob)
                    if (
                        "trendyol" not in low
                        and _extract_code(visible) is None
                        and _extract_verification_link(content_blob) is None
                    ):
                        continue
                    result = _parse_verification_mail(content_blob)
                    if result.link or result.code:
                        return result
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
    tempmail.lol sitesinden gercek inbox (TR'de ucretsiz API kapali olabilir).
    Reset ile tempmail.lol / icodetensor domaini aranir.
    """
    LOG_BUS.emit("INFO", 0, "Temp mail aciliyor (tempmail.lol)...")
    api_blocked: str | None = None

    async def _on_response(response) -> None:
        nonlocal api_blocked
        if "api.tempmail.lol" in response.url and "/inbox/create" in response.url:
            if response.status == 403:
                try:
                    body = await response.json()
                    api_blocked = str(body.get("error", body))
                except Exception:
                    api_blocked = "403 Forbidden (TR IP engeli olabilir)"

    page.on("response", _on_response)
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

    if api_blocked and ("TR" in api_blocked.upper() or "country" in api_blocked.lower()):
        LOG_BUS.emit(
            "ERROR",
            0,
            "tempmail.lol ucretsiz API Turkiye IP'den kapali. "
            "TempMail Plus API key (TEMPMAIL_API_KEY) veya VPN gerekli.",
        )
        raise RuntimeError(
            "tempmail.lol TR engeli — TEMPMAIL_API_KEY girin (tempmail.lol/pricing) veya VPN kullanin"
        )

    raise RuntimeError(
        "Uygun temp mail bulunamadi — tempmail.lol sitesini kontrol edin veya TEMPMAIL_API_KEY deneyin"
    )


async def create_temp_inbox_api_key() -> TempInbox | None:
    """TempMail Plus/Ultra API key varsa (TR bypass)."""
    api_key = os.environ.get("TEMPMAIL_API_KEY", "").strip()
    if not api_key:
        from config import TEMPMAIL_API_KEY as _cfg_key
        api_key = _cfg_key
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        r = await client.post(
            "https://api.tempmail.lol/v2/inbox/create",
            json={"prefix": "ty" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))},
        )
        if r.status_code != 201:
            detail = r.text[:200]
            LOG_BUS.emit("WARNING", 0, f"TempMail API ({r.status_code}): {detail}")
            if r.status_code == 403 and "TR" in r.text:
                LOG_BUS.emit(
                    "ERROR",
                    0,
                    "TempMail Plus key TR IP'den taninmadi — hesapta Plus aktif mi kontrol edin "
                    "(tempmail.lol → Login → API) veya VPN deneyin.",
                )
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


async def wait_verification(inbox: TempInbox, *, timeout_sec: int = 180) -> VerificationResult | None:
    fetcher = TempMailLolFetcher()
    LOG_BUS.emit("INFO", 0, f"Dogrulama maili bekleniyor ({inbox.address})...")
    result = await fetcher.wait_verification(inbox, timeout_sec=timeout_sec)
    if result and result.link:
        short = result.link[:70] + ("..." if len(result.link) > 70 else "")
        LOG_BUS.emit("SUCCESS", 0, f"Dogrulama linki alindi: {short}")
    elif result and result.code:
        LOG_BUS.emit("SUCCESS", 0, f"Dogrulama kodu alindi: {result.code}")
    else:
        LOG_BUS.emit("ERROR", 0, "Dogrulama maili gelmedi (timeout)")
    return result


async def wait_verification_code(inbox: TempInbox, *, timeout_sec: int = 180) -> str | None:
    result = await wait_verification(inbox, timeout_sec=timeout_sec)
    return result.code if result else None
