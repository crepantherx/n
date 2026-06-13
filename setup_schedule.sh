#!/bin/bash
set -euo pipefail
cat <<'MSG'
Legacy setup_schedule.sh has been disabled in this repaired build.

Use the web dashboard schedule controls instead:
  1. Start the dashboard with ./start.sh
  2. Open http://127.0.0.1:8787
  3. Configure each task schedule from the UI

The dashboard includes a portable in-app scheduler and optional cron sync.
MSG
