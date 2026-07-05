@echo off
REM μ|LLM USB launcher — auto-detects Python, starts server
REM Drop this folder on a USB drive, double-click start.bat

title muLLM

cd /d "%~dp0"

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Trying py launcher...
    py --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ERROR: Python not found.
        echo Run install.ps1 first, or install Python 3.11+ from python.org
        echo.
        pause
        exit /b 1
    )
    set PY=py
) else (
    set PY=python
)

REM Install mullm wheel if not already installed
%PY% -c "import router" >nul 2>&1
if errorlevel 1 (
    echo Installing muLLM...
    if exist mullm-*.whl (
        %PY% -m pip install mullm-*.whl --quiet
    ) else (
        %PY% -m pip install mullm --quiet
    )
)

REM Check for Ollama (local inference)
ollama --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo NOTE: Ollama not found - running in cloud-only mode.
    echo       Simple queries (2+2, binary search) still route to groundtruth/cache instantly.
    echo       Complex queries will use cloud APIs ^(requires API key^).
    echo       To enable local GPU inference: run install_ollama.ps1
    echo.
    set MULLM_LOCAL_MODE=false
) else (
    echo Ollama found. Checking for local model...
    ollama list 2>nul | findstr /i "qwen" >nul
    if errorlevel 1 (
        echo Pulling qwen3.5:9b ^(~5.5GB, may take a while^)...
        echo You can Ctrl+C and use cloud-only mode instead.
        ollama pull qwen3.5:9b
    )
    set MULLM_LOCAL_MODE=true
)

REM Start mullm
echo.
echo Starting muLLM on http://127.0.0.1:8100
echo Open your browser to: http://127.0.0.1:8100
echo Press Ctrl+C to stop.
echo.

%PY% -m router.main --host 127.0.0.1

pause
