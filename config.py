from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Chromium Windows'ta Türkçe karakter / boşluk içeren yollarda kilit dosyası oluşturamaz.
# Profiller ASCII güvenli AppData altında tutulur.
_LEGACY_PROFILES_DIR = BASE_DIR / "user_profiles"
PROFILES_DIR = Path(
    os.environ.get(
        "TRENDYOL_HIT_PROFILES",
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TrendyolHit" / "user_profiles",
    )
).resolve()
PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_profiles() -> None:
    """Eski proje klasöründeki profilleri AppData'ya taşı (bir kez)."""
    if not _LEGACY_PROFILES_DIR.exists():
        return
    for legacy in _LEGACY_PROFILES_DIR.iterdir():
        if not legacy.is_dir() or legacy.name.startswith("."):
            continue
        target = PROFILES_DIR / legacy.name
        if target.exists():
            continue
        try:
            shutil.copytree(legacy, target)
        except OSError:
            pass


_migrate_legacy_profiles()
TRENDYOL_HOME = "https://www.trendyol.com"

# reCAPTCHA otomatik cozum — https://2captcha.com API key
def _load_captcha_key() -> str:
    env = (
        os.environ.get("CAPTCHA_2CAPTCHA_KEY", "").strip()
        or os.environ.get("CAPTCHA_API_KEY", "").strip()
    )
    if env:
        return env
    key_file = BASE_DIR / "captcha_key.txt"
    if key_file.exists():
        line = key_file.read_text(encoding="utf-8").strip().splitlines()
        for ln in line:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                return ln
    return ""


CAPTCHA_API_KEY = _load_captcha_key()


# reCAPTCHA otomatik cozum — https://capsolver.com API key (2captcha'dan daha hizli)
def _load_capsolver_key() -> str:
    env = (
        os.environ.get("CAPSOLVER_API_KEY", "").strip()
        or os.environ.get("CAPTCHA_CAPSOLVER_KEY", "").strip()
    )
    if env:
        return env
    key_file = BASE_DIR / "capsolver_key.txt"
    if key_file.exists():
        for ln in key_file.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                return ln
    return ""


CAPSOLVER_API_KEY = _load_capsolver_key()

# "capsolver" | "2captcha" | "auto" (bos = auto): auto/bos ise CAPSOLVER_API_KEY
# doluysa CapSolver birincil servis olarak secilir (2captcha'dan daha hizli).
CAPTCHA_SERVICE = os.environ.get("CAPTCHA_SERVICE", "auto").strip().lower()


def _load_tempmail_key() -> str:
    env = os.environ.get("TEMPMAIL_API_KEY", "").strip()
    if env:
        return env
    key_file = BASE_DIR / "tempmail_key.txt"
    if key_file.exists():
        for ln in key_file.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                return ln
    return ""


TEMPMAIL_API_KEY = _load_tempmail_key()

# Buster — ucretsiz reCAPTCHA extension (setup_buster.bat ile kurulur)
BUSTER_EXTENSION_DIR = Path(
    os.environ.get(
        "BUSTER_EXTENSION_DIR",
        str(BASE_DIR / "extensions" / "buster"),
    )
).resolve()

# Gercek Chrome kullan (captcha / bot tespiti daha az)
USE_CHROME_CHANNEL = os.environ.get("USE_CHROME_CHANNEL", "1").strip() not in ("0", "false", "no")

# Popüler mobil cihaz havuzu
DEVICE_POOL = [
    {
        "name": "iPhone 14 Pro",
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "viewport": {"width": 393, "height": 852},
        "platform": "iPhone",
        "is_mobile": True,
    },
    {
        "name": "Samsung S23 Ultra",
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
        ),
        "viewport": {"width": 412, "height": 915},
        "platform": "Linux armv81",
        "is_mobile": True,
    },
    {
        "name": "Pixel 7 Pro",
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 14; Pixel 7 Pro) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
        ),
        "viewport": {"width": 412, "height": 892},
        "platform": "Linux armv81",
        "is_mobile": True,
    },
    {
        "name": "Desktop Chrome",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1920, "height": 1080},
        "platform": "Win32",
        "is_mobile": False,
    },
]

BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-infobars",
]


@dataclass
class FeatureFlags:
    favorite: bool = True
    cart: bool = True
    collection: bool = False
    store_browse: bool = True
    review_like: bool = True
    coupon: bool = False
    qa_browse: bool = False
    photo_gallery: bool = True
    store_follow: bool = False


@dataclass
class OperationConfig:
    mode: str = "sniper"  # sniper | bulk
    targets: list[str] = field(default_factory=list)
    search_keyword: str = ""
    category_url: str = ""
    profile: str = "profile_1"
    bot_slots: int = 1
    speed_multiplier: float = 1.0
    headless: bool = False
    login_strategy: str = "hybrid"  # guest | member | hybrid
    proxy: str = ""
    features: FeatureFlags = field(default_factory=FeatureFlags)
    max_search_pages: int = 5
