param(
    [string]$Venv = "$env:USERPROFILE\.mullm",
    [int]$Port = 6856,
    [switch]$NoBrowser,
    [switch]$SkipPythonInstall,
    [switch]$CleanVenv,
    [switch]$StopOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Get-PythonVersion([string]$PythonExe) {
    $code = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    try {
        $out = & $PythonExe -c $code 2>$null
        return [version]($out.Trim())
    } catch {
        return $null
    }
}

function Test-Python312([string]$PythonExe) {
    $version = Get-PythonVersion $PythonExe
    return ($version -ne $null -and $version -ge [version]"3.12.0")
}

function Find-Python312 {
    $candidates = @()

    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            & py -3.12 -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return "py -3.12" }
        } catch {}
        try {
            & py -3 -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { $candidates += "py -3" }
        } catch {}
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { $candidates += $python.Source }

    $common = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe"
    )
    foreach ($path in $common) {
        if ($path -and (Test-Path $path)) { $candidates += $path }
    }

    foreach ($candidate in $candidates) {
        $exe = $candidate
        if ($candidate -eq "py -3") {
            try {
                $out = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
                if ([version]($out.Trim()) -ge [version]"3.12.0") { return "py -3" }
            } catch {}
        } elseif (Test-Python312 $exe) {
            return $exe
        }
    }
    return $null
}

function Install-Python312 {
    if ($SkipPythonInstall) {
        throw "Python 3.12+ was not found and -SkipPythonInstall was set."
    }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Step "Installing Python 3.12 with winget"
        & winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "winget Python install failed with exit code $LASTEXITCODE."
        }
        return
    }

    $choco = Get-Command choco.exe -ErrorAction SilentlyContinue
    if ($choco) {
        Write-Step "Installing Python 3.12 with Chocolatey"
        & choco install python312 -y
        if ($LASTEXITCODE -ne 0) {
            throw "Chocolatey Python install failed with exit code $LASTEXITCODE."
        }
        return
    }

    Write-Step "Opening Python 3.12 download page"
    Start-Process "https://www.python.org/downloads/windows/"
    throw "Install Python 3.12+ from python.org, winget, or Chocolatey, then double-click Start muLLM Setup.bat again."
}

function Invoke-Python([string]$PythonCommand, [string[]]$Arguments) {
    if ($PythonCommand -like "py *") {
        $parts = $PythonCommand.Split(" ")
        & $parts[0] $parts[1] @Arguments
    } else {
        & $PythonCommand @Arguments
    }
}

function Resolve-InputFile([string]$Pattern, [string]$Description) {
    $places = @(
        $PSScriptRoot,
        (Split-Path -Parent $PSScriptRoot),
        (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "dist")
    )
    foreach ($place in $places) {
        if (-not (Test-Path $place)) { continue }
        $match = Get-ChildItem -Path $place -Filter $Pattern -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime |
            Select-Object -Last 1
        if ($match) { return $match.FullName }
    }
    throw "Could not find $Description ($Pattern). Put it beside this script and rerun."
}

function Add-Pid([hashtable]$Table, [object]$Value) {
    try {
        $procId = [int]$Value
        if ($procId -gt 0 -and $procId -ne $PID) {
            $Table[$procId] = $true
        }
    } catch {}
}

function Stop-MullmServer([int]$Port, [string]$Venv) {
    Write-Step "Stopping existing muLLM processes"

    $task = Get-ScheduledTask -TaskName "mullm" -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName "mullm" -ErrorAction SilentlyContinue
    }

    $svc = Get-Service -Name "mullm" -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne "Stopped") {
        Stop-Service -Name "mullm" -Force -ErrorAction SilentlyContinue
    }

    $pids = @{}
    $logDir = Join-Path $env:LOCALAPPDATA "mullm"
    $pidFiles = @(
        (Join-Path $logDir "mullm-server.pid"),
        (Join-Path $Venv "mullm-server.pid")
    )
    foreach ($pidFile in $pidFiles) {
        if (Test-Path $pidFile) {
            Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue |
                ForEach-Object { Add-Pid $pids $_ }
        }
    }

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $listeners) {
        if ($conn.OwningProcess) { Add-Pid $pids $conn.OwningProcess }
    }
    try {
        & netstat.exe -ano -p tcp 2>$null | ForEach-Object {
            if ($_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
                Add-Pid $pids $Matches[1]
            }
        }
    } catch {}

    $venvRegex = [regex]::Escape($Venv)
    $localAppDataRegex = [regex]::Escape((Join-Path $env:LOCALAPPDATA "mullm"))
    try {
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.CommandLine -and (
                    $_.CommandLine -match "mullm-server" -or
                    $_.CommandLine -match "mullm1-server" -or
                    $_.CommandLine -match "router\.main" -or
                    $_.CommandLine -match "uvicorn.*router" -or
                    $_.CommandLine -match $venvRegex -or
                    $_.CommandLine -match $localAppDataRegex
                )
            } |
            ForEach-Object { Add-Pid $pids $_.ProcessId }
    } catch {}

    try {
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.ExecutablePath -and (
                    $_.ExecutablePath.StartsWith($Venv, [StringComparison]::OrdinalIgnoreCase) -or
                    $_.ExecutablePath.StartsWith((Join-Path $env:LOCALAPPDATA "mullm"), [StringComparison]::OrdinalIgnoreCase)
                )
            } |
            ForEach-Object { Add-Pid $pids $_.ProcessId }
    } catch {}

    Get-Process -Name "mullm-server","mullm1-server","uvicorn" -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Pid $pids $_.Id }

    foreach ($procId in $pids.Keys) {
        try {
            & taskkill.exe /PID $procId /T /F 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Killed process tree $procId" -ForegroundColor Green
                continue
            }
        } catch {}
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "Stopped process $procId" -ForegroundColor Green
        } catch {
            Write-Host "Could not stop process ${procId}: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    foreach ($pidFile in $pidFiles) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Milliseconds 500
    $remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($remaining) {
        $owners = ($remaining | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique) -join ", "
        throw "Port $Port is still listening after stop attempt. Owning PID(s): $owners. Stop them or run PowerShell as Administrator, then rerun."
    }
}

function Archive-Venv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $parent = Split-Path -Parent $Path
    $name = Split-Path -Leaf $Path
    $dest = Join-Path $parent "$name.backup-$stamp"
    Rename-Item -Path $Path -NewName (Split-Path -Leaf $dest)
    Write-Host "Archived existing venv to: $dest" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "muLLM Windows quickstart" -ForegroundColor Yellow
Write-Host "This will install Python 3.12+ if needed, create a venv, install muLLM, start the server, and open Setup."

Stop-MullmServer $Port $Venv
if ($StopOnly) {
    Write-Host ""
    Write-Host "muLLM stop complete." -ForegroundColor Green
    exit 0
}

Write-Step "Checking Python"
$PythonCommand = Find-Python312
if (-not $PythonCommand) {
    Install-Python312
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $PythonCommand = Find-Python312
}
if (-not $PythonCommand) {
    throw "Python 3.12+ is still not available after install. Restart PowerShell or Windows and run this again."
}
Write-Host "Using Python: $PythonCommand" -ForegroundColor Green

Write-Step "Locating wheel and constraints"
$Wheel = Resolve-InputFile "mullm-*.whl" "muLLM wheel"
$Constraints = Resolve-InputFile "constraints.txt" "constraints.txt"
Write-Host "Wheel: $Wheel"
Write-Host "Constraints: $Constraints"

Write-Step "Creating virtual environment"
if ($CleanVenv) {
    Archive-Venv $Venv
}
if (-not (Test-Path $Venv)) {
    Invoke-Python $PythonCommand @("-m", "venv", $Venv)
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$ServerExe = Join-Path $Venv "Scripts\mullm-server.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment Python was not created at $VenvPython"
}

Write-Step "Installing muLLM"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install --force-reinstall -c $Constraints $Wheel

if (-not (Test-Path $ServerExe)) {
    $ServerExe = Join-Path $Venv "Scripts\mullm1-server.exe"
}
if (-not (Test-Path $ServerExe)) {
    throw "Could not find mullm-server.exe or mullm1-server.exe in the venv."
}

Write-Step "Starting muLLM"
$LogDir = Join-Path $env:LOCALAPPDATA "mullm"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogOutFile = Join-Path $LogDir "mullm-server.out.log"
$LogErrFile = Join-Path $LogDir "mullm-server.err.log"
$PidFile = Join-Path $LogDir "mullm-server.pid"

$envBlock = @{
    "MULLM_PORT" = "$Port"
    "MULLM_HOST" = "127.0.0.1"
    "MULLM_LOG_LEVEL" = "INFO"
    "PYTHONUTF8" = "1"
    "PYTHONIOENCODING" = "utf-8"
}
foreach ($key in $envBlock.Keys) {
    [System.Environment]::SetEnvironmentVariable($key, $envBlock[$key], "Process")
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $owners = ($existing | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique) -join ", "
    throw "Port $Port is still occupied by PID(s): $owners. Refusing to reuse a stale server."
} else {
    $serverProcess = Start-Process -FilePath $ServerExe -RedirectStandardOutput $LogOutFile -RedirectStandardError $LogErrFile -WindowStyle Minimized -PassThru
    Set-Content -LiteralPath $PidFile -Value $serverProcess.Id -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $Venv "mullm-server.pid") -Value $serverProcess.Id -Encoding ASCII
    Write-Host "Started PID: $($serverProcess.Id)" -ForegroundColor Green
}

Write-Step "Waiting for setup page"
$SetupUrl = "http://127.0.0.1:$Port/setup"
$HealthUrl = "http://127.0.0.1:$Port/health"
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) {
    Write-Host "Server stdout log: $LogOutFile" -ForegroundColor Yellow
    Write-Host "Server stderr log: $LogErrFile" -ForegroundColor Yellow
    throw "muLLM did not become healthy within 60 seconds."
}

if (-not $NoBrowser) {
    Start-Process $SetupUrl
}

Write-Host ""
Write-Host "muLLM is running." -ForegroundColor Green
Write-Host "Setup: $SetupUrl"
Write-Host "Venv:  $Venv"
Write-Host "Log:   $LogOutFile"
Write-Host "Err:   $LogErrFile"
Write-Host ""
Write-Host "Close the muLLM server from Task Manager or stop the mullm-server process when finished."
