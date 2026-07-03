@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%~dp0venv\Scripts\python.exe"
"%PY%" "%~dp0sahne_demo.py" --login
pause
