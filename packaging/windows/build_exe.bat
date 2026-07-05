@echo off
:: packaging\windows\build_exe.bat
:: Builds muLLM.exe (single-file Windows executable via PyInstaller)
::
:: Prerequisites:
::   pip install pyinstaller
::
:: Usage (from the repo root):
::   packaging\windows\build_exe.bat
::
:: Output: dist\muLLM.exe
:: NOTE: packaging\windows\icon.ico must exist — create with a PNG-to-ICO converter.
::       If absent, the build will run without a custom icon.

setlocal enabledelayedexpansion

for /f "usebackq delims=" %%v in (`python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"`) do set VERSION=%%v
set APP_NAME=muLLM
set ICON_PATH=packaging\windows\icon.ico
set LAUNCHER=packaging\windows\launcher.py

echo =^> Installing PyInstaller...
pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Is Python in your PATH?
    exit /b 1
)

echo =^> Building %APP_NAME%.exe...

:: Build the icon argument only if the file exists
set ICON_ARG=
if exist "%ICON_PATH%" (
    set ICON_ARG=--icon "%ICON_PATH%"
) else (
    echo   WARNING: %ICON_PATH% not found - building without custom icon
    echo   To add one: convert packaging\windows\icon.png to ICO format
)

pyinstaller ^
    --onefile ^
    --windowed ^
    --noconsole ^
    --name "%APP_NAME%" ^
    --noconfirm ^
    --clean ^
    --hidden-import "router.main" ^
    --hidden-import "router.cli" ^
    %ICON_ARG% ^
    "%LAUNCHER%"

if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

echo.
echo =^> Done!
echo     Output: dist\%APP_NAME%.exe
echo.
echo     To test:
echo       dist\%APP_NAME%.exe
echo.
echo     To package as an installer (NSIS — optional):
echo       makensis packaging\windows\mullm.nsi
echo       (requires NSIS from https://nsis.sourceforge.io/)
echo.
echo     To sign the executable (requires a code-signing certificate):
echo       signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 dist\%APP_NAME%.exe
endlocal
