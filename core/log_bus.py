from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque


@dataclass
class LogEntry:
    ts: str
    level: str
    bot_id: int
    message: str


class LogBus:
    """Canlı log terminali için thread-safe kuyruk."""

    def __init__(self, maxlen: int = 500) -> None:
        self._lock = threading.Lock()
        self._entries: Deque[LogEntry] = deque(maxlen=maxlen)

    def emit(self, level: str, bot_id: int, message: str) -> None:
        entry = LogEntry(
            ts=datetime.now().strftime("%H:%M:%S"),
            level=level.upper(),
            bot_id=bot_id,
            message=message,
        )
        with self._lock:
            self._entries.append(entry)

    def snapshot(self, limit: int = 200) -> list[LogEntry]:
        with self._lock:
            items = list(self._entries)
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


LOG_BUS = LogBus()
