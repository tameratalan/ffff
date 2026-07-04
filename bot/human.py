from __future__ import annotations

import asyncio
import math
import random

from playwright.async_api import Page

from core.async_utils import interruptible_sleep, should_stop
from core.log_bus import LOG_BUS


async def human_delay(
    bot_id: int,
    min_sec: float,
    max_sec: float,
    *,
    label: str = "",
    speed: float = 1.0,
) -> bool:
    """Rastgele bekleme. False = durduruldu."""
    lo = min_sec / max(speed, 0.1)
    hi = max_sec / max(speed, 0.1)
    wait = random.uniform(lo, hi)
    msg = f"Bekleniyor ({wait:.0f}sn)..."
    if label:
        msg = f"{label} ({wait:.0f}sn)..."
    LOG_BUS.emit("INFO", bot_id, msg)
    return await interruptible_sleep(wait)


def _bezier_point(t: float, p0, p1, p2, p3):
    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return x, y


async def bezier_move(page: Page, x: float, y: float, *, steps: int = 25) -> None:
    """Bezier eğrisi ile doğal fare hareketi."""
    viewport = page.viewport_size or {"width": 390, "height": 844}
    start = (
        random.uniform(viewport["width"] * 0.2, viewport["width"] * 0.8),
        random.uniform(viewport["height"] * 0.2, viewport["height"] * 0.8),
    )
    end = (x, y)
    cp1 = (
        start[0] + random.uniform(-80, 80),
        start[1] + random.uniform(-60, 60),
    )
    cp2 = (
        end[0] + random.uniform(-80, 80),
        end[1] + random.uniform(-60, 60),
    )
    for i in range(steps + 1):
        t = i / steps
        px, py = _bezier_point(t, start, cp1, cp2, end)
        jitter_x = random.uniform(-1.5, 1.5)
        jitter_y = random.uniform(-1.5, 1.5)
        await page.mouse.move(px + jitter_x, py + jitter_y)
        await asyncio.sleep(random.uniform(0.005, 0.02))


async def quick_click(page: Page, selector: str, bot_id: int, *, timeout: float = 3_000, force: bool = False) -> bool:
    """Turbo mod — kisa timeout, bezier yok."""
    loc = page.locator(selector).first
    try:
        await loc.scroll_into_view_if_needed(timeout=timeout)
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click(timeout=timeout, force=force)
        return True
    except Exception:
        return False


async def human_click(page: Page, selector: str, bot_id: int) -> bool:
    loc = page.locator(selector).first
    try:
        await loc.wait_for(state="visible", timeout=12_000)
        box = await loc.bounding_box()
        if box:
            tx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            ty = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            await bezier_move(page, tx, ty)
        await asyncio.sleep(random.uniform(0.15, 0.45))
        await loc.click()
        return True
    except Exception as exc:
        LOG_BUS.emit("WARNING", bot_id, f"Tıklama başarısız ({selector}): {exc}")
        return False


async def smooth_scroll(
    page: Page,
    bot_id: int,
    *,
    direction: int = 1,
    bursts: int | None = None,
    speed: float = 1.0,
) -> None:
    """Yumuşak, duraksamalı kaydırma."""
    n = bursts or random.randint(2, 5)
    for _ in range(n):
        if should_stop():
            return
        delta = direction * random.randint(180, 420)
        await page.mouse.wheel(0, delta)
        await human_delay(
            bot_id,
            0.4,
            1.2,
            label="Kaydırma arası",
            speed=speed,
        )


async def natural_type(page: Page, selector: str, text: str, bot_id: int) -> None:
    """Klavyeden yazıyormuş gibi karakter karakter yaz."""
    loc = page.locator(selector).first
    await loc.click()
    await loc.fill("")
    for ch in text:
        await loc.type(ch, delay=random.randint(60, 180))
        if random.random() < 0.08:
            await asyncio.sleep(random.uniform(0.2, 0.6))
    LOG_BUS.emit("INFO", bot_id, f"🔎 Arama yazıldı: {text}")


async def scroll_to_element(page: Page, selector: str, bot_id: int) -> None:
    try:
        loc = page.locator(selector).first
        await loc.scroll_into_view_if_needed(timeout=8000)
        LOG_BUS.emit("INFO", bot_id, "📜 Elemente kaydırıldı.")
    except Exception:
        await smooth_scroll(page, bot_id, direction=1)
