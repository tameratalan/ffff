"""TrendyolHit — arama, hit ve modul motoru."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Playwright, async_playwright

from bot.interactions import add_favorite, add_to_cart, ask_question_with_account, view_product_page
from bot.login import ensure_logged_in, trendyol_login
from bot.navigation import dismiss_overlays, find_product_organically, goto_home, goto_product_direct
from bot.stealth import launch_persistent_context
from config import PROFILES_DIR
from core.async_utils import interruptible_sleep, should_stop
from core.log_bus import LOG_BUS
from core.parser import ParsedTarget, parse_target
from core.state import STATE
from rank_checker import resolve_product_ids


@dataclass
class HitModules:
    hit: bool = True
    favorite: bool = False
    cart: bool = False
    question: bool = False
    question_text: str = "Urun orijinal mi?"


@dataclass
class HitJob:
    product_url: str
    keywords: list[str]
    max_pages: int = 50
    headless: bool = True
    guest_mode: bool = True
    accounts: list[tuple[str, str]] = field(default_factory=list)
    modules: HitModules = field(default_factory=HitModules)
    delay_between: float = 1.0
    entry_mode: str = "organic"  # organic | direct
    parallel: int = 10
    total_hits: int = 50  # 0 = DURDUR'a kadar sonsuz dalga
    product_ids: list[str] = field(default_factory=list)
    split_by_keyword: bool = False  # toplam hit'i kelimelere esit bol


class HitEngine:
    def __init__(self) -> None:
        self.stats: dict[str, int] = {"ok": 0, "fail": 0, "total": 0, "waves": 0}
        self.keyword_stats: dict[str, dict[str, int]] = {}

    def stop(self) -> None:
        STATE.request_stop()
        LOG_BUS.emit("WARNING", 0, "DURDUR — islem kesiliyor...")

    def reset(self) -> None:
        STATE.reset_stop()
        self.stats = {"ok": 0, "fail": 0, "total": 0, "waves": 0}
        self.keyword_stats = {}

    def _init_keyword_stats(self, keywords: list[str]) -> None:
        self.keyword_stats = {kw: {"ok": 0, "fail": 0} for kw in keywords}

    def _record_keyword_result(self, keyword: str, ok: bool) -> None:
        if keyword not in self.keyword_stats:
            self.keyword_stats[keyword] = {"ok": 0, "fail": 0}
        if ok:
            self.keyword_stats[keyword]["ok"] += 1
        else:
            self.keyword_stats[keyword]["fail"] += 1

    def _keyword_for_session(self, job: HitJob, keywords: list[str], index: int) -> str:
        if len(keywords) == 1:
            return keywords[0]
        if not job.split_by_keyword or job.total_hits <= 0:
            return keywords[index % len(keywords)]
        per_kw = max(1, job.total_hits // len(keywords))
        extra = job.total_hits % len(keywords)
        slots: list[str] = []
        for i, kw in enumerate(keywords):
            n = per_kw + (1 if i < extra else 0)
            slots.extend([kw] * n)
        if index < len(slots):
            return slots[index]
        return keywords[index % len(keywords)]

    def _profile_name(self, index: int, guest: bool, email: str | None = None) -> str:
        if guest:
            return f"guest_{index}_{uuid.uuid4().hex[:8]}"
        if email:
            digest = hashlib.md5(email.strip().lower().encode()).hexdigest()[:12]
            return f"acc_{digest}"
        return f"hit_profile_{index}"

    async def _run_one(
        self,
        pw: Playwright,
        job: HitJob,
        keyword: str,
        session_index: int,
        email: str | None,
        password: str | None,
    ) -> bool:
        if should_stop():
            return False

        bot_id = session_index + 1
        target = parse_target(job.product_url, default_keyword=keyword)
        profile = self._profile_name(session_index, job.guest_mode, email)
        prof_path = str((PROFILES_DIR / profile).resolve())

        pid = target.product_id or "?"
        LOG_BUS.emit(
            "INFO",
            bot_id,
            f"#{session_index + 1} | hedef -p-{pid} | \"{keyword}\" | "
            f"misafir={job.guest_mode}",
        )

        ctx, _device = await launch_persistent_context(
            pw, prof_path, headless=job.headless, bot_id=bot_id,
            desktop_only=job.entry_mode == "direct",
            enable_buster=not job.headless,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            if not job.guest_mode and email and password:
                if not await trendyol_login(page, email, password, bot_id):
                    LOG_BUS.emit("ERROR", bot_id, "Giris basarisiz")
                    return False
            else:
                await goto_home(page, bot_id, speed=1.0)

            if job.modules.question and email and password:
                if not await ensure_logged_in(page, email, password, bot_id):
                    LOG_BUS.emit("ERROR", bot_id, "Soru icin giris gerekli — oturum acilamadi")
                    return False

            if job.entry_mode == "direct":
                url = target.product_url or job.product_url
                if not url:
                    LOG_BUS.emit("ERROR", bot_id, "Urun linki yok")
                    return False
                LOG_BUS.emit("INFO", bot_id, f"Dogrudan hedef urun (-p-{pid})")
                found = await goto_product_direct(page, bot_id, url, speed=1.0)
                if found and job.modules.question:
                    await asyncio.sleep(1.5)
                    await page.evaluate("window.scrollBy(0, 400)")
            else:
                if not target.product_id:
                    LOG_BUS.emit("ERROR", bot_id, "Hedef urun ID yok — baska urune tiklanmaz, iptal")
                    return False
                search_target = ParsedTarget(
                    raw=target.raw,
                    product_id=target.product_id,
                    product_url=target.product_url,
                    search_keyword=keyword,
                )
                ids = job.product_ids or ([target.product_id] if target.product_id else [])
                LOG_BUS.emit(
                    "INFO",
                    bot_id,
                    f"Hedef p-{ids[0]} araniyor (max {job.max_pages} sayfa)",
                )
                found = await find_product_organically(
                    page, bot_id, search_target, max_pages=job.max_pages, speed=1.0,
                    product_ids=ids,
                )

            if should_stop():
                LOG_BUS.emit("WARNING", bot_id, "Oturum durduruldu")
                return False
            if not found:
                if job.entry_mode == "direct":
                    LOG_BUS.emit("ERROR", bot_id, "Hedef urun acilamadi")
                else:
                    LOG_BUS.emit(
                        "WARNING",
                        bot_id,
                        f'"{keyword}" — hedef -p-{pid} {job.max_pages} sayfada yok',
                    )
                return False

            await dismiss_overlays(page, bot_id)

            if job.modules.hit:
                await view_product_page(page, bot_id, speed=1.0, scroll_bursts=4)
            if job.modules.favorite:
                await add_favorite(page, bot_id, speed=1.0)
            if job.modules.cart:
                await add_to_cart(page, bot_id, speed=1.0)
            if job.modules.question:
                ok = await ask_question_with_account(
                    page,
                    bot_id,
                    job.modules.question_text,
                    speed=1.0,
                    email=email or "",
                    password=password or "",
                )
                if not ok:
                    LOG_BUS.emit("WARNING", bot_id, "Soru gonderilemedi")
                    return False

            LOG_BUS.emit("SUCCESS", bot_id, f"Hedef urune hit OK (-p-{pid})")
            return True
        finally:
            try:
                await ctx.close()
                await asyncio.sleep(0.2)
            except Exception:
                pass
            if job.guest_mode:
                try:
                    p = Path(prof_path)
                    if p.is_dir() and p.name.startswith("guest_"):
                        shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass

    def _session_credentials(
        self,
        job: HitJob,
        index: int,
        keywords: list[str],
    ) -> tuple[str, str | None, str | None]:
        if job.entry_mode == "direct":
            acc = job.accounts[0]
            return "direct", acc[0], acc[1]
        kw = self._keyword_for_session(job, keywords, index)
        if job.guest_mode:
            return kw, None, None
        acc = job.accounts[index % len(job.accounts)]
        return kw, acc[0], acc[1]

    async def _run_wave(
        self,
        pw: Playwright,
        job: HitJob,
        keywords: list[str],
        *,
        wave_size: int,
        start_index: int,
    ) -> tuple[int, int]:
        """Paralel dalga — wave_size tarayici ayni anda."""
        sem = asyncio.Semaphore(max(1, job.parallel))

        async def _guarded(idx: int) -> bool:
            if should_stop():
                return False
            async with sem:
                if should_stop():
                    return False
                kw, email, pwd = self._session_credentials(job, idx, keywords)
                ok = await self._run_one(pw, job, kw, idx, email, pwd)
                self._record_keyword_result(kw, ok)
                if ok:
                    self.stats["ok"] += 1
                else:
                    self.stats["fail"] += 1
                self.stats["total"] = self.stats["ok"] + self.stats["fail"]
                return ok

        tasks = [_guarded(start_index + i) for i in range(wave_size)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = fail = 0
        for r in results:
            if r is True:
                ok += 1
            elif r is False:
                fail += 1
            else:
                fail += 1
        return ok, fail

    async def _resolve_product_ids(self, pw: Playwright, product_url: str) -> list[str]:
        """Siralama tarayicisi ile ayni: link + urun sayfasindaki tum varyant ID'leri."""
        profile = f"id_resolve_{uuid.uuid4().hex[:8]}"
        prof_path = str((PROFILES_DIR / profile).resolve())
        ctx = None
        try:
            ctx, _ = await launch_persistent_context(
                pw, prof_path, headless=True, bot_id=0,
                desktop_only=True, enable_buster=False,
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            return await resolve_product_ids(page, product_url)
        except Exception as exc:
            LOG_BUS.emit("WARNING", 0, f"ID cozme hatasi: {exc}")
            return []
        finally:
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass
            try:
                shutil.rmtree(Path(prof_path), ignore_errors=True)
            except Exception:
                pass

    async def run(self, job: HitJob) -> dict[str, int]:
        self.reset()
        LOG_BUS.clear()

        if not job.product_url.strip():
            LOG_BUS.emit("ERROR", 0, "Urun linki bos")
            return self.stats

        keywords = [k.strip() for k in job.keywords if k.strip()]
        if job.entry_mode == "organic" and not keywords:
            LOG_BUS.emit("ERROR", 0, "Anahtar kelime bos")
            return self.stats

        self._init_keyword_stats(keywords)

        target = parse_target(job.product_url, default_keyword=keywords[0] if keywords else "")
        if job.entry_mode == "organic" and not target.product_id:
            LOG_BUS.emit(
                "ERROR",
                0,
                "Organik mod: linkte -p-URUNID olmali (sadece o urune hit)",
            )
            return self.stats

        if job.entry_mode == "direct":
            if job.guest_mode:
                LOG_BUS.emit("ERROR", 0, "Direct mod icin hesap gerekli")
                return self.stats
            if not job.accounts:
                LOG_BUS.emit("ERROR", 0, "Hesap listesi bos")
                return self.stats
            job.total_hits = max(1, job.total_hits or 1)
            job.parallel = min(job.parallel, job.total_hits)

        parallel = max(1, min(job.parallel, 100))
        unlimited = job.total_hits <= 0 and job.entry_mode == "organic"

        if unlimited:
            planned = "sonsuz (DURDUR)"
        else:
            planned = str(job.total_hits or len(keywords))

        LOG_BUS.emit(
            "INFO",
            0,
            f"HEDEF -p-{target.product_id or '?'} | {parallel} tarayici paralel | "
            f"toplam hit: {planned} | {len(keywords)} kelime | arka plan",
        )
        if len(keywords) > 1:
            kw_list = ", ".join(f'"{k}"' for k in keywords[:4])
            extra = f" (+{len(keywords) - 4})" if len(keywords) > 4 else ""
            LOG_BUS.emit("INFO", 0, f"Coklu kelime: {kw_list}{extra} — ayni dalgada paralel")
            if job.split_by_keyword and job.total_hits > 0:
                per = max(1, job.total_hits // len(keywords))
                LOG_BUS.emit(
                    "INFO",
                    0,
                    f"Esit bolme: ~{per} hit / kelime (toplam {job.total_hits})",
                )
        if parallel >= 15:
            LOG_BUS.emit(
                "WARNING",
                0,
                f"{parallel} paralel = ayni anda {parallel} Chrome; 8GB RAM icin 3-5, 16GB icin 8-12 onerilir",
            )
        elif parallel >= 8:
            LOG_BUS.emit(
                "INFO",
                0,
                f"{parallel} paralel tarayici — RAM/CPU yuksek olabilir",
            )

        completed = 0
        session_index = 0

        async with async_playwright() as pw:
            if job.entry_mode == "organic":
                job.product_ids = await self._resolve_product_ids(pw, job.product_url)
                if not job.product_ids and target.product_id:
                    job.product_ids = [target.product_id]
                if job.product_ids:
                    preview = ", ".join(f"p-{x}" for x in job.product_ids)
                    LOG_BUS.emit(
                        "INFO",
                        0,
                        f"Hedef ID (sadece link): {preview}",
                    )

            if unlimited:
                while not should_stop():
                    wave = parallel
                    self.stats["waves"] += 1
                    LOG_BUS.emit(
                        "INFO",
                        0,
                        f"Dalga {self.stats['waves']}: {wave} tarayici baslatiliyor...",
                    )
                    ok, fail = await self._run_wave(
                        pw, job, keywords, wave_size=wave, start_index=session_index,
                    )
                    session_index += wave
                    LOG_BUS.emit(
                        "INFO",
                        0,
                        f"Dalga bitti: +{ok} OK / +{fail} FAIL | "
                        f"toplam {self.stats['ok']} OK / {self.stats['fail']} FAIL",
                    )
                    if should_stop():
                        break
                    if job.delay_between > 0:
                        if not await interruptible_sleep(job.delay_between):
                            break
            else:
                total = job.total_hits if job.total_hits > 0 else len(keywords)
                self.stats["total"] = total
                while completed < total and not should_stop():
                    wave = min(parallel, total - completed)
                    self.stats["waves"] += 1
                    ok, fail = await self._run_wave(
                        pw, job, keywords, wave_size=wave, start_index=session_index,
                    )
                    session_index += wave
                    completed += wave
                    LOG_BUS.emit(
                        "INFO",
                        0,
                        f"Ilerleme: {completed}/{total} | OK {self.stats['ok']} FAIL {self.stats['fail']}",
                    )
                    if should_stop():
                        break
                    if completed < total and job.delay_between > 0:
                        if not await interruptible_sleep(job.delay_between):
                            break

        if should_stop():
            LOG_BUS.emit(
                "WARNING",
                0,
                f"Durduruldu: {self.stats['ok']} OK / {self.stats['fail']} FAIL "
                f"({self.stats['waves']} dalga)",
            )
        else:
            LOG_BUS.emit(
                "INFO",
                0,
                f"Bitti: {self.stats['ok']} OK / {self.stats['fail']} FAIL "
                f"({self.stats['waves']} dalga)",
            )
        return self.stats
