@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if "%NAUKRI_WEB_HOST%"=="" set NAUKRI_WEB_HOST=127.0.0.1
if "%NAUKRI_WEB_PORT%"=="" set NAUKRI_WEB_PORT=8787
set PIP_DISABLE_PIP_VERSION_CHECK=1

if not exist data mkdir data
if not exist data\logs mkdir data\logs
if not exist data\run mkdir data\run

if exist data\run\backend.pid (
  set /p EXISTING_PID=<data\run\backend.pid
  tasklist /FI "PID eq !EXISTING_PID!" | findstr /R /C:"!EXISTING_PID!" >nul 2>nul
  if not errorlevel 1 (
    echo Dashboard is already running with PID !EXISTING_PID!.
    echo Open http://%NAUKRI_WEB_HOST%:%NAUKRI_WEB_PORT%
    exit /b 0
  )
  del /q data\run\backend.pid >nul 2>nul
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%NAUKRI_WEB_PORT% .*LISTENING"') do (
  echo Port %NAUKRI_WEB_PORT% is already in use by PID %%p.
  echo Run stop.bat or set NAUKRI_WEB_PORT to another port.
  exit /b 1
)

if not exist .venv (
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -m playwright install chromium firefox webkit >nul 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath '%cd%\.venv\Scripts\python.exe' -ArgumentList 'backend/server.py' -WorkingDirectory '%cd%' -WindowStyle Minimized -RedirectStandardOutput '%cd%\data\logs\backend.log' -RedirectStandardError '%cd%\data\logs\backend.err' -PassThru; $p.Id | Out-File -FilePath '%cd%\data\run\backend.pid' -Encoding ascii"

start "" "http://%NAUKRI_WEB_HOST%:%NAUKRI_WEB_PORT%"
echo Dashboard launching at http://%NAUKRI_WEB_HOST%:%NAUKRI_WEB_PORT%
echo Backend log: data\logs\backend.log. Use stop.bat to stop it.
endlocal
