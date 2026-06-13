#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export NAUKRI_WEB_HOST="${NAUKRI_WEB_HOST:-127.0.0.1}"
export NAUKRI_WEB_PORT="${NAUKRI_WEB_PORT:-8787}"
export PIP_DISABLE_PIP_VERSION_CHECK=1

mkdir -p data/logs data/run
PID_FILE="data/run/backend.pid"
LOG_FILE="data/logs/backend.log"

if [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
  echo "Dashboard is already running with PID $(cat "$PID_FILE")."
  echo "Open http://${NAUKRI_WEB_HOST}:${NAUKRI_WEB_PORT}"
  exit 0
fi

port_in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$NAUKRI_WEB_PORT" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$NAUKRI_WEB_PORT" >/dev/null 2>&1
  else
    return 1
  fi
}

if port_in_use; then
  echo "Port $NAUKRI_WEB_PORT is already in use." >&2
  echo "Run ./stop.sh --port=$NAUKRI_WEB_PORT to stop this suite, or choose another NAUKRI_WEB_PORT." >&2
  exit 1
fi

if [ -n "${PYTHON_EXE:-}" ]; then
  PY_BOOT="$PYTHON_EXE"
elif command -v python3.12 >/dev/null 2>&1; then
  PY_BOOT="python3.12"
elif command -v python3.11 >/dev/null 2>&1; then
  PY_BOOT="python3.11"
elif command -v python3.10 >/dev/null 2>&1; then
  PY_BOOT="python3.10"
elif command -v python3 >/dev/null 2>&1; then
  PY_BOOT="python3"
else
  PY_BOOT="python"
fi

if [ ! -d ".venv" ]; then
  "$PY_BOOT" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

# Install Playwright browser binaries when possible. If the host blocks downloads,
# the dashboard still starts and task runs will show a clear browser error.
python -m playwright install chromium firefox webkit >/dev/null 2>&1 || true

nohup python backend/server.py > "$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

echo "Dashboard started with PID $PID."
echo "Open http://${NAUKRI_WEB_HOST}:${NAUKRI_WEB_PORT}"
echo "Backend log: $LOG_FILE"
