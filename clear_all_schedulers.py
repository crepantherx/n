#!/usr/bin/env python3
"""Clear all local scheduler state created by the dashboard.

This removes Naukri-related crontab entries and disables saved schedules in
per-user config files under data/users/*/config.json. It does not delete user
accounts, credentials, resumes, or logs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USER_DIR = ROOT / "data" / "users"
TASK_SCRIPT_NAMES = (
    "naukri_job_applier.py",
    "naukri_bot.py",
    "linkedin_job_applier.py",
    "intl_linkedin_applier.py",
    "intl_indeed_applier.py",
    "intl_reed_applier.py",
    "intl_career_page_crawler.py",
    "lead_scraper.py",
)
SCHEDULE_KEYS = (
    "schedule_times",
    "bot_schedule_times",
    "linkedin_schedule_times",
    "intl_schedule_times",
    "intl_linkedin_schedule_times",
    "intl_indeed_schedule_times",
    "intl_reed_schedule_times",
    "intl_crawler_schedule_times",
    "lead_scraper_schedule_times",
)
ENABLED_KEYS = (
    "schedule_enabled_naukri",
    "schedule_enabled_bot",
    "schedule_enabled_linkedin",
    "schedule_enabled_intl_linkedin",
    "schedule_enabled_intl_indeed",
    "schedule_enabled_intl_reed",
    "schedule_enabled_intl_crawler",
    "schedule_enabled_lead_scraper",
)


def _crontab_bin() -> str | None:
    found = shutil.which("crontab")
    if found:
        return found
    for candidate in ("/usr/bin/crontab", "/bin/crontab"):
        if Path(candidate).exists():
            return candidate
    return None


def clear_cron_jobs() -> None:
    crontab = _crontab_bin()
    if not crontab:
        print("crontab is not available on this system; skipping system cron cleanup.")
        return

    result = subprocess.run([crontab, "-l"], capture_output=True, text=True, check=False)
    current = result.stdout if result.returncode == 0 else ""
    if not current.strip():
        print("No cron jobs found.")
        return

    kept: list[str] = []
    removed: list[str] = []
    for line in current.splitlines():
        managed = ("naukri-automation-suite" in line or "naukri-managed" in line or any(name in line for name in TASK_SCRIPT_NAMES))
        if managed:
            removed.append(line)
        else:
            kept.append(line)

    if not removed:
        print("No Naukri-related cron jobs found.")
        return

    new_cron = "\n".join(kept).rstrip() + ("\n" if kept else "")
    process = subprocess.run([crontab, "-"], input=new_cron, text=True, check=False)
    if process.returncode == 0:
        print(f"Removed {len(removed)} cron job(s).")
    else:
        print("Failed to update crontab.")


def clear_config_schedules() -> None:
    if not USER_DIR.exists():
        print("No per-user config folders found.")
        return

    changed = 0
    for path in USER_DIR.glob("*/config.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            for key in SCHEDULE_KEYS:
                data[key] = []
            for key in ENABLED_KEYS:
                data[key] = False
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
            changed += 1
        except Exception as exc:
            print(f"Could not update {path}: {exc}")

    print(f"Disabled schedules in {changed} user config file(s).")


def main() -> None:
    clear_cron_jobs()
    clear_config_schedules()
    print("Scheduler cleanup complete.")


if __name__ == "__main__":
    main()
