"""Urun siralama taramasi — anahtar kelimede kacinci sayfa / sira."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from playwright.async_api import Page, async_playwright

from bot.navigation import (
    card_product_href,
    goto_search_page,
    scroll_search_results,
    wait_for_search_results,
)
from bot.selectors import SELECTORS
from bot.stealth import launch_persistent_context
from config import PROFILES_DIR
from core.async_utils import should_stop
from core.log_bus import LOG_BUS
from core.parser import (
    extract_product_id,
    href_matches_product,
    parse_all_product_ids,
    parse_target,
)


@dataclass
class RankResult:
    keyword: str
    product_id: str
    found: bool
    page: int = 0
    position_on_page: int = 0
    estimated_rank: int = 0
    products_on_page: int = 0
    pages_scanned: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    def summary(self) -> str:
        if not self.found:
            return (
                f'"{self.keyword}" - BULUNAMADI '
                f"({self.pages_scanned} sayfa, ~{self.estimated_rank or 0} urun tarandi)"
            )
        return (
            f'"{self.keyword}" - Sayfa {self.page}, '
            f"sira {self.position_on_page}/{self.products_on_page}, "
            f"tahmini genel sira ~{self.estimated_rank}"
        )


async def resolve_product_ids(page: Page, product_url: str) -> list[str]:
    """
    Sadece link, yonlendirme ve canonical URL'deki ID'ler.
    Sayfa HTML'indeki benzer urun / oneri ID'leri DAHIL EDILMEZ.
    """
    ids = parse_all_product_ids(product_url)
    if not product_url.strip().startswith("http"):
        return ids

    url = product_url.strip().split("#")[0]
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        await page.wait_for_timeout(1500)
        ids.extend(parse_all_product_ids(page.url))
        canonical = await page.locator('link[rel="canonical"]').get_attribute("href")
        if canonical:
            ids.extend(parse_all_product_ids(canonical))
    except Exception as exc:
        LOG_BUS.emit("WARNING", 0, f"Urun sayfasi acilamadi (ID cozme): {exc}")

    return list(dict.fromkeys(i for i in ids if i))


async def _scan_cards(
    page: Page,
    product_ids: list[str],
    *,
    seen_ids: set[str],
    rank_offset: int,
    page_num: int,
) -> tuple[RankResult | None, int, set[str], int]:
    cards = page.locator(SELECTORS["product_link"])
    count = await cards.count()
    pos_on_page = 0
    rank = rank_offset
    new_on_page = 0

    for i in range(count):
        if should_stop():
            break
        href = await card_product_href(cards.nth(i))
        pid = extract_product_id(href)
        if not pid:
            continue
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        new_on_page += 1
        pos_on_page += 1
        rank += 1

        if href_matches_product(href, product_ids):
            hit = RankResult(keyword="", product_id=product_ids[0], found=True)
            hit.page = page_num
            hit.position_on_page = pos_on_page
            hit.products_on_page = count
            hit.estimated_rank = rank
            return hit, rank, seen_ids, new_on_page

    return None, rank, seen_ids, new_on_page


async def _log_page1_miss(page: Page, product_ids: list[str], seen_ids: set[str]) -> None:
    sample = ", ".join(f"p-{x}" for x in list(seen_ids)[:6])
    targets = ", ".join(f"p-{x}" for x in product_ids)
    LOG_BUS.emit(
        "WARNING",
        0,
        f"Hedef [{targets}] ilk sonuclarda yok. Ilk bulunanlar: {sample or '—'}",
    )


async def scan_rank(
    product_url: str,
    keyword: str,
    *,
    max_pages: int = 50,
    headless: bool = True,
    click_product: bool = False,
) -> RankResult:
    target = parse_target(product_url, default_keyword=keyword)
    result = RankResult(keyword=keyword, product_id=target.product_id or "", found=False)

    profile = f"rank_scan_{uuid.uuid4().hex[:8]}"
    prof_path = str((PROFILES_DIR / profile).resolve())

    async with async_playwright() as pw:
        ctx, _ = await launch_persistent_context(
            pw, prof_path, headless=headless, bot_id=0, desktop_only=True,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        seen_ids: set[str] = set()
        global_rank = 0

        try:
            product_ids = await resolve_product_ids(page, product_url)
            if not product_ids:
                LOG_BUS.emit("ERROR", 0, "Urun ID cikarilamadi — gecerli Trendyol linki girin")
                return result

            result.product_id = product_ids[0]
            id_text = ", ".join(f"p-{x}" for x in product_ids)
            LOG_BUS.emit(
                "INFO",
                0,
                f'Siralama taramasi: "{keyword}" (max {max_pages} sayfa, hedef {id_text})',
            )

            loaded = await goto_search_page(page, 0, keyword, page_num=1)
            if loaded == 0:
                LOG_BUS.emit("ERROR", 0, "Arama sonuclari yuklenemedi")
                return result

            result.pages_scanned = 1
            first_batch = True

            # Sayfa 1: once gorunur kartlar, sonra scroll ile devam
            scroll_rounds = min(max_pages, 15)
            for scroll_round in range(scroll_rounds):
                if should_stop():
                    return result

                hit, global_rank, seen_ids, new_count = await _scan_cards(
                    page,
                    product_ids,
                    seen_ids=seen_ids,
                    rank_offset=global_rank,
                    page_num=1,
                )
                result.products_on_page = await page.locator(SELECTORS["product_link"]).count()
                result.estimated_rank = global_rank

                if hit:
                    result.found = True
                    result.page = 1
                    result.position_on_page = hit.position_on_page
                    result.estimated_rank = hit.estimated_rank
                    LOG_BUS.emit("SUCCESS", 0, result.summary())
                    return result

                if first_batch:
                    first_batch = False
                    if not any(pid in seen_ids for pid in product_ids):
                        await _log_page1_miss(page, product_ids, seen_ids)

                if scroll_round >= scroll_rounds - 1:
                    break

                before = len(seen_ids)
                card_before = result.products_on_page
                await scroll_search_results(page, 0)
                await wait_for_search_results(page, 0)
                card_after = await page.locator(SELECTORS["product_link"]).count()
                if card_after <= card_before and len(seen_ids) == before:
                    LOG_BUS.emit("INFO", 0, "Scroll ile yeni urun gelmedi")
                    break

            # pi=2..N (yeni urun gelmezse dur)
            for page_num in range(2, max_pages + 1):
                if should_stop():
                    LOG_BUS.emit("WARNING", 0, f"Siralama durduruldu — sayfa {page_num}")
                    return result

                before = len(seen_ids)
                loaded = await goto_search_page(page, 0, keyword, page_num=page_num)
                if loaded == 0:
                    LOG_BUS.emit("WARNING", 0, f"Sayfa {page_num}: kart yuklenmedi, durduruluyor")
                    break

                result.pages_scanned = page_num
                hit, global_rank, seen_ids, new_count = await _scan_cards(
                    page,
                    product_ids,
                    seen_ids=seen_ids,
                    rank_offset=global_rank,
                    page_num=page_num,
                )
                result.products_on_page = await page.locator(SELECTORS["product_link"]).count()
                result.estimated_rank = global_rank

                if hit:
                    result.found = True
                    result.page = hit.page
                    result.position_on_page = hit.position_on_page
                    result.estimated_rank = hit.estimated_rank
                    LOG_BUS.emit("SUCCESS", 0, result.summary())
                    if click_product:
                        cards = page.locator(SELECTORS["product_link"])
                        for i in range(await cards.count()):
                            href = await card_product_href(cards.nth(i))
                            if href_matches_product(href, product_ids):
                                await cards.nth(i).click()
                                await page.wait_for_load_state("domcontentloaded")
                                LOG_BUS.emit("SUCCESS", 0, "Urun sayfasina girildi")
                                break
                    return result

                if len(seen_ids) == before:
                    LOG_BUS.emit(
                        "INFO",
                        0,
                        f"Sayfa {page_num}: yeni urun yok (tekrar eden sonuc), tarama durdu",
                    )
                    break

            LOG_BUS.emit("WARNING", 0, result.summary())
            return result
        finally:
            try:
                await ctx.close()
            except Exception:
                pass


async def scan_all_keywords(
    product_url: str,
    keywords: list[str],
    *,
    max_pages: int,
    headless: bool,
) -> list[RankResult]:
    results: list[RankResult] = []
    for kw in keywords:
        if should_stop():
            LOG_BUS.emit("WARNING", 0, "Siralama taramasi durduruldu")
            break
        kw = kw.strip()
        if not kw:
            continue
        r = await scan_rank(product_url, kw, max_pages=max_pages, headless=headless)
        results.append(r)
    return results


def format_rank_report(label: str, results: list[RankResult]) -> str:
    lines = [f"=== {label} ==="]
    for r in results:
        lines.append(f"[{r.timestamp}] {r.summary()}")
    return "\n".join(lines)
