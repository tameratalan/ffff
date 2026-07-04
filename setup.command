#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "=== Film Sahnesi — Mac Kurulum ==="
echo

PY="${PY:-/opt/homebrew/bin/python3.12}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="$(command -v python3.12 || command -v python3)"
fi

if [[ ! -d venv ]]; then
  echo "Sanal ortam oluşturuluyor..."
  "$PY" -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

if [[ ! -f hesaplar.txt ]]; then
  cat > hesaplar.txt.example <<'EOF'
# Her satır: eposta:sifre
ornek@mail.com:sifreniz
EOF
  echo
  echo "hesaplar.txt yok — hesaplar.txt.example oluşturuldu."
  echo "Kopyalayıp düzenleyin: cp hesaplar.txt.example hesaplar.txt"
fi

echo
echo "Kurulum tamam."
echo
echo "Sonraki adımlar:"
echo "  1. sahne_config.toml dosyasını düzenleyin"
echo "  2. ./sahne_giris.sh   — hesaplara giriş"
echo "  3. ./baslat.sh        — GUI"
echo
