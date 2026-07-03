"""
TrendyolHit — 2 hesap arama botu (film teknik altyapi)
URL / anahtar kelime / diyalog sahne tarafinda girilir.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

from bot.interactions import add_favorite, add_to_cart, view_product_page
from bot.login import trendyol_login
from bot.navigation import dismiss_overlays, find_product_organically, goto_home
from bot.stealth import launch_persistent_context
from config import PROFILES_DIR, TRENDYOL_HOME
from core.log_bus import LOG_BUS
from core.parser import ParsedTarget, parse_target

G = "\033[92m"
C = "\033[96m"
Y = "\033[93m"
D = "\033[2m"
B = "\033[1m"
X = "\033[0m"

CONFIG_PATH = Path(__file__).parent / "sahne_config.toml"


def setup_console() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_config() -> dict:
    defaults = {
        "profile_1": "film_hesap_1",
        "profile_2": "film_hesap_2",
        "headless": True,
        "max_search_pages": 5,
        "account_1_action": "favorite",
        "account_2_action": "cart",
        "accounts_file": "hesaplar.txt",
    }
    if not CONFIG_PATH.exists():
        return defaults

    data = dict(defaults)
    for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if val.lower() == "true":
            data[key] = True
        elif val.lower() == "false":
            data[key] = False
        elif val.isdigit():
            data[key] = int(val)
        else:
            data[key] = val
    return data


def log(tag: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"{D}[{ts}]{X} {C}{tag:10}{X} | {msg}")
    sys.stdout.flush()


def wait_user(label: str = "Devam") -> None:
    input(f"\n{D}>>> {label} (Enter)...{X}")


def resolve_profile(name: str) -> str:
    p = Path(name)
    if p.is_absolute():
        return str(p.resolve())
    return str((PROFILES_DIR / name).resolve())


def build_target(product_url: str, keyword: str, product_id: str = "") -> ParsedTarget:
    target = parse_target(product_url, default_keyword=keyword)
    if product_id:
        target.product_id = product_id
    return target


def load_accounts(file_path: Path) -> list[tuple[str, str]]:
    """hesaplar.txt — satir basina eposta:sifre"""
    if not file_path.exists():
        raise FileNotFoundError(f"Hesap dosyasi yok: {file_path}")

    accounts: list[tuple[str, str]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in (":", ";", "\t", "|"):
            if sep in line:
                email, pwd = line.split(sep, 1)
                email, pwd = email.strip(), pwd.strip()
                if email and pwd:
                    accounts.append((email, pwd))
                break
    return accounts


async def login_account(
    email: str,
    password: str,
    profile_name: str,
    label: str,
    *,
    headless: bool,
) -> bool:
    prof = resolve_profile(profile_name)
    bot_id = 0
    log("GIRIS", f"{label} | headless={headless}")

    try:
        async with async_playwright() as pw:
            ctx, _ = await launch_persistent_context(
                pw, prof, headless=headless, bot_id=bot_id
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            ok = await trendyol_login(page, email, password, bot_id)
            await ctx.close()
            if ok:
                log("OK", f"{label} kaydedildi -> {profile_name}")
            return ok
    except Exception as exc:
        log("HATA", f"{label}: {exc}")
        return False


async def login_from_file(cfg: dict, accounts_path: Path, *, headless: bool) -> bool:
    accounts = load_accounts(accounts_path)
    if not accounts:
        log("HATA", f"{accounts_path.name} bos veya hatali format")
        return False

    profiles = [cfg["profile_1"], cfg["profile_2"]]
    all_ok = True

    for i, (email, pwd) in enumerate(accounts[:2]):
        label = f"HESAP {i + 1}"
        ok = await login_account(email, pwd, profiles[i], label, headless=headless)
        if not ok:
            all_ok = False
        if i == 0 and len(accounts) > 1:
            await asyncio.sleep(2)

    if len(accounts) > 2:
        log("UYARI", f"Dosyada {len(accounts)} hesap var, ilk 2 kullanildi.")

    return all_ok


async def login_profile(profile_name: str, label: str) -> None:
    prof = resolve_profile(profile_name)
    log("GIRIS", f"{label} — {profile_name}")

    try:
        async with async_playwright() as pw:
            ctx, _ = await launch_persistent_context(pw, prof, headless=False, bot_id=0)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(TRENDYOL_HOME, wait_until="domcontentloaded", timeout=60_000)
            await dismiss_overlays(page, 0)
            log("GIRIS", "Tarayici acildi — Trendyol'a giris yapin")
            input(f"\n>>> {label} giris tamam — Enter...")
            await ctx.close()
    except Exception as exc:
        print(f"\n{Y}HATA: Tarayici acilamadi: {exc}{X}")
        print(f"{D}Cozum: setup.bat tekrar calistirin veya baska Chrome kapatın.{X}\n")
        raise

    log("OK", f"{label} kaydedildi.")


async def run_session(
    profile_name: str,
    account_label: str,
    target: ParsedTarget,
    keyword: str,
    headless: bool,
    max_pages: int,
    action: str,
) -> bool:
    prof = resolve_profile(profile_name)
    bot_id = 1 if account_label.endswith("1") else 2

    log(account_label, f"basladi | profil={profile_name} | headless={headless}")

    async with async_playwright() as pw:
        ctx, device = await launch_persistent_context(
            pw, prof, headless=headless, bot_id=bot_id
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        log(account_label, f"cihaz={device['name']}")

        try:
            await goto_home(page, bot_id, speed=1.0)

            search_target = ParsedTarget(
                raw=target.raw,
                product_id=target.product_id,
                product_url=target.product_url,
                search_keyword=keyword,
            )

            log(account_label, f'arama="{keyword}"')
            found = await find_product_organically(
                page, bot_id, search_target, max_pages=max_pages, speed=1.0
            )
            if not found:
                log(account_label, "urun bulunamadi")
                return False

            await dismiss_overlays(page, bot_id)
            await view_product_page(page, bot_id, speed=1.0, scroll_bursts=3)

            if action == "favorite":
                await add_favorite(page, bot_id, speed=1.0)
            elif action == "cart":
                await add_to_cart(page, bot_id, speed=1.0)

            for e in LOG_BUS.snapshot(15):
                log("bot", e.message)

            log(account_label, "bitti")
            return True
        finally:
            try:
                await ctx.close()
                await asyncio.sleep(0.5)
            except Exception:
                pass


async def run_both(
    cfg: dict,
    product_url: str,
    keyword: str,
    product_id: str,
    *,
    pause_between: bool,
) -> None:
    target = build_target(product_url, keyword, product_id)
    headless = bool(cfg.get("headless", False))
    max_pages = int(cfg.get("max_search_pages", 5))

    ok1 = await run_session(
        cfg["profile_1"], "HESAP-1", target, keyword, headless, max_pages,
        str(cfg.get("account_1_action", "favorite")),
    )

    if pause_between:
        wait_user("Hesap 2 icin hazir ol")

    ok2 = await run_session(
        cfg["profile_2"], "HESAP-2", target, keyword, headless, max_pages,
        str(cfg.get("account_2_action", "cart")),
    )

    print(f"\n{G}sonuc: hesap1={'OK' if ok1 else 'FAIL'}  hesap2={'OK' if ok2 else 'FAIL'}{X}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="TrendyolHit — 2 hesap arama")
    parser.add_argument("--login", action="store_true", help="hesaplar.txt ile headless giris")
    parser.add_argument("--login-manual", action="store_true", help="Elle giris (tarayici gorunur)")
    parser.add_argument("--accounts-file", help="Hesap dosyasi yolu")
    parser.add_argument("--url", help="Urun linki veya ID")
    parser.add_argument("--keyword", help="Arama kelimesi")
    parser.add_argument("--product-id", default="", help="Opsiyonel urun ID")
    parser.add_argument("--only", type=int, choices=[1, 2])
    parser.add_argument("--no-pause", action="store_true", help="Hesaplar arasi bekleme yok")
    parser.add_argument("--visible", action="store_true", help="Tarayici penceresi goster (debug)")
    args = parser.parse_args()
    cfg = load_config()
    if args.visible:
        cfg["headless"] = False
    setup_console()

    if args.login or args.accounts_file:
        accounts_path = Path(args.accounts_file) if args.accounts_file else (
            Path(__file__).parent / str(cfg.get("accounts_file", "hesaplar.txt"))
        )
        ok = asyncio.run(login_from_file(cfg, accounts_path, headless=True))
        sys.exit(0 if ok else 1)

    if args.login_manual:
        asyncio.run(login_profile(cfg["profile_1"], "HESAP 1"))
        asyncio.run(login_profile(cfg["profile_2"], "HESAP 2"))
        return

    if not args.url or not args.keyword:
        print(f"{Y}url ve keyword gerekli:{X}")
        print("  python sahne_demo.py --url LINK --keyword KELIME")
        print("  veya sahne_demo.bat menusunu kullanin")
        sys.exit(1)

    if args.only == 1:
        target = build_target(args.url, args.keyword, args.product_id)
        asyncio.run(run_session(
            cfg["profile_1"], "HESAP-1", target, args.keyword,
            cfg["headless"], cfg["max_search_pages"],
            str(cfg.get("account_1_action", "favorite")),
        ))
        return

    if args.only == 2:
        target = build_target(args.url, args.keyword, args.product_id)
        asyncio.run(run_session(
            cfg["profile_2"], "HESAP-2", target, args.keyword,
            cfg["headless"], cfg["max_search_pages"],
            str(cfg.get("account_2_action", "cart")),
        ))
        return

    asyncio.run(run_both(
        cfg, args.url, args.keyword, args.product_id,
        pause_between=not args.no_pause,
    ))


if __name__ == "__main__":
    main()
