#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PORT="${NAUKRI_WEB_PORT:-8787}"
CLEAR_SCHEDULES=0

for arg in "$@"; do
  case "$arg" in
    --all|--clear-schedules|--panic)
      CLEAR_SCHEDULES=1
      ;;
    --port=*)
      PORT="${arg#--port=}"
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: ./stop.sh [--all|--clear-schedules|--panic] [--port=8787]" >&2
      exit 2
      ;;
  esac
done

choose_python() {
  if [ -x "$DIR/.venv/bin/python" ]; then
    printf '%s\n' "$DIR/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    command -v python || true
  fi
}

terminate_pid() {
  pid="$1"
  [ -n "$pid" ] || return 0
  [ "$pid" != "$$" ] || return 0
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi
  echo "Stopping PID $pid"
  # Most task processes are process-group leaders, so this also catches Playwright children.
  kill -TERM "-$pid" >/dev/null 2>&1 || kill -TERM "$pid" >/dev/null 2>&1 || true
}

force_pid() {
  pid="$1"
  [ -n "$pid" ] || return 0
  [ "$pid" != "$$" ] || return 0
  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "Force killing PID $pid"
    kill -KILL "-$pid" >/dev/null 2>&1 || kill -KILL "$pid" >/dev/null 2>&1 || true
  fi
}

if [ "$CLEAR_SCHEDULES" = "1" ]; then
  PY="$(choose_python)"
  if [ -n "$PY" ]; then
    "$PY" clear_all_schedulers.py || true
  else
    echo "Python not found; skipped schedule cleanup." >&2
  fi
fi

PIDS=""
PID_FILE="data/run/backend.pid"
if [ -f "$PID_FILE" ]; then
  PIDS="$PIDS $(cat "$PID_FILE" 2>/dev/null || true)"
  rm -f "$PID_FILE"
fi
if [ -f backend.pid ]; then
  PIDS="$PIDS $(cat backend.pid 2>/dev/null || true)"
  rm -f backend.pid
fi

SCRIPT_PATTERNS=(
  "$DIR/backend/server.py"
  "$DIR/naukri_job_applier.py"
  "$DIR/naukri_bot.py"
  "$DIR/linkedin_job_applier.py"
  "$DIR/intl_linkedin_applier.py"
  "$DIR/intl_indeed_applier.py"
  "$DIR/intl_reed_applier.py"
  "$DIR/intl_career_page_crawler.py"
  "$DIR/lead_scraper.py"
  "$DIR/run_agent.py"
)

if command -v pgrep >/dev/null 2>&1; then
  for pattern in "${SCRIPT_PATTERNS[@]}"; do
    PIDS="$PIDS $(pgrep -f "$pattern" 2>/dev/null || true)"
  done
  # Server is usually launched with a relative path from this folder.
  PIDS="$PIDS $(pgrep -f "backend/server.py" 2>/dev/null || true)"
fi

if command -v lsof >/dev/null 2>&1; then
  PIDS="$PIDS $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
elif command -v fuser >/dev/null 2>&1; then
  PIDS="$PIDS $(fuser -n tcp "$PORT" 2>/dev/null || true)"
fi

UNIQUE_PIDS="$(printf '%s\n' $PIDS | awk '/^[0-9]+$/ && !seen[$1]++ {print $1}')"
if [ -n "$UNIQUE_PIDS" ]; then
  for pid in $UNIQUE_PIDS; do
    terminate_pid "$pid"
  done
  sleep 2
  for pid in $UNIQUE_PIDS; do
    force_pid "$pid"
  done
else
  echo "No matching dashboard/task processes found."
fi

rm -f data/run/backend.pid backend.pid

echo "Stopped dashboard/task processes and freed port $PORT when it was used."
if [ "$CLEAR_SCHEDULES" = "0" ]; then
  echo "Saved schedules were left unchanged. Run ./stop_all.sh to clear schedules too."
fi
