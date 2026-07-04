"""
Film Sahnesi — kompakt GUI (MacBook / yayin icin)
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

from accounts_loader import load_accounts, load_accounts_full, mask_email
from account_creator import create_accounts, save_hesaplar
from bot.single_action import run_batch_accounts, run_single_action
from core.async_utils import should_stop
from core.log_bus import LOG_BUS
from core.rank_store import RankSnapshot, load_snapshot, save_snapshot
from core.state import STATE
from hit_engine import HitEngine, HitJob
from rank_checker import RankResult, format_rank_report, scan_all_keywords

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Yayinda okunakli, sade palet
ACCENT = "#6366f1"
ACCENT_H = "#4f46e5"
VIOLET = "#8b5cf6"
VIOLET_H = "#7c3aed"
SKY = "#38bdf8"
SKY_H = "#0ea5e9"
BG = "#0c0c10"
CARD = "#17171f"
CARD_HOVER = "#1e1e2a"
INSET = "#0a0a0e"
BORDER = "#2a2a38"
TEXT = "#f1f5f9"
SUBTLE = "#94a3b8"   # ikincil hiyerarsi: kart basliklari, alan etiketleri
MUTED = "#64748b"    # ucuncul/mikro metin: zaman damgasi, bos durum, ipucu
OK = "#34d399"
FAIL = "#f87171"
WARN = "#fbbf24"

# Bosluk ve koseyuvarlaklik olcegi — tum sekmelerde tutarli kullanilir
PAD = 14        # kart ic dolgusu
PAD_SM = 8      # kompakt ic dolgu (etiket-alan arasi)
GAP = 10        # kartlar/blok gruplari arasi dikey bosluk
GAP_SM = 6      # yakin iliskili elemanlar arasi
RADIUS = 12     # kart kose yuvarlakligi
RADIUS_SM = 8   # buton/pill/ic kutu kose yuvarlakligi

# Tipografi olcegi — tum sekmelerde ayni hiyerarsiyi takip eder
SIZE_H1 = 18    # uygulama basligi
SIZE_H2 = 13    # kart / bolum basligi
SIZE_BODY = 12  # govde metni, giris alanlari
SIZE_SUB = 11   # ikincil etiketler
SIZE_MICRO = 10 # rozet, sayac, mikro metin

BTN_H_PRIMARY = 40
BTN_H_SECONDARY = 34

FONT = "SF Pro Text"
FONT_MONO = "Menlo"


class TrendyolHitApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Trendyol Operasyon Paneli")
        self.geometry("1120x680")
        self.minsize(900, 560)
        self.configure(fg_color=BG)
        self.grid_propagate(False)
        # customtkinter'in kendi <Configure> izleyicisi (_update_dimensions_event),
        # sekmeler icindeki yogun icerik (ozellikle Araclar) kurulurken olusan
        # gecici/gercek boyut sicramalarini "_current_width/_height" olarak
        # kaydedip DPI olcekleme tetiklendiginde o (yanlislikla buyumus) boyutu
        # pencereye geri uyguluyor — grid_propagate(False) bunu engellemiyor.
        # Kurulum sirasinda bu izleyiciyi kapatip sonunda gercek boyutu elle
        # geri yaziyoruz.
        self._block_update_dimensions_event = True

        self.engine = HitEngine()
        self._accounts: list[tuple[str, str, str | None]] = []
        self._running = False
        self._tools_running = False
        self._batch_running = False
        self._batch_accounts: list[tuple[str, str, str | None]] = []
        self._worker: threading.Thread | None = None
        self._batch_worker: threading.Thread | None = None
        self._rank_before: list[RankResult] = []
        self._rank_after: list[RankResult] = []
        self._rank_snapshot: RankSnapshot | None = load_snapshot()
        self._hit_target: int = 0
        self._batch_live_counts = {"hit": 0, "favorite": 0, "cart": 0, "store_follow": 0}
        self._batch_seen_events: set[tuple[int, str, str]] = set()
        self._rank_row_widgets: list[ctk.CTkFrame] = []
        self._kw_stat_labels: dict[str, ctk.CTkLabel] = {}

        self._build_ui()

        self.update_idletasks()
        self.geometry("1120x680")
        self.update_idletasks()
        self._current_width = 1120
        self._current_height = 680
        self.minsize(900, 560)
        # Kullanici pencereyi serbestce genisletip daraltabilsin; maxsize
        # ozellikle log panelini buyutmeyi engelledigi icin artik kullanilmiyor.
        self._block_update_dimensions_event = False

        self._poll_logs()
        self.after(100, self._refresh_tool_acc_label)
        self.after(150, self._load_batch_accounts)
        if self._rank_snapshot:
            self.after(100, lambda: self._render_rank_dashboard(self._rank_snapshot))

    def _on_tab_changed(self) -> None:
        """CTkTabview'da (ozellikle yeni Araclar sekmesi) bir sekme ilk kez
        gorunur oldugunda Tk/macOS bazen pencereyi icerigin dogal boyutuna
        gore buyutebiliyor (grid_propagate(False) bunu her zaman engellemiyor).
        Sekme degisiminden hemen sonra gercek boyutu olcup, kilitli/bilinen
        boyuttan (kullanicinin elle ayarladigi son boyut) buyukse geri
        cekiyoruz; kucukse (kullanici kucultmus/yeniden boyutlandirmis) yeni
        degeri kilitli boyut olarak benimsiyoruz."""
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        lw, lh = self._locked_size
        if w > lw or h > lh:
            cur_min = self.winfo_toplevel().wm_minsize()
            cur_max = self.winfo_toplevel().wm_maxsize()
            self.maxsize(lw, lh)
            self.minsize(lw, lh)
            self.geometry(f"{lw}x{lh}")
            self.update_idletasks()
            self._current_width = lw
            self._current_height = lh
            self.minsize(*cur_min)
            self.maxsize(*cur_max)
        else:
            self._locked_size = (w, h)

    def _card(self, parent, title: str | None = None) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=RADIUS, border_width=1, border_color=BORDER)
        if title:
            ctk.CTkLabel(
                frame,
                text=title.upper(),
                font=ctk.CTkFont(family=FONT, size=SIZE_H2, weight="bold"),
                text_color=SUBTLE,
            ).pack(anchor="w", padx=PAD, pady=(10, 6))
            ctk.CTkFrame(frame, fg_color=BORDER, height=1, corner_radius=0).pack(
                fill="x", padx=PAD, pady=(0, 6)
            )
        return frame

    def _field_label(self, parent, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE)

    def _secondary_btn(self, parent, text: str, command, *, width: int | None = None, height: int = BTN_H_SECONDARY) -> ctk.CTkButton:
        kwargs = dict(
            text=text, height=height, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold"),
            fg_color=BORDER, hover_color="#343446", text_color=TEXT,
            command=command,
        )
        if width is not None:
            kwargs["width"] = width
        return ctk.CTkButton(parent, **kwargs)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- ust bar ---
        top = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=56)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top,
            text="Trendyol Operasyon Paneli",
            font=ctk.CTkFont(family=FONT, size=SIZE_H1, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, padx=(16, 10), pady=10, sticky="w")

        self.lbl_stats = ctk.CTkLabel(
            top,
            text="Hazir",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY),
            text_color=SUBTLE,
        )
        self.lbl_stats.grid(row=0, column=1, padx=8, pady=10, sticky="w")

        stat_pill = ctk.CTkFrame(top, fg_color=BORDER, corner_radius=RADIUS_SM + 6)
        stat_pill.grid(row=0, column=2, padx=(14, 8), pady=8, sticky="e")
        self.lbl_hit_ok = ctk.CTkLabel(
            stat_pill, text="0", font=ctk.CTkFont(size=14, weight="bold"), text_color=OK,
        )
        self.lbl_hit_ok.pack(side="left", padx=(12, 2), pady=4)
        ctk.CTkLabel(stat_pill, text="OK", font=ctk.CTkFont(size=SIZE_MICRO), text_color=MUTED).pack(side="left", padx=(0, 8), pady=4)
        self.lbl_hit_fail = ctk.CTkLabel(
            stat_pill, text="0", font=ctk.CTkFont(size=14, weight="bold"), text_color=FAIL,
        )
        self.lbl_hit_fail.pack(side="left", padx=(0, 2), pady=4)
        ctk.CTkLabel(stat_pill, text="FAIL", font=ctk.CTkFont(size=SIZE_MICRO), text_color=MUTED).pack(side="left", padx=(0, 12), pady=4)
        self.lbl_hit_goal = ctk.CTkLabel(top, text="/ 50", font=ctk.CTkFont(size=SIZE_SUB), text_color=MUTED)
        self.lbl_hit_goal.grid(row=0, column=3, padx=(0, 16), pady=10, sticky="e")
        self.lbl_hit_waves = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=0))
        self.lbl_hit_waves.grid_remove()

        # --- tek sayfa operasyon alani ---
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew", padx=14, pady=(10, 10))
        main.grid_columnconfigure(0, weight=3, minsize=560)
        main.grid_columnconfigure(1, weight=2, minsize=340)
        main.grid_rowconfigure(2, weight=1)
        self._locked_size = (1120, 680)

        self._build_corporate_panel(main)

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate", height=4, corner_radius=2, progress_color=ACCENT)
        self.progress.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.progress.set(0)

        self.geometry("1120x680")

    def _build_corporate_panel(self, parent) -> None:
        target = self._card(parent, "Hedefler")
        target.grid(row=0, column=0, sticky="ew", padx=(0, GAP), pady=(0, GAP))
        target_inner = ctk.CTkFrame(target, fg_color="transparent")
        target_inner.pack(fill="x", padx=PAD, pady=(0, PAD_SM))

        self._field_label(target_inner, "Urun linki").pack(anchor="w")
        self.ent_tool_url = ctk.CTkEntry(
            target_inner, height=34, corner_radius=RADIUS_SM,
            placeholder_text="https://www.trendyol.com/...-p-123456",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY),
        )
        self.ent_tool_url.pack(fill="x", pady=(4, GAP_SM))

        self._field_label(target_inner, "Magaza linki").pack(anchor="w")
        self.ent_store_url = ctk.CTkEntry(
            target_inner, height=34, corner_radius=RADIUS_SM,
            placeholder_text="https://www.trendyol.com/magaza/phantaso-m-1262129",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY),
        )
        self.ent_store_url.pack(fill="x", pady=(4, 0))

        accounts = self._card(parent, "Hesap Kaynagi")
        accounts.grid(row=1, column=0, sticky="ew", padx=(0, GAP), pady=(0, GAP))
        acc_inner = ctk.CTkFrame(accounts, fg_color="transparent")
        acc_inner.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD_SM))
        acc_row = ctk.CTkFrame(acc_inner, fg_color="transparent")
        acc_row.pack(fill="x", pady=(0, GAP_SM))
        self._secondary_btn(acc_row, "Hesaplari Yukle", self._load_accounts_file, width=128, height=32).pack(side="left", padx=(0, GAP_SM))
        self._secondary_btn(acc_row, "Kaydet", self._save_accounts_file, width=70, height=32).pack(side="left")
        self.lbl_acc_count = ctk.CTkLabel(acc_row, text="0 hesap", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=MUTED)
        self.lbl_acc_count.pack(side="right")
        self.lbl_batch_count = ctk.CTkLabel(
            acc_inner, text="Hesap listesi bekleniyor", font=ctk.CTkFont(family=FONT, size=SIZE_MICRO), text_color=MUTED,
        )
        self.lbl_batch_count.pack(anchor="w", pady=(0, GAP_SM))
        self.txt_accounts = ctk.CTkTextbox(
            acc_inner, height=74, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), fg_color=INSET,
        )
        self.txt_accounts.pack(fill="both", expand=True)
        self.txt_accounts.insert("1.0", "# email:sifre:token veya email:token\n")
        self.lbl_tool_acc = ctk.CTkLabel(
            acc_inner, text="Hesap: —", font=ctk.CTkFont(family=FONT, size=SIZE_MICRO), text_color=MUTED,
        )
        self.lbl_tool_acc.pack(anchor="w", pady=(4, 0))

        ops = self._card(parent, "Operasyon")
        ops.grid(row=2, column=0, sticky="new", padx=(0, GAP), pady=(0, GAP))
        inner = ctk.CTkFrame(ops, fg_color="transparent")
        inner.pack(fill="x", padx=PAD, pady=(0, PAD_SM))

        action_row = ctk.CTkFrame(inner, fg_color="transparent")
        action_row.pack(fill="x", pady=(0, GAP_SM))
        self._field_label(action_row, "Aksiyonlar").pack(side="left", padx=(0, GAP_SM))
        self.chk_batch_hit = ctk.CTkCheckBox(
            action_row, text="Hit", width=64,
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold"),
            text_color=ACCENT, fg_color=ACCENT, hover_color=ACCENT_H,
        )
        self.chk_batch_hit.select()
        self.chk_batch_hit.pack(side="left", padx=(0, 10))
        self.chk_batch_favorite = self._chk_inline(action_row, "Favori")
        self.chk_batch_cart = self._chk_inline(action_row, "Sepet")
        self.chk_batch_store_follow = self._chk_inline(action_row, "Magaza Takip")
        self.chk_batch_question = ctk.CTkCheckBox(
            action_row, text="Soru Sor", font=ctk.CTkFont(size=12), width=88,
            command=self._toggle_batch_question,
        )
        self.chk_batch_question.pack(side="left")

        self.ent_batch_question = ctk.CTkEntry(
            inner, height=30, corner_radius=RADIUS_SM,
            placeholder_text="Soru metni (Soru Sor secildiginde)",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY), state="disabled",
        )
        self.ent_batch_question.pack(fill="x", pady=(0, GAP_SM))

        control_row = ctk.CTkFrame(inner, fg_color="transparent")
        control_row.pack(fill="x", pady=(0, GAP_SM))
        ctk.CTkLabel(control_row, text="Paralel:", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE).pack(side="left")
        self.ent_batch_parallel = ctk.CTkEntry(control_row, width=42, height=34, corner_radius=RADIUS_SM)
        self.ent_batch_parallel.insert(0, "10")
        self.ent_batch_parallel.pack(side="left", padx=(6, 12))
        ctk.CTkLabel(control_row, text="Limit:", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE).pack(side="left")
        self.ent_batch_limit = ctk.CTkEntry(control_row, width=54, height=34, corner_radius=RADIUS_SM)
        self.ent_batch_limit.insert(0, "500")
        self.ent_batch_limit.pack(side="left", padx=(6, 12))
        self.chk_batch_turbo = ctk.CTkCheckBox(control_row, text="Turbo", font=ctk.CTkFont(size=12), width=72)
        self.chk_batch_turbo.select()
        self.chk_batch_turbo.pack(side="left", padx=(0, 12))
        self.sw_headless = ctk.CTkSwitch(
            control_row, text="Arka plan", font=ctk.CTkFont(family=FONT, size=SIZE_BODY), progress_color=ACCENT,
        )
        self.sw_headless.select()
        self.sw_headless.pack(side="left", padx=(0, 12))
        self.btn_batch_start = ctk.CTkButton(
            control_row, text="BASLAT", height=BTN_H_PRIMARY, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_H, command=self._start_batch_action,
        )
        self.btn_batch_start.pack(side="left", fill="x", expand=True, padx=(0, GAP_SM))
        self.btn_batch_stop = ctk.CTkButton(
            control_row, text="DUR", width=76, height=BTN_H_PRIMARY, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold"),
            fg_color="#7f1d1d", hover_color="#991b1b",
            command=self._stop_batch_action, state="disabled",
        )
        self.btn_batch_stop.pack(side="left")

        count_row = ctk.CTkFrame(inner, fg_color=INSET, corner_radius=RADIUS_SM)
        count_row.pack(fill="x", pady=(0, GAP_SM))
        self.lbl_batch_counter_hit = ctk.CTkLabel(count_row, text="Hit: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE)
        self.lbl_batch_counter_hit.pack(side="left", padx=(10, 8), pady=6)
        self.lbl_batch_counter_fav = ctk.CTkLabel(count_row, text="Favori: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE)
        self.lbl_batch_counter_fav.pack(side="left", padx=8, pady=6)
        self.lbl_batch_counter_cart = ctk.CTkLabel(count_row, text="Sepet: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE)
        self.lbl_batch_counter_cart.pack(side="left", padx=8, pady=6)
        self.lbl_batch_counter_store = ctk.CTkLabel(count_row, text="Magaza: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE)
        self.lbl_batch_counter_store.pack(side="left", padx=8, pady=6)

        self.lbl_batch_status = ctk.CTkLabel(
            inner, text="Hazir", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE, anchor="w",
        )
        self.lbl_batch_status.pack(fill="x")

        log_card = self._card(parent, "Canli Log")
        log_card.grid(row=0, column=1, rowspan=3, sticky="nsew")
        self.txt_log_tools = ctk.CTkTextbox(
            log_card, font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), state="disabled",
            corner_radius=RADIUS_SM, fg_color=INSET, border_width=0,
        )
        self.txt_log_tools.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD_SM))
        # Eski metodlar ayni log alanini kullanmaya devam etsin.
        self.txt_log = self.txt_log_tools
        self.txt_log_acc = self.txt_log_tools
        self.lbl_tools_status = self.lbl_batch_status
        self.sw_guest = ctk.CTkSwitch(parent, text="")
        self.sw_guest.deselect()
        self.sw_split_kw = ctk.CTkSwitch(parent, text="")
        self.ent_question = self.ent_batch_question

    def _build_hit_tab(self, parent) -> None:
        form = self._card(parent)
        form.grid(row=0, column=0, sticky="ew", pady=(0, GAP))

        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="x", padx=PAD, pady=(10, PAD_SM))

        self._field_label(inner, "Urun linki").pack(anchor="w")
        self.ent_url = ctk.CTkEntry(
            inner, height=32, corner_radius=RADIUS_SM, placeholder_text="trendyol.com/...-p-123456",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY),
        )
        self.ent_url.pack(fill="x", pady=(4, GAP_SM))

        self._field_label(inner, "Anahtar kelimeler").pack(anchor="w")
        self.txt_keywords = ctk.CTkTextbox(inner, height=52, corner_radius=RADIUS_SM, font=ctk.CTkFont(family=FONT, size=SIZE_BODY))
        self.txt_keywords.pack(fill="x", pady=(4, GAP_SM))
        self.txt_keywords.insert("1.0", "retinol krem\nretinol krem dr snail\n")

        sliders = ctk.CTkFrame(inner, fg_color="transparent")
        sliders.pack(fill="x", pady=(2, 2))
        for col in range(3):
            sliders.grid_columnconfigure(col, weight=1)

        for col, (label, attr_slider, attr_lbl, default, steps, to_) in enumerate([
            ("Sayfa", "slider_pages", "lbl_pages", 50, 499, 500),
            ("Paralel", "slider_parallel", "lbl_parallel", 5, 99, 100),
        ]):
            box = ctk.CTkFrame(sliders, fg_color="transparent")
            box.grid(row=0, column=col, sticky="ew", padx=(0, 14 if col < 2 else 0))
            ctk.CTkLabel(box, text=label, font=ctk.CTkFont(family=FONT, size=SIZE_MICRO), text_color=MUTED).pack(anchor="w")
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x")
            cb = self._parallel_changed if label == "Paralel" else self._pages_changed
            slider = ctk.CTkSlider(row, from_=1, to=to_, number_of_steps=steps, height=14, progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_H, command=cb)
            slider.set(default)
            slider.pack(side="left", fill="x", expand=True, padx=(0, 8))
            lbl = ctk.CTkLabel(row, text=str(default), width=28, font=ctk.CTkFont(family=FONT, size=SIZE_SUB))
            lbl.pack(side="right")
            setattr(self, attr_slider, slider)
            setattr(self, attr_lbl, lbl)

        hit_box = ctk.CTkFrame(sliders, fg_color="transparent")
        hit_box.grid(row=0, column=2, sticky="ew")
        ctk.CTkLabel(hit_box, text="Hit", font=ctk.CTkFont(family=FONT, size=SIZE_MICRO), text_color=MUTED).pack(anchor="w")
        self.ent_total_hits = ctk.CTkEntry(hit_box, height=28, width=60, corner_radius=RADIUS_SM, font=ctk.CTkFont(family=FONT, size=SIZE_BODY))
        self.ent_total_hits.insert(0, "50")
        self.ent_total_hits.pack(anchor="w")

        # --- aksiyon satiri: ikincil (Sira tara/Tam test) solda, birincil (BASLAT/DUR) sagda ---
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=(0, GAP_SM))
        actions.grid_columnconfigure(2, weight=1)

        self._secondary_btn(actions, "Sira tara", self._check_rank_before, width=92).grid(row=0, column=0, padx=(0, GAP_SM))
        self._secondary_btn(actions, "Tam test", self._full_test, width=92).grid(row=0, column=1, padx=(0, 14))

        self.btn_start = ctk.CTkButton(
            actions, text="BASLAT", height=BTN_H_PRIMARY, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_H, command=self._start,
        )
        self.btn_start.grid(row=0, column=2, sticky="ew", padx=(0, GAP_SM))
        self.btn_stop = ctk.CTkButton(
            actions, text="DUR", width=68, height=BTN_H_PRIMARY, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold"),
            fg_color="#7f1d1d", hover_color="#991b1b",
            command=self._stop, state="disabled",
        )
        self.btn_stop.grid(row=0, column=3)

        # kelime bazli sayac — buton ve log arasinda ince bir durum seridi
        self.kw_stats_frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=RADIUS_SM, border_width=1, border_color=BORDER)
        self.kw_stats_frame.grid(row=2, column=0, sticky="ew", pady=(0, GAP))
        self.lbl_kw_stats_empty = ctk.CTkLabel(
            self.kw_stats_frame,
            text="Kelime bazli sayac hit ile dolacak",
            font=ctk.CTkFont(family=FONT, size=SIZE_MICRO),
            text_color=MUTED,
        )
        self.lbl_kw_stats_empty.pack(anchor="w", padx=PAD_SM, pady=6)

        # --- log ---
        log_card = self._card(parent, "Canli log")
        log_card.grid(row=4, column=0, sticky="nsew")
        self.txt_log = ctk.CTkTextbox(
            log_card, font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), state="disabled",
            corner_radius=RADIUS_SM, fg_color=INSET, border_width=0,
        )
        self.txt_log.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD_SM))

    def _build_rank_tab(self, parent) -> None:
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, GAP_SM))
        head.grid_columnconfigure(0, weight=1)

        self.lbl_rank_updated = ctk.CTkLabel(
            head, text="Son tarama: —", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=MUTED, anchor="w",
        )
        self.lbl_rank_updated.grid(row=0, column=0, sticky="w")
        self._secondary_btn(head, "Yenile", self._check_rank_before, width=76).grid(row=0, column=1)

        self.lbl_rank_product = ctk.CTkLabel(
            parent, text="Urun: —", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE, anchor="w",
        )
        self.lbl_rank_product.grid(row=1, column=0, sticky="ew", pady=(0, GAP))

        dash = self._card(parent, "Kelime sonuclari")
        dash.grid(row=2, column=0, sticky="nsew", pady=(0, GAP))
        dash.grid_rowconfigure(1, weight=1)
        self.rank_rows_frame = ctk.CTkScrollableFrame(dash, fg_color="transparent", height=160)
        self.rank_rows_frame.pack(fill="both", expand=True, padx=PAD_SM, pady=(0, PAD_SM))

        cmp_card = self._card(parent, "Once / sonra")
        cmp_card.grid(row=3, column=0, sticky="ew")
        self.txt_rank = ctk.CTkTextbox(
            cmp_card, height=56, corner_radius=RADIUS_SM, font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB),
            fg_color=INSET,
        )
        self.txt_rank.pack(fill="x", padx=PAD, pady=(0, PAD_SM))
        self.txt_rank.insert("1.0", "Tam test sonrasi karsilastirma burada.\n")

    def _build_account_tab(self, parent) -> None:
        acc = self._card(parent, "Hesaplar")
        acc.pack(fill="x", pady=(0, GAP))

        row = ctk.CTkFrame(acc, fg_color="transparent")
        row.pack(fill="x", padx=PAD, pady=(0, GAP_SM))
        self._secondary_btn(row, "Yukle", self._load_accounts_file, width=72, height=32).pack(side="left", padx=(0, GAP_SM))
        self._secondary_btn(row, "Kaydet", self._save_accounts_file, width=72, height=32).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(row, text="Olustur:", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE).pack(side="left")
        self.ent_create_count = ctk.CTkEntry(row, width=36, height=32, corner_radius=RADIUS_SM)
        self.ent_create_count.insert(0, "2")
        self.ent_create_count.pack(side="left", padx=6)
        ctk.CTkLabel(row, text="Paralel:", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE).pack(side="left", padx=(8, 0))
        self.ent_create_parallel = ctk.CTkEntry(row, width=36, height=32, corner_radius=RADIUS_SM)
        self.ent_create_parallel.insert(0, "1")
        self.ent_create_parallel.pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="Hesap ac", width=84, height=32, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_H, command=self._create_accounts,
        ).pack(side="left", padx=(8, 8))
        self.lbl_acc_count = ctk.CTkLabel(row, text="0 hesap", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=MUTED)
        self.lbl_acc_count.pack(side="right")

        self.txt_accounts = ctk.CTkTextbox(
            acc, height=72, corner_radius=RADIUS_SM, font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), fg_color=INSET,
        )
        self.txt_accounts.pack(fill="x", padx=PAD, pady=(0, GAP_SM))
        self.txt_accounts.insert("1.0", "# eposta:sifre\n")

        self.sw_guest = ctk.CTkSwitch(
            acc, text="Misafir modu (hesapsiz hit)",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY), progress_color=ACCENT,
            command=self._toggle_guest,
        )
        self.sw_guest.select()
        self.sw_guest.pack(anchor="w", padx=PAD, pady=(0, PAD_SM))

        adv = self._card(parent, "Gelismis")
        adv.pack(fill="x", pady=(0, GAP))

        self.sw_split_kw = ctk.CTkSwitch(
            adv,
            text="Hit'i kelimelere esit bol",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY), progress_color=ACCENT,
        )
        self.sw_split_kw.pack(anchor="w", padx=PAD, pady=(6, GAP_SM))

        self.sw_headless = ctk.CTkSwitch(
            adv, text="Arka planda calis (headless — Chrome gorunmez)",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY), progress_color=ACCENT,
        )
        self.sw_headless.select()
        self.sw_headless.pack(anchor="w", padx=PAD, pady=(0, 10))

        log_card = self._card(parent, "Canli log")
        log_card.pack(fill="both", expand=True, pady=(0, GAP))
        self.txt_log_acc = ctk.CTkTextbox(
            log_card, font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), state="disabled",
            corner_radius=RADIUS_SM, fg_color=INSET, border_width=0,
        )
        self.txt_log_acc.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD_SM))

    def _build_tools_tab(self, parent) -> None:
        # Tekil aksiyon + Toplu Hesap Aksiyonu + log birlikte 580px yuksekligi asabildigi
        # icin sekme icerigi kaydirilabilir bir cerceveye sarilir — pencere boyutu sabit
        # kalir, kart dili/aralik degerleri (PAD/GAP/RADIUS) degismeden korunur.
        # height sabitlenmezse CTkScrollableFrame icerigin dogal boyutunu
        # yukari dogru istekte bulunup pencereyi buyutebiliyor; sabit bir
        # deger vererek tab alani icinde kaydirma ile sinirli tutuyoruz.
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent", height=420)
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        # CTkScrollableFrame.grid_propagate() kutuphanede parametresiz cagriliyor
        # (kwargs iletilmiyor), bu yuzden dogrudan ic frame'e erisip kapatiyoruz —
        # aksi halde ic icerik disariya tasip pencereyi buyutebiliyor.
        scroll._parent_frame.grid_propagate(False)
        parent.grid_propagate(False)
        parent = scroll

        form = self._card(parent, "Tekil aksiyon")
        form.pack(fill="x", pady=(0, GAP))

        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="x", padx=PAD, pady=(0, PAD_SM))

        self._field_label(inner, "Urun linki").pack(anchor="w")
        self.ent_tool_url = ctk.CTkEntry(
            inner, height=32, corner_radius=RADIUS_SM, placeholder_text="trendyol.com/...-p-123456",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY),
        )
        self.ent_tool_url.pack(fill="x", pady=(4, GAP_SM))

        self._field_label(inner, "Soru metni").pack(anchor="w")
        self.ent_question = ctk.CTkEntry(inner, height=30, corner_radius=RADIUS_SM, placeholder_text="Urun orijinal mi?", font=ctk.CTkFont(family=FONT, size=SIZE_BODY))
        self.ent_question.pack(fill="x", pady=(4, GAP_SM))

        self.lbl_tool_acc = ctk.CTkLabel(
            inner, text="Hesap: — (Hesap sekmesinden yukleyin)",
            font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=MUTED,
        )
        self.lbl_tool_acc.pack(anchor="w", pady=(0, GAP_SM))

        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x", pady=(4, 0))
        btn_font = ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold")
        ctk.CTkButton(
            actions, text="Soru Sor", height=BTN_H_SECONDARY + 2, corner_radius=RADIUS_SM, font=btn_font,
            fg_color=VIOLET, hover_color=VIOLET_H,
            command=lambda: self._start_tool_action("question"),
        ).pack(side="left", padx=(0, GAP_SM), fill="x", expand=True)
        ctk.CTkButton(
            actions, text="Favorile", height=BTN_H_SECONDARY + 2, corner_radius=RADIUS_SM, font=btn_font,
            fg_color=ACCENT, hover_color=ACCENT_H,
            command=lambda: self._start_tool_action("favorite"),
        ).pack(side="left", padx=(0, GAP_SM), fill="x", expand=True)
        ctk.CTkButton(
            actions, text="Sepete Ekle", height=BTN_H_SECONDARY + 2, corner_radius=RADIUS_SM, font=btn_font,
            fg_color=SKY, hover_color=SKY_H, text_color="#08131a",
            command=lambda: self._start_tool_action("cart"),
        ).pack(side="left", fill="x", expand=True)

        self.lbl_tools_status = ctk.CTkLabel(
            parent, text="Hazir", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE, anchor="w",
        )
        self.lbl_tools_status.pack(fill="x", pady=(0, GAP_SM))

        self._build_batch_panel(parent)

        log_card = self._card(parent, "Canli log")
        log_card.pack(fill="both", expand=True, pady=(0, GAP))
        self.txt_log_tools = ctk.CTkTextbox(
            log_card, height=160, font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), state="disabled",
            corner_radius=RADIUS_SM, fg_color=INSET, border_width=0,
        )
        self.txt_log_tools.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD_SM))

    def _build_batch_panel(self, parent) -> None:
        batch = self._card(parent, "Toplu Hesap Aksiyonu")
        batch.pack(fill="x", pady=(0, GAP))

        inner = ctk.CTkFrame(batch, fg_color="transparent")
        inner.pack(fill="x", padx=PAD, pady=(0, PAD_SM))

        # --- hesap kaynagi ---
        acc_row = ctk.CTkFrame(inner, fg_color="transparent")
        acc_row.pack(fill="x", pady=(0, GAP_SM))
        self._secondary_btn(
            acc_row, "Hesaplari Yukle", lambda: self._load_batch_accounts(from_button=True), width=134, height=32,
        ).pack(side="left", padx=(0, GAP_SM))
        self.lbl_batch_count = ctk.CTkLabel(
            acc_row, text="Yukleniyor...", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=MUTED,
        )
        self.lbl_batch_count.pack(side="left")
        ctk.CTkLabel(
            acc_row, text="Urun linki: yukaridaki alan kullanilir",
            font=ctk.CTkFont(family=FONT, size=SIZE_MICRO), text_color=MUTED,
        ).pack(side="right")

        # --- aksiyon secimi ---
        chk_row = ctk.CTkFrame(inner, fg_color="transparent")
        chk_row.pack(fill="x", pady=(0, GAP_SM))
        self._field_label(chk_row, "Aksiyonlar:").pack(side="left", padx=(0, GAP_SM))
        self.chk_batch_hit = ctk.CTkCheckBox(
            chk_row, text="Hit", width=64,
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold"),
            text_color=ACCENT, fg_color=ACCENT, hover_color=ACCENT_H,
        )
        self.chk_batch_hit.select()
        self.chk_batch_hit.pack(side="left", padx=(0, 10))
        self.chk_batch_favorite = self._chk_inline(chk_row, "Favori")
        self.chk_batch_cart = self._chk_inline(chk_row, "Sepet")
        self.chk_batch_question = ctk.CTkCheckBox(
            chk_row, text="Soru Sor", font=ctk.CTkFont(size=12), width=90,
            command=self._toggle_batch_question,
        )
        self.chk_batch_question.pack(side="left")
        self.chk_batch_store_follow = self._chk_inline(chk_row, "Magaza Takip")

        self.ent_batch_question = ctk.CTkEntry(
            inner, height=30, corner_radius=RADIUS_SM, placeholder_text="Soru metni (Soru Sor secildiginde)",
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY), state="disabled",
        )
        self.ent_batch_question.pack(fill="x", pady=(0, GAP_SM))

        # --- paralel + baslat/dur ---
        ctrl_row = ctk.CTkFrame(inner, fg_color="transparent")
        ctrl_row.pack(fill="x", pady=(0, GAP_SM))
        ctk.CTkLabel(
            ctrl_row, text="Paralel:", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE,
        ).pack(side="left")
        self.ent_batch_parallel = ctk.CTkEntry(ctrl_row, width=36, height=32, corner_radius=RADIUS_SM)
        self.ent_batch_parallel.insert(0, "10")
        self.ent_batch_parallel.pack(side="left", padx=(6, 12))
        self.chk_batch_turbo = ctk.CTkCheckBox(
            ctrl_row, text="Turbo (yayin)", font=ctk.CTkFont(size=12), width=110,
        )
        self.chk_batch_turbo.select()
        self.chk_batch_turbo.pack(side="left", padx=(0, 12))

        self.btn_batch_start = ctk.CTkButton(
            ctrl_row, text="BASLAT", height=BTN_H_PRIMARY, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_H, command=self._start_batch_action,
        )
        self.btn_batch_start.pack(side="left", fill="x", expand=True, padx=(0, GAP_SM))
        self.btn_batch_stop = ctk.CTkButton(
            ctrl_row, text="DUR", width=68, height=BTN_H_PRIMARY, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=FONT, size=SIZE_BODY, weight="bold"),
            fg_color="#7f1d1d", hover_color="#991b1b",
            command=self._stop_batch_action, state="disabled",
        )
        self.btn_batch_stop.pack(side="left")

        count_row = ctk.CTkFrame(inner, fg_color=INSET, corner_radius=RADIUS_SM)
        count_row.pack(fill="x", pady=(0, GAP_SM))
        self.lbl_batch_counter_hit = ctk.CTkLabel(
            count_row, text="Hit: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE,
        )
        self.lbl_batch_counter_hit.pack(side="left", padx=(10, 8), pady=5)
        self.lbl_batch_counter_fav = ctk.CTkLabel(
            count_row, text="Favori: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE,
        )
        self.lbl_batch_counter_fav.pack(side="left", padx=8, pady=5)
        self.lbl_batch_counter_cart = ctk.CTkLabel(
            count_row, text="Sepet: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE,
        )
        self.lbl_batch_counter_cart.pack(side="left", padx=8, pady=5)
        self.lbl_batch_counter_store = ctk.CTkLabel(
            count_row, text="Magaza: 0", font=ctk.CTkFont(family=FONT_MONO, size=SIZE_SUB), text_color=SUBTLE,
        )
        self.lbl_batch_counter_store.pack(side="left", padx=8, pady=5)

        self.lbl_batch_status = ctk.CTkLabel(
            inner, text="Hazir", font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=SUBTLE, anchor="w",
        )
        self.lbl_batch_status.pack(fill="x", pady=(2, 0))

    def _chk_inline(self, parent, text: str, default: bool = False) -> ctk.CTkCheckBox:
        cb = ctk.CTkCheckBox(parent, text=text, font=ctk.CTkFont(size=12), width=90)
        if default:
            cb.select()
        cb.pack(side="left", padx=(0, 10))
        return cb

    def _clear_rank_rows(self) -> None:
        for w in self._rank_row_widgets:
            w.destroy()
        self._rank_row_widgets.clear()

    def _format_rank_line(self, r: RankResult) -> tuple[str, str, str]:
        if r.found:
            title = f'"{r.keyword}"'
            value = f"Sayfa {r.page} · sira {r.position_on_page} · ~#{r.estimated_rank}"
            return title, value, OK
        title = f'"{r.keyword}"'
        value = f"Listede yok ({r.pages_scanned} sayfa)"
        return title, value, FAIL

    def _render_rank_dashboard(self, snap: RankSnapshot | None) -> None:
        self._clear_rank_rows()
        if not snap or not snap.results:
            self.lbl_rank_updated.configure(text="Son tarama: —")
            self.lbl_rank_product.configure(text="Urun: — · Sira tara ile guncelle")
            empty = ctk.CTkLabel(
                self.rank_rows_frame,
                text="Henuz tarama yok. \"Sira tara\" ile baslatin.",
                font=ctk.CTkFont(family=FONT, size=SIZE_SUB),
                text_color=MUTED,
            )
            empty.pack(fill="x", padx=PAD_SM, pady=16)
            self._rank_row_widgets.append(empty)
            return

        self.lbl_rank_updated.configure(text=f"Son tarama: {snap.display_time}")
        pid = snap.product_id or "?"
        self.lbl_rank_product.configure(text=f"p-{pid} · {len(snap.results)} kelime")

        for r in snap.results:
            row = ctk.CTkFrame(self.rank_rows_frame, fg_color=INSET, corner_radius=RADIUS_SM)
            row.pack(fill="x", pady=3, padx=2)
            self._rank_row_widgets.append(row)

            title, value, color = self._format_rank_line(r)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=PAD_SM + 2, pady=8)
            ctk.CTkLabel(
                inner, text=title, font=ctk.CTkFont(family=FONT, size=SIZE_SUB), text_color=TEXT, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                inner, text=value, font=ctk.CTkFont(family=FONT, size=SIZE_SUB, weight="bold"), text_color=color, anchor="e",
            ).pack(side="right")

    def _save_and_show_rank(self, product_url: str, results: list[RankResult]) -> None:
        snap = save_snapshot(product_url, results)
        self._rank_snapshot = snap
        self._render_rank_dashboard(snap)

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
        self.txt_accounts.configure(state="disabled" if guest else "normal")

    def _load_accounts_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Hesap listesi",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if not path:
            return
        acc = load_accounts_full(Path(path))
        if not acc:
            messagebox.showwarning("Uyari", "Dosyada token'li hesap bulunamadi.\nFormat: email:sifre:token veya email:token")
            return
        self._reload_accounts_ui(acc)

    def _save_accounts_file(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="hesaplar.txt")
        if path:
            Path(path).write_text(self.txt_accounts.get("1.0", "end"), encoding="utf-8")

    def _parse_accounts_from_text(self) -> list[tuple[str, str, str | None]]:
        tmp = Path("_tmp_acc.txt")
        tmp.write_text(self.txt_accounts.get("1.0", "end"), encoding="utf-8")
        try:
            return load_accounts_full(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def _reload_accounts_ui(self, accs: list[tuple[str, str, str | None]]) -> None:
        self._accounts = accs
        self.txt_accounts.configure(state="normal")
        self.txt_accounts.delete("1.0", "end")
        for email, _pwd, _tok in accs:
            self.txt_accounts.insert("end", f"{mask_email(email)}\n")
        token_n = sum(1 for _e, _p, t in accs if t)
        extra = f" ({token_n} tokenli)" if token_n else ""
        self.lbl_acc_count.configure(text=f"{len(accs)} hesap{extra}")
        self.sw_guest.deselect()
        self._refresh_tool_acc_label()
        self._batch_accounts = accs
        if accs:
            self.lbl_batch_count.configure(text=f"{len(accs)} hesap yuklendi{extra}", text_color=OK)

    def _create_accounts(self) -> None:
        try:
            count = max(1, min(20, int(self.ent_create_count.get())))
        except ValueError:
            count = 2

        try:
            parallel = max(1, min(4, int(self.ent_create_parallel.get())))
        except ValueError:
            parallel = 1

        headless = bool(self.sw_headless.get())

        def work() -> None:
            LOG_BUS.clear()
            mode = "arka planda (headless)" if headless else "Chrome acilarak"
            LOG_BUS.emit("INFO", 0, f"Hesap olusturma basladi ({mode})")
            path = Path(__file__).parent / "hesaplar.txt"
            # save_path sayesinde her hesap basarili olur olmaz aninda
            # hesaplar.txt'ye yaziliyor — batch bitmeden kesinti/crash olsa
            # bile o ana kadar acilan hesaplar kaybolmuyor. Asagidaki
            # save_hesaplar cagrisi artik sadece bir guvenlik agi: zaten
            # kaydedilmis hesaplari tekrar yazmak zararsiz (merge/idempotent).
            accs = asyncio.run(
                create_accounts(count=count, headless=headless, parallel=parallel, save_path=path)
            )
            if accs:
                save_hesaplar(path, accs)
            all_accs = load_accounts_full(path)
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
                        lines.append(f'"{b.keyword}": ~{b.estimated_rank} -> ~{a.estimated_rank}  (+{diff})')
                    elif diff < 0:
                        lines.append(f'"{b.keyword}": ~{b.estimated_rank} -> ~{a.estimated_rank}  ({diff})')
                    else:
                        lines.append(f'"{b.keyword}": ayni (~{a.estimated_rank})')
                elif not b.found and a.found:
                    lines.append(f'"{b.keyword}": yok -> Sayfa {a.page} sira {a.position_on_page}')
                elif b.found and not a.found:
                    lines.append(f'"{b.keyword}": kayboldu')
                else:
                    lines.append(f'"{b.keyword}": hala yok')
        self.txt_rank.delete("1.0", "end")
        self.txt_rank.insert("1.0", "\n".join(lines))

    def _run_async_job(self, coro_fn, on_done_msg: str = "Tamamlandi") -> None:
        if self._running or self._batch_running:
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
            self.lbl_stats.configure(text="Durduruldu")
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

        self._run_async_job(work, "Siralama tamam")

    def _full_test(self) -> None:
        job = self._build_job()
        if not job:
            return
        url, kws = job.product_url, job.keywords
        max_p = int(self.slider_pages.get())
        headless = bool(self.sw_headless.get())
        job.headless = True
        hit_label = str(job.total_hits) if job.total_hits > 0 else "sonsuz"

        self.lbl_stats.configure(text=f"Tam test · {hit_label} hit")
        LOG_BUS.emit("INFO", 0, f"Tam test: max {max_p} sayfa, {hit_label} hit")

        def work() -> None:
            LOG_BUS.clear()
            LOG_BUS.emit("INFO", 0, "=== 1/3 ONCE SIRALAMA ===")
            before = asyncio.run(
                scan_all_keywords(url, kws, max_pages=max_p, headless=headless)
            )
            self._rank_before = before
            self.after(0, lambda: self._show_rank_report(before, product_url=url))

            if should_stop():
                return

            LOG_BUS.emit("INFO", 0, "=== 2/3 HIT ===")
            asyncio.run(self.engine.run(job))

            if should_stop():
                self.after(0, lambda: self._show_rank_report(before, product_url=url))
                return

            LOG_BUS.emit("INFO", 0, "=== 3/3 SONRA SIRALAMA ===")
            after = asyncio.run(
                scan_all_keywords(url, kws, max_pages=max_p, headless=headless)
            )
            self._rank_after = after
            self.after(0, lambda: self._show_rank_report(before, after, product_url=url))

        self._run_async_job(work, "Tam test bitti")

    def _get_accounts_full(self) -> list[tuple[str, str, str | None]]:
        accounts = self._accounts or self._parse_accounts_from_text()
        if not accounts:
            default_file = Path(__file__).parent / "hesaplar.txt"
            if default_file.exists():
                accounts = load_accounts_full(default_file)
                if accounts:
                    self._accounts = accounts
        return accounts

    def _get_accounts(self) -> list[tuple[str, str, str | None]]:
        return self._get_accounts_full()

    def _build_job(self) -> HitJob | None:
        data = self._get_url_keywords()
        if not data:
            return None
        url, kws = data

        guest = bool(self.sw_guest.get())
        accounts = [] if guest else self._get_accounts()
        if not guest and accounts and not any(t for _e, _p, t in accounts):
            messagebox.showwarning(
                "Token gerekli",
                "Hesaplarda token yok.\nFormat: email:sifre:token veya email:token\n\nMisafir modu acik degilse hit calismaz.",
            )
            return None

        return HitJob(
            product_url=url,
            keywords=kws,
            max_pages=int(self.slider_pages.get()),
            headless=True,
            guest_mode=guest,
            accounts=accounts,
            parallel=int(self.slider_parallel.get()),
            total_hits=self._parse_total_hits(),
            delay_between=0.5,
            split_by_keyword=bool(self.sw_split_kw.get()),
        )

    def _start(self) -> None:
        if self._running:
            return
        job = self._build_job()
        if not job:
            return
        self._run_hit_job(job)

    def _run_hit_job(self, job: HitJob) -> None:
        if self._running or self._batch_running:
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
        self.lbl_stats.configure(text="Hit calisiyor...")

        def worker() -> None:
            try:
                asyncio.run(self.engine.run(job))
            finally:
                self.after(0, self._on_done)

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _stop(self) -> None:
        if not self._running:
            return
        STATE.request_stop()
        self.engine.stop()
        self.lbl_stats.configure(text="Durduruluyor...")
        LOG_BUS.emit("WARNING", 0, ">>> DUR <<<")

    def _on_done(self) -> None:
        self._running = False
        self.progress.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if STATE.is_stopped():
            self.lbl_stats.configure(text="Durduruldu")
            return
        s = self.engine.stats
        self.lbl_stats.configure(text=f"Bitti · {s['ok']} OK / {s['fail']} FAIL")
        self._refresh_hit_counter()

    def _reset_hit_counter(self) -> None:
        self.lbl_hit_ok.configure(text="0")
        self.lbl_hit_fail.configure(text="0")
        if self._hit_target > 0:
            self.lbl_hit_goal.configure(text=f"/ {self._hit_target}")
        else:
            self.lbl_hit_goal.configure(text="/ ∞")
        self._render_keyword_stats({})

    def _render_keyword_stats(self, kw_stats: dict[str, dict[str, int]]) -> None:
        for w in self.kw_stats_frame.winfo_children():
            w.destroy()
        self._kw_stat_labels.clear()
        if not kw_stats:
            self.lbl_kw_stats_empty = ctk.CTkLabel(
                self.kw_stats_frame,
                text="Kelime bazli sayac hit ile dolacak",
                font=ctk.CTkFont(family=FONT, size=SIZE_MICRO),
                text_color=MUTED,
            )
            self.lbl_kw_stats_empty.pack(anchor="w", padx=PAD_SM, pady=6)
            return
        parts: list[str] = []
        for kw, st in kw_stats.items():
            ok = st.get("ok", 0)
            fail = st.get("fail", 0)
            short = kw if len(kw) <= 22 else kw[:19] + "..."
            parts.append(f"{short} {ok}/{fail}")
        ctk.CTkLabel(
            self.kw_stats_frame,
            text="  ·  ".join(parts),
            font=ctk.CTkFont(family=FONT, size=SIZE_MICRO),
            text_color=SUBTLE,
            anchor="w",
        ).pack(fill="x", padx=PAD_SM, pady=6)

    def _refresh_hit_counter(self) -> None:
        s = self.engine.stats
        ok = s.get("ok", 0)
        fail = s.get("fail", 0)
        self.lbl_hit_ok.configure(text=str(ok))
        self.lbl_hit_fail.configure(text=str(fail))
        if self._hit_target > 0:
            self.lbl_hit_goal.configure(text=f"/ {self._hit_target}")
        else:
            self.lbl_hit_goal.configure(text=f"/ ∞ ({ok + fail})")
        self._render_keyword_stats(self.engine.keyword_stats)
        if self._running:
            if self._hit_target > 0:
                self.lbl_stats.configure(text=f"Hit · {ok}/{self._hit_target}")
            else:
                self.lbl_stats.configure(text=f"Hit · {ok} OK")

    def _refresh_tool_acc_label(self) -> None:
        accounts = self._get_accounts()
        if accounts:
            self.lbl_tool_acc.configure(text=f"Hesap: {mask_email(accounts[0][0])} (ilk hesap kullanilir)")
        else:
            self.lbl_tool_acc.configure(text="Hesap: — (Hesap sekmesinden yukleyin)")

    def _start_tool_action(self, action: str) -> None:
        if self._running or self._tools_running or self._batch_running:
            messagebox.showwarning("Mesgul", "Baska bir islem calisiyor, bekleyin.")
            return

        url = self.ent_tool_url.get().strip()
        if not url:
            messagebox.showwarning("Eksik", "Urun linki girin")
            return

        question_text = self.ent_question.get().strip() or "Urun orijinal mi?"
        if action == "question" and not self.ent_question.get().strip():
            messagebox.showwarning("Eksik", "Soru metnini yazin")
            return

        accounts = self._get_accounts()
        if not accounts:
            messagebox.showwarning("Eksik", "En az bir hesap yukleyin (Hesap sekmesi)")
            return
        email, password, token = accounts[0]
        if not token:
            messagebox.showwarning("Eksik", "Token gerekli — email:sifre:token formatinda hesap yukleyin")
            return
        headless = bool(self.sw_headless.get())

        label = {"question": "Soru gonderiliyor...", "favorite": "Favoriye ekleniyor...", "cart": "Sepete ekleniyor..."}[action]

        self._tools_running = True
        STATE.reset_stop()
        self.lbl_tools_status.configure(text=label)
        LOG_BUS.clear()
        LOG_BUS.emit("INFO", 0, f"{label} — {mask_email(email)} — {'headless' if headless else 'gorunur'}")

        def worker() -> None:
            try:
                ok = asyncio.run(
                    run_single_action(
                        url, email, password, action,
                        question_text=question_text,
                        headless=headless,
                        token=token,
                    )
                )
            except Exception as exc:
                LOG_BUS.emit("ERROR", 0, f"Islem hatasi: {exc}")
                ok = False
            finally:
                self.after(0, lambda: self._on_tool_done(action, ok))

        threading.Thread(target=worker, daemon=True).start()

    def _on_tool_done(self, action: str, ok: bool) -> None:
        self._tools_running = False
        labels_ok = {"question": "Soru gonderildi", "favorite": "Favoriye eklendi", "cart": "Sepete eklendi"}
        labels_fail = {"question": "Soru basarisiz", "favorite": "Favorileme basarisiz", "cart": "Sepete ekleme basarisiz"}
        self.lbl_tools_status.configure(text=labels_ok[action] if ok else labels_fail[action])

    def _toggle_batch_question(self) -> None:
        enabled = bool(self.chk_batch_question.get())
        self.ent_batch_question.configure(state="normal" if enabled else "disabled")

    def _load_batch_accounts(self, *, from_button: bool = False) -> None:
        if from_button:
            path_str = filedialog.askopenfilename(
                title="Hesap listesi",
                filetypes=[("Text", "*.txt"), ("All", "*.*")],
            )
            if not path_str:
                return
            path = Path(path_str)
        else:
            path = Path(__file__).parent / "hesaplar.txt"
        accs = load_accounts_full(path)
        self._batch_accounts = accs
        if accs:
            token_count = sum(1 for _e, _p, tok in accs if tok)
            extra = f" ({token_count} tokenli)" if token_count else ""
            self.lbl_batch_count.configure(text=f"{len(accs)} hesap yuklendi{extra}", text_color=OK)
        else:
            self.lbl_batch_count.configure(text="Dosya bos veya hesap bulunamadi", text_color=MUTED)

    def _get_batch_actions(self) -> list[str]:
        actions: list[str] = []
        if self.chk_batch_hit.get():
            actions.append("hit")
        if self.chk_batch_favorite.get():
            actions.append("favorite")
        if self.chk_batch_cart.get():
            actions.append("cart")
        if self.chk_batch_question.get():
            actions.append("question")
        if self.chk_batch_store_follow.get():
            actions.append("store_follow")
        return actions

    def _reset_batch_counters(self) -> None:
        self._batch_live_counts = {"hit": 0, "favorite": 0, "cart": 0, "store_follow": 0}
        self._batch_seen_events = set()
        for lbl, text in (
            (self.lbl_batch_counter_hit, "Hit: 0"),
            (self.lbl_batch_counter_fav, "Favori: 0"),
            (self.lbl_batch_counter_cart, "Sepet: 0"),
            (self.lbl_batch_counter_store, "Magaza: 0"),
        ):
            lbl.configure(text=text, text_color=SUBTLE)

    def _refresh_batch_counters(self, results: list[dict] | None = None) -> None:
        if results is not None:
            counts = {
                "hit": sum(1 for r in results if r.get("results", {}).get("hit")),
                "favorite": sum(1 for r in results if r.get("results", {}).get("favorite")),
                "cart": sum(1 for r in results if r.get("results", {}).get("cart")),
                "store_follow": sum(1 for r in results if r.get("results", {}).get("store_follow")),
            }
            self._batch_live_counts = counts
        else:
            entries = LOG_BUS.snapshot(500)
            markers = {
                "hit": "Hit tamamlandi",
                "favorite": "Favoriye eklendi",
                "cart": "Sepete eklendi",
                "store_follow": "Magaza takip edildi",
            }
            for e in entries:
                for action, marker in markers.items():
                    if marker not in e.message:
                        continue
                    event_key = (e.bot_id, e.ts, e.message)
                    if event_key in self._batch_seen_events:
                        continue
                    self._batch_seen_events.add(event_key)
                    self._batch_live_counts[action] += 1
            counts = dict(self._batch_live_counts)

        self.lbl_batch_counter_hit.configure(text=f"Hit: {counts['hit']}", text_color=OK if counts["hit"] else SUBTLE)
        self.lbl_batch_counter_fav.configure(text=f"Favori: {counts['favorite']}", text_color=OK if counts["favorite"] else SUBTLE)
        self.lbl_batch_counter_cart.configure(text=f"Sepet: {counts['cart']}", text_color=OK if counts["cart"] else SUBTLE)
        self.lbl_batch_counter_store.configure(text=f"Magaza: {counts['store_follow']}", text_color=OK if counts["store_follow"] else SUBTLE)

    def _start_batch_action(self) -> None:
        if self._running or self._tools_running or self._batch_running:
            messagebox.showwarning("Mesgul", "Baska bir islem calisiyor, bekleyin.")
            return

        actions = self._get_batch_actions()
        if not actions:
            messagebox.showwarning("Eksik", "En az bir aksiyon secin (Hit/Favori/Sepet/Soru/Magaza Takip)")
            return

        product_actions = [a for a in actions if a != "store_follow"]
        store_actions = [a for a in actions if a == "store_follow"]
        product_url = self.ent_tool_url.get().strip()
        store_url = self.ent_store_url.get().strip()
        if product_actions and not product_url:
            messagebox.showwarning("Eksik", "Hit/Favori/Sepet/Soru icin Urun linki girin")
            return
        if store_actions and not store_url:
            messagebox.showwarning("Eksik", "Magaza Takip icin Magaza linki girin")
            return

        question_text = self.ent_batch_question.get().strip()
        if "question" in actions and not question_text:
            messagebox.showwarning("Eksik", "Soru metnini yazin")
            return

        if not self._batch_accounts:
            self._load_batch_accounts()
        token_accounts = [(e, p, t) for e, p, t in self._batch_accounts if t]
        if not token_accounts:
            messagebox.showwarning("Eksik", "Token'li hesap bulunamadi.\nFormat: email:sifre:token veya email:token")
            return

        try:
            parallel = max(1, min(30, int(self.ent_batch_parallel.get())))
        except ValueError:
            parallel = 10

        try:
            batch_limit = max(1, min(5000, int(self.ent_batch_limit.get())))
        except ValueError:
            batch_limit = 500

        turbo = bool(self.chk_batch_turbo.get())

        headless = bool(self.sw_headless.get())
        accounts_payload = list(token_accounts)
        total = min(batch_limit, len(accounts_payload))

        self._batch_running = True
        STATE.reset_stop()
        self.btn_batch_start.configure(state="disabled")
        self.btn_batch_stop.configure(state="normal")
        self.lbl_batch_status.configure(text=f"Calisiyor... 0/{total} hesap", text_color=SUBTLE)
        self._reset_batch_counters()
        LOG_BUS.clear()
        LOG_BUS.emit(
            "INFO", 0,
            f"Toplu hesap aksiyonu basladi: limit {batch_limit}, {parallel} paralel"
            + (", TURBO" if turbo else "")
            + f", aksiyonlar: {', '.join(actions)}",
        )

        def work() -> None:
            try:
                run_url = product_url if product_actions else store_url
                results = asyncio.run(
                    run_batch_accounts(
                        run_url, accounts_payload, actions,
                        store_url=store_url,
                        question_text=question_text, headless=headless,
                        speed=1.0, parallel=parallel, turbo=turbo,
                        batch_limit=batch_limit,
                    )
                )
            except Exception as exc:
                LOG_BUS.emit("ERROR", 0, f"Toplu islem hatasi: {exc}")
                results = []
            finally:
                self.after(0, lambda: self._on_batch_done(results, actions, total))

        self._batch_worker = threading.Thread(target=work, daemon=True)
        self._batch_worker.start()

    def _stop_batch_action(self) -> None:
        if not self._batch_running:
            return
        STATE.request_stop()
        self.lbl_batch_status.configure(text="Durduruluyor...")
        LOG_BUS.emit("WARNING", 0, ">>> DUR <<<")

    def _on_batch_done(self, results: list[dict], actions: list[str], total: int) -> None:
        self._batch_running = False
        self.btn_batch_start.configure(state="normal")
        self.btn_batch_stop.configure(state="disabled")
        if STATE.is_stopped():
            self._refresh_batch_counters(results)
            self.lbl_batch_status.configure(text=f"Durduruldu ({len(results)}/{total} hesap islendi)", text_color=WARN)
            return

        labels = {
            "hit": "Hit",
            "favorite": "Favori",
            "cart": "Sepet",
            "question": "Soru",
            "store_follow": "Magaza",
        }
        per_action_ok = {a: 0 for a in actions}
        for r in results:
            for a, ok in r.get("results", {}).items():
                if ok and a in per_action_ok:
                    per_action_ok[a] += 1

        self._refresh_batch_counters(results)
        parts = [f"{labels.get(a, a)}: {per_action_ok[a]}/{total} basarili" for a in actions]
        summary = f"{len(results)}/{total} hesap tamamlandi, " + ", ".join(parts)
        self.lbl_batch_status.configure(text=summary, text_color=OK)
        LOG_BUS.emit("SUCCESS", 0, summary)

    def _poll_logs(self) -> None:
        if self._running:
            self._refresh_hit_counter()
        if self._batch_running:
            self._refresh_batch_counters()
        entries = LOG_BUS.snapshot(60)
        if entries:
            text = "\n".join(f"[{e.ts}] {e.message}" for e in entries) + "\n"
            for widget in (self.txt_log, self.txt_log_acc, self.txt_log_tools):
                widget.configure(state="normal")
                widget.delete("1.0", "end")
                widget.insert("end", text)
                widget.see("end")
                widget.configure(state="disabled")
        self.after(400, self._poll_logs)


def main() -> None:
    app = TrendyolHitApp()
    app.mainloop()


if __name__ == "__main__":
    main()
