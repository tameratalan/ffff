"""Bagimsiz tekil aksiyon calistirici — Araclar sekmesi icin.

Hit kampanyasindan (paralel/dalga/total_hits) tamamen ayri: tek oturum,
tek hesap, tek veya birden fazla aksiyon (Hit / Soru Sor / Favorile / Sepete Ekle).

- run_single_action: tek oturum, tek hesap, TEK aksiyon (geriye donuk uyumlu).
- run_account_session: tek oturum, tek hesap, BIRDEN FAZLA aksiyon sirayla.
- run_batch_accounts: birden fazla hesap, HER HESAP KENDI oturumunda, PARALEL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

from playwright.async_api import Page, async_playwright

from bot.interactions import (
    add_favorite,
    add_to_cart,
    ask_question_with_account,
    follow_store,
    view_product_page,
)
from bot.login import login_with_token, is_logged_in
from bot.navigation import (
    dismiss_overlays,
    goto_product_direct,
    wait_for_product_page,
    _is_product_404,
)
from bot.stealth import launch_persistent_context
from config import BASE_DIR, PROFILES_DIR
from core.async_utils import should_stop
from core.async_utils import interruptible_sleep
from core.log_bus import LOG_BUS
from core.parser import parse_target, canonical_product_url, primary_product_id

ACTIONS = ("question", "favorite", "cart", "store_follow")

# run_account_session / run_batch_accounts icin desteklenen aksiyonlar — "hit" dahil.
ALL_ACTIONS = ("hit", "favorite", "cart", "question", "store_follow")

_ACTION_LABELS = {
    "question": ("Soru gonderildi", "Soru gonderilemedi"),
    "favorite": ("Favoriye eklendi", "Favoriye eklenemedi"),
    "cart": ("Sepete eklendi", "Sepete eklenemedi"),
    "store_follow": ("Magaza takip edildi", "Magaza takip edilemedi"),
}

_SESSION_ACTION_LABELS = {
    "hit": ("Hit tamamlandi", "Hit basarisiz"),
    **_ACTION_LABELS,
}

USED_ACTIONS_PATH = BASE_DIR / "used_actions.json"


def _clean_target_url(url: str) -> str:
    return (url or "").strip().split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def _action_target(action: str, product_url: str, store_url: str = "") -> str:
    if action == "store_follow":
        return _clean_target_url(store_url or product_url)
    target = parse_target(product_url)
    pid = target.product_id or primary_product_id(product_url)
    return f"product:{pid}" if pid else _clean_target_url(product_url)


def _used_key(email: str, action: str, product_url: str, store_url: str = "") -> str:
    target = _action_target(action, product_url, store_url)
    raw = f"{email.strip().lower()}|{action}|{target}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _load_used_actions() -> set[str]:
    try:
        data = json.loads(USED_ACTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(data, dict):
        items = data.get("used", [])
    else:
        items = data
    return {str(x) for x in items if x}


def _save_used_actions(keys: set[str]) -> None:
    payload = {
        "updated_at": int(time.time()),
        "used": sorted(keys),
    }
    tmp = USED_ACTIONS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USED_ACTIONS_PATH)


def _profile_name(email: str) -> str:
    """hit_engine._profile_name'deki hesap-bazli dalin birebir kopyasi —
    ayni hesap icin ayni profil kullanilsin (login state paylasilsin)."""
    digest = hashlib.md5(email.strip().lower().encode()).hexdigest()[:12]
    return f"acc_{digest}"


async def _open_context(pw, email: str, headless: bool, bot_id: int):
    """Hesaba ozel (md5 hash'li) profil ile persistent context acar."""
    profile = _profile_name(email)
    prof_path = str((PROFILES_DIR / profile).resolve())
    ctx, _device = await launch_persistent_context(
        pw, prof_path, headless=headless, bot_id=bot_id,
        desktop_only=False,
        enable_buster=not headless,
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return ctx, page


async def _login_and_open_product(
    page: Page,
    bot_id: int,
    email: str,
    product_url: str,
    speed: float,
    *,
    token: str,
    turbo: bool = False,
) -> str | None:
    """Token ile giris yapar ve urun sayfasina gider."""
    if should_stop():
        return None

    target = parse_target(product_url)
    url = target.product_url or product_url
    if not url:
        LOG_BUS.emit("ERROR", bot_id, "Urun linki yok")
        return None

    token = (token or "").strip()
    if not token:
        LOG_BUS.emit("ERROR", bot_id, "Token yok — sadece token ile giris destekleniyor")
        return None

    if turbo:
        if not await login_with_token(
            page, token, email, bot_id, speed=speed, redirect_url=url,
        ):
            LOG_BUS.emit("ERROR", bot_id, "Token ile giris basarisiz")
            return None
        await dismiss_overlays(page, bot_id)
        is_store_url = "/magaza/" in url
        if await _is_product_404(page):
            pid = primary_product_id(url)
            if pid:
                alt = canonical_product_url(url)
                LOG_BUS.emit("INFO", bot_id, f"404 — alternatif URL: {alt[:70]}...")
                try:
                    await page.goto(alt, wait_until="domcontentloaded", timeout=20_000)
                    await dismiss_overlays(page, bot_id)
                except Exception as exc:
                    LOG_BUS.emit("ERROR", bot_id, f"Alternatif URL acilamadi: {exc}")
        if await _is_product_404(page):
            LOG_BUS.emit("ERROR", bot_id, "Urun sayfasi bulunamadi (404) — gecerli urun linki girin")
            return None
        if is_store_url:
            return url
        if not await wait_for_product_page(page, bot_id, timeout=12_000):
            LOG_BUS.emit("ERROR", bot_id, "Urun icerigi yuklenmedi")
            return None
        return url

    is_store_url = "/magaza/" in url

    if not await login_with_token(page, token, email, bot_id, speed=speed):
        LOG_BUS.emit("ERROR", bot_id, "Token ile giris basarisiz")
        return None

    if not await is_logged_in(page):
        LOG_BUS.emit("ERROR", bot_id, "Oturum acilamadi")
        return None

    if should_stop():
        LOG_BUS.emit("WARNING", bot_id, "Durduruldu")
        return None

    if is_store_url:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await dismiss_overlays(page, bot_id)
            return url
        except Exception as exc:
            LOG_BUS.emit("ERROR", bot_id, f"Magaza sayfasi acilamadi: {exc}")
            return None

    if not await goto_product_direct(page, bot_id, url, speed=speed):
        LOG_BUS.emit("ERROR", bot_id, "Urun sayfasi acilamadi")
        return None

    await dismiss_overlays(page, bot_id)

    if should_stop():
        LOG_BUS.emit("WARNING", bot_id, "Durduruldu")
        return None

    return url


async def _safe_close(ctx, bot_id: int) -> None:
    try:
        await asyncio.wait_for(ctx.close(), timeout=10.0)
    except asyncio.TimeoutError:
        LOG_BUS.emit("WARNING", bot_id, "Tarayici kapanma zaman asimi")
    except Exception:
        pass


async def run_single_action(
    product_url: str,
    email: str,
    password: str,
    action: str,
    *,
    question_text: str = "",
    headless: bool = True,
    speed: float = 1.0,
    bot_id: int = 1,
    token: str | None = None,
    turbo: bool = False,
) -> bool:
    """Tek oturum, tek hesap, tek aksiyon. Sadece token ile giris."""
    if action not in ACTIONS:
        LOG_BUS.emit("ERROR", bot_id, f"Bilinmeyen aksiyon: {action}")
        return False

    if not (token or "").strip():
        LOG_BUS.emit("ERROR", bot_id, "Token gerekli — email:sifre:token formatinda hesap yukleyin")
        return False

    ok_label, fail_label = _ACTION_LABELS[action]

    if should_stop():
        return False

    async with async_playwright() as pw:
        ctx, page = await _open_context(pw, email, headless, bot_id)
        try:
            url = await _login_and_open_product(
                page, bot_id, email, product_url, speed, token=token or "", turbo=turbo,
            )
            if not url:
                return False

            if action == "question":
                ok = await ask_question_with_account(
                    page, bot_id, question_text, speed=speed,
                    email=email, password=password,
                )
            elif action == "favorite":
                ok = await add_favorite(page, bot_id, speed=speed, turbo=turbo)
            elif action == "cart":
                ok = await add_to_cart(page, bot_id, speed=speed, turbo=turbo)
            else:
                ok = await follow_store(page, bot_id, speed=speed, turbo=turbo)

            if ok:
                LOG_BUS.emit("SUCCESS", bot_id, ok_label)
            else:
                LOG_BUS.emit("WARNING", bot_id, fail_label)
            return ok
        except Exception as exc:
            LOG_BUS.emit("ERROR", bot_id, f"{fail_label} — hata: {exc}")
            return False
        finally:
            await _safe_close(ctx, bot_id)


async def run_account_session(
    product_url: str,
    email: str,
    password: str,
    actions: list[str],
    *,
    store_url: str = "",
    question_text: str = "",
    headless: bool = True,
    speed: float = 1.0,
    bot_id: int = 1,
    token: str | None = None,
    turbo: bool = False,
) -> dict[str, bool]:
    """Tek oturum, tek hesap, BIRDEN FAZLA aksiyon sirayla. Sadece token ile giris."""
    results: dict[str, bool] = {}

    if not (token or "").strip():
        LOG_BUS.emit("ERROR", bot_id, "Token gerekli — email:sifre:token formatinda hesap yukleyin")
        return results

    wanted = [a for a in actions if a in ALL_ACTIONS]
    for unknown in [a for a in actions if a not in ALL_ACTIONS]:
        LOG_BUS.emit("WARNING", bot_id, f"Bilinmeyen aksiyon atlandi: {unknown}")

    if not wanted:
        LOG_BUS.emit("ERROR", bot_id, "Gecerli aksiyon listesi bos")
        return results

    if should_stop():
        return results

    LOG_BUS.emit(
        "INFO", bot_id,
        f"Oturum basliyor ({email}) — aksiyonlar: {', '.join(wanted)}",
    )

    async with async_playwright() as pw:
        ctx, page = await _open_context(pw, email, headless, bot_id)
        try:
            url = await _login_and_open_product(
                page, bot_id, email, product_url, speed, token=token or "", turbo=turbo,
            )
            if not url:
                LOG_BUS.emit("ERROR", bot_id, "Oturum baslatilamadi — aksiyonlar atlandi")
                return results

            scroll_bursts = 0 if turbo else (2 if headless else 4)

            for action in wanted:
                if should_stop():
                    LOG_BUS.emit("WARNING", bot_id, "Durduruldu — kalan aksiyonlar atlandi")
                    break

                ok_label, fail_label = _SESSION_ACTION_LABELS[action]
                try:
                    if should_stop():
                        LOG_BUS.emit("WARNING", bot_id, "Durduruldu — kalan aksiyonlar atlandi")
                        break
                    if action == "hit":
                        await dismiss_overlays(page, bot_id)
                        bursts = 2 if turbo else scroll_bursts
                        hit_speed = max(speed, 3.0) if turbo else speed
                        await view_product_page(
                            page, bot_id, speed=hit_speed, scroll_bursts=bursts,
                        )
                        # Trendyol analytics icin sayfada minimum sure kal
                        dwell = 4000 if turbo else 2500
                        if not await interruptible_sleep(dwell / 1000, chunk=0.2):
                            LOG_BUS.emit("WARNING", bot_id, "Hit beklemesi durduruldu")
                            break
                        ok = True
                    elif action == "favorite":
                        ok = await add_favorite(page, bot_id, speed=speed, turbo=turbo)
                    elif action == "cart":
                        ok = await add_to_cart(page, bot_id, speed=speed, turbo=turbo)
                    elif action == "store_follow":
                        if store_url:
                            LOG_BUS.emit("INFO", bot_id, "Magaza sayfasina geciliyor...")
                            await page.goto(store_url, wait_until="domcontentloaded", timeout=20_000)
                            await dismiss_overlays(page, bot_id)
                        ok = await follow_store(page, bot_id, speed=speed, turbo=turbo)
                    else:  # "question"
                        ok = await ask_question_with_account(
                            page, bot_id, question_text, speed=speed,
                            email=email, password=password,
                        )
                except Exception as exc:
                    LOG_BUS.emit("ERROR", bot_id, f"{fail_label} — hata: {exc}")
                    ok = False

                results[action] = ok
                if ok:
                    LOG_BUS.emit("SUCCESS", bot_id, ok_label)
                else:
                    LOG_BUS.emit("WARNING", bot_id, fail_label)

            return results
        finally:
            await _safe_close(ctx, bot_id)
            ok_count = sum(1 for v in results.values() if v)
            LOG_BUS.emit(
                "INFO", bot_id,
                f"Oturum bitti ({email}) — {ok_count}/{len(wanted)} aksiyon basarili",
            )


async def run_batch_accounts(
    product_url: str,
    accounts: list[tuple[str, str]] | list[tuple[str, str, str | None]],
    actions: list[str],
    *,
    store_url: str = "",
    question_text: str = "",
    headless: bool = True,
    speed: float = 1.0,
    parallel: int = 1,
    turbo: bool = False,
    batch_limit: int | None = None,
) -> list[dict]:
    """Birden fazla hesap — HER HESAP KENDI oturumunda, ayni aksiyon listesini
    PARALEL calistirir (account_creator.create_accounts'daki Semaphore +
    gather(..., return_exceptions=True) deseninin birebir ayni).

    `accounts` her eleman `(email, sifre, token)` uclusu olmali; token zorunlu.
    `(email, sifre)` ikilisi verilirse token alani yok sayilir ve hesap atlanir.

    Doner: [{"email": ..., "results": {"hit": bool, "favorite": bool, ...}}, ...]
    """
    used_actions = _load_used_actions()
    if batch_limit and batch_limit > 0:
        filtered_accounts = []
        for acc in accounts:
            email = acc[0]
            has_pending = any(
                _used_key(email, action, product_url, store_url) not in used_actions
                for action in actions
            )
            if has_pending:
                filtered_accounts.append(acc)
            if len(filtered_accounts) >= batch_limit:
                break
        accounts = filtered_accounts

    total = len(accounts)
    if total == 0:
        LOG_BUS.emit("WARNING", 0, "Islenecek yeni hesap yok (hepsi kullanilmis olabilir)")
        return []

    parallel = max(1, min(parallel, total))
    eff_speed = 5.0 if turbo else speed
    mode = "TURBO" if turbo else "normal"
    LOG_BUS.emit(
        "INFO", 0,
        f"{total} hesap, {parallel} paralel ({mode}) — aksiyonlar: {', '.join(actions)}",
    )

    done = 0
    done_lock = asyncio.Lock()
    out: list[dict] = []
    out_lock = asyncio.Lock()
    used_lock = asyncio.Lock()
    queue: asyncio.Queue[tuple[int, tuple] | None] = asyncio.Queue()
    for i, acc in enumerate(accounts):
        queue.put_nowait((i, acc))
    for _ in range(parallel):
        queue.put_nowait(None)

    async def _process(index: int, acc: tuple) -> dict:
        nonlocal done
        bot_id = index + 1
        email = acc[0]
        password = acc[1] if len(acc) >= 2 else ""
        token = acc[2] if len(acc) >= 3 else None
        if not (token or "").strip():
            LOG_BUS.emit("WARNING", bot_id, f"Token yok, atlaniyor: {email}")
            async with done_lock:
                done += 1
                progress = done
            LOG_BUS.emit("INFO", bot_id, f"{progress}/{total} hesap tamamlandi")
            return {"email": email, "results": {}}
        if should_stop():
            return {"email": email, "results": {}}
        async with used_lock:
            pending_actions = [
                action for action in actions
                if _used_key(email, action, product_url, store_url) not in used_actions
            ]
        if not pending_actions:
            LOG_BUS.emit("INFO", bot_id, f"{email} daha once kullanilmis — atlaniyor")
            async with done_lock:
                done += 1
                progress = done
            LOG_BUS.emit("INFO", bot_id, f"{progress}/{total} hesap tamamlandi")
            return {"email": email, "results": {}}
        try:
            session_results = await run_account_session(
                product_url, email, password, pending_actions,
                store_url=store_url, question_text=question_text, headless=headless,
                speed=eff_speed, bot_id=bot_id, token=token, turbo=turbo,
            )
        except Exception as exc:
            LOG_BUS.emit("ERROR", bot_id, f"Hesap oturum hatasi ({email}): {exc}")
            session_results = {}

        successful_keys = {
            _used_key(email, action, product_url, store_url)
            for action, ok in session_results.items()
            if ok
        }
        if successful_keys:
            async with used_lock:
                used_actions.update(successful_keys)
                _save_used_actions(used_actions)

        async with done_lock:
            done += 1
            progress = done
        ok_count = sum(1 for v in session_results.values() if v)
        LOG_BUS.emit(
            "INFO", bot_id,
            f"{email} tamamlandi ({ok_count}/{len(pending_actions)} yeni aksiyon basarili) — "
            f"{progress}/{total} hesap tamamlandi",
        )
        return {"email": email, "results": session_results}

    async def _worker() -> None:
        while not should_stop():
            item = await queue.get()
            if item is None:
                return
            index, acc = item
            result = await _process(index, acc)
            async with out_lock:
                out.append(result)

    workers = [asyncio.create_task(_worker()) for _ in range(parallel)]
    try:
        await asyncio.gather(*workers)
    finally:
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    if should_stop():
        LOG_BUS.emit("WARNING", 0, f"Toplu islem durduruldu: {len(out)}/{total} hesap islendi")
    else:
        LOG_BUS.emit("INFO", 0, f"Toplu islem bitti: {len(out)}/{total} hesap islendi")
    return out
