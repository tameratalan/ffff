@echo off
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" account_creator.py --count 2 --save hesaplar.txt
pause
