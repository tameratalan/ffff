@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 2captcha API key — otomatik reCAPTCHA cozumu icin
REM https://2captcha.com adresinden key alin (~3$/1000 captcha)
REM Asagidaki satirin basindaki REM'i kaldirin ve key'inizi yazin:
REM set CAPTCHA_2CAPTCHA_KEY=YOUR_2CAPTCHA_KEY_HERE

if exist "captcha_key.txt" (
  for /f "usebackq delims=" %%K in ("captcha_key.txt") do set CAPTCHA_2CAPTCHA_KEY=%%K
)

python gui_app.py
