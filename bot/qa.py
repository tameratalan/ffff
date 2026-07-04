"""Trendyol urun sayfasi — soru sorma akisi."""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import Page

from bot.human import human_delay
from bot.login import ensure_logged_in, is_logged_in
from bot.navigation import dismiss_overlays
from core.log_bus import LOG_BUS

_FOOTER_SKIP = re.compile(r"sıkça|sikca|sss|yardım|yardim|destek", re.I)
_QA_TAB = re.compile(r"(\d+\s*)?soru.?cevap|satıcı soruları|satici sorulari", re.I)
_ASK_BTN = re.compile(r"^soru\s*sor$|satıcıya\s*sor|saticiya\s*sor|yeni\s*soru", re.I)
_SUBMIT_BTN = re.compile(r"^gönder$|^gonder$|^sor$", re.I)
# Soru-Cevap sekmesindeki "sorularda ara" arama kutusu placeholder'inda
# "soru" gectigi icin yanlislikla soru yazma alani sanilabiliyor — bunu
# her zaman reddet, "soru" icerse bile.
_SEARCH_FIELD = re.compile(r"\bara\b|arayın|arayin|search|filtrele", re.I)
# Soru metninin altindaki "ad soyad gosterme" tercihi — kisisel bir ayar,
# kullanici ozel talep etmedikce dokunulmaz (varsayilan durumu korunur).
_NAME_DISPLAY_CHECKBOX = re.compile(r"ad\s*soyad|isim\s*soyisim|isim\s*soyad", re.I)

_FIND_FIELD_JS = """
() => {
  const bad = (s) => {
    const x = (s || '').toLowerCase();
    if (x.includes('vendor') || x.includes('suggestion')) return true;
    if (x.includes('satıcıları') || x.includes('saticilari')) return true;
    if (/\bara\b|arayın|arayin|search|filtrele/.test(x)) return true;
    return false;
  };
  const pick = (el) => {
    const ph = el.getAttribute('placeholder') || '';
    const nm = el.getAttribute('name') || '';
    const id = el.id || '';
    const combo = ph + nm + id;
    if (bad(combo)) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 16) return null;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return null;
    if (!el.offsetParent && el.tagName !== 'TEXTAREA') return null;
    return el;
  };
  const nodes = document.querySelectorAll(
    'textarea, input[type="text"], input:not([type]), [role="textbox"], [contenteditable="true"]'
  );
  const scored = [];
  for (const el of nodes) {
    const ok = pick(el);
    if (!ok) continue;
    const ph = (el.getAttribute('placeholder') || '').toLowerCase();
    const nm = (el.getAttribute('name') || '').toLowerCase();
    let score = 0;
    if (el.tagName === 'TEXTAREA') score += 3;
    if (ph.includes('soru') || nm.includes('question')) score += 5;
    if (el.closest('[role="dialog"], [class*="modal"], [class*="overlay"]')) score += 4;
    scored.push({ el, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.length ? scored[0].el : null;
}
"""

_FIND_CHECKBOXES_JS = """
(field) => {
  let container = field;
  for (let i = 0; i < 12 && container; i++) {
    if (container.querySelectorAll && container.querySelectorAll("input[type='checkbox']").length > 0) {
      break;
    }
    container = container.parentElement;
  }
  if (!container) container = document.body;
  const boxes = Array.from(container.querySelectorAll("input[type='checkbox']"));
  return boxes.map((cb) => {
    let label = '';
    if (cb.id) {
      const lbl = document.querySelector(`label[for='${cb.id}']`);
      if (lbl) label = lbl.innerText.trim();
    }
    if (!label && cb.closest('label')) label = cb.closest('label').innerText.trim();
    return { id: cb.id || '', checked: cb.checked, label: label.slice(0, 200) };
  });
}
"""

_SUBMIT_DISABLED_JS = """
() => {
  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden';
  };
  const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
  const btn = btns.find((b) => {
    const t = (b.innerText || '').trim().toLowerCase();
    return (t === 'gönder' || t === 'gonder' || t === 'sor') && isVisible(b);
  });
  return btn ? !!btn.disabled : null;
}
"""

_SUBMIT_JS = """
() => {
  const labels = ['gönder', 'gonder', 'sor', 'gönder'];
  const btns = document.querySelectorAll('button, [role="button"]');
  for (const b of btns) {
    const t = (b.innerText || '').trim().toLowerCase();
    if (!t) continue;
    if (t === 'gönder' || t === 'gonder' || t === 'sor') {
      if (b.offsetParent !== null && !b.disabled) {
        b.click();
        return t;
      }
    }
  }
  return null;
}
"""


async def _is_in_footer(page: Page, locator) -> bool:
    try:
        return await locator.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                const docH = document.documentElement.scrollHeight || document.body.scrollHeight;
                return (r.top + window.scrollY) > docH * 0.82;
            }"""
        )
    except Exception:
        return False


async def _click_qa_tab(page: Page, bot_id: int) -> bool:
    LOG_BUS.emit("INFO", bot_id, "Soru-Cevap sekmesi araniyor...")

    for _ in range(16):
        candidates = page.locator("a, button, [role='tab'], span").filter(has_text=_QA_TAB)
        count = await candidates.count()
        for i in range(count):
            el = candidates.nth(i)
            try:
                if not await el.is_visible(timeout=500):
                    continue
                text = (await el.inner_text()).strip().replace("\n", " ")
                if _FOOTER_SKIP.search(text) or await _is_in_footer(page, el):
                    continue
                await el.scroll_into_view_if_needed()
                await el.click(timeout=4000)
                LOG_BUS.emit("INFO", bot_id, f"Sekme acildi: {text[:50]}")
                await human_delay(bot_id, 1.2, 2.0, speed=1.0)
                return True
            except Exception:
                continue
        await page.evaluate("window.scrollBy(0, Math.min(window.innerHeight * 0.7, 800))")
        await asyncio.sleep(0.4)
    return False


async def _click_ask_button(page: Page, bot_id: int, *, after_show_all: bool = False) -> bool:
    LOG_BUS.emit("INFO", bot_id, "'Soru Sor' butonu araniyor...")

    for scope in (page.locator("main"), page):
        try:
            if scope != page and await scope.count() == 0:
                continue
            root = scope.first if scope != page else page
            buttons = root.locator("button, a").filter(has_text=_ASK_BTN)
            for i in range(await buttons.count()):
                btn = buttons.nth(i)
                try:
                    if not await btn.is_visible(timeout=800):
                        continue
                    label = (await btn.inner_text()).strip()
                    if not _ASK_BTN.search(label.lower()):
                        continue
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=4000)
                    LOG_BUS.emit("INFO", bot_id, f"Butona tiklandi: {label[:40]}")
                    await human_delay(bot_id, 1.0, 1.8, speed=1.0)
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    if not after_show_all:
        show_all = page.get_by_text(re.compile(r"TÜM SORULARI GÖSTER|TUM SORULARI GOSTER", re.I))
        try:
            if await show_all.count() > 0 and await show_all.first.is_visible(timeout=1000):
                await show_all.first.click()
                await human_delay(bot_id, 1.0, 1.5, speed=1.0)
                return await _click_ask_button(page, bot_id, after_show_all=True)
        except Exception:
            pass
    return False


async def _find_field_locator(page: Page, bot_id: int, *, long_wait: bool = False):
    loops = 30 if long_wait else 8
    placeholders = (
        re.compile(r"soru", re.I),
        re.compile(r"merak", re.I),
        re.compile(r"yaz", re.I),
    )

    for _ in range(loops):
        for ph_re in placeholders:
            loc = page.get_by_placeholder(ph_re)
            try:
                for i in range(await loc.count()):
                    field = loc.nth(i)
                    if not await field.is_visible(timeout=400):
                        continue
                    ph = (await field.get_attribute("placeholder") or "")
                    if _SEARCH_FIELD.search(ph):
                        continue
                    LOG_BUS.emit("INFO", bot_id, "Yazma alani (placeholder)")
                    return field
            except Exception:
                pass

        for sel in (
            "textarea:visible",
            "[role='textbox']:visible",
            "input[type='text']:visible",
        ):
            loc = page.locator(sel)
            for i in range(await loc.count()):
                field = loc.nth(i)
                try:
                    if not await field.is_visible(timeout=300):
                        continue
                    ph = (await field.get_attribute("placeholder") or "").lower()
                    if _SEARCH_FIELD.search(ph):
                        continue
                    if "vendor" in ph or "satici" in ph:
                        continue
                    LOG_BUS.emit("INFO", bot_id, f"Yazma alani ({sel})")
                    return field
                except Exception:
                    continue

        handle = await page.evaluate_handle(_FIND_FIELD_JS)
        element = handle.as_element() if handle else None
        if element:
            LOG_BUS.emit("INFO", bot_id, "Yazma alani (JS)")
            return element

        await asyncio.sleep(0.45)

    return None


async def _write_question(page: Page, field, text: str, bot_id: int) -> bool:
    try:
        await field.scroll_into_view_if_needed()
        await field.click(timeout=3000)
        await field.fill("")
        await field.fill(text)
        return True
    except Exception:
        pass

    try:
        await field.click(timeout=3000)
        await page.keyboard.press("Control+A")
        await page.keyboard.type(text, delay=25)
        return True
    except Exception:
        pass

    try:
        await field.evaluate(
            """(el, text) => {
                el.focus();
                if (el.isContentEditable) el.textContent = text;
                else el.value = text;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            text,
        )
        return True
    except Exception as exc:
        LOG_BUS.emit("WARNING", bot_id, f"Yazma hatasi: {exc}")
        return False


async def _set_checkbox(page: Page, cb_id: str, checked: bool, bot_id: int) -> bool:
    """Onay kutusunu istenen duruma (isaretli/isaretsiz) getir.

    Native input genelde gorsel olarak gizlenmis (0x0) oluyor; gercek
    kutucuk CSS ile label'a bagli render ediliyor. Label'in TAM ortasina
    tiklamak yerine sol ust kosesine (gorsel kutunun oldugu yer) tikliyoruz,
    cunku label metninde ic-ice link olabiliyor (orn. "Kullanici Sozlesmesi"
    linki) ve ortasina tiklamak o linki acabiliyor.
    """
    if cb_id:
        try:
            label = page.locator(f"label[for='{cb_id}']")
            if await label.count() > 0:
                await label.first.click(timeout=3000, position={"x": 9, "y": 9})
                if await page.locator(f"#{cb_id}").is_checked() == checked:
                    return True
        except Exception:
            pass

    try:
        await page.evaluate(
            """([id, checked]) => {
                const cb = document.getElementById(id);
                if (!cb || cb.checked === checked) return;
                cb.checked = checked;
                cb.dispatchEvent(new Event('input', { bubbles: true }));
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                cb.dispatchEvent(new Event('click', { bubbles: true }));
            }""",
            [cb_id, checked],
        )
        return True
    except Exception as exc:
        LOG_BUS.emit("WARNING", bot_id, f"Onay kutusu durumu degistirilemedi: {exc}")
        return False


async def _handle_consent_checkboxes(page: Page, field, bot_id: int) -> None:
    """Soru metninin ALTINDAKI onay kutularini ele al.

    - "Ad soyad gosterme" tercihi: kullanici adinin/soyadinin sorularda
      gizli kalmasini istiyor — isaretliyse KALDIRILIR (uncheck). Zaten
      isaretsizse dokunulmaz.
    - Gonder butonunu pasif tutan (zorunlu onay/sozlesme gibi) kutucuklar
      tespit edilip SADECE onlar isaretlenir.
    """
    try:
        boxes = await field.evaluate(_FIND_CHECKBOXES_JS)
    except Exception:
        boxes = []

    if not boxes:
        return

    LOG_BUS.emit("INFO", bot_id, f"Soru formunda {len(boxes)} onay kutusu bulundu")

    for box in boxes:
        label = (box.get("label") or "").strip()
        if not _NAME_DISPLAY_CHECKBOX.search(label):
            continue

        if not box.get("checked"):
            LOG_BUS.emit("INFO", bot_id, "Isim/soyad gosterme tercihi zaten isaretsiz (gizli)")
            continue

        if await _set_checkbox(page, box.get("id") or "", False, bot_id):
            box["checked"] = False
            LOG_BUS.emit(
                "INFO", bot_id, f"Isim/soyad gosterme tercihi kaldirildi (gizlendi): {label[:70]}"
            )
            await human_delay(bot_id, 0.2, 0.5, speed=1.0)
        else:
            LOG_BUS.emit("WARNING", bot_id, f"Isim/soyad tercihi kaldirilamadi: {label[:70]}")

    try:
        disabled = await page.evaluate(_SUBMIT_DISABLED_JS)
    except Exception:
        disabled = None

    if disabled is False:
        return

    for box in boxes:
        label = (box.get("label") or "").strip()
        if box.get("checked") or _NAME_DISPLAY_CHECKBOX.search(label):
            continue

        try:
            still_disabled = await page.evaluate(_SUBMIT_DISABLED_JS)
        except Exception:
            still_disabled = None
        if still_disabled is False:
            break

        if await _set_checkbox(page, box.get("id") or "", True, bot_id):
            LOG_BUS.emit(
                "INFO", bot_id, f"Zorunlu onay kutusu isaretlendi: {label[:70] or 'isimsiz'}"
            )
            await human_delay(bot_id, 0.2, 0.5, speed=1.0)
        else:
            LOG_BUS.emit(
                "WARNING", bot_id, f"Onay kutusu isaretlenemedi: {label[:70] or 'isimsiz'}"
            )


async def _submit_question(page: Page, bot_id: int, speed: float) -> bool:
    for scope in (page.locator("[role='dialog']"), page.locator("main"), page):
        try:
            root = scope.first if scope != page else page
            if scope != page and await scope.count() == 0:
                continue
            buttons = root.locator("button").filter(has_text=_SUBMIT_BTN)
            for i in range(await buttons.count()):
                btn = buttons.nth(i)
                if await btn.is_visible(timeout=500) and await btn.is_enabled():
                    await btn.click(timeout=3000)
                    LOG_BUS.emit("INFO", bot_id, "Gonder butonuna basildi")
                    await human_delay(bot_id, 1.0, 2.0, speed=speed)
                    return True
        except Exception:
            continue

    clicked = await page.evaluate(_SUBMIT_JS)
    if clicked:
        LOG_BUS.emit("INFO", bot_id, f"Gonder (JS): {clicked}")
        await human_delay(bot_id, 1.0, 2.0, speed=speed)
        return True
    return False


async def ask_product_question(
    page: Page,
    bot_id: int,
    question_text: str,
    speed: float,
    *,
    email: str | None = None,
    password: str | None = None,
) -> bool:
    text = question_text.strip()[:200]
    if len(text) < 3:
        LOG_BUS.emit("WARNING", bot_id, "Soru metni cok kisa")
        return False

    LOG_BUS.emit("INFO", bot_id, "Soru soruluyor...")

    if not await is_logged_in(page):
        if email and password:
            if not await ensure_logged_in(page, email, password, bot_id, speed=speed):
                LOG_BUS.emit("ERROR", bot_id, "Giris yapilamadi — soru gonderilemez")
                return False
        else:
            LOG_BUS.emit("ERROR", bot_id, "Giris yapilmamis — soru sormak icin hesap gerekli")
            return False

    if not await _click_qa_tab(page, bot_id):
        LOG_BUS.emit("WARNING", bot_id, "Soru-Cevap sekmesi bulunamadi")
        return False

    # Her zaman once "Soru Sor" / "Saticiya Sor" butonuna tikla — aksi halde
    # sekmedeki "sorularda ara" arama kutusu yanlislikla soru yazma alani
    # sanilabiliyor.
    if not await _click_ask_button(page, bot_id):
        LOG_BUS.emit("WARNING", bot_id, "'Soru Sor' butonu bulunamadi")
        return False

    await dismiss_overlays(page, bot_id)
    await asyncio.sleep(1.0)
    field = await _find_field_locator(page, bot_id, long_wait=True)

    if field is None:
        LOG_BUS.emit("WARNING", bot_id, "Soru yazma alani acilmadi")
        return False

    if not await _write_question(page, field, text, bot_id):
        LOG_BUS.emit("WARNING", bot_id, "Soru metni yazilamadi")
        return False

    LOG_BUS.emit("INFO", bot_id, "Soru metni yazildi")
    await human_delay(bot_id, 0.6, 1.2, speed=speed)

    await _handle_consent_checkboxes(page, field, bot_id)

    if await _submit_question(page, bot_id, speed):
        LOG_BUS.emit("SUCCESS", bot_id, "Soru gonderildi")
        return True

    try:
        await field.press("Enter")
        await human_delay(bot_id, 1.0, 1.5, speed=speed)
        LOG_BUS.emit("SUCCESS", bot_id, "Soru gonderildi (Enter)")
        return True
    except Exception:
        pass

    LOG_BUS.emit("WARNING", bot_id, "Gonder butonu bulunamadi")
    return False
