@echo off
chcp 65001 >nul
cd /d "%~dp0"

title TRENDYOLHIT — Simulasyon Yakın Cekim
color 0A
mode con: cols=95 lines=40

if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
python ghost_trendyol.py --profiles 2 --sessions 20 --speed 1.2 --no-code
pause
