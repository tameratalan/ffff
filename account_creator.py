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


async def create_one_account(*, headless: bool = False, speed: float = 1.0) -> tuple[str, str] | None:
    if should_stop():
        return None

    password = _trendyol_password()
    prof_path = str((PROFILES_DIR / f"reg_{random.randint(1000, 9999)}").resolve())
    bot_id = 1

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
                    return inbox.address, password

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
) -> list[tuple[str, str]]:
    accounts: list[tuple[str, str]] = []

    LOG_BUS.emit(
        "INFO",
        0,
        f"{count} Trendyol hesabi — tempmail.lol kullanilir (mail.tm/guerrilla Trendyol'da yasak)",
    )

    for i in range(1, count + 1):
        if should_stop():
            break

        LOG_BUS.emit("INFO", 0, f"--- Hesap {i}/{count} ---")
        result = await create_one_account(headless=headless, speed=speed)
        if result:
            accounts.append(result)
            LOG_BUS.emit("SUCCESS", 0, f"Kayit OK: {result[0]}")
        else:
            LOG_BUS.emit("ERROR", 0, f"Hesap {i} basarisiz")

        if i < count and not should_stop():
            await asyncio.sleep(2.0)

    LOG_BUS.emit("INFO", 0, f"Toplam: {len(accounts)}/{count} hesap olusturuldu")
    return accounts


def save_hesaplar(path: str | Path, accounts: list[tuple[str, str]]) -> None:
    p = Path(path)
    existing: list[tuple[str, str]] = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            e, pw = line.split(":", 1)
            existing.append((e.strip(), pw.strip()))
    merged = {e: pw for e, pw in existing}
    for e, pw in accounts:
        merged[e] = pw
    p.write_text("\n".join(f"{e}:{pw}" for e, pw in merged.items()) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--save", default="")
    args = p.parse_args()

    STATE.reset_stop()
    accs = asyncio.run(
        create_accounts(args.count, headless=args.headless, speed=args.speed)
    )
    if args.save and accs:
        save_hesaplar(args.save, accs)
        print(f"Kaydedildi: {args.save}")


if __name__ == "__main__":
    main()
