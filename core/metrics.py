from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class Metrics:
    success: int = 0
    failed: int = 0
    cart_ok: int = 0
    favorite_ok: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self, *, cart: bool = False, favorite: bool = False) -> None:
        with self._lock:
            self.success += 1
            if cart:
                self.cart_ok += 1
            if favorite:
                self.favorite_ok += 1

    def record_fail(self, reason: str = "unknown") -> None:
        with self._lock:
            self.failed += 1
            self.errors[reason] = self.errors.get(reason, 0) + 1

    @property
    def total(self) -> int:
        return self.success + self.failed

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return round(100.0 * self.success / self.total, 1)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "success": self.success,
                "failed": self.failed,
                "total": self.total,
                "success_rate": self.success_rate,
                "cart_ok": self.cart_ok,
                "favorite_ok": self.favorite_ok,
                "errors": dict(self.errors),
            }

    def reset(self) -> None:
        with self._lock:
            self.success = 0
            self.failed = 0
            self.cart_ok = 0
            self.favorite_ok = 0
            self.errors.clear()


METRICS = Metrics()
