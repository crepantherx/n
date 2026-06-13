"""Vercel entrypoint for the FastAPI dashboard.

Local desktop installs continue to use backend/server.py through start.sh/start.bat.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Mark serverless mode before importing backend.app so scheduler/process behavior
# is adapted for Vercel.
os.environ.setdefault("NAUKRI_CLOUD_MODE", "1")
os.environ.setdefault("NAUKRI_DATA_ROOT", "/tmp/naukri_automation_suite/data")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import app  # noqa: E402
