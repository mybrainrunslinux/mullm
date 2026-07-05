param(
    [string]$Venv = "$env:USERPROFILE\.mullm",
    [int]$Port = 6856,
    [switch]$DeleteArchive
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
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
    Write-Step "Stopping muLLM"

    $task = Get-ScheduledTask -TaskName "mullm" -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName "mullm" -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName "mullm" -Confirm:$false -ErrorAction SilentlyContinue
    }

    $svc = Get-Service -Name "mullm" -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne "Stopped") {
        Stop-Service -Name "mullm" -Force -ErrorAction SilentlyContinue
    }
    if (Get-Command nssm.exe -ErrorAction SilentlyContinue) {
        nssm stop mullm 2>$null
        nssm remove mullm confirm 2>$null
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
        } catch {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
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
    if (-not (Test-Path $Path)) { return $null }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $parent = Split-Path -Parent $Path
    $name = Split-Path -Leaf $Path
    $dest = Join-Path $parent "$name.uninstalled-$stamp"
    Rename-Item -Path $Path -NewName (Split-Path -Leaf $dest)
    return $dest
}

Write-Host ""
Write-Host "muLLM Windows uninstaller" -ForegroundColor Yellow
Stop-MullmServer $Port $Venv

Write-Step "Archiving virtual environment"
$archive = Archive-Venv $Venv
if ($archive) {
    Write-Host "Archived $Venv to $archive" -ForegroundColor Yellow
    if ($DeleteArchive) {
        Remove-Item -LiteralPath $archive -Recurse -Force
        Write-Host "Deleted archive: $archive" -ForegroundColor Yellow
    } else {
        Write-Host "Archive retained so local .env/secrets are not silently destroyed." -ForegroundColor Yellow
    }
} else {
    Write-Host "No venv found at $Venv"
}

Write-Host ""
Write-Host "muLLM uninstall complete." -ForegroundColor Green
