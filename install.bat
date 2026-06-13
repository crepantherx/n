@echo off
setlocal
cd /d "%~dp0"
set PIP_DISABLE_PIP_VERSION_CHECK=1

if not exist .venv (
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -m playwright install chromium firefox webkit
if not exist data mkdir data
if not exist data\logs mkdir data\logs
if not exist data\run mkdir data\run
if not exist data\users mkdir data\users

echo Install complete. Start with start.bat
endlocal
