@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

title TrendyolHit

set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
    echo.
    echo  HATA: venv bulunamadi. Once setup.bat calistirin.
    echo.
    pause
    exit /b 1
)

color 0A
mode con: cols=90 lines=35

:menu
cls
echo.
echo   TrendyolHit
echo   -----------
echo   1 - Giris (hesaplar.txt - arka plan)
echo   2 - Calistir (link + kelime sorar)
echo   3 - Sadece Hesap 1
echo   4 - Sadece Hesap 2
echo   0 - Cikis
echo.

set "secim="
set /p secim="Secim: "

if "%secim%"=="0" exit /b 0
if "%secim%"=="1" goto login
if "%secim%"=="2" goto run
if "%secim%"=="3" goto run1
if "%secim%"=="4" goto run2

echo.
echo  Gecersiz secim.
timeout /t 2 >nul
goto menu

:login
echo.
echo  hesaplar.txt — format: eposta:sifre
echo  Arka planda (headless) giris yapilir, pencere acilmaz.
echo.
if not exist "%~dp0hesaplar.txt" (
    echo  HATA: hesaplar.txt bulunamadi!
    pause
    goto menu
)
"%PY%" "%~dp0sahne_demo.py" --login
echo.
pause
goto menu

:run
echo.
set "url="
set "kw="
set /p url="Urun linki veya ID: "
set /p kw="Anahtar kelime: "
if "!url!"=="" goto menu
if "!kw!"=="" goto menu
"%PY%" "%~dp0sahne_demo.py" --url "!url!" --keyword "!kw!"
echo.
pause
goto menu

:run1
echo.
set "url="
set "kw="
set /p url="Urun linki veya ID: "
set /p kw="Anahtar kelime: "
if "!url!"=="" goto menu
if "!kw!"=="" goto menu
"%PY%" "%~dp0sahne_demo.py" --only 1 --url "!url!" --keyword "!kw!"
echo.
pause
goto menu

:run2
echo.
set "url="
set "kw="
set /p url="Urun linki veya ID: "
set /p kw="Anahtar kelime: "
if "!url!"=="" goto menu
if "!kw!"=="" goto menu
"%PY%" "%~dp0sahne_demo.py" --only 2 --url "!url!" --keyword "!kw!"
echo.
pause
goto menu
