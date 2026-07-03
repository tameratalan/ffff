from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class GlobalState:
    """Dashboard ve bot havuzu arasında paylaşılan durum."""

    stop_event: threading.Event = field(default_factory=threading.Event)
    running: bool = False
    active_bots: int = 0
    mode: str = "idle"

    def request_stop(self) -> None:
        self.stop_event.set()

    def reset_stop(self) -> None:
        self.stop_event.clear()

    def is_stopped(self) -> bool:
        return self.stop_event.is_set()


STATE = GlobalState()
