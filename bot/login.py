"""Trendyol otomatik giris — headless destekli."""

from __future__ import annotations

import asyncio
import re
import time

from playwright.async_api import Page

from bot.captcha import captcha_visible, resolve_captcha
from bot.human import human_delay
from bot.navigation import dismiss_overlays
from config import TRENDYOL_HOME
from core.async_utils import should_stop
from core.log_bus import LOG_BUS

LOGIN_URL = "https://www.trendyol.com/giris?cb=%2F"

EMAIL_SELECTORS = [
    "#login-email",
    "input[name='email']",
    "input[type='email']",
    "input[placeholder*='E-posta' i]",
    "input[placeholder*='e-posta' i]",
    "input[placeholder*='E-Posta' i]",
    "input[autocomplete='email']",
]

PASSWORD_SELECTORS = [
    "#login-password",
    "input[name='password']",
    "input[type='password']",
    "input[placeholder*='ifre' i]",
    "input[placeholder*='Sifre' i]",
    "input[autocomplete='current-password']",
]

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button:has-text('GİRİŞ YAP')",
    "button:has-text('Giriş Yap')",
    "button:has-text('Giriş')",
    ".login-button",
]

LOGGED_IN_SELECTORS = [
    "a[href*='hesabim']",
    "[data-testid='account-button']",
    "[class*='account-user']",
    "[data-testid='user-account']",
]

_LOGIN_ERROR = re.compile(
    r"hatal[iı]|yanl[iı][sş]|ge[cç]ersiz|bulunamad[iı]|"
    r"robot|recaptcha|captcha|guvenlik",
    re.I,
)


async def _header_guest_link(page: Page) -> bool:
    """Sadece ust menudeki Giriş Yap linki (formdaki buton degil)."""
    for root_sel in ("header", "[data-testid='header']", ".account-nav"):
        try:
            root = page.locator(root_sel)
            if await root.count() == 0:
                continue
            login = root.first.get_by_role("link", name=re.compile(r"Giri[sş]\s*Yap", re.I))
            if await login.count() > 0 and await login.first.is_visible(timeout=800):
                return True
        except Exception:
            continue

    try:
        login = page.locator("a[href*='giris']").first
        if await login.is_visible(timeout=600):
            txt = (await login.inner_text()).lower()
            if "giri" in txt:
                return True
    except Exception:
        pass
    return False


async def is_logged_in(page: Page) -> bool:
    url = (page.url or "").lower()
    if "/giris" in url or "/login" in url:
        return False

    if await _header_guest_link(page):
        return False

    for sel in LOGGED_IN_SELECTORS:
        try:
            if await page.locator(sel).first.is_visible(timeout=1500):
                return True
        except Exception:
            continue

    try:
        hesap = page.get_by_text(re.compile(r"Hesabım|Hesabim", re.I))
        if await hesap.count() > 0 and await hesap.first.is_visible(timeout=800):
            return True
    except Exception:
        pass

    return False


async def _password_visible(page: Page) -> bool:
    try:
        pw = page.get_by_role("textbox", name=re.compile(r"^Şifre$|^Sifre$", re.I))
        if await pw.count() > 0 and await pw.first.is_visible(timeout=600):
            return True
    except Exception:
        pass
    for sel in PASSWORD_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=600):
                return True
        except Exception:
            continue
    return False


async def _fill_first(page: Page, selectors: list[str], value: str) -> bool:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if await loc.is_visible(timeout=3000):
                await loc.click()
                await loc.fill("")
                await loc.fill(value)
                return True
        except Exception:
            continue

    for label in (r"E-Posta \*", r"E-Posta", r"E-posta"):
        try:
            loc = page.get_by_role("textbox", name=re.compile(label, re.I)).first
            if await loc.is_visible(timeout=1500):
                await loc.click()
                await loc.fill(value)
                return True
        except Exception:
            continue

    try:
        loc = page.get_by_placeholder(re.compile(r"E-?Posta", re.I)).first
        if await loc.is_visible(timeout=1500):
            await loc.click()
            await loc.fill(value)
            return True
    except Exception:
        pass
    return False


async def _click_devam_et(page: Page) -> bool:
    try:
        btn = page.get_by_role("button", name=re.compile(r"Devam\s*Et", re.I)).first
        if await btn.is_visible(timeout=2500):
            await btn.click()
            return True
    except Exception:
        pass
    try:
        btn = page.locator("button:has-text('Devam Et')").first
        if await btn.is_visible(timeout=1500):
            await btn.click()
            return True
    except Exception:
        pass
    return False


async def _wait_password_step(page: Page, bot_id: int) -> bool:
    for _ in range(25):
        if await _password_visible(page):
            return True
        await asyncio.sleep(0.25)
    LOG_BUS.emit("ERROR", bot_id, "Sifre adimi acilmadi (Devam Et sonrasi)")
    return False


async def _fill_password(page: Page, password: str) -> bool:
    try:
        loc = page.get_by_role("textbox", name=re.compile(r"^Şifre$|^Sifre$", re.I)).first
        if await loc.is_visible(timeout=4000):
            await loc.click()
            await loc.fill(password)
            return True
    except Exception:
        pass

    if await _fill_first(page, PASSWORD_SELECTORS, password):
        return True

    try:
        loc = page.get_by_label(re.compile(r"Şifre|Sifre", re.I)).first
        if await loc.is_visible(timeout=2000):
            await loc.click()
            await loc.fill(password)
            return True
    except Exception:
        pass

    try:
        loc = page.get_by_placeholder(re.compile(r"Şifre|Sifre|ifre", re.I)).first
        if await loc.is_visible(timeout=2000):
            await loc.click()
            await loc.fill(password)
            return True
    except Exception:
        pass
    return False


async def _click_login_submit(page: Page) -> bool:
    try:
        btn = page.get_by_role("button", name=re.compile(r"^Giri[sş]\s*Yap$", re.I)).first
        if await btn.is_visible(timeout=2500):
            await btn.click()
            return True
    except Exception:
        pass

    for sel in SUBMIT_SELECTORS:
        loc = page.locator(sel).first
        try:
            if await loc.is_visible(timeout=2000):
                await loc.click()
                return True
        except Exception:
            continue
    return False


async def _login_error_text(page: Page) -> str | None:
    try:
        body = await page.inner_text("body")
        for line in body.splitlines():
            line = line.strip()
            if len(line) < 8 or len(line) > 200:
                continue
            if _LOGIN_ERROR.search(line):
                return line
    except Exception:
        pass
    return None


async def _wait_login_result(
    page: Page,
    bot_id: int,
    *,
    speed: float,
    allow_captcha: bool = False,
    fast_timeout_sec: float = 12.0,
) -> bool:
    """Giris sonucu (basarili/hatali) icin HIZLI bekleme.

    Var olan bir hesapla normal (form) giriste Trendyol pratikte captcha
    istemiyor — sadece supheli/yeni cihaz girislerinde nadiren SMS/captcha
    cikabiliyor. Bu yuzden:
    - Captcha bekleme/cozme mantigi VARSAYILAN OLARAK KAPALI
      (allow_captcha=False) — "captcha gelebilir" diye bekleme YOK, login
      sonucu (`is_logged_in` / hata mesaji) en hizli sekilde kontrol edilir.
    - Polling araligi 2.0s -> 0.25s'e indirildi, gereksiz `human_delay`
      cagrisi kaldirildi; toplam hizli-bekleme suresi `fast_timeout_sec`
      (varsayilan 12 sn) ile sinirli.
    - Gercek SMS/OTP dogrulama (captcha degil, hesap guvenligi — otomatik
      cozulemez) icin ayri/daha uzun bir bekleme dali korunuyor; bu, "her
      hesaba giris hizli olsun" talebini etkilemez cunku OTP zaten nadir
      ve elle mudahale gerektiren bir durumdur.
    """
    captcha_handled = False
    otp_warned = False
    otp_extra_ticks = 0
    OTP_MAX_EXTRA_TICKS = 60  # OTP gorulurse ekstra ~60 * 1.0s = 60 sn

    deadline = time.monotonic() + fast_timeout_sec

    while True:
        if should_stop():
            return False

        if await is_logged_in(page):
            return True

        if allow_captcha and await captcha_visible(page):
            if not captcha_handled:
                ok = await resolve_captcha(page, bot_id, timeout_sec=180)
                captcha_handled = True
                if not ok:
                    return False
                if await _password_visible(page):
                    LOG_BUS.emit("INFO", bot_id, "Captcha sonrasi tekrar Giris Yap tiklaniyor")
                    await _click_login_submit(page)
                continue

        err = await _login_error_text(page)
        if err and "robot" not in err.lower() and "captcha" not in err.lower():
            LOG_BUS.emit("ERROR", bot_id, f"Giris hatasi: {err[:120]}")
            return False

        otp_now = False
        try:
            otp = page.locator(
                "input[placeholder*='kod' i], input[name*='otp' i], input[autocomplete='one-time-code']"
            )
            otp_now = await otp.first.is_visible(timeout=200)
        except Exception:
            pass

        if otp_now:
            if not otp_warned:
                LOG_BUS.emit(
                    "WARNING", bot_id, "SMS/dogrulama kodu — tarayicida elle girin (60 sn)",
                )
                otp_warned = True
            if otp_extra_ticks >= OTP_MAX_EXTRA_TICKS:
                break
            otp_extra_ticks += 1
            await asyncio.sleep(1.0)
            continue

        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.25)

    return await is_logged_in(page)


async def trendyol_login(
    page: Page,
    email: str,
    password: str,
    bot_id: int,
    *,
    speed: float = 1.0,
    force: bool = False,
    allow_captcha: bool = False,
) -> bool:
    """Trendyol'a email/sifre ile giris (2 adimli: e-posta -> Devam Et -> sifre).

    `allow_captcha=False` (varsayilan): LOGIN akisinda captcha bekleme/cozme
    mantigi tamamen devre disi — var olan hesaplarla normal giriste Trendyol
    pratikte captcha istemiyor, bu yuzden giris cok daha hizli sonuclanir.
    Supheli/yeni cihaz gibi nadir durumlarda captcha cikarsa ve cozulmesi
    isteniyorsa `allow_captcha=True` verilebilir (eski davranis). NOT: Bu
    parametre SADECE giris icindir — hesap OLUSTURMA (signup) akisi
    (`bot/signup.py`) captcha'yi kendi icinde ayri ve degismeden kullanmaya
    devam eder.
    """
    LOG_BUS.emit("INFO", bot_id, f"Giris deneniyor: {email[:3]}***")

    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
    await dismiss_overlays(page, bot_id)
    await human_delay(bot_id, 1.5, 2.5, speed=speed)
    await dismiss_overlays(page, bot_id)

    if not force and await is_logged_in(page):
        LOG_BUS.emit("SUCCESS", bot_id, "Oturum acik (hesap zaten girisli)")
        return True

    LOG_BUS.emit("INFO", bot_id, "Giris formu dolduruluyor...")

    if not await _password_visible(page):
        if not await _fill_first(page, EMAIL_SELECTORS, email):
            LOG_BUS.emit("ERROR", bot_id, "E-posta alani bulunamadi")
            return False

        await human_delay(bot_id, 0.4, 0.9, speed=speed)

        if allow_captcha and await captcha_visible(page):
            if not await resolve_captcha(page, bot_id):
                return False

        if not await _click_devam_et(page):
            LOG_BUS.emit("ERROR", bot_id, "Devam Et butonu bulunamadi")
            return False

        LOG_BUS.emit("INFO", bot_id, "E-posta gonderildi — sifre adimi bekleniyor")
        await human_delay(bot_id, 1.0, 2.0, speed=speed)
        if not await _wait_password_step(page, bot_id):
            return False

    if not await _fill_password(page, password):
        LOG_BUS.emit("ERROR", bot_id, "Sifre alani bulunamadi")
        return False

    await human_delay(bot_id, 0.5, 1.0, speed=speed)

    if allow_captcha and await captcha_visible(page):
        LOG_BUS.emit("INFO", bot_id, "Sifre adiminda captcha var — once cozun")
        if not await resolve_captcha(page, bot_id):
            return False

    if not await _click_login_submit(page):
        await page.keyboard.press("Enter")

    LOG_BUS.emit("INFO", bot_id, "Giris sonucu bekleniyor...")
    if not await _wait_login_result(page, bot_id, speed=speed, allow_captcha=allow_captcha):
        if allow_captcha and await captcha_visible(page):
            LOG_BUS.emit("ERROR", bot_id, "reCAPTCHA cozulmedi — Chrome'da kutucugu isaretleyin")
        else:
            LOG_BUS.emit("ERROR", bot_id, "Giris basarisiz — e-posta/sifre veya SMS dogrulama")
        return False

    await page.goto(TRENDYOL_HOME, wait_until="domcontentloaded")
    await dismiss_overlays(page, bot_id)

    if await is_logged_in(page):
        LOG_BUS.emit("SUCCESS", bot_id, "Giris basarili")
        return True

    LOG_BUS.emit("ERROR", bot_id, "Giris basarisiz — ana sayfada oturum yok")
    return False


async def login_with_token(
    page: Page,
    token: str,
    email: str = "",
    bot_id: int = 0,
    *,
    speed: float = 1.0,
    redirect_url: str = "",
) -> bool:
    """Trendyol'a JWT auth token'i ('token' cookie'si) enjekte ederek giris yapar.

    Form tabanli girise (`trendyol_login`) gore avantajlari:
    - ~10-15x daha hizli (form doldurma / "Devam Et" adimlari yok).
    - Yanlis sifre / captcha riski yok (sifre hic kullanilmiyor).

    Token, Trendyol'un normal giris sonrasi `.trendyol.com` domaininde
    ayarladigi httpOnly `token` cookie'siyle ayni formattadir (ES256 imzali
    JWT; `email`/`userId`/`iss=auth.trendyol.com` claim'leri icerir). Hesap
    olusturma veya harici bir akistan elde edilmis boyle bir token varsa
    burada kullanilabilir; token gecersiz/suresi dolmussa fonksiyon False
    doner ve cagiran taraf normal form-login'e (`trendyol_login`) geri
    dusebilir.
    """
    token = (token or "").strip()
    if not token:
        LOG_BUS.emit("ERROR", bot_id, "login_with_token: token bos")
        return False

    masked = f"{email[:3]}***" if email else "???"
    LOG_BUS.emit("INFO", bot_id, f"Token ile giris deneniyor: {masked}")

    try:
        await page.context.add_cookies([
            {
                "name": "token",
                "value": token,
                "domain": ".trendyol.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ])
    except Exception as exc:
        LOG_BUS.emit("ERROR", bot_id, f"Token cookie eklenemedi: {exc}")
        return False

    try:
        dest = (redirect_url or TRENDYOL_HOME).strip()
        await page.goto(dest, wait_until="domcontentloaded", timeout=20_000 if redirect_url else 30_000)
    except Exception as exc:
        LOG_BUS.emit("ERROR", bot_id, f"Sayfa acilamadi: {exc}")
        return False

    await dismiss_overlays(page, bot_id)
    if not redirect_url:
        await human_delay(bot_id, 0.3, 0.7, speed=speed)

    if await is_logged_in(page):
        LOG_BUS.emit("SUCCESS", bot_id, "Token ile giris basarili")
        return True

    LOG_BUS.emit("WARNING", bot_id, "Token ile giris basarisiz — token gecersiz/suresi dolmus olabilir")
    return False


async def smart_login(
    page: Page,
    email: str,
    password: str,
    bot_id: int,
    *,
    token: str = "",
    speed: float = 1.0,
    force: bool = False,
    allow_captcha: bool = False,
) -> bool:
    """Varsa once token ile (hizli/guvenilir), olmazsa/basarisiz olursa
    normal email+sifre formuyla giris dener. Mevcut cagrilari degistirmez —
    yeni, opsiyonel bir giris noktasidir."""
    if token:
        if await login_with_token(page, token, email, bot_id, speed=speed):
            return True
        LOG_BUS.emit("INFO", bot_id, "Token basarisiz — form-login'e dusuluyor")

    return await trendyol_login(
        page, email, password, bot_id, speed=speed, force=force, allow_captcha=allow_captcha,
    )


async def ensure_logged_in(
    page: Page,
    email: str,
    password: str,
    bot_id: int,
    *,
    speed: float = 1.0,
    allow_captcha: bool = False,
) -> bool:
    """Mevcut sayfada oturum yoksa giris yap."""
    if await is_logged_in(page):
        return True
    LOG_BUS.emit("WARNING", bot_id, "Oturum yok — tekrar giris yapiliyor")
    return await trendyol_login(
        page, email, password, bot_id, speed=speed, force=True, allow_captcha=allow_captcha,
    )
