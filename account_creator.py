"""
Trendyol hesap olusturucu — gercek kayit + e-posta dogrulama.

    python account_creator.py --count 2 --save hesaplar.txt
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import string
from pathlib import Path

from playwright.async_api import async_playwright

from bot.signup import register_trendyol_account
from bot.stealth import launch_persistent_context
from config import PROFILES_DIR
from core.async_utils import should_stop
from core.log_bus import LOG_BUS
from core.state import STATE
from services.temp_mail import EmailRejectedError, create_temp_inbox

MAX_EMAIL_RETRIES = 6


def _trendyol_password() -> str:
    letters = "".join(random.choices(string.ascii_letters, k=8))
    digits = "".join(random.choices(string.digits, k=3))
    return letters + digits + "Aa1!"


def _profile_name(email: str) -> str:
    digest = hashlib.md5(email.strip().lower().encode()).hexdigest()[:12]
    return f"reg_{digest}"


async def _extract_auth_token(ctx) -> str | None:
    for cookie in await ctx.cookies():
        if cookie.get("name") == "token" and "trendyol" in cookie.get("domain", ""):
            return cookie.get("value")
    return None


async def create_one_account(
    *, headless: bool = False, speed: float = 1.0, bot_id: int = 1,
) -> tuple[str, str, str | None] | None:
    if should_stop():
        return None

    password = _trendyol_password()
    prof_path = str((PROFILES_DIR / f"reg_{random.randint(1000, 9999)}").resolve())

    async with async_playwright() as pw:
        ctx, _device = await launch_persistent_context(
            pw, prof_path, headless=headless, bot_id=bot_id, desktop_only=True,
        )
        mail_page = await ctx.new_page()
        ty_page = await ctx.new_page()

        try:
            for attempt in range(1, MAX_EMAIL_RETRIES + 1):
                if should_stop():
                    return None

                try:
                    inbox = await create_temp_inbox(mail_page)
                except RuntimeError as exc:
                    LOG_BUS.emit("ERROR", bot_id, str(exc))
                    return None

                LOG_BUS.emit("INFO", bot_id, f"Kayit denemesi {attempt}/{MAX_EMAIL_RETRIES}: {inbox.address}")

                try:
                    ok = await register_trendyol_account(
                        ty_page, inbox, password, bot_id, speed=speed,
                    )
                except EmailRejectedError:
                    LOG_BUS.emit("WARNING", bot_id, "Domain reddedildi — yeni temp mail deneniyor...")
                    continue

                if ok:
                    token = await _extract_auth_token(ctx)
                    if token:
                        LOG_BUS.emit("SUCCESS", bot_id, "Auth token yakalandi")
                    else:
                        LOG_BUS.emit("WARNING", bot_id, "Kayit basarili ama token yakalanamadi")
                    return inbox.address, password, token

                LOG_BUS.emit("WARNING", bot_id, "Kayit tamamlanamadi")

            LOG_BUS.emit("ERROR", bot_id, f"{MAX_EMAIL_RETRIES} denemede uygun mail bulunamadi")
            return None
        finally:
            try:
                await ctx.close()
                await asyncio.sleep(0.3)
            except Exception:
                pass


async def create_accounts(
    count: int = 1,
    *,
    headless: bool = False,
    speed: float = 1.0,
    parallel: int = 1,
    save_path: str | Path | None = None,
) -> list[tuple[str, str, str | None]]:
    accounts: list[tuple[str, str, str | None]] = []
    # save_path verildiginde her basarili hesap ANINDA diske yazilir — batch
    # bitmeden bir kesinti/crash olsa bile o ana kadar acilan hesaplar kaybolmaz.
    save_lock = asyncio.Lock()

    LOG_BUS.emit(
        "INFO",
        0,
        f"{count} Trendyol hesabi — tempmail.lol kullanilir (mail.tm/guerrilla Trendyol'da yasak)",
    )

    parallel = max(1, min(parallel, count))

    if parallel <= 1:
        for i in range(1, count + 1):
            if should_stop():
                break

            LOG_BUS.emit("INFO", 0, f"--- Hesap {i}/{count} ---")
            result = await create_one_account(headless=headless, speed=speed)
            if result:
                accounts.append(result)
                LOG_BUS.emit("SUCCESS", 0, f"Kayit OK: {result[0]}")
                if save_path is not None:
                    async with save_lock:
                        save_hesaplar(save_path, [result])
            else:
                LOG_BUS.emit("ERROR", 0, f"Hesap {i} basarisiz")

            if i < count and not should_stop():
                await asyncio.sleep(2.0)

        LOG_BUS.emit("INFO", 0, f"Toplam: {len(accounts)}/{count} hesap olusturuldu")
        return accounts

    LOG_BUS.emit("INFO", 0, f"{parallel} tarayici paralel hesap aciyor ({count} hesap)")
    sem = asyncio.Semaphore(parallel)
    done = 0

    async def _guarded(bot_id: int) -> tuple[str, str, str | None] | None:
        nonlocal done
        if should_stop():
            return None
        async with sem:
            if should_stop():
                return None
            result = await create_one_account(headless=headless, speed=speed, bot_id=bot_id)
            done += 1
            if result:
                LOG_BUS.emit("SUCCESS", bot_id, f"Kayit OK: {result[0]} ({done}/{count} hesap tamamlandi)")
                if save_path is not None:
                    async with save_lock:
                        save_hesaplar(save_path, [result])
            else:
                LOG_BUS.emit("ERROR", bot_id, f"Hesap basarisiz ({done}/{count} hesap tamamlandi)")
            return result

    tasks = [_guarded(i) for i in range(1, count + 1)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            LOG_BUS.emit("ERROR", 0, f"Hesap olusturma hatasi: {r}")
            continue
        if r:
            accounts.append(r)

    LOG_BUS.emit("INFO", 0, f"Toplam: {len(accounts)}/{count} hesap olusturuldu")
    return accounts


def save_hesaplar(
    path: str | Path,
    accounts: list[tuple[str, str] | tuple[str, str, str | None]],
) -> None:
    p = Path(path)
    existing: dict[str, tuple[str, str | None]] = {}
    if p.exists():
        from accounts_loader import load_accounts_full
        for email, pwd, tok in load_accounts_full(p):
            existing[email] = (pwd, tok)
    for item in accounts:
        email = item[0]
        pwd = item[1]
        tok = item[2] if len(item) >= 3 else existing.get(email, ("", None))[1]
        existing[email] = (pwd, tok)
    lines: list[str] = []
    for email, (pwd, tok) in existing.items():
        if tok:
            lines.append(f"{email}:{pwd}:{tok}")
        else:
            lines.append(f"{email}:{pwd}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--save", default="")
    args = p.parse_args()

    STATE.reset_stop()
    accs = asyncio.run(
        create_accounts(
            args.count,
            headless=args.headless,
            speed=args.speed,
            parallel=args.parallel,
            save_path=args.save or None,
        )
    )
    if args.save and accs:
        save_hesaplar(args.save, accs)
        print(f"Kaydedildi: {args.save}")


if __name__ == "__main__":
    main()
