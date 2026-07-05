@echo off
setlocal
chcp 65001 >nul
title muLLM Setup
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-and-start.ps1"
if errorlevel 1 (
  echo.
  echo muLLM setup did not complete. See the messages above.
  pause
)
