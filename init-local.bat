@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r backend\requirements-local.lock.txt
if errorlevel 1 goto fail
cd frontend
call npm ci
if errorlevel 1 goto fail
call npm run build
if errorlevel 1 goto fail
cd ..
echo Ready. Run start-local.bat
pause
exit /b 0
:fail
echo Initialization failed. Python 3.11+ and Node.js are required.
pause
exit /b 1
