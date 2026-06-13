#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export PIP_DISABLE_PIP_VERSION_CHECK=1

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
python -m playwright install chromium firefox webkit || true

mkdir -p data/logs data/run data/users

echo "Install complete. Start with ./start.sh"
