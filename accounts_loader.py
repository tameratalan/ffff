"""Hesap dosyasi okuma."""

from __future__ import annotations

from pathlib import Path

_SEPARATORS = (":", ";", "\t", "|")


def _split_line(line: str) -> list[str] | None:
    """Bir hesap satirini ayirici ile en fazla 3 parcaya boler.

    Format: ``email<sep>sifre`` (eski, geriye donuk uyumlu) veya
    ``email<sep>sifre<sep>token`` (yeni, opsiyonel 3. alan). ``maxsplit=2``
    kullanildigi icin token alani icinde ayni ayirici tekrar gecse bile
    (JWT'ler ':' icermez ama garanti olsun diye) token butunlugu bozulmaz.
    """
    for sep in _SEPARATORS:
        if sep in line:
            return [p.strip() for p in line.split(sep, 2)]
    return None


def _is_jwt(value: str) -> bool:
    return value.startswith("eyJ") and value.count(".") >= 2


def load_accounts_full(file_path: Path) -> list[tuple[str, str, str | None]]:
    """(email, sifre, token) uclusu dondurur — token zorunlu.

    Desteklenen satir formatlari:
    - ``email:token``              (sadece token ile giris)
    - ``email:sifre:token``        (sifre dosyada kalir ama giris icin kullanilmaz)
    """
    if not file_path.exists():
        return []

    accounts: list[tuple[str, str, str | None]] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = _split_line(line)
        if not parts or len(parts) < 2:
            continue

        email = parts[0].strip()
        if len(parts) >= 3:
            pwd = parts[1].strip()
            token = parts[2].strip()
        elif _is_jwt(parts[1].strip()):
            pwd = ""
            token = parts[1].strip()
        else:
            continue

        if email and token:
            accounts.append((email, pwd, token))

    return accounts


def load_accounts(file_path: Path) -> list[tuple[str, str]]:
    """Geriye donuk uyumlu: sadece (email, sifre) ikilisi dondurur.

    ``email:sifre:token`` formatindaki satirlarda token alani sessizce
    yoksayilir — bu fonksiyona bagli tum mevcut cagrilar (gui_app.py,
    checker_demo.py, bot/single_action.py vb.) degismeden calismaya devam
    eder. Token'a ihtiyac duyan yeni kod `load_accounts_full` kullanmalidir.
    """
    return [(email, pwd) for email, pwd, _token in load_accounts_full(file_path)]


def mask_email(email: str) -> str:
    if "@" not in email:
        return email[:3] + "***"
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}"
