#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PY="./venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "HATA: Önce ./setup.sh çalıştırın."
  exit 1
fi

if [[ ! -f hesaplar.txt ]]; then
  echo "HATA: hesaplar.txt bulunamadı (format: eposta:sifre)"
  exit 1
fi

exec "$PY" sahne_demo.py --login
