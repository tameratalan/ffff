from __future__ import annotations

import random

from playwright.async_api import Page

from bot.human import human_delay, natural_type, smooth_scroll
from bot.selectors import SELECTORS
from config import TRENDYOL_HOME
from core.async_utils import should_stop
from core.log_bus import LOG_BUS
from core.parser import ParsedTarget, build_search_url, canonical_product_url, extract_product_id, href_matches_product, primary_product_id


async def card_product_href(card) -> str:
    """Urun kartindan link cikar — href gecikmeli yuklenebilir."""
    for attr in ("href", "data-url", "data-href"):
        try:
            val = await card.get_attribute(attr) or ""
            if "-p-" in val:
                return val
        except Exception:
            pass
    try:
        inner = card.locator("a[href*='-p-']").first
        if await inner.count() > 0:
            return await inner.get_attribute("href") or ""
    except Exception:
        pass
    return ""


async def wait_for_search_results(page: Page, bot_id: int, timeout: float = 15_000) -> int:
    """Arama sonucu kartlari yuklenene kadar bekle. Donus: bulunan link sayisi."""
    deadline = timeout / 1000
    import asyncio
    import time

    start = time.monotonic()
    while time.monotonic() - start < deadline:
        if should_stop():
            return 0
        cards = page.locator(SELECTORS["product_link"])
        count = await cards.count()
        if count > 0:
            for i in range(min(count, 8)):
                href = await card_product_href(cards.nth(i))
                if extract_product_id(href):
                    return count
        await asyncio.sleep(0.3)

    count = await page.locator(SELECTORS["product_link"]).count()
    if count > 0:
        LOG_BUS.emit("WARNING", bot_id, "Kart var ama urun linki okunamadi (href bekleniyor)")
        return count
    LOG_BUS.emit("WARNING", bot_id, "Urun kartlari yuklenmedi (timeout)")
    return 0


async def scroll_search_results(page: Page, bot_id: int) -> None:
    await page.evaluate("window.scrollBy(0, window.innerHeight * 0.85)")
    await human_delay(bot_id, 1.0, 2.0, label="Asagi kaydiriliyor", speed=1.0)


async def goto_search_page(page: Page, bot_id: int, keyword: str, page_num: int = 1) -> int:
    url = build_search_url(keyword, page_num)
    if page_num == 1:
        LOG_BUS.emit("INFO", bot_id, f'Arama aciliyor: "{keyword}"')
    else:
        LOG_BUS.emit("INFO", bot_id, f"Sayfa {page_num} aciliyor...")
    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await dismiss_overlays(page, bot_id)
    count = await wait_for_search_results(page, bot_id)
    if count:
        LOG_BUS.emit("INFO", bot_id, f"{count} urun karti yuklendi (sayfa {page_num})")
    return count


async def dismiss_overlays(page: Page, bot_id: int) -> None:
    for sel in (
        SELECTORS["cookie_accept"],
        SELECTORS["app_banner_close"],
        SELECTORS["popup_close"],
    ):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                LOG_BUS.emit("INFO", bot_id, "🚫 Popup/banner kapatıldı.")
                await human_delay(bot_id, 0.5, 1.0, speed=1.0)
        except Exception:
            pass


async def _is_product_404(page: Page) -> bool:
    try:
        text = await page.inner_text("body")
        return "sayfa bulunamad" in text.lower() or "aradığınız sayfa bulunamad" in text.lower()
    except Exception:
        return False


async def wait_for_product_page(page: Page, bot_id: int, timeout: float = 15_000) -> bool:
    import asyncio
    import time

    checks = [
        SELECTORS["product_title"],
        'button[data-testid="favorite-button"]',
        'button[data-testid="add-to-basket"]',
    ]
    start = time.monotonic()
    while time.monotonic() - start < timeout / 1000:
        if await _is_product_404(page):
            return False
        for sel in checks:
            loc = page.locator(sel).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            except Exception:
                continue
        await asyncio.sleep(0.3)
    return False


async def goto_product_direct(page: Page, bot_id: int, url: str, speed: float) -> bool:
    """Urun sayfasina git. Slug 404 ise x-p-ID ile tekrar dener."""
    pid = primary_product_id(url)
    candidates: list[str] = []
    clean = (url or "").strip().split("?")[0].split("#")[0]
    if clean:
        candidates.append(clean)
    if pid:
        canonical = canonical_product_url(url)
        if canonical not in candidates:
            candidates.append(canonical)

    last_err = ""
    for attempt_url in candidates:
        LOG_BUS.emit("INFO", bot_id, f"Urun sayfasi aciliyor: {attempt_url[:75]}...")
        try:
            await page.goto(attempt_url, wait_until="domcontentloaded", timeout=30_000)
            await dismiss_overlays(page, bot_id)
            await human_delay(bot_id, 1.0, 2.0, label="Sayfa yukleniyor", speed=speed)

            if await _is_product_404(page):
                LOG_BUS.emit("WARNING", bot_id, "Sayfa bulunamadi (404) — alternatif URL deneniyor...")
                continue

            if await wait_for_product_page(page, bot_id):
                if attempt_url != clean and clean:
                    LOG_BUS.emit("INFO", bot_id, "Urun x-p-ID linki ile acildi")
                return True

            last_err = "Urun icerigi yuklenmedi"
        except Exception as exc:
            last_err = str(exc)

    LOG_BUS.emit("ERROR", bot_id, f"Urun sayfasi acilamadi: {last_err or 'bilinmeyen hata'}")
    return False


async def goto_home(page: Page, bot_id: int, speed: float) -> None:
    LOG_BUS.emit("INFO", bot_id, "🏠 Trendyol ana sayfa açılıyor...")
    await page.goto(TRENDYOL_HOME, wait_until="domcontentloaded")
    await dismiss_overlays(page, bot_id)
    await human_delay(bot_id, 2, 4, label="Ana sayfa ısınma", speed=speed)


async def _find_visible_search_input(page: Page):
    loc = page.locator(SELECTORS["search_input"])
    for i in range(await loc.count()):
        item = loc.nth(i)
        try:
            if await item.is_visible():
                return item
        except Exception:
            continue
    return None


async def search_keyword(page: Page, bot_id: int, keyword: str, speed: float) -> None:
    LOG_BUS.emit("INFO", bot_id, f"Organik arama: {keyword}")
    await dismiss_overlays(page, bot_id)

    try:
        search = await _find_visible_search_input(page)
        if search is not None:
            await search.click()
            await search.fill("")
            await natural_type(page, SELECTORS["search_input"], keyword, bot_id)
            await human_delay(bot_id, 0.5, 1.2, speed=speed)
            await page.keyboard.press("Enter")
            await page.wait_for_load_state("domcontentloaded")
            if await wait_for_search_results(page, bot_id, timeout=12_000) > 0:
                await human_delay(bot_id, 1.0, 2.0, label="Arama sonuclari", speed=speed)
                return
    except Exception:
        pass

    LOG_BUS.emit("INFO", bot_id, "Arama kutusu kullanilamadi, URL ile gidiliyor")
    await goto_search_page(page, bot_id, keyword, page_num=1)
    await human_delay(bot_id, 1.0, 2.0, label="Arama sonuclari", speed=speed)


async def find_product_organically(
    page: Page,
    bot_id: int,
    target: ParsedTarget,
    *,
    max_pages: int,
    speed: float,
    product_ids: list[str] | None = None,
) -> bool:
    """
    Ürünü arama sonuçlarından veya kategori sayfasından bulup tıkla.
    Direkt URL'ye gitmez (organik sinyal).
    """
    ids = product_ids or ([target.product_id] if target.product_id else [])
    keyword = target.search_keyword or target.raw

    if not ids:
        LOG_BUS.emit("ERROR", bot_id, "Hedef urun ID yok — rastgele urune tiklanmaz")
        return False

    await search_keyword(page, bot_id, keyword, speed)
    if should_stop():
        LOG_BUS.emit("WARNING", bot_id, "Durduruldu — arama iptal")
        return False

    for page_num in range(1, max_pages + 1):
        if should_stop():
            LOG_BUS.emit("WARNING", bot_id, f"Durduruldu — sayfa {page_num}de kesildi")
            return False
        if page_num > 1:
            LOG_BUS.emit("INFO", bot_id, f"Sayfa {page_num} taranıyor...")
            count = await goto_search_page(page, bot_id, keyword, page_num)
            if count == 0:
                continue
            await human_delay(bot_id, 1.0, 2.0, speed=speed)

        links = page.locator(SELECTORS["product_link"])
        count = await links.count()
        LOG_BUS.emit("INFO", bot_id, f"🔍 {count} ürün kartı bulundu (sayfa {page_num}).")

        for i in range(count):
            if should_stop():
                return False
            href = await card_product_href(links.nth(i))
            if href_matches_product(href, ids):
                matched = extract_product_id(href) or ids[0]
                LOG_BUS.emit(
                    "SUCCESS",
                    bot_id,
                    f"🎯 Kart bulundu p-{matched} (sayfa {page_num}) — tiklaniyor",
                )
                await smooth_scroll(page, bot_id, bursts=random.randint(1, 3), speed=speed)
                await links.nth(i).click()
                await page.wait_for_load_state("domcontentloaded")
                await human_delay(bot_id, 2, 5, label="Ürün sayfası yüklendi", speed=speed)
                opened = primary_product_id(page.url) or extract_product_id(page.url)
                if opened and not href_matches_product(page.url, ids):
                    LOG_BUS.emit(
                        "ERROR",
                        bot_id,
                        f"Yanlis urun acildi p-{opened} — hedef p-{ids[0]} degil, iptal",
                    )
                    return False
                if opened:
                    LOG_BUS.emit("SUCCESS", bot_id, f"✓ Dogrulandi: p-{opened}")
                return True

        await smooth_scroll(page, bot_id, bursts=3, speed=speed)

    LOG_BUS.emit("WARNING", bot_id, "Hedef ürün arama sonuçlarında bulunamadı.")
    return False


async def browse_category_entry(
    page: Page,
    bot_id: int,
    category_url: str,
    target: ParsedTarget,
    *,
    max_pages: int,
    speed: float,
) -> bool:
    """Kategori sayfasından organik giriş."""
    if not category_url:
        return False

    LOG_BUS.emit("INFO", bot_id, f"📂 Kategori sayfasından giriş: {category_url[:60]}...")
    await page.goto(category_url, wait_until="domcontentloaded")
    await dismiss_overlays(page, bot_id)
    await human_delay(bot_id, 3, 6, label="Kategori gezintisi", speed=speed)
    await smooth_scroll(page, bot_id, bursts=4, speed=speed)

    product_id = target.product_id
    if not product_id:
        links = page.locator(SELECTORS["product_link"])
        if await links.count() > 0:
            await links.first.click()
            return True
        return False

    for _ in range(max_pages):
        links = page.locator(SELECTORS["product_link"])
        count = await links.count()
        for i in range(count):
            href = await links.nth(i).get_attribute("href") or ""
            if href_matches_product(href, product_id):
                LOG_BUS.emit("SUCCESS", bot_id, "🎯 Kategoriden hedef ürün bulundu!")
                await links.nth(i).click()
                await human_delay(bot_id, 2, 4, speed=speed)
                return True
        await smooth_scroll(page, bot_id, bursts=2, speed=speed)
        try:
            next_btn = page.locator("a:has-text('Sonraki'), .pagination-next").first
            if await next_btn.is_visible(timeout=2000):
                await next_btn.click()
                await human_delay(bot_id, 2, 3, speed=speed)
            else:
                break
        except Exception:
            break
    return False
