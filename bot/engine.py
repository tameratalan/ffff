from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path

from playwright.async_api import async_playwright

from bot.human import human_delay
from bot.interactions import run_interactions
from bot.navigation import (
    browse_category_entry,
    dismiss_overlays,
    find_product_organically,
    goto_home,
)
from bot.personas import PersonaProfile, pick_persona
from bot.stealth import launch_persistent_context
from config import PROFILES_DIR, OperationConfig
from core.log_bus import LOG_BUS
from core.metrics import METRICS
from core.parser import parse_target
from core.state import STATE


def resolve_session_profile(config: OperationConfig, bot_id: int) -> str:
    """
    Her paralel bot için ayrı profil dizini.
    Tek slot: profile_1
    Çok slot: profile_1_bot1, profile_1_bot2 ...
    """
    base = config.profile.strip() or "profile_1"
    if config.bot_slots > 1:
        name = f"{base}_bot{bot_id}"
    else:
        name = base
    return profile_path(name)


def profile_path(name: str) -> str:
    p = Path(name)
    if p.is_absolute():
        return str(p.resolve())
    return str((PROFILES_DIR / name).resolve())


async def run_session(
    bot_id: int,
    target_raw: str,
    config: OperationConfig,
) -> bool:
    """Tek bot oturumu."""
    if STATE.is_stopped():
        return False

    persona: PersonaProfile = pick_persona()
    target = parse_target(target_raw, default_keyword=config.search_keyword)
    prof = resolve_session_profile(config, bot_id)
    speed = config.speed_multiplier
    t0 = time.monotonic()

    LOG_BUS.emit(
        "INFO",
        bot_id,
        f"{persona.emoji} Bot #{bot_id} başladı — Persona: {persona.name} | Profil: {Path(prof).name}",
    )

    try:
        async with async_playwright() as pw:
            ctx, device = await launch_persistent_context(
                pw,
                prof,
                headless=config.headless,
                proxy=config.proxy,
                bot_id=bot_id,
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            LOG_BUS.emit("INFO", bot_id, f"📱 Cihaz: {device['name']}")

            try:
                await goto_home(page, bot_id, speed)

                found = False
                if config.category_url:
                    found = await browse_category_entry(
                        page,
                        bot_id,
                        config.category_url,
                        target,
                        max_pages=config.max_search_pages,
                        speed=speed,
                    )

                if not found:
                    found = await find_product_organically(
                        page,
                        bot_id,
                        target,
                        max_pages=config.max_search_pages,
                        speed=speed,
                    )

                if not found:
                    LOG_BUS.emit("WARNING", bot_id, "Ürün bulunamadı — oturum başarısız.")
                    METRICS.record_fail("product_not_found")
                    return False

                await dismiss_overlays(page, bot_id)

                interaction = await run_interactions(
                    page,
                    bot_id,
                    speed,
                    config.features,
                    cart_priority=persona.cart_priority,
                    favorite_priority=persona.favorite_priority,
                    read_reviews_flag=persona.read_reviews,
                    browse_store_flag=persona.browse_store,
                    photo_gallery_flag=persona.photo_gallery,
                    scroll_intensity=persona.scroll_intensity,
                )

                elapsed = time.monotonic() - t0
                target_duration = random.uniform(
                    persona.min_session_sec,
                    persona.max_session_sec,
                ) / max(speed, 0.1)
                remaining = target_duration - elapsed
                if remaining > 0:
                    LOG_BUS.emit(
                        "INFO",
                        bot_id,
                        f"⏳ Doğallık için {remaining:.0f} sn daha bekleniyor...",
                    )
                    await human_delay(
                        bot_id,
                        remaining * 0.9,
                        remaining * 1.1,
                        speed=speed,
                    )

                total = time.monotonic() - t0
                LOG_BUS.emit(
                    "SUCCESS",
                    bot_id,
                    f"✅ OTURUM TAMAMLANDI. (Toplam: {total:.0f} sn)",
                )
                METRICS.record_success(
                    cart=interaction.get("cart", False),
                    favorite=interaction.get("favorite", False),
                )
                return True
            finally:
                try:
                    for p in ctx.pages:
                        try:
                            await p.close()
                        except Exception:
                            pass
                    await ctx.close()
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

    except Exception as exc:
        LOG_BUS.emit("ERROR", bot_id, f"❌ Hata: {exc}")
        METRICS.record_fail(type(exc).__name__)
        return False
