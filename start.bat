@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (echo Python 3.11+ required. & pause & exit /b 1)
python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
if errorlevel 1 (pause & exit /b 1)
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (pause & exit /b 1)
echo Open http://127.0.0.1:8020 - Keep this window open.
.venv\Scripts\python.exe -m uvicorn lab.main:app --host 127.0.0.1 --port 8020 --workers 1
pause
