#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PY="./venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo
  echo "HATA: Kurulum yapılmamış. Önce: ./setup.sh"
  echo
  exit 1
fi

echo "Film Sahnesi açılıyor..."
exec "$PY" gui_app.py
