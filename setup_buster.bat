@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo === Buster (ucretsiz reCAPTCHA) kurulumu ===
echo    Node.js + Git gerekir
echo.

set "SRC=extensions\buster-src"
set "OUT=extensions\buster"

where git >nul 2>&1
if errorlevel 1 (
    echo HATA: Git yok — https://git-scm.com/download/win
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo HATA: Node.js/npm yok — https://nodejs.org
    pause
    exit /b 1
)

if exist "%OUT%\manifest.json" (
    echo Buster zaten kurulu: %OUT%
    goto :done
)

if exist "%SRC%" rmdir /S /Q "%SRC%"
if exist "%OUT%" rmdir /S /Q "%OUT%"

echo [1/4] GitHub'dan indiriliyor...
git clone --depth 1 https://github.com/dessant/buster.git "%SRC%"
if errorlevel 1 (
    echo Git clone basarisiz.
    pause
    exit /b 1
)

echo [2/4] npm paketleri...
pushd "%SRC%"
call npm ci
if errorlevel 1 (
    echo npm ci basarisiz.
    popd
    pause
    exit /b 1
)

echo [3/4] Extension derleniyor (1-3 dk)...
call npm run build:prod:chrome
if errorlevel 1 (
    echo Derleme basarisiz.
    popd
    pause
    exit /b 1
)
popd

if not exist "%SRC%\dist\chrome\manifest.json" (
    echo HATA: dist\chrome\manifest.json yok.
    pause
    exit /b 1
)

echo [4/4] Kopyalaniyor...
xcopy /E /I /Y "%SRC%\dist\chrome\*" "%OUT%\"
rmdir /S /Q "%SRC%"

:done
echo.
echo Tamam — ucretsiz reCAPTCHA hazir.
echo TrendyolHit'i yeniden baslatin.
echo.
pause
