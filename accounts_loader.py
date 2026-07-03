"""Hesap dosyasi okuma."""

from __future__ import annotations

from pathlib import Path


def load_accounts(file_path: Path) -> list[tuple[str, str]]:
    if not file_path.exists():
        return []

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


def mask_email(email: str) -> str:
    if "@" not in email:
        return email[:3] + "***"
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}"
