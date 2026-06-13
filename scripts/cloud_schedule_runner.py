#!/usr/bin/env python3
"""Free cloud worker runner for GitHub Actions or any CI cron.

Vercel's free serverless functions are not a durable browser worker. This runner
lets you keep the dashboard on Vercel while running the real Playwright jobs from
GitHub Actions without changing local macOS/Windows scheduling.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ci"
CONFIG_FILE = DATA_DIR / "config.json"
TASKS = {
    "naukri": "naukri_job_applier.py",
    "bot": "naukri_bot.py",
    "linkedin": "linkedin_job_applier.py",
    "intl_linkedin": "intl_linkedin_applier.py",
    "intl_indeed": "intl_indeed_applier.py",
    "intl_reed": "intl_reed_applier.py",
    "intl_crawler": "intl_career_page_crawler.py",
    "lead_scraper": "lead_scraper.py",
}


def _tasks_from_env() -> list[str]:
    raw = os.getenv("RUN_TASKS") or os.getenv("NAUKRI_CLOUD_TASKS") or "naukri"
    selected = []
    for item in raw.split(","):
        task = item.strip().lower()
        if not task:
            continue
        if task not in TASKS:
            raise SystemExit(f"Unknown task in RUN_TASKS: {task}")
        selected.append(task)
    return selected or ["naukri"]


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("NAUKRI_CONFIG_PATH", str(CONFIG_FILE))
    env.setdefault("NAUKRI_DATA_DIR", str(DATA_DIR))
    env.setdefault("PYTHONUNBUFFERED", "1")
    target = os.getenv("RUN_TARGET") or os.getenv("NAUKRI_CLOUD_TARGET") or "30"
    failures = 0
    for task in _tasks_from_env():
        args = [] if task == "bot" else ["--target", target]
        args.append("--headless")
        cmd = [sys.executable, "-u", str(ROOT / TASKS[task]), *args]
        print("::group::" + " ".join(cmd))
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
        print("::endgroup::")
        if proc.returncode != 0:
            failures += 1
            print(f"Task {task} failed with exit code {proc.returncode}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
