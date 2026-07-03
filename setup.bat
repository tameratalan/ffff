@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo === TrendyolHit Kurulum ===
echo.

if not exist "venv\Scripts\python.exe" (
    echo Sanal ortam olusturuluyor...
    python -m venv venv
)

call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

echo.
echo Opsiyonel — ucretsiz reCAPTCHA icin:
echo   setup_buster.bat
echo.
echo Kurulum tamam.
echo.
echo Sonraki adimlar:
echo   1. sahne_config.toml dosyasini duzenle
echo   2. sahne_giris.bat  — 2 hesaba giris
echo   3. sahne_demo.bat   — film sahnesi
echo.
