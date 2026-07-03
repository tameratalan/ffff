"""
TrendyolHit — Film GUI
Modern arayuz: hesap yukleme, anahtar kelime, moduller, canli log.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit("customtkinter eksik. Calistirin: pip install customtkinter")

from accounts_loader import load_accounts, mask_email
from account_creator import create_accounts, save_hesaplar
from core.async_utils import should_stop
from core.log_bus import LOG_BUS
from core.rank_store import RankSnapshot, load_snapshot, save_snapshot
from core.state import STATE
from hit_engine import HitEngine, HitJob, HitModules
from rank_checker import RankResult, format_rank_report, scan_all_keywords, scan_rank

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#667eea"
BG = "#0f0f1a"
CARD = "#1a1a2e"
TEXT = "#e8e8f0"


class TrendyolHitApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TrendyolHit Pro")
        self.geometry("1320x920")
        self.minsize(1100, 720)
        self.configure(fg_color=BG)

        self.engine = HitEngine()
        self._accounts: list[tuple[str, str]] = []
        self._running = False
        self._worker: threading.Thread | None = None
        self._rank_before: list[RankResult] = []
        self._rank_after: list[RankResult] = []
        self._rank_snapshot: RankSnapshot | None = load_snapshot()

        self._build_ui()
        self._poll_logs()
        if self._rank_snapshot:
            self.after(100, lambda: self._render_rank_dashboard(self._rank_snapshot))

    def _card(self, parent, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=ACCENT
        ).pack(anchor="w", padx=16, pady=(12, 8))
        return frame

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            header,
            text="TrendyolHit Pro",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=TEXT,
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text="Film demo — arama · hit · moduller",
            font=ctk.CTkFont(size=13),
            text_color="#888",
        ).pack(side="left", padx=(12, 0), pady=(8, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(5, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # --- Hesaplar ---
        acc_card = self._card(left, "Hesaplar")
        acc_card.pack(fill="x", pady=(0, 10))

        acc_btns = ctk.CTkFrame(acc_card, fg_color="transparent")
        acc_btns.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(acc_btns, text="Dosya Yukle (.txt)", command=self._load_accounts_file, width=140).pack(side="left", padx=(0, 8))
        ctk.CTkButton(acc_btns, text="Kaydet", command=self._save_accounts_file, width=80).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(acc_btns, text="Adet:").pack(side="left")
        self.ent_create_count = ctk.CTkEntry(acc_btns, width=45)
        self.ent_create_count.insert(0, "2")
        self.ent_create_count.pack(side="left", padx=(6, 8))
        ctk.CTkButton(
            acc_btns, text="Hesap Olustur", width=110,
            command=self._create_accounts,
        ).pack(side="left")
        self.lbl_acc_count = ctk.CTkLabel(acc_btns, text="0 hesap", text_color="#aaa")
        self.lbl_acc_count.pack(side="right")

        self.txt_accounts = ctk.CTkTextbox(acc_card, height=100, font=ctk.CTkFont(family="Consolas", size=12))
        self.txt_accounts.pack(fill="x", padx=16, pady=(0, 8))
        self.txt_accounts.insert("1.0", "# eposta:sifre (satir basina)\n")

        self.sw_guest = ctk.CTkSwitch(
            acc_card,
            text="Misafir modu (hesap gerekmez — sadece hit)",
            command=self._toggle_guest,
        )
        self.sw_guest.select()
        self.sw_guest.pack(anchor="w", padx=16, pady=(0, 12))

        # --- Operasyon ---
        op_card = self._card(left, "Operasyon")
        op_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(op_card, text="Urun linki", anchor="w").pack(fill="x", padx=16)
        self.ent_url = ctk.CTkEntry(op_card, placeholder_text="https://www.trendyol.com/...-p-123456")
        self.ent_url.pack(fill="x", padx=16, pady=(4, 10))

        ctk.CTkLabel(op_card, text="Anahtar kelimeler (satir basina — coklu hit)", anchor="w").pack(fill="x", padx=16)
        self.txt_keywords = ctk.CTkTextbox(op_card, height=100, font=ctk.CTkFont(size=13))
        self.txt_keywords.pack(fill="x", padx=16, pady=(4, 4))
        self.txt_keywords.insert(
            "1.0",
            "retinol krem\nretinol krem dr snail\n",
        )
        ctk.CTkLabel(
            op_card,
            text="Ayni dalgada her tarayici farkli kelime arayabilir (paralel)",
            font=ctk.CTkFont(size=11),
            text_color="#888",
        ).pack(anchor="w", padx=16, pady=(0, 4))
        self.sw_split_kw = ctk.CTkSwitch(
            op_card,
            text="Toplam hit'i kelimelere esit bol (50 hit, 2 kelime = 25+25)",
        )
        self.sw_split_kw.pack(anchor="w", padx=16, pady=(0, 8))

        pages_row = ctk.CTkFrame(op_card, fg_color="transparent")
        pages_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(pages_row, text="Max arama sayfasi:").pack(side="left")
        self.slider_pages = ctk.CTkSlider(pages_row, from_=1, to=500, number_of_steps=499, command=self._pages_changed)
        self.slider_pages.set(50)
        self.slider_pages.pack(side="left", fill="x", expand=True, padx=10)
        self.lbl_pages = ctk.CTkLabel(pages_row, text="50", width=40)
        self.lbl_pages.pack(side="right")

        blast_row = ctk.CTkFrame(op_card, fg_color="transparent")
        blast_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(blast_row, text="Paralel tarayici:").pack(side="left")
        self.slider_parallel = ctk.CTkSlider(
            blast_row, from_=1, to=100, number_of_steps=99, command=self._parallel_changed,
        )
        self.slider_parallel.set(5)
        self.slider_parallel.pack(side="left", fill="x", expand=True, padx=10)
        self.lbl_parallel = ctk.CTkLabel(blast_row, text="5", width=36)
        self.lbl_parallel.pack(side="right")
        ctk.CTkLabel(
            op_card,
            text="Oneri: 8GB RAM → 3-5 | 16GB RAM → 8-12 | 50 hedef icin paralel 5 yeter (10 dalga)",
            font=ctk.CTkFont(size=11),
            text_color="#888",
        ).pack(anchor="w", padx=16, pady=(0, 4))

        hits_row = ctk.CTkFrame(op_card, fg_color="transparent")
        hits_row.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(hits_row, text="Toplam hit:").pack(side="left")
        self.ent_total_hits = ctk.CTkEntry(hits_row, width=80)
        self.ent_total_hits.insert(0, "50")
        self.ent_total_hits.pack(side="left", padx=(8, 12))
        ctk.CTkLabel(
            hits_row,
            text="0 = DURDUR'a kadar sonsuz | sadece linkteki urun",
            text_color="#888",
            font=ctk.CTkFont(size=11),
        ).pack(side="left")

        self.sw_headless = ctk.CTkSwitch(op_card, text="Arka planda (siralama testi icin)")
        self.sw_headless.select()
        self.sw_headless.pack(anchor="w", padx=16, pady=(0, 4))
        ctk.CTkLabel(
            op_card,
            text="Hit artirma her zaman arka planda — pencere acilmaz",
            font=ctk.CTkFont(size=11),
            text_color="#888",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        # --- Siralama kontrolu ---
        rank_row = ctk.CTkFrame(op_card, fg_color="transparent")
        rank_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(
            rank_row, text="Siralama Kontrol (ONCE)", width=160,
            fg_color="#2d6a4f", hover_color="#1b4332",
            command=self._check_rank_before,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            rank_row, text="Tam Test (Once+Hit+Sonra)", width=180,
            fg_color="#e67e22", hover_color="#d35400",
            command=self._full_test,
        ).pack(side="left")

        # --- Mevcut Siralama (sol) ---
        rank_dash = self._card(left, "Mevcut Siralama")
        rank_dash.pack(fill="x", pady=(0, 10))

        rank_head = ctk.CTkFrame(rank_dash, fg_color="transparent")
        rank_head.pack(fill="x", padx=16, pady=(0, 6))
        self.lbl_rank_updated = ctk.CTkLabel(
            rank_head,
            text="Son guncelleme: —",
            font=ctk.CTkFont(size=12),
            text_color="#888",
            anchor="w",
        )
        self.lbl_rank_updated.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            rank_head,
            text="Yenile",
            width=72,
            height=28,
            fg_color="#2d6a4f",
            hover_color="#1b4332",
            command=self._check_rank_before,
        ).pack(side="right")

        self.lbl_rank_product = ctk.CTkLabel(
            rank_dash,
            text="Urun: —",
            font=ctk.CTkFont(size=11),
            text_color="#666",
            anchor="w",
        )
        self.lbl_rank_product.pack(fill="x", padx=16, pady=(0, 8))

        self.rank_rows_frame = ctk.CTkFrame(rank_dash, fg_color="transparent")
        self.rank_rows_frame.pack(fill="x", padx=12, pady=(0, 12))
        self._rank_row_widgets: list[ctk.CTkFrame] = []

        # --- Moduller ---
        mod_card = self._card(right, "Moduller")
        mod_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.chk_hit = self._chk(mod_card, "Hit / Urun gezintisi", True, enabled=True)
        self.chk_fav = self._chk(mod_card, "Favori / Begeni")
        self.chk_cart = self._chk(mod_card, "Sepete ekle")

        ctk.CTkLabel(mod_card, text="Soru sorma", anchor="w").pack(fill="x", padx=16, pady=(8, 0))
        self.ent_question = ctk.CTkEntry(mod_card, placeholder_text="Ornek: Urun orijinal mi?")
        self.ent_question.pack(fill="x", padx=16, pady=(4, 8))

        q_row = ctk.CTkFrame(mod_card, fg_color="transparent")
        q_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(
            q_row, text="SORU SOR", width=120, height=32,
            fg_color="#9b59b6", hover_color="#8e44ad",
            command=self._start_question,
        ).pack(side="left")
        ctk.CTkLabel(
            q_row, text="Hesap gerekli · arama/hit yapmaz",
            text_color="#888", font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(10, 0))

        self.chk_q_with_hit = self._chk(mod_card, "Hit sonrasi soru da sor", False)

        # --- Kontrol ---
        ctrl = ctk.CTkFrame(right, fg_color="transparent")
        ctrl.grid(row=1, column=0, sticky="ew", pady=4)
        self.btn_start = ctk.CTkButton(
            ctrl, text="BASLAT (Hit / Paralel)", height=44, font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT, hover_color="#5568d3", command=self._start,
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_stop = ctk.CTkButton(
            ctrl, text="DURDUR", height=44, width=100,
            fg_color="#c0392b", hover_color="#922b21",
            command=self._stop, state="disabled",
        )
        self.btn_stop.pack(side="left")

        stats = ctk.CTkFrame(right, fg_color=CARD, corner_radius=12)
        stats.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.lbl_stats = ctk.CTkLabel(stats, text="Hazir", font=ctk.CTkFont(size=14))
        self.lbl_stats.pack(padx=16, pady=(12, 8))

        counter_row = ctk.CTkFrame(stats, fg_color="transparent")
        counter_row.pack(fill="x", padx=16, pady=(0, 12))
        counter_row.columnconfigure(0, weight=1)
        counter_row.columnconfigure(1, weight=1)

        ok_box = ctk.CTkFrame(counter_row, fg_color="#1e2d1e", corner_radius=10)
        ok_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(
            ok_box, text="BASARILI HIT", font=ctk.CTkFont(size=11), text_color="#8fbc8f",
        ).pack(pady=(10, 0))
        self.lbl_hit_ok = ctk.CTkLabel(
            ok_box, text="0", font=ctk.CTkFont(size=36, weight="bold"), text_color="#6ee7a0",
        )
        self.lbl_hit_ok.pack(pady=(0, 4))
        self.lbl_hit_goal = ctk.CTkLabel(
            ok_box, text="/ —", font=ctk.CTkFont(size=12), text_color="#888",
        )
        self.lbl_hit_goal.pack(pady=(0, 10))

        fail_box = ctk.CTkFrame(counter_row, fg_color="#2d1e1e", corner_radius=10)
        fail_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(
            fail_box, text="BASARISIZ", font=ctk.CTkFont(size=11), text_color="#c99595",
        ).pack(pady=(10, 0))
        self.lbl_hit_fail = ctk.CTkLabel(
            fail_box, text="0", font=ctk.CTkFont(size=36, weight="bold"), text_color="#f08080",
        )
        self.lbl_hit_fail.pack(pady=(0, 4))
        self.lbl_hit_waves = ctk.CTkLabel(
            fail_box, text="Dalga: 0", font=ctk.CTkFont(size=12), text_color="#888",
        )
        self.lbl_hit_waves.pack(pady=(0, 10))

        self._hit_target: int = 0

        kw_stats_card = ctk.CTkFrame(stats, fg_color="#12121f", corner_radius=8)
        kw_stats_card.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            kw_stats_card,
            text="Kelime bazli hit",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#aaa",
        ).pack(anchor="w", padx=10, pady=(8, 4))
        self.kw_stats_frame = ctk.CTkFrame(kw_stats_card, fg_color="transparent")
        self.kw_stats_frame.pack(fill="x", padx=8, pady=(0, 8))
        self._kw_stat_labels: dict[str, ctk.CTkLabel] = {}
        self.lbl_kw_stats_empty = ctk.CTkLabel(
            self.kw_stats_frame,
            text="Hit baslayinca kelime sayaclari burada",
            font=ctk.CTkFont(size=11),
            text_color="#666",
        )
        self.lbl_kw_stats_empty.pack(anchor="w", padx=4, pady=4)

        rank_card = self._card(right, "Siralama Karsilastirma")
        rank_card.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.txt_rank = ctk.CTkTextbox(
            rank_card, height=72, font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.txt_rank.pack(fill="x", padx=16, pady=(0, 10))
        self.txt_rank.insert("1.0", "Tam Test sonrasi once/sonra farki burada.\n")

        self.progress = ctk.CTkProgressBar(right, mode="indeterminate")
        self.progress.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.progress.set(0)

        log_card = self._card(right, "Canli Log")
        log_card.grid(row=5, column=0, sticky="nsew")
        self.txt_log = ctk.CTkTextbox(
            log_card, font=ctk.CTkFont(family="Consolas", size=12), state="disabled"
        )
        self.txt_log.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    def _clear_rank_rows(self) -> None:
        for w in self._rank_row_widgets:
            w.destroy()
        self._rank_row_widgets.clear()

    def _format_rank_line(self, r: RankResult) -> tuple[str, str, str]:
        """Baslik, deger, renk."""
        if r.found:
            title = f'"{r.keyword}"'
            value = f"Sayfa {r.page}  ·  Sira {r.position_on_page}  ·  ~#{r.estimated_rank}"
            color = "#6ee7a0"
            return title, value, color
        title = f'"{r.keyword}"'
        value = f"BULUNAMADI  ({r.pages_scanned} sayfa, ~{r.estimated_rank} urun)"
        return title, value, "#f08080"

    def _render_rank_dashboard(self, snap: RankSnapshot | None) -> None:
        self._clear_rank_rows()
        if not snap or not snap.results:
            self.lbl_rank_updated.configure(text="Son guncelleme: —")
            self.lbl_rank_product.configure(text="Urun: —  |  Siralama Kontrol veya Yenile")
            empty = ctk.CTkLabel(
                self.rank_rows_frame,
                text="Henuz siralama taramasi yok.\nUrun linki + kelime girip Yenile'ye basin.",
                font=ctk.CTkFont(size=12),
                text_color="#666",
                justify="left",
            )
            empty.pack(fill="x", padx=4, pady=8)
            self._rank_row_widgets.append(empty)
            return

        self.lbl_rank_updated.configure(text=f"Son guncelleme: {snap.display_time}")
        pid = snap.product_id or "?"
        self.lbl_rank_product.configure(
            text=f"Urun: p-{pid}  |  {len(snap.results)} kelime",
        )

        for r in snap.results:
            row = ctk.CTkFrame(self.rank_rows_frame, fg_color="#12121f", corner_radius=8)
            row.pack(fill="x", pady=3, padx=4)
            self._rank_row_widgets.append(row)

            title, value, color = self._format_rank_line(r)
            ctk.CTkLabel(
                row,
                text=title,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(
                row,
                text=value,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=color,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(2, 8))

    def _save_and_show_rank(self, product_url: str, results: list[RankResult]) -> None:
        snap = save_snapshot(product_url, results)
        self._rank_snapshot = snap
        self._render_rank_dashboard(snap)

    def _chk(self, parent, text: str, default: bool = False, enabled: bool = True) -> ctk.CTkCheckBox:
        cb = ctk.CTkCheckBox(parent, text=text)
        if default:
            cb.select()
        if not enabled:
            cb.configure(state="disabled")
        cb.pack(anchor="w", padx=16, pady=4)
        return cb

    def _pages_changed(self, val: float) -> None:
        self.lbl_pages.configure(text=str(int(val)))

    def _parallel_changed(self, val: float) -> None:
        self.lbl_parallel.configure(text=str(int(val)))

    def _parse_total_hits(self) -> int:
        try:
            return max(0, int(self.ent_total_hits.get().strip()))
        except ValueError:
            return 50

    def _toggle_guest(self) -> None:
        guest = self.sw_guest.get()
        state = "disabled" if guest else "normal"
        self.txt_accounts.configure(state=state)

    def _load_accounts_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Hesap listesi",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if not path:
            return
        acc = load_accounts(Path(path))
        self._accounts = acc
        self.txt_accounts.delete("1.0", "end")
        for email, _ in acc:
            self.txt_accounts.insert("end", f"{mask_email(email)}\n")
        self.lbl_acc_count.configure(text=f"{len(acc)} hesap yuklendi")
        self.sw_guest.deselect()

    def _save_accounts_file(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="hesaplar.txt")
        if path:
            Path(path).write_text(self.txt_accounts.get("1.0", "end"), encoding="utf-8")

    def _parse_accounts_from_text(self) -> list[tuple[str, str]]:
        tmp = Path("_tmp_acc.txt")
        tmp.write_text(self.txt_accounts.get("1.0", "end"), encoding="utf-8")
        return load_accounts(tmp)

    def _reload_accounts_ui(self, accs: list[tuple[str, str]]) -> None:
        self._accounts = accs
        self.txt_accounts.configure(state="normal")
        self.txt_accounts.delete("1.0", "end")
        for email, _ in accs:
            self.txt_accounts.insert("end", f"{mask_email(email)}\n")
        self.lbl_acc_count.configure(text=f"{len(accs)} hesap")
        self.sw_guest.deselect()

    def _create_accounts(self) -> None:
        try:
            count = max(1, min(20, int(self.ent_create_count.get())))
        except ValueError:
            count = 2

        def work() -> None:
            LOG_BUS.clear()
            LOG_BUS.emit(
                "INFO",
                0,
                "Trendyol kayit: tempmail.lol + Chrome (captcha elle cozulebilir)",
            )
            accs = asyncio.run(create_accounts(count=count, headless=False))
            path = Path(__file__).parent / "hesaplar.txt"
            if accs and not should_stop():
                save_hesaplar(path, accs)
                all_accs = load_accounts(path)
                LOG_BUS.emit("INFO", 0, f"hesaplar.txt kaydedildi ({len(all_accs)} hesap)")
                self.after(0, lambda: self._reload_accounts_ui(all_accs))

        self._run_async_job(work, f"{count} hesap olusturuldu")

    def _get_product_url(self) -> str | None:
        url = self.ent_url.get().strip()
        if not url:
            messagebox.showwarning("Eksik", "Urun linki girin")
            return None
        return url

    def _get_url_keywords(self) -> tuple[str, list[str]] | None:
        url = self._get_product_url()
        if not url:
            return None
        kws = [
            ln.strip()
            for ln in self.txt_keywords.get("1.0", "end").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        if not kws:
            messagebox.showwarning("Eksik", "En az bir anahtar kelime girin")
            return None
        return url, kws

    def _show_rank_report(
        self,
        before: list[RankResult],
        after: list[RankResult] | None = None,
        *,
        product_url: str = "",
    ) -> None:
        if product_url and after is None:
            self._save_and_show_rank(product_url, before)
        elif product_url and after is not None:
            self._save_and_show_rank(product_url, after)
        lines = [format_rank_report("ONCE", before)]
        if after is not None:
            lines.append("")
            lines.append(format_rank_report("SONRA", after))
            lines.append("")
            lines.append("=== KARSILASTIRMA ===")
            for b, a in zip(before, after):
                if b.found and a.found:
                    diff = b.estimated_rank - a.estimated_rank
                    if diff > 0:
                        lines.append(f'"{b.keyword}": ~{b.estimated_rank} -> ~{a.estimated_rank}  (YUKARI +{diff})')
                    elif diff < 0:
                        lines.append(f'"{b.keyword}": ~{b.estimated_rank} -> ~{a.estimated_rank}  (asagi {diff})')
                    else:
                        lines.append(f'"{b.keyword}": degismedi (~{a.estimated_rank})')
                elif not b.found and a.found:
                    lines.append(f'"{b.keyword}": yok -> Sayfa {a.page} sira {a.position_on_page}')
                elif b.found and not a.found:
                    lines.append(f'"{b.keyword}": Sayfa {b.page} -> kayboldu')
                else:
                    lines.append(f'"{b.keyword}": hala bulunamadi')
        self.txt_rank.delete("1.0", "end")
        self.txt_rank.insert("1.0", "\n".join(lines))

    def _run_async_job(self, coro_fn, on_done_msg: str = "Tamamlandi") -> None:
        if self._running:
            return
        STATE.reset_stop()
        self._running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.start()
        self.lbl_stats.configure(text="Calisiyor...")

        def worker() -> None:
            try:
                coro_fn()
            except Exception as exc:
                LOG_BUS.emit("ERROR", 0, f"Islem hatasi: {exc}")
                err = str(exc)
                self.after(0, lambda e=err: messagebox.showerror("Hata", e))
            finally:
                self.after(0, lambda: self._on_done_custom(on_done_msg))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _on_done_custom(self, msg: str) -> None:
        self._running = False
        self.progress.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if STATE.is_stopped():
            self.lbl_stats.configure(text="DURDURULDU")
        else:
            self.lbl_stats.configure(text=msg)

    def _check_rank_before(self) -> None:
        data = self._get_url_keywords()
        if not data:
            return
        url, kws = data
        headless = bool(self.sw_headless.get())
        max_p = int(self.slider_pages.get())

        def work() -> None:
            LOG_BUS.clear()
            results = asyncio.run(
                scan_all_keywords(url, kws, max_pages=max_p, headless=headless)
            )
            self._rank_before = results
            self.after(0, lambda: self._show_rank_report(results, product_url=url))

        self._run_async_job(work, "Siralama kontrolu tamam")

    def _full_test(self) -> None:
        job = self._build_job()
        if not job:
            return
        url, kws = job.product_url, job.keywords
        max_p = int(self.slider_pages.get())
        headless = bool(self.sw_headless.get())
        job.headless = True
        hit_label = str(job.total_hits) if job.total_hits > 0 else "sonsuz (DURDUR)"

        self.lbl_stats.configure(
            text=f"Tam test basliyor... (max {max_p} sayfa, {hit_label} hit)",
        )
        LOG_BUS.emit(
            "INFO",
            0,
            f"Tam test: siralama max {max_p} sayfa, hit: {hit_label}",
        )

        def work() -> None:
            LOG_BUS.clear()
            LOG_BUS.emit("INFO", 0, "=== ADIM 1: ONCE SIRALAMA ===")
            before = asyncio.run(
                scan_all_keywords(url, kws, max_pages=max_p, headless=headless)
            )
            self._rank_before = before
            self.after(0, lambda: self._show_rank_report(before, product_url=url))

            if should_stop():
                return

            LOG_BUS.emit("INFO", 0, "=== ADIM 2: HIT ARTIRMA (tikla + gez) ===")
            asyncio.run(self.engine.run(job))

            if should_stop():
                self.after(0, lambda: self._show_rank_report(before, product_url=url))
                return

            LOG_BUS.emit("INFO", 0, "=== ADIM 3: SONRA SIRALAMA ===")
            after = asyncio.run(
                scan_all_keywords(url, kws, max_pages=max_p, headless=headless)
            )
            self._rank_after = after
            self.after(0, lambda: self._show_rank_report(before, after, product_url=url))

        self._run_async_job(work, "Tam test bitti — logu kontrol edin")

    def _get_accounts(self) -> list[tuple[str, str]]:
        accounts = self._accounts or self._parse_accounts_from_text()
        if not accounts:
            default_file = Path(__file__).parent / "hesaplar.txt"
            if default_file.exists():
                accounts = load_accounts(default_file)
                if accounts:
                    self._accounts = accounts
        return accounts

    def _build_job(self) -> HitJob | None:
        data = self._get_url_keywords()
        if not data:
            return None
        url, kws = data

        guest = bool(self.sw_guest.get())
        accounts = [] if guest else self._get_accounts()

        if bool(self.chk_q_with_hit.get()) and guest:
            messagebox.showwarning(
                "Hesap gerekli",
                "Hit ile soru sormak icin misafir modunu kapatip hesap yukleyin.",
            )
            return None

        modules = HitModules(
            hit=bool(self.chk_hit.get()),
            favorite=bool(self.chk_fav.get()),
            cart=bool(self.chk_cart.get()),
            question=bool(self.chk_q_with_hit.get()),
            question_text=self.ent_question.get() or "Urun orijinal mi?",
        )

        return HitJob(
            product_url=url,
            keywords=kws,
            max_pages=int(self.slider_pages.get()),
            headless=True,
            guest_mode=guest,
            accounts=accounts,
            modules=modules,
            entry_mode="organic",
            parallel=int(self.slider_parallel.get()),
            total_hits=self._parse_total_hits(),
            delay_between=0.5,
            split_by_keyword=bool(self.sw_split_kw.get()),
        )

    def _build_question_job(self) -> HitJob | None:
        url = self._get_product_url()
        if not url:
            return None
        question = self.ent_question.get().strip()
        if not question:
            messagebox.showwarning("Eksik", "Soru metnini yazin")
            return None
        if self.sw_guest.get():
            messagebox.showwarning(
                "Hesap gerekli",
                "Soru sormak icin misafir modunu kapatip hesap yukleyin.",
            )
            return None
        accounts = self._get_accounts()
        if not accounts:
            messagebox.showwarning("Eksik", "En az bir hesap yukleyin")
            return None

        return HitJob(
            product_url=url,
            keywords=[],
            max_pages=1,
            headless=False,
            guest_mode=False,
            accounts=accounts,
            modules=HitModules(
                hit=False,
                favorite=False,
                cart=False,
                question=True,
                question_text=question,
            ),
            entry_mode="direct",
        )

    def _start_question(self) -> None:
        job = self._build_question_job()
        if not job:
            return
        LOG_BUS.emit(
            "INFO",
            0,
            "reCAPTCHA: setup_buster.bat (ucretsiz) veya Chrome'da elle isaretle",
        )
        self._run_hit_job(job, done_label="Soru gonderildi")

    def _start(self) -> None:
        if self._running:
            return
        job = self._build_job()
        if not job:
            return
        self._run_hit_job(job, done_label=None)

    def _run_hit_job(self, job: HitJob, done_label: str | None) -> None:
        if self._running:
            return

        self._running = True
        STATE.reset_stop()
        self._hit_target = job.total_hits if job.total_hits > 0 else 0
        self._reset_hit_counter()
        kws = [k.strip() for k in job.keywords if k.strip()]
        if kws:
            self.engine.keyword_stats = {k: {"ok": 0, "fail": 0} for k in kws}
            self._render_keyword_stats(self.engine.keyword_stats)
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.start()
        label = "Soru soruluyor..." if job.entry_mode == "direct" else "Calisiyor..."
        self.lbl_stats.configure(text=label)

        def worker() -> None:
            try:
                if job.entry_mode == "direct":
                    LOG_BUS.clear()
                    LOG_BUS.emit("INFO", 0, f'Mod: Soru sor | "{job.modules.question_text[:60]}"')
                    LOG_BUS.emit("INFO", 0, "Soru modu: tarayici penceresi acilir (modal icin)")
                asyncio.run(self.engine.run(job))
            finally:
                self.after(0, lambda: self._on_done(done_label))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _stop(self) -> None:
        if not self._running:
            return
        STATE.request_stop()
        self.engine.stop()
        self.lbl_stats.configure(text="Durduruluyor...")
        LOG_BUS.emit("WARNING", 0, ">>> DURDUR butonuna basildi <<<")

    def _on_done(self, done_label: str | None = None) -> None:
        self._running = False
        self.progress.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if STATE.is_stopped():
            self.lbl_stats.configure(text="DURDURULDU")
            return
        if done_label and self.engine.stats.get("ok", 0) > 0:
            self.lbl_stats.configure(text=done_label)
            return
        s = self.engine.stats
        self.lbl_stats.configure(text=f"Tamamlandi — OK: {s['ok']}  FAIL: {s['fail']}  / {s['total']}")
        self._refresh_hit_counter()

    def _reset_hit_counter(self) -> None:
        self.lbl_hit_ok.configure(text="0")
        self.lbl_hit_fail.configure(text="0")
        self.lbl_hit_waves.configure(text="Dalga: 0")
        if self._hit_target > 0:
            self.lbl_hit_goal.configure(text=f"/ {self._hit_target} hedef")
        else:
            self.lbl_hit_goal.configure(text="/ sonsuz")
        self._render_keyword_stats({})

    def _render_keyword_stats(self, kw_stats: dict[str, dict[str, int]]) -> None:
        for w in self.kw_stats_frame.winfo_children():
            w.destroy()
        self._kw_stat_labels.clear()
        if not kw_stats:
            self.lbl_kw_stats_empty = ctk.CTkLabel(
                self.kw_stats_frame,
                text="Hit baslayinca kelime sayaclari burada",
                font=ctk.CTkFont(size=11),
                text_color="#666",
            )
            self.lbl_kw_stats_empty.pack(anchor="w", padx=4, pady=4)
            return
        for kw, st in kw_stats.items():
            ok = st.get("ok", 0)
            fail = st.get("fail", 0)
            short = kw if len(kw) <= 28 else kw[:25] + "..."
            row = ctk.CTkLabel(
                self.kw_stats_frame,
                text=f'"{short}"  OK {ok}  FAIL {fail}',
                font=ctk.CTkFont(size=11),
                text_color="#6ee7a0" if ok > 0 else "#888",
                anchor="w",
            )
            row.pack(fill="x", padx=4, pady=1)
            self._kw_stat_labels[kw] = row

    def _refresh_hit_counter(self) -> None:
        s = self.engine.stats
        ok = s.get("ok", 0)
        fail = s.get("fail", 0)
        waves = s.get("waves", 0)
        self.lbl_hit_ok.configure(text=str(ok))
        self.lbl_hit_fail.configure(text=str(fail))
        self.lbl_hit_waves.configure(text=f"Dalga: {waves}")
        if self._hit_target > 0:
            self.lbl_hit_goal.configure(text=f"/ {self._hit_target} hedef")
        else:
            self.lbl_hit_goal.configure(text=f"/ sonsuz  (toplam {ok + fail})")
        self._render_keyword_stats(self.engine.keyword_stats)
        if self._running:
            if self._hit_target > 0:
                self.lbl_stats.configure(
                    text=f"Calisiyor... {ok}/{self._hit_target} basarili hit",
                )
            else:
                self.lbl_stats.configure(text=f"Calisiyor... {ok} basarili hit")

    def _poll_logs(self) -> None:
        if self._running:
            self._refresh_hit_counter()
        entries = LOG_BUS.snapshot(80)
        if entries:
            self.txt_log.configure(state="normal")
            self.txt_log.delete("1.0", "end")
            for e in entries:
                color_tag = e.level
                line = f"[{e.ts}] {e.message}\n"
                self.txt_log.insert("end", line)
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        self.after(400, self._poll_logs)


def main() -> None:
    app = TrendyolHitApp()
    app.mainloop()


if __name__ == "__main__":
    main()
