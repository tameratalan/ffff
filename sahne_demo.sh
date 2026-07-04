#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PY="./venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "HATA: Önce ./setup.sh çalıştırın."
  exit 1
fi

echo "Film Sahnesi"
echo "------------"
echo "1 - Giriş (hesaplar.txt)"
echo "2 - Çalıştır (link + kelime sorar)"
echo "3 - Sadece Hesap 1"
echo "4 - Sadece Hesap 2"
echo "0 - Çıkış"
echo
read -r -p "Seçim: " secim

case "$secim" in
  0) exit 0 ;;
  1)
    [[ -f hesaplar.txt ]] || { echo "hesaplar.txt yok"; exit 1; }
    "$PY" sahne_demo.py --login
    ;;
  2)
    read -r -p "Ürün linki veya ID: " url
    read -r -p "Anahtar kelime: " kw
    [[ -n "$url" && -n "$kw" ]] && "$PY" sahne_demo.py --url "$url" --keyword "$kw"
    ;;
  3)
    read -r -p "Ürün linki veya ID: " url
    read -r -p "Anahtar kelime: " kw
    [[ -n "$url" && -n "$kw" ]] && "$PY" sahne_demo.py --only 1 --url "$url" --keyword "$kw"
    ;;
  4)
    read -r -p "Ürün linki veya ID: " url
    read -r -p "Anahtar kelime: " kw
    [[ -n "$url" && -n "$kw" ]] && "$PY" sahne_demo.py --only 2 --url "$url" --keyword "$kw"
    ;;
  *) echo "Geçersiz seçim" ;;
esac
