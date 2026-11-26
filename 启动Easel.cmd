@echo off
cd /d "%~dp0"
start "" http://localhost:7860
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-easel.ps1"
pause
