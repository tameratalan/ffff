"""Trendyol hesap kaydi — uyelik + e-posta dogrulama."""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import Page

from bot.captcha import captcha_visible, ensure_captcha_before_action, resolve_captcha
from bot.captcha_detect import clear_recaptcha_tokens, reset_recaptcha_widget, signup_captcha_ready
from bot.human import human_delay
from bot.login import is_logged_in
from bot.navigation import dismiss_overlays
from core.async_utils import should_stop
from core.log_bus import LOG_BUS
from services.temp_mail import EmailRejectedError, TempInbox, wait_verification

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


async def _click_uye_ol(page: Page, bot_id: int) -> bool:
    if not await ensure_captcha_before_action(page, bot_id, label="Kayit captcha"):
        LOG_BUS.emit("ERROR", bot_id, "Captcha cozulmeden Uye Ol tiklanamaz")
        return False

    for wait_i in range(15):
        if await signup_captcha_ready(page):
            break
        LOG_BUS.emit("INFO", bot_id, f"Uye Ol bekleniyor — captcha callback ({wait_i + 1}/15)")
        if await captcha_visible(page):
            await ensure_captcha_before_action(page, bot_id, label="Kayit captcha")
        await asyncio.sleep(1.0)

    selectors = (
        page.get_by_role("button", name=re.compile(r"Üye\s*Ol|Kay[iı]t\s*Ol", re.I)).first,
        page.locator("button:has-text('Üye Ol'), button:has-text('Uye Ol')").first,
        page.locator("button[type='submit'], input[type='submit']").first,
    )
    for attempt in range(10):
        for btn in selectors:
            try:
                if not await btn.is_visible(timeout=1500):
                    continue
                if await btn.is_disabled():
                    LOG_BUS.emit("INFO", bot_id, f"Uye Ol pasif — captcha bekleniyor ({attempt + 1}/10)")
                    if await captcha_visible(page):
                        await ensure_captcha_before_action(page, bot_id, label="Kayit captcha")
                    await asyncio.sleep(2.0)
                    continue
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=5000, force=True)
                LOG_BUS.emit("INFO", bot_id, "Uye Ol tiklandi")
                return True
            except Exception:
                continue

        try:
            submitted = await page.evaluate(
                """
                () => {
                  for (const f of document.querySelectorAll('form')) {
                    if (f.querySelector('input[type=password], input[name*=password i]')) {
                      if (typeof f.requestSubmit === 'function') { f.requestSubmit(); return 'requestSubmit'; }
                      f.submit(); return 'submit';
                    }
                  }
                  return '';
                }
                """
            )
            if submitted:
                LOG_BUS.emit("INFO", bot_id, f"Uye Ol formu gonderildi ({submitted})")
                await asyncio.sleep(2.0)
                return True
        except Exception:
            pass

        await asyncio.sleep(1.0)
    return False


_SIGNUP_ERROR = re.compile(r"bir hata olu[sş]tu", re.I)


async def _signup_error_visible(page: Page) -> bool:
    """Uye Ol sonrasi sunucu hatasi popup'i — genelde suresi dolmus
    captcha token'indan kaynaklanir (2captcha uzun surdugunde token
    Google tarafinda ~2 dk icinde gecersiz olabiliyor)."""
    try:
        loc = page.get_by_text(_SIGNUP_ERROR)
        return await loc.count() > 0 and await loc.first.is_visible(timeout=600)
    except Exception:
        return False


async def _dismiss_signup_error(page: Page) -> bool:
    for btn in (
        page.get_by_role("button", name=re.compile(r"^tamam$", re.I)).first,
        page.locator("button:has-text('Tamam')").first,
    ):
        try:
            if await btn.is_visible(timeout=1000):
                await btn.click()
                return True
        except Exception:
            continue
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


async def _verify_code_in_cells(page: Page, code: str, cell_count: int) -> bool:
    """OTP hucrelerine yazilan kodu geri okuyup dogrula."""
    try:
        cells = page.locator("input[maxlength='1']")
        parts = []
        for i in range(cell_count):
            parts.append((await cells.nth(i).input_value()) or "")
        return "".join(parts) == code
    except Exception:
        return False


async def _fill_verification_code(page: Page, code: str, bot_id: int) -> bool:
    code = re.sub(r"\D", "", code)[:6]
    if len(code) < 4:
        return False

    # OTP kutulari (ayri input'lar) — coklu kutularda cogu implementasyon
    # bir hucreye yazilinca otomatik bir sonrakine focus atar; click+fill
    # her hucrede tekrarlanirsa bu otomatik atlamayla catisip harfleri
    # karistirabiliyor. Once ilk hucreye tiklayip klavye ile art arda
    # yazmayi (auto-advance'e guvenerek) deniyoruz, sonucu geri okuyup
    # dogruluyoruz; tutmazsa hucre-hucre eski yonteme dusuyoruz.
    try:
        cells = page.locator("input[maxlength='1']")
        n = await cells.count()
        if n >= len(code):
            await cells.nth(0).click()
            await page.keyboard.type(code, delay=90)
            await asyncio.sleep(0.3)
            if await _verify_code_in_cells(page, code, len(code)):
                LOG_BUS.emit("INFO", bot_id, "Dogrulama kodu OTP kutularina yazildi (klavye)")
                return True

            for i, ch in enumerate(code):
                await cells.nth(i).click()
                await cells.nth(i).fill(ch)
            await asyncio.sleep(0.2)
            LOG_BUS.emit("INFO", bot_id, "Dogrulama kodu OTP kutularina yazildi (hucre-hucre)")
            return True
    except Exception:
        pass

    # Tek kutu
    for sel in (
        page.get_by_role("textbox", name=re.compile(r"Do[gğ]rulama\s*Kodu", re.I)).first,
        page.locator("input[autocomplete='one-time-code']").first,
        page.locator("input[inputmode='numeric']").first,
        page.locator("input[type='tel']").first,
        page.locator("input[type='text']").first,
    ):
        try:
            if await sel.is_visible(timeout=2000):
                await sel.click()
                await sel.fill(code)
                LOG_BUS.emit("INFO", bot_id, f"Dogrulama kodu yazildi ({len(code)} hane)")
                return True
        except Exception:
            continue

    return False


async def _complete_verification_link(page: Page, link: str, bot_id: int) -> bool:
    short = link[:65] + ("..." if len(link) > 65 else "")
    LOG_BUS.emit("INFO", bot_id, f"Dogrulama linki aciliyor: {short}")
    try:
        await page.goto(link, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        LOG_BUS.emit("ERROR", bot_id, f"Dogrulama linki acilamadi: {exc}")
        return False
    await dismiss_overlays(page, bot_id)
    await asyncio.sleep(2.0)
    for _ in range(40):
        if should_stop():
            return False
        if await is_logged_in(page):
            LOG_BUS.emit("SUCCESS", bot_id, "Dogrulama linki ile hesap acildi")
            return True
        await asyncio.sleep(1.0)
    return await is_logged_in(page)


_VERIFY_BUTTON_TEXT = re.compile(
    r"Devam\s*Et|G[oö]nder|Onayla|Do[gğ]rula|Kaydı?\s*Tamamla|Tamamla|Kayd[iı]\s*Tamamla|"
    r"Hesab[iı]m[iı]?\s*Olu[sş]tur|Devam|Continue|Submit|Verify",
    re.I,
)


async def _click_verify_continue(page: Page, bot_id: int | None = None) -> bool:
    for btn in (
        page.get_by_role("button", name=_VERIFY_BUTTON_TEXT).first,
        page.locator("button:not([disabled])").filter(has_text=_VERIFY_BUTTON_TEXT).first,
        page.locator("button[type='submit']:not([disabled])").first,
        page.locator("input[type='submit']:not([disabled])").first,
    ):
        try:
            if await btn.is_visible(timeout=1500) and not await btn.is_disabled():
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=4000, force=True)
                return True
        except Exception:
            continue

    # Hicbir buton bulunamadi/tiklanamadi — formu JS ile dogrudan gonder
    try:
        submitted = await page.evaluate(
            """
            () => {
              const codeInputs = document.querySelectorAll(
                "input[maxlength='1'], input[autocomplete='one-time-code'], input[inputmode='numeric']"
              );
              let form = null;
              for (const inp of codeInputs) {
                if (inp.closest('form')) { form = inp.closest('form'); break; }
              }
              if (!form) form = document.querySelector('form');
              if (!form) return '';
              if (typeof form.requestSubmit === 'function') { form.requestSubmit(); return 'requestSubmit'; }
              form.submit();
              return 'submit';
            }
            """
        )
        if submitted:
            if bot_id is not None:
                LOG_BUS.emit("INFO", bot_id, f"Dogrulama formu JS ile gonderildi ({submitted})")
            return True
    except Exception:
        pass

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
        if not await ensure_captcha_before_action(page, bot_id):
            return False

    for uye_attempt in range(3):
        if not await _click_uye_ol(page, bot_id):
            LOG_BUS.emit("ERROR", bot_id, "Uye Ol butonu tiklanamadi")
            return False

        await asyncio.sleep(1.5)
        if not await _signup_error_visible(page):
            break

        LOG_BUS.emit(
            "WARNING", bot_id,
            f"Sunucu hatasi (suresi dolmus captcha token olabilir) — "
            f"taze captcha ile tekrar deneniyor ({uye_attempt + 1}/3)",
        )
        await _dismiss_signup_error(page)
        await asyncio.sleep(0.5)
        await reset_recaptcha_widget(page)
        await clear_recaptcha_tokens(page)
        await asyncio.sleep(0.5)
        if not await resolve_captcha(page, bot_id, force=True):
            LOG_BUS.emit("ERROR", bot_id, "Tekrar captcha cozulemedi")
            return False
    else:
        LOG_BUS.emit("ERROR", bot_id, "Uye Ol sunucu hatasi tekrar tekrar verdi")
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
        try:
            shot = f"debug_no_verify_{bot_id}.png"
            await page.screenshot(path=shot)
            body = (await page.inner_text("body"))[:400].replace("\n", " | ")
            LOG_BUS.emit(
                "ERROR", bot_id,
                f"Dogrulama ekrani acilmadi — url={page.url} ekran={shot} govde={body}",
            )
        except Exception:
            LOG_BUS.emit("ERROR", bot_id, f"Dogrulama ekrani acilmadi — url={page.url}")
        return False

    verification = await wait_verification(inbox, timeout_sec=180)
    if verification and verification.link:
        if await _complete_verification_link(page, verification.link, bot_id):
            return True
        LOG_BUS.emit("WARNING", bot_id, "Link ile dogrulama basarisiz — kod deneniyor")

    if verification and verification.code:
        if not await _fill_verification_code(page, verification.code, bot_id):
            LOG_BUS.emit("ERROR", bot_id, "Dogrulama kodu yazilamadi")
            return False
        await human_delay(bot_id, 0.4, 0.8, speed=speed)
        clicked = await _click_verify_continue(page, bot_id)
        if not clicked:
            LOG_BUS.emit("WARNING", bot_id, "Devam/Gonder butonu bulunamadi — Enter deneniyor")
            await page.keyboard.press("Enter")
        else:
            LOG_BUS.emit("INFO", bot_id, "Dogrulama kodu gonderildi (buton tiklandi)")
        for _ in range(30):
            if should_stop():
                return False
            if await is_logged_in(page):
                LOG_BUS.emit("SUCCESS", bot_id, "Trendyol hesabi acildi")
                return True
            await asyncio.sleep(1.0)
        try:
            shot = f"debug_verify_fail_{bot_id}.png"
            await page.screenshot(path=shot)
            LOG_BUS.emit("ERROR", bot_id, f"Dogrulama sonrasi oturum acilmadi — url={page.url} ekran={shot}")
        except Exception:
            LOG_BUS.emit("ERROR", bot_id, f"Dogrulama sonrasi oturum acilmadi — url={page.url}")

        try:
            diag = await page.evaluate(
                """
                () => {
                  const btns = Array.from(document.querySelectorAll('button')).map(b => ({
                    text: (b.innerText || b.value || '').trim().slice(0, 40),
                    disabled: b.disabled,
                    visible: b.offsetParent !== null,
                    cls: (b.className || '').slice(0, 60),
                  })).filter(b => b.text);
                  const err = Array.from(document.querySelectorAll('[class*=error i], [class*=toast i], [class*=alert i], [role=alert]'))
                    .map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 5);
                  const inputs = Array.from(document.querySelectorAll('input')).map(i => ({
                    name: i.name, type: i.type, maxlen: i.maxLength, val: (i.value||'').slice(0,10), disabled: i.disabled,
                  }));
                  return { btns, err, inputs, bodyText: document.body.innerText.slice(0, 500) };
                }
                """
            )
            LOG_BUS.emit("ERROR", bot_id, f"TESHIS butonlar: {diag.get('btns')}")
            LOG_BUS.emit("ERROR", bot_id, f"TESHIS hatalar: {diag.get('err')}")
            LOG_BUS.emit("ERROR", bot_id, f"TESHIS inputlar: {diag.get('inputs')}")
        except Exception as exc:
            LOG_BUS.emit("ERROR", bot_id, f"Teshis basarisiz: {exc}")
        return False

    LOG_BUS.emit(
        "WARNING",
        bot_id,
        "Dogrulama maili yok — tarayicida elle tamamlayin (90 sn)",
    )
    for _ in range(45):
        if should_stop():
            return False
        if await is_logged_in(page):
            break
        await asyncio.sleep(2.0)
    return await is_logged_in(page)
