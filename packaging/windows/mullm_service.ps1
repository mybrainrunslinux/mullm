# muLLM Windows service installer
# Run as Administrator. Uses NSSM (Non-Sucking Service Manager) if available,
# falls back to sc.exe with a wrapper task.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File mullm_service.ps1 install
#   powershell -ExecutionPolicy Bypass -File mullm_service.ps1 uninstall

param([string]$Action = "install")

$ServiceName = "mullm"
$DisplayName = "muLLM LLM Router"
$MullmExe = (Get-Command mullm-server -ErrorAction SilentlyContinue)?.Source

if (-not $MullmExe) {
    $MullmExe = (Get-Command mullm1-server -ErrorAction SilentlyContinue)?.Source
}

if (-not $MullmExe) {
    $Candidates = @(
        "$env:USERPROFILE\.local\bin\mullm-server.exe",
        "$env:USERPROFILE\.mullm\Scripts\mullm-server.exe",
        "$env:USERPROFILE\.mullm1\Scripts\mullm-server.exe",
        "$env:LOCALAPPDATA\Programs\mullm\mullm-server.exe",
        "$env:USERPROFILE\.mullm1\Scripts\mullm1-server.exe",
        "$env:LOCALAPPDATA\Programs\mullm\mullm1-server.exe"
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            $MullmExe = $Candidate
            break
        }
    }
}

if (-not $MullmExe) {
    throw "Could not find mullm-server or mullm1-server. Install muLLM before installing the service."
}

switch ($Action) {
    "install" {
        if (Get-Command nssm -ErrorAction SilentlyContinue) {
            nssm install $ServiceName $MullmExe
            nssm set $ServiceName DisplayName $DisplayName
            nssm set $ServiceName Start SERVICE_AUTO_START
            nssm start $ServiceName
            Write-Host "muLLM installed as Windows service via NSSM."
        } else {
            # Scheduled task fallback (runs at login, no admin needed for user tasks)
            $action = New-ScheduledTaskAction -Execute $MullmExe
            $trigger = New-ScheduledTaskTrigger -AtLogOn
            $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
            Register-ScheduledTask -TaskName $ServiceName -Action $action `
                -Trigger $trigger -Settings $settings -Description $DisplayName -Force
            Start-ScheduledTask -TaskName $ServiceName
            Write-Host "muLLM registered as a startup task (NSSM not found; install NSSM for true service)."
            Write-Host "Get NSSM: winget install nssm OR choco install nssm"
        }
    }
    "uninstall" {
        if (Get-Command nssm -ErrorAction SilentlyContinue) {
            nssm stop $ServiceName 2>$null
            nssm remove $ServiceName confirm
        } else {
            Stop-ScheduledTask -TaskName $ServiceName 2>$null
            Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false
        }
        Write-Host "muLLM service removed."
    }
    "status" {
        if (Get-Command nssm -ErrorAction SilentlyContinue) {
            nssm status $ServiceName
        } else {
            Get-ScheduledTask -TaskName $ServiceName | Select-Object TaskName, State
        }
    }
}
