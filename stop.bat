@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if "%NAUKRI_WEB_PORT%"=="" set NAUKRI_WEB_PORT=8787
set CLEAR_SCHEDULES=0

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--all" set CLEAR_SCHEDULES=1
if /I "%~1"=="--clear-schedules" set CLEAR_SCHEDULES=1
if /I "%~1"=="--panic" set CLEAR_SCHEDULES=1
shift
goto parse_args
:args_done

if "%CLEAR_SCHEDULES%"=="1" (
  if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe clear_all_schedulers.py
  ) else (
    py -3 clear_all_schedulers.py 2>nul || python clear_all_schedulers.py
  )
)

if exist data\run\backend.pid (
  for /f %%p in (data\run\backend.pid) do taskkill /PID %%p /T /F >nul 2>nul
  del /q data\run\backend.pid >nul 2>nul
)
if exist backend.pid (
  for /f %%p in (backend.pid) do taskkill /PID %%p /T /F >nul 2>nul
  del /q backend.pid >nul 2>nul
)

for %%S in (backend\server.py naukri_job_applier.py naukri_bot.py linkedin_job_applier.py intl_linkedin_applier.py intl_indeed_applier.py intl_reed_applier.py intl_career_page_crawler.py lead_scraper.py run_agent.py) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*%%S*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%NAUKRI_WEB_PORT% .*LISTENING"') do (
  taskkill /PID %%p /T /F >nul 2>nul
)

echo Stopped dashboard/task processes and freed port %NAUKRI_WEB_PORT% when it was used.
if "%CLEAR_SCHEDULES%"=="0" echo Saved schedules were left unchanged. Run stop_all.bat to clear schedules too.
endlocal
