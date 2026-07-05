# μ|LLM Windows installer — Run with: powershell -ExecutionPolicy Bypass -File install.ps1
# Installs: Python 3.11, mullm, and optionally Ollama + ROCm for AMD GPU
#
# Usage:
#   .\install.ps1           # Python + mullm only (cloud-only mode)
#   .\install.ps1 -Ollama   # + Ollama (GPU inference if ROCm works, else CPU)
#   .\install.ps1 -ROCm     # + Ollama + AMD ROCm HIP SDK (full GPU support)

param(
    [switch]$Ollama,
    [switch]$ROCm
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  μ|LLM installer for Windows" -ForegroundColor Yellow
Write-Host "  ==============================" -ForegroundColor DarkGray
Write-Host ""

# ── Python check ──────────────────────────────────────────────────────────────
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python not found. Downloading Python 3.11..." -ForegroundColor Cyan
    $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $pyInstaller = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller
    Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1" -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    Write-Host "Python 3.11 installed." -ForegroundColor Green
} else {
    Write-Host "Python found: $($py.Source)" -ForegroundColor Green
}

# ── Install mullm ─────────────────────────────────────────────────────────────
Write-Host "Installing muLLM..." -ForegroundColor Cyan
$whl = Get-ChildItem -Path $PSScriptRoot -Filter "mullm-*.whl" | Select-Object -First 1
if ($whl) {
    python -m pip install $whl.FullName --quiet
    Write-Host "muLLM installed from wheel: $($whl.Name)" -ForegroundColor Green
} else {
    python -m pip install mullm --quiet
    Write-Host "muLLM installed from PyPI." -ForegroundColor Green
}

# ── Ollama ────────────────────────────────────────────────────────────────────
if ($Ollama -or $ROCm) {
    $ollamaInstalled = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaInstalled) {
        Write-Host "Downloading Ollama for Windows..." -ForegroundColor Cyan
        $ollamaUrl = "https://ollama.com/download/OllamaSetup.exe"
        $ollamaInstaller = "$env:TEMP\OllamaSetup.exe"
        Invoke-WebRequest -Uri $ollamaUrl -OutFile $ollamaInstaller
        Start-Process -FilePath $ollamaInstaller -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
        Write-Host "Ollama installed." -ForegroundColor Green
    } else {
        Write-Host "Ollama already installed." -ForegroundColor Green
    }
}

# ── AMD ROCm / HIP SDK ────────────────────────────────────────────────────────
if ($ROCm) {
    Write-Host ""
    Write-Host "AMD ROCm Setup" -ForegroundColor Yellow
    Write-Host "─────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray

    # Detect GPU
    $gpuInfo = Get-WmiObject Win32_VideoController | Where-Object { $_.Name -match "AMD|Radeon|RX" }
    if ($gpuInfo) {
        Write-Host "Detected AMD GPU: $($gpuInfo.Name)" -ForegroundColor Green
        Write-Host ""
        Write-Host "ROCm for Windows requires HIP SDK 6.1 or newer." -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Download from AMD (automated install not yet available via this script):" -ForegroundColor Yellow
        Write-Host "  https://www.amd.com/en/developer/resources/rocm-hub/hip-sdk.html" -ForegroundColor White
        Write-Host ""
        Write-Host "After installing HIP SDK:" -ForegroundColor Cyan
        Write-Host "  1. Restart your machine"
        Write-Host "  2. Ollama will automatically detect ROCm"
        Write-Host "  3. Run: ollama pull qwen3.5:9b"
        Write-Host "  4. Run start.bat to launch muLLM with full local inference"
        Write-Host ""
        Write-Host "Supported AMD GPUs (ROCm 6.1+):" -ForegroundColor DarkGray
        Write-Host "  RX 6600 / 6700 / 6700 XT / 6750 XT / 6800 / 6800 XT / 6900 XT" -ForegroundColor DarkGray
        Write-Host "  RX 7600 / 7700 / 7800 XT / 7900 / 7900 XTX / 7900 GRE" -ForegroundColor DarkGray
        Write-Host "  Radeon PRO W6000 / W7000 series" -ForegroundColor DarkGray
    } else {
        Write-Host "No AMD GPU detected. ROCm not applicable." -ForegroundColor Yellow
    }
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Done! Run start.bat to launch muLLM." -ForegroundColor Green
Write-Host ""

if (-not ($Ollama -or $ROCm)) {
    Write-Host "Tip: muLLM starts in cloud-only mode without Ollama." -ForegroundColor DarkGray
    Write-Host "     Add an API key in the Setup page (http://127.0.0.1:8100/setup)" -ForegroundColor DarkGray
    Write-Host "     Basic queries (2+2, 'what is binary search') are free via groundtruth cache." -ForegroundColor DarkGray
}
