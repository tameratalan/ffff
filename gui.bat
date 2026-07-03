@echo off
chcp 65001 >nul
cd /d "%~dp0"

title TrendyolHit

set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
    echo.
    echo  HATA: Kurulum yapilmamis.
    echo  Once calistirin: setup.bat
    echo.
    pause
    exit /b 1
)

"%PY%" -m pip show customtkinter >nul 2>&1
if errorlevel 1 (
    echo customtkinter kuruluyor...
    "%PY%" -m pip install customtkinter
)

echo TrendyolHit aciliyor...
"%PY%" "%~dp0gui_app.py"
if errorlevel 1 (
    echo.
    echo  GUI baslatilamadi. Yukaridaki hatayi kontrol edin.
    pause
)
