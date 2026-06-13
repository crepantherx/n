#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

./start.sh
open "http://${NAUKRI_WEB_HOST:-127.0.0.1}:${NAUKRI_WEB_PORT:-8787}" 2>/dev/null || true
