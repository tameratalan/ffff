"""Kesintili bekleme ve global durdurma."""

from __future__ import annotations

import asyncio

from core.state import STATE


def should_stop() -> bool:
    return STATE.is_stopped()


async def interruptible_sleep(seconds: float, *, chunk: float = 0.25) -> bool:
    """Bekler; durdurulursa False doner."""
    elapsed = 0.0
    while elapsed < seconds:
        if should_stop():
            return False
        step = min(chunk, seconds - elapsed)
        await asyncio.sleep(step)
        elapsed += step
    return True
