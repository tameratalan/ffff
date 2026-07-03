"""
TRENDYOL — Film Prop Demo
=========================
Yakın çekim / terminal sahnesi için. Varsayılan: SIMÜLASYON (Trendyol'a bağlanmaz).

Kullanım:
    python ghost_trendyol.py              # Film modu — sahnedeki loglar
    python ghost_trendyol.py --speed 2    # 2x hızlı (çekim için)
    python ghost_trendyol.py --profiles 50 # Daha az profil (kısa sahne)
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

# ── Film renkleri ──────────────────────────────────────────────
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

KEYWORDS = [
    "spor ayakkabı erkek",
    "koşu ayakkabısı",
    "nike erkek ayakkabı",
    "günlük erkek sneaker",
    "hafif koşu ayakkabısı",
]

SEARCH_STYLES = ["aceleci", "kararsiz", "fiyat_avcisi", "inceleyici", "gece_gezen"]


@dataclass
class GhostProfile:
    name: str
    search_style: str
    session_seed: int


@dataclass
class TrendyolStage:
    keyword: str
    target_sku: str = "p-847291"

    def act_one_search(self, ghost: GhostProfile) -> bool:
        log("INFO", ghost.name, f'🔎 "{self.keyword}" arandi')
        human_pause(0.8, 2.0)
        pages = random.randint(1, 4)
        for p in range(1, pages + 1):
            log("INFO", ghost.name, f"📄 Sayfa {p} taranıyor...")
            human_pause(0.5, 1.2)
        found = random.random() > 0.12
        if found:
            log("SUCCESS", ghost.name, "🎯 Hedef ürün bulundu!")
        else:
            log("WARNING", ghost.name, "Ürün bu sayfalarda yok — sonraki oturum.")
        return found

    def act_two_visit(self, ghost: GhostProfile) -> dict:
        log("INFO", ghost.name, "👀 Ürün inceleniyor...")
        human_pause(0.6, 1.5)
        log("INFO", ghost.name, "🖼️ Fotoğraflara bakılıyor...")
        human_pause(0.4, 1.0)

        actions = []
        roll = random.random()
        if roll < 0.35:
            log("SUCCESS", ghost.name, "❤️ favori")
            actions.append("favorite")
        elif roll < 0.55:
            log("SUCCESS", ghost.name, "🛒 sepet")
            actions.append("cart")
        elif roll < 0.60:
            log("SUCCESS", ghost.name, "💬 soru soruldu")
            actions.append("question")
        elif roll < 0.70:
            log("SUCCESS", ghost.name, "👍 yorum faydalı")
            actions.append("review")

        wait = random.uniform(12, 38)
        log("INFO", ghost.name, f"⏳ Doğallık beklemesi ({wait:.0f}sn)...")
        human_pause(0.3, 0.8)
        return {"actions": actions, "weight": ghost.session_seed}

    def act_three_exit(self, ghost: GhostProfile) -> None:
        log("INFO", ghost.name, "↩️ Oturum kapatılıyor...")
        human_pause(0.2, 0.5)
        log("SUCCESS", ghost.name, "✅ OTURUM TAMAMLANDI")


def log(level: str, ghost: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    colors = {
        "INFO": CYAN,
        "SUCCESS": GREEN,
        "WARNING": YELLOW,
        "ERROR": RED,
    }
    c = colors.get(level, RESET)
    print(f"{DIM}[{ts}]{RESET} {DIM}{ghost:12}{RESET} {c}| {message}{RESET}")
    sys.stdout.flush()


def human_pause(lo: float, hi: float, speed: float = 1.0) -> None:
    time.sleep(random.uniform(lo, hi) / speed)


def build_profiles(count: int) -> list[GhostProfile]:
    profiles = []
    for i in range(count):
        profiles.append(
            GhostProfile(
                name=f"ghost_{random.randint(1000, 9999)}",
                search_style=random.choice(SEARCH_STYLES),
                session_seed=random.randint(1, 9999),
            )
        )
    return profiles


def print_banner(target_sku: str, profile_count: int) -> None:
    art = f"""
{BOLD}{GREEN}+----------------------------------------------------------+
|          TRENDYOL - ghost_trendyol.py  [FILM DEMO]        |
|          Perde arkasindaki karakter - Simulasyon modu     |
+----------------------------------------------------------+{RESET}
"""
    print(art)
    print(f"  {DIM}Hedef SKU:{RESET}  {BOLD}{target_sku}{RESET}")
    print(f"  {DIM}Profil:{RESET}     {BOLD}{profile_count:,}{RESET} ghost oturum")
    print(f"  {DIM}Mod:{RESET}        {YELLOW}SIMULASYON - gercek siteye baglanmaz{RESET}")
    print(f"  {DIM}Anahtar:{RESET}     {', '.join(KEYWORDS[:3])}...")
    print()


def print_code_teaser() -> None:
    """Yakın çekim için ekranda kısa kod parçası."""
    snippet = f"""
{GREEN}class TrendyolStage:
    KEYWORD = "spor ayakkabı erkek"
    TARGET_SKU = "p-847291"

    def act_one_search(self, ghost):
        self.browser.type_slowly(self.KEYWORD)
        return self.find_target_in_results(self.TARGET_SKU)

    def act_two_visit(self, ghost):
        self.scroll_gallery()
        self.maybe_add_favorite()
        return HitSignal(weight=ghost.session_seed){RESET}
"""
    print(snippet)
    print(f"{DIM}  # orchestrator başlatılıyor...{RESET}\n")
    time.sleep(1.2)


def maestro(
    profiles: list[GhostProfile],
    target_sku: str,
    speed: float,
    max_sessions: int,
) -> None:
    sessions_done = 0
    hits = 0
    favorites = 0
    carts = 0

    print(f"{BOLD}▶ maestro() — orkestra şefi devrede{RESET}\n")

    while sessions_done < max_sessions:
        ghost = random.choice(profiles)
        keyword = random.choice(KEYWORDS)
        stage = TrendyolStage(keyword=keyword, target_sku=target_sku)

        if stage.act_one_search(ghost):
            hits += 1
            result = stage.act_two_visit(ghost)
            if "favorite" in result["actions"]:
                favorites += 1
            if "cart" in result["actions"]:
                carts += 1
            stage.act_three_exit(ghost)

        sessions_done += 1

        if sessions_done % 7 == 0:
            rank = max(847 - sessions_done * 3, 12)
            print(
                f"\n{DIM}─── metrik ─── "
                f"hit:{hits} fav:{favorites} sepet:{carts} "
                f"tahmini_sıra:~{rank} ───{RESET}\n"
            )

        human_pause(0.4, 1.0, speed)

    print(f"\n{BOLD}{GREEN}══ SAHNE TAMAMLANDI ══{RESET}")
    print(f"  Oturum: {sessions_done} | Hit: {hits} | Favori: {favorites} | Sepet: {carts}")
    print(f"  {DIM}Film demo — gerçek Trendyol etkileşimi yok.{RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trendyol Film Prop Demo")
    parser.add_argument("--sku", default="p-847291", help="Hedef ürün SKU")
    parser.add_argument("--profiles", type=int, default=200, help="Ghost profil sayısı (gösterim)")
    parser.add_argument("--sessions", type=int, default=25, help="Simüle oturum sayısı")
    parser.add_argument("--speed", type=float, default=1.0, help="Hız çarpanı (2 = 2x hızlı çekim)")
    parser.add_argument("--no-code", action="store_true", help="Açılış kod snippet'ini gizle")
    args = parser.parse_args()

    # Windows terminal renk + UTF-8
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    profiles = build_profiles(args.profiles)
    print_banner(args.sku, args.profiles)

    if not args.no_code:
        print_code_teaser()

    try:
        maestro(profiles, args.sku, args.speed, args.sessions)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}⏹ Sahne durduruldu (Ctrl+C){RESET}")


if __name__ == "__main__":
    main()
