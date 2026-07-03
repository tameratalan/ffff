from __future__ import annotations

import asyncio
import threading
from typing import Callable

from bot.engine import run_session
from config import OperationConfig
from core.log_bus import LOG_BUS
from core.state import STATE


class BotPool:
    """Paralel bot slot yönetimi."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_running(self) -> bool:
        return STATE.running

    def start(self, config: OperationConfig) -> None:
        if STATE.running:
            LOG_BUS.emit("WARNING", 0, "Operasyon zaten çalışıyor.")
            return
        STATE.reset_stop()
        STATE.running = True
        STATE.mode = config.mode
        self._thread = threading.Thread(
            target=self._run_thread,
            args=(config,),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        LOG_BUS.emit("WARNING", 0, "🛑 ACİL DURDURMA — tüm botlar sonlandırılıyor...")
        STATE.request_stop()

    def _run_thread(self, config: OperationConfig) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._run_all(config))
        finally:
            STATE.running = False
            STATE.active_bots = 0
            STATE.mode = "idle"
            loop.close()
            LOG_BUS.emit("INFO", 0, "Operasyon durdu.")

    async def _run_all(self, config: OperationConfig) -> None:
        targets = list(config.targets)
        if not targets:
            LOG_BUS.emit("ERROR", 0, "Hedef listesi boş.")
            return

        if config.mode == "sniper":
            targets = targets[:1]

        semaphore = asyncio.Semaphore(max(1, config.bot_slots))

        async def worker(bot_id: int, target: str) -> None:
            if STATE.is_stopped():
                return
            async with semaphore:
                STATE.active_bots += 1
                try:
                    await run_session(bot_id, target, config)
                finally:
                    STATE.active_bots -= 1
                if config.mode == "bulk":
                    await asyncio.sleep(1.0 / max(config.speed_multiplier, 0.1))

        # Bulk + tek slot: aynı profili sırayla kullan (paralel task yerine seri)
        if config.mode == "bulk" and config.bot_slots == 1:
            for i, target in enumerate(targets):
                if STATE.is_stopped():
                    break
                STATE.active_bots = 1
                try:
                    await run_session(1, target, config)
                finally:
                    STATE.active_bots = 0
                await asyncio.sleep(1.0 / max(config.speed_multiplier, 0.1))
            return

        tasks = []
        for i, target in enumerate(targets):
            if STATE.is_stopped():
                break
            bot_id = (i % config.bot_slots) + 1
            tasks.append(asyncio.create_task(worker(bot_id, target)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


POOL = BotPool()
