from __future__ import annotations

import random

from playwright.async_api import Page

from bot.human import human_click, human_delay, quick_click, scroll_to_element, smooth_scroll
from bot.navigation import dismiss_overlays
from bot.qa import ask_product_question
from bot.selectors import SELECTORS
from config import FeatureFlags
from core.log_bus import LOG_BUS


async def _favorite_is_active(page: Page) -> bool:
    fav = page.locator("[data-testid='favorite-toggle']").first
    try:
        if await fav.count() == 0:
            return False
        cls = await fav.evaluate(
            "el => (el.querySelector('i')?.className || '') + ' ' + (el.getAttribute('aria-pressed') || '')",
            timeout=2000,
        )
        low = cls.lower()
        return (
            "heart-filled" in low
            or "i-heart-fill" in low
            or "aria-pressed=true" in low.replace(" ", "")
            or "_red_" in low
        )
    except Exception:
        return False


async def _cart_button_state(page: Page) -> str:
    for sel in SELECTORS["add_to_cart"].split(", "):
        loc = page.locator(sel.strip()).first
        try:
            if await loc.count() > 0 and await loc.is_visible(timeout=1500):
                return (await loc.inner_text(timeout=2000)).strip()
        except Exception:
            continue
    return ""


async def view_product_page(page: Page, bot_id: int, speed: float, *, scroll_bursts: int) -> None:
    LOG_BUS.emit("INFO", bot_id, "👀 Ürün inceleniyor...")
    await smooth_scroll(page, bot_id, bursts=scroll_bursts, speed=speed)
    title = page.locator(SELECTORS["product_title"]).first
    try:
        t = await title.inner_text(timeout=6000)
        LOG_BUS.emit("INFO", bot_id, f"📦 {t.strip()[:80]}")
    except Exception:
        pass


async def browse_photo_gallery(page: Page, bot_id: int, speed: float) -> None:
    LOG_BUS.emit("INFO", bot_id, "🖼️ Fotoğraflara bakılıyor...")
    imgs = page.locator(SELECTORS["gallery_image"])
    count = min(await imgs.count(), 5)
    for i in range(count):
        try:
            await imgs.nth(i).click(timeout=3000)
            await human_delay(bot_id, 1.5, 3.5, label="Fotoğraf inceleme", speed=speed)
            nxt = page.locator(SELECTORS["gallery_next"]).first
            if await nxt.is_visible(timeout=1000):
                await nxt.click()
        except Exception:
            pass


async def read_reviews(page: Page, bot_id: int, speed: float) -> None:
    LOG_BUS.emit("INFO", bot_id, "💬 Yorumlar okunuyor...")
    tab = page.locator(SELECTORS["reviews_tab"]).first
    try:
        if await tab.is_visible(timeout=4000):
            await tab.click()
            await human_delay(bot_id, 2, 4, speed=speed)
    except Exception:
        await scroll_to_element(page, SELECTORS["review_item"], bot_id)

    reviews = page.locator(SELECTORS["review_item"])
    count = min(await reviews.count(), 4)
    for i in range(count):
        await reviews.nth(i).scroll_into_view_if_needed()
        read_time = random.uniform(3, 8) / max(speed, 0.1)
        LOG_BUS.emit("INFO", bot_id, f"📖 Yorum okuma ({read_time:.0f}sn)...")
        await human_delay(bot_id, read_time * 0.8, read_time * 1.2, speed=speed)


async def like_review(page: Page, bot_id: int, speed: float) -> None:
    btn = page.locator(SELECTORS["review_helpful"]).first
    try:
        if await btn.is_visible(timeout=3000):
            await btn.click()
            LOG_BUS.emit("SUCCESS", bot_id, "👍 Faydalı butonuna basıldı.")
            await human_delay(bot_id, 1, 2, speed=speed)
    except Exception:
        pass


async def add_favorite(page: Page, bot_id: int, speed: float, *, turbo: bool = False) -> bool:
    LOG_BUS.emit("INFO", bot_id, "Favoriye ekleniyor...")
    await dismiss_overlays(page, bot_id)

    if await _favorite_is_active(page):
        LOG_BUS.emit("INFO", bot_id, "Zaten favorilerde.")
        return True

    fav = page.locator("[data-testid='favorite-toggle']").first
    try:
        await fav.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    clicked = False
    try:
        async with page.expect_response(
            lambda r: "add-to-favorites" in r.url and r.status == 200,
            timeout=8_000,
        ):
            for sel in SELECTORS["favorite_btn"].split(", "):
                sel = sel.strip()
                if turbo:
                    ok = await quick_click(page, sel, bot_id, timeout=4_000, force=True)
                else:
                    ok = await human_click(page, sel, bot_id)
                if ok:
                    clicked = True
                    break
            if not clicked:
                return False
        LOG_BUS.emit("SUCCESS", bot_id, "Favoriye eklendi (dogrulandi).")
        return True
    except Exception:
        clicked = False
        for sel in SELECTORS["favorite_btn"].split(", "):
            sel = sel.strip()
            if turbo:
                ok = await quick_click(page, sel, bot_id, timeout=4_000, force=True)
            else:
                ok = await human_click(page, sel, bot_id)
            if ok:
                clicked = True
                break

    if not clicked:
        LOG_BUS.emit("WARNING", bot_id, "Favori butonu bulunamadi.")
        return False

    await page.wait_for_timeout(1500)

    if await _favorite_is_active(page):
        LOG_BUS.emit("SUCCESS", bot_id, "Favoriye eklendi (dogrulandi).")
        return True

    try:
        fav = page.locator("[data-testid='favorite-toggle']").first
        cls = await fav.evaluate("el => el.querySelector('i')?.className || ''", timeout=2000)
        if "heart" in cls.lower() and "_black_" not in cls:
            LOG_BUS.emit("SUCCESS", bot_id, "Favoriye eklendi (ikon degisti).")
            return True
    except Exception:
        pass

    LOG_BUS.emit("WARNING", bot_id, "Favori islemi tamamlanamadi — cookie/popup veya gecersiz urun linki olabilir.")
    return False


async def add_to_cart(page: Page, bot_id: int, speed: float, *, turbo: bool = False) -> bool:
    LOG_BUS.emit("INFO", bot_id, "Sepete ekleme deneniyor...")
    await dismiss_overlays(page, bot_id)

    state = await _cart_button_state(page)
    if "tükendi" in state.lower() or "tukendi" in state.lower():
        LOG_BUS.emit("WARNING", bot_id, "Urun tukendi — sepete eklenemez.")
        return False
    if "eklendi" in state.lower():
        LOG_BUS.emit("INFO", bot_id, "Zaten sepette.")
        return True

    sizes = page.locator(SELECTORS["size_option"])
    try:
        if await sizes.count() > 0:
            idx = random.randint(0, min(await sizes.count(), 5) - 1)
            await sizes.nth(idx).click(timeout=3_000, force=True)
            if not turbo:
                await human_delay(bot_id, 0.8, 1.5, speed=speed)
    except Exception:
        pass

    clicked = False
    for sel in SELECTORS["add_to_cart"].split(", "):
        sel = sel.strip()
        if turbo:
            ok = await quick_click(page, sel, bot_id, timeout=4_000, force=True)
        else:
            ok = await human_click(page, sel, bot_id)
        if ok:
            clicked = True
            break

    if not clicked:
        LOG_BUS.emit("WARNING", bot_id, "Sepete Ekle butonu bulunamadi.")
        return False

    await page.wait_for_timeout(2500 if turbo else 1500)
    after = await _cart_button_state(page)
    if "eklendi" in after.lower():
        LOG_BUS.emit("SUCCESS", bot_id, "Sepete eklendi (dogrulandi).")
        return True

    LOG_BUS.emit("WARNING", bot_id, "Sepet butonuna tiklandi ama 'Sepete Eklendi' gorulmedi.")
    return False


async def browse_store(page: Page, bot_id: int, speed: float) -> None:
    LOG_BUS.emit("INFO", bot_id, "🏪 Mağazaya bakılıyor...")
    seller = page.locator(SELECTORS["seller_link"]).first
    try:
        if await seller.is_visible(timeout=5000):
            await seller.click()
            await human_delay(bot_id, 8, 15, label="Mağaza içi", speed=speed)
            await smooth_scroll(page, bot_id, bursts=3, speed=speed)
            LOG_BUS.emit("INFO", bot_id, "⬆️ Yukarı çıkılıyor...")
            await smooth_scroll(page, bot_id, direction=-1, bursts=2, speed=speed)
            await page.go_back()
            await human_delay(bot_id, 2, 4, label="Ürüne geri dönüldü", speed=speed)
            LOG_BUS.emit("INFO", bot_id, "↩️ Ürüne geri dönüldü.")
    except Exception as exc:
        LOG_BUS.emit("WARNING", bot_id, f"Mağaza gezintisi atlandı: {exc}")


async def follow_store(page: Page, bot_id: int, speed: float, *, turbo: bool = False) -> bool:
    LOG_BUS.emit("INFO", bot_id, "Magaza takip ediliyor...")
    await dismiss_overlays(page, bot_id)

    async def _is_following() -> bool:
        try:
            body = (await page.inner_text("body", timeout=4000)).lower()
        except Exception:
            body = ""
        return (
            "takip ediliyor" in body
            or "takibi bırak" in body
            or "takibi birak" in body
        )

    if await _is_following():
        LOG_BUS.emit("INFO", bot_id, "Magaza zaten takip ediliyor.")
        return True

    for sel in SELECTORS["seller_follow"].split(", "):
        sel = sel.strip()
        try:
            async with page.expect_response(
                lambda r: "/api/follow/" in r.url and 200 <= r.status < 300,
                timeout=8000,
            ):
                ok = (
                    await quick_click(page, sel, bot_id, timeout=5000, force=True)
                    if turbo
                    else await human_click(page, sel, bot_id)
                )
                if not ok:
                    continue
            await page.wait_for_timeout(1500 if turbo else 1000)
            if await _is_following():
                LOG_BUS.emit("SUCCESS", bot_id, "Magaza takip edildi (API + buton dogrulandi).")
                return True
            LOG_BUS.emit("SUCCESS", bot_id, "Magaza takip edildi (API dogrulandi).")
            return True
        except Exception:
            # Selector yanlis olabilir veya hesap zaten takipte olabilir; siradaki
            # selectoru denemeden once sayfa durumuna tekrar bak.
            if await _is_following():
                LOG_BUS.emit("SUCCESS", bot_id, "Magaza takip edildi (buton dogrulandi).")
                return True
            continue

    LOG_BUS.emit("WARNING", bot_id, "Magaza takip butonu bulunamadi.")
    return False


async def collect_coupon(page: Page, bot_id: int, speed: float) -> None:
    btn = page.locator(SELECTORS["coupon_btn"]).first
    try:
        if await btn.is_visible(timeout=3000):
            await btn.click()
            LOG_BUS.emit("SUCCESS", bot_id, "🎟️ Kupon toplandı.")
            await human_delay(bot_id, 1, 2, speed=speed)
    except Exception:
        pass

async def ask_question(page: Page, bot_id: int, question_text: str, speed: float) -> bool:
    return await ask_product_question(page, bot_id, question_text, speed)


async def ask_question_with_account(
    page: Page,
    bot_id: int,
    question_text: str,
    speed: float,
    email: str,
    password: str,
) -> bool:
    return await ask_product_question(
        page, bot_id, question_text, speed, email=email, password=password,
    )


async def browse_qa(page: Page, bot_id: int, speed: float) -> None:
    tab = page.locator(SELECTORS["qa_tab"]).first
    try:
        if await tab.is_visible(timeout=3000):
            await tab.click()
            await human_delay(bot_id, 3, 6, label="Soru-Cevap gezintisi", speed=speed)
    except Exception:
        pass


async def run_interactions(
    page: Page,
    bot_id: int,
    speed: float,
    features: FeatureFlags,
    *,
    cart_priority: float,
    favorite_priority: float,
    read_reviews_flag: bool,
    browse_store_flag: bool,
    photo_gallery_flag: bool,
    scroll_intensity: int,
) -> dict[str, bool]:
    result = {"favorite": False, "cart": False}

    await view_product_page(page, bot_id, speed, scroll_bursts=scroll_intensity)

    if photo_gallery_flag and features.photo_gallery:
        await browse_photo_gallery(page, bot_id, speed)

    if read_reviews_flag and features.review_like:
        await read_reviews(page, bot_id, speed)
        await like_review(page, bot_id, speed)

    if browse_store_flag and features.store_browse:
        await browse_store(page, bot_id, speed)

    if features.qa_browse:
        await browse_qa(page, bot_id, speed)

    if features.coupon:
        await collect_coupon(page, bot_id, speed)

    if features.store_follow:
        await follow_store(page, bot_id, speed)

    if features.favorite and random.random() < favorite_priority:
        result["favorite"] = await add_favorite(page, bot_id, speed)

    if features.cart and random.random() < cart_priority:
        result["cart"] = await add_to_cart(page, bot_id, speed)

    return result
