"""TrendyolHit — arama, hit ve modul motoru."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Playwright, async_playwright

from bot.interactions import view_product_page
from bot.login import login_with_token, is_logged_in
from bot.navigation import dismiss_overlays, find_product_organically, goto_home
from bot.stealth import launch_persistent_context
from config import PROFILES_DIR
from core.async_utils import interruptible_sleep, should_stop
from core.log_bus import LOG_BUS
from core.parser import ParsedTarget, parse_target
from core.state import STATE
from rank_checker import resolve_product_ids, scan_rank


@dataclass
class HitJob:
    product_url: str
    keywords: list[str]
    max_pages: int = 50
    headless: bool = True
    guest_mode: bool = True
    accounts: list[tuple[str, str, str | None]] = field(default_factory=list)
    delay_between: float = 1.0
    parallel: int = 10
    total_hits: int = 50  # 0 = DURDUR'a kadar sonsuz dalga
    product_ids: list[str] = field(default_factory=list)
    split_by_keyword: bool = False  # toplam hit'i kelimelere esit bol
    session_timeout: float = 120.0  # tek oturum max saniye
    rank_check_pages: int = 25  # hit oncesi sira taramasi max sayfa


class HitEngine:
    def __init__(self) -> None:
        self.stats: dict[str, int] = {"ok": 0, "fail": 0, "total": 0, "waves": 0}
        self.keyword_stats: dict[str, dict[str, int]] = {}
        self._excluded_keywords: set[str] = set()

    def stop(self) -> None:
        STATE.request_stop()
        LOG_BUS.emit("WARNING", 0, "DURDUR — islem kesiliyor...")

    def reset(self) -> None:
        STATE.reset_stop()
        self.stats = {"ok": 0, "fail": 0, "total": 0, "waves": 0}
        self.keyword_stats = {}
        self._excluded_keywords = set()

    def _active_keywords(self, keywords: list[str]) -> list[str]:
        return [k for k in keywords if k not in self._excluded_keywords]

    async def _filter_ranked_keywords(self, job: HitJob, keywords: list[str]) -> list[str]:
        """Organik hit oncesi: sadece siralamada bulunan kelimeleri birak."""
        ranked: list[str] = []
        check_pages = max(1, min(job.max_pages, job.rank_check_pages))
        LOG_BUS.emit(
            "INFO",
            0,
            f"Siralama on kontrolu ({len(keywords)} kelime, max {check_pages} sayfa)...",
        )
        for kw in keywords:
            if should_stop():
                break
            result = await scan_rank(
                job.product_url,
                kw,
                max_pages=check_pages,
                headless=job.headless,
            )
            if result.found:
                ranked.append(kw)
                LOG_BUS.emit(
                    "SUCCESS",
                    0,
                    f'Hit icin uygun: "{kw}" (sayfa {result.page}, sira ~{result.estimated_rank})',
                )
            else:
                self._excluded_keywords.add(kw)
                LOG_BUS.emit(
                    "WARNING",
                    0,
                    f'Atlandi — siralamada yok: "{kw}" ({result.pages_scanned} sayfa tarandi)',
                )
        return ranked

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
        active = self._active_keywords(keywords)
        if not active:
            return keywords[0] if keywords else ""
        if len(active) == 1:
            return active[0]
        if not job.split_by_keyword or job.total_hits <= 0:
            return active[index % len(active)]
        per_kw = max(1, job.total_hits // len(active))
        extra = job.total_hits % len(active)
        slots: list[str] = []
        for i, kw in enumerate(active):
            n = per_kw + (1 if i < extra else 0)
            slots.extend([kw] * n)
        if index < len(slots):
            return slots[index]
        return active[index % len(active)]

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
        token: str | None = None,
    ) -> bool:
        if should_stop():
            return False

        bot_id = session_index + 1
        target = parse_target(job.product_url, default_keyword=keyword)
        profile = self._profile_name(session_index, job.guest_mode, email)
        prof_path = str((PROFILES_DIR / profile).resolve())
        speed = 2.5 if job.headless else 1.0
        scroll_bursts = 2 if job.headless else 4

        pid = target.product_id or "?"
        LOG_BUS.emit(
            "INFO",
            bot_id,
            f"#{session_index + 1} | hedef -p-{pid} | \"{keyword}\" | "
            f"misafir={job.guest_mode}",
        )

        ctx, _device = await launch_persistent_context(
            pw, prof_path, headless=job.headless, bot_id=bot_id,
            desktop_only=False,
            enable_buster=not job.headless,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            if not job.guest_mode and email:
                if not (token or "").strip():
                    LOG_BUS.emit("ERROR", bot_id, "Token yok — misafir modu kapali ve token gerekli")
                    return False
                if not await login_with_token(page, token, email, bot_id, speed=speed):
                    LOG_BUS.emit("ERROR", bot_id, "Token ile giris basarisiz")
                    return False
                if not await is_logged_in(page):
                    LOG_BUS.emit("ERROR", bot_id, "Oturum acilamadi")
                    return False
            else:
                await goto_home(page, bot_id, speed=speed)

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
                page, bot_id, search_target, max_pages=job.max_pages, speed=speed,
                product_ids=ids,
            )

            if should_stop():
                LOG_BUS.emit("WARNING", bot_id, "Oturum durduruldu")
                return False
            if not found:
                self._excluded_keywords.add(keyword)
                LOG_BUS.emit(
                    "WARNING",
                    bot_id,
                    f'"{keyword}" — hedef -p-{pid} {job.max_pages} sayfada yok; tekrar aranmayacak',
                )
                return False

            await dismiss_overlays(page, bot_id)
            await view_product_page(page, bot_id, speed=speed, scroll_bursts=scroll_bursts)
            await page.wait_for_timeout(3000)

            LOG_BUS.emit("SUCCESS", bot_id, f"Hedef urune hit OK (-p-{pid})")
            return True
        finally:
            try:
                await asyncio.wait_for(ctx.close(), timeout=10.0)
            except asyncio.TimeoutError:
                LOG_BUS.emit("WARNING", bot_id, "Tarayici kapanma zaman asimi")
            except Exception:
                pass
            await asyncio.sleep(0.1)
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
    ) -> tuple[str, str | None, str | None, str | None]:
        kw = self._keyword_for_session(job, keywords, index)
        if job.guest_mode:
            return kw, None, None, None
        acc = job.accounts[index % len(job.accounts)]
        email = acc[0]
        pwd = acc[1] if len(acc) >= 2 else ""
        tok = acc[2] if len(acc) >= 3 else None
        return kw, email, pwd, tok

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
                kw, email, pwd, tok = self._session_credentials(job, idx, keywords)
                bot_id = idx + 1
                try:
                    ok = await asyncio.wait_for(
                        self._run_one(pw, job, kw, idx, email, pwd, tok),
                        timeout=job.session_timeout,
                    )
                except asyncio.TimeoutError:
                    LOG_BUS.emit(
                        "ERROR",
                        bot_id,
                        f'Oturum zaman asimi ({int(job.session_timeout)}sn) — "{kw}" atlandi',
                    )
                    ok = False
                except Exception as exc:
                    LOG_BUS.emit("ERROR", bot_id, f"Oturum hatasi: {exc}")
                    ok = False
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
        if not keywords:
            LOG_BUS.emit("ERROR", 0, "Anahtar kelime bos")
            return self.stats

        target = parse_target(job.product_url, default_keyword=keywords[0] if keywords else "")
        if not target.product_id:
            LOG_BUS.emit(
                "ERROR",
                0,
                "Organik mod: linkte -p-URUNID olmali (sadece o urune hit)",
            )
            return self.stats

        parallel = max(1, min(job.parallel, 100))
        unlimited = job.total_hits <= 0

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

            keywords = await self._filter_ranked_keywords(job, keywords)
            if not keywords:
                LOG_BUS.emit(
                    "ERROR",
                    0,
                    "Hicbir kelimede urun siralamada bulunamadi — hit baslatilmadi",
                )
                return self.stats
            skipped = self._excluded_keywords
            if skipped:
                LOG_BUS.emit(
                    "INFO",
                    0,
                    f"Hit sadece {len(keywords)} kelime icin: {', '.join(f'\"{k}\"' for k in keywords)}",
                )

            self._init_keyword_stats(keywords)

            if unlimited:
                while not should_stop():
                    if not self._active_keywords(keywords):
                        LOG_BUS.emit("WARNING", 0, "Tum kelimeler siralama disi — hit durduruldu")
                        break
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
                    if not self._active_keywords(keywords):
                        LOG_BUS.emit("WARNING", 0, "Tum kelimeler siralama disi — hit durduruldu")
                        break
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
                        f"Dalga {self.stats['waves']} bitti · {completed}/{total} · "
                        f"OK {self.stats['ok']} FAIL {self.stats['fail']}",
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
