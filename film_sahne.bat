@echo off
chcp 65001 >nul
cd /d "%~dp0"

title TRENDYOLHIT — Film Sahne
color 0A
mode con: cols=90 lines=35

if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
python ghost_trendyol.py --profiles 2 --sessions 20 --speed 1.5
pause
