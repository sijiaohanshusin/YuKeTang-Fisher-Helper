@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" local_service.py stop
pause
