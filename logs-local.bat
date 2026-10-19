@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -Command "Get-Content -LiteralPath 'logs\backend.log' -Tail 60 -Wait"
