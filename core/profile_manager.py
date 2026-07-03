from __future__ import annotations

import asyncio
import shutil
import threading
from pathlib import Path

from core.log_bus import LOG_BUS

_meta = threading.Lock()
_profile_mutexes: dict[str, threading.Lock] = {}

STALE_LOCK_NAMES = (
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "lockfile",
)

CHROME_PROCESS_NAMES = ("chrome.exe", "chromium.exe")


def get_profile_mutex(profile_dir: str) -> threading.Lock:
    key = str(Path(profile_dir).resolve())
    with _meta:
        if key not in _profile_mutexes:
            _profile_mutexes[key] = threading.Lock()
        return _profile_mutexes[key]


def kill_chrome_for_profile(profile_dir: str | Path, *, bot_id: int = 0) -> int:
    """Bu profile bağlı Playwright/Chromium süreçlerini sonlandır."""
    root = str(Path(profile_dir).resolve())
    root_key = root.lower()
    killed = 0

    try:
        import psutil
    except ImportError:
        return killed

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in CHROME_PROCESS_NAMES:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if root_key in cmdline or "user-data-dir" in cmdline and Path(root).name.lower() in cmdline:
                proc.kill()
                killed += 1
        except (psutil.Error, OSError):
            continue

    if killed:
        LOG_BUS.emit("INFO", bot_id, f"🔄 {killed} eski Chromium süreci kapatıldı.")
    return killed


def clean_stale_locks(profile_dir: str | Path, *, bot_id: int = 0) -> int:
    root = Path(profile_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    removed = 0

    for name in STALE_LOCK_NAMES:
        target = root / name
        if target.exists() or target.is_symlink():
            try:
                target.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass

    default_lock = root / "Default" / "LOCK"
    if default_lock.exists():
        try:
            default_lock.unlink(missing_ok=True)
            removed += 1
        except OSError:
            pass

    if removed:
        LOG_BUS.emit(
            "INFO",
            bot_id,
            f"🔓 {removed} eski profil kilidi temizlendi: {root.name}",
        )
    return removed


def prepare_profile_dir(profile_dir: str | Path, *, bot_id: int = 0) -> Path:
    """Profil dizinini başlatmadan önce hazırla."""
    root = Path(profile_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    kill_chrome_for_profile(root, bot_id=bot_id)
    clean_stale_locks(root, bot_id=bot_id)
    return root


async def launch_with_profile_guard(
    profile_dir: str,
    bot_id: int,
    launch_fn,
    *,
    max_retries: int = 3,
):
    mutex = get_profile_mutex(profile_dir)
    loop = asyncio.get_event_loop()

    acquired = await loop.run_in_executor(None, mutex.acquire, True, 45)
    if not acquired:
        raise TimeoutError(
            f"Profil 45 sn içinde serbest bırakılmadı: {profile_dir}"
        )

    last_exc: Exception | None = None
    try:
        for attempt in range(1, max_retries + 1):
            prepare_profile_dir(profile_dir, bot_id=bot_id)
            try:
                return await launch_fn()
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                if "ProcessSingleton" not in msg and "profile is already in use" not in msg:
                    raise
                LOG_BUS.emit(
                    "WARNING",
                    bot_id,
                    f"⚠️ Profil açılamadı (deneme {attempt}/{max_retries})...",
                )
                kill_chrome_for_profile(profile_dir, bot_id=bot_id)
                clean_stale_locks(profile_dir, bot_id=bot_id)
                if attempt < max_retries:
                    await asyncio.sleep(2.5 * attempt)
        hint = (
            "Profil yolu: "
            f"{Path(profile_dir).resolve()} — "
            "Açık Chromium pencerelerini kapatın veya sidebar'dan 'Profil Kilidini Temizle' kullanın."
        )
        LOG_BUS.emit("ERROR", bot_id, hint)
        raise last_exc or RuntimeError("Profil açılamadı.")
    finally:
        mutex.release()
