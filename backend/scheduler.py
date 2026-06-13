from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List

from .config_store import ConfigStore, normalize_times
from .log_hub import LogHub


@dataclass
class SchedulerConfig:
    enabled: bool
    times: List[str]


class SimpleScheduler:
    """Small in-process daily scheduler.

    It runs while the web server process is alive. System cron sync remains optional;
    this scheduler is the portable fallback that works on every OS.
    """

    def __init__(
        self,
        *,
        get_users: Callable[[], list[str]],
        get_config_store: Callable[[str], ConfigStore],
        log_hub: LogHub,
        trigger: Callable[[str, str], None],
        poll_seconds: float = 15.0,
    ):
        self._get_users = get_users
        self._get_config_store = get_config_store
        self._log_hub = log_hub
        self._trigger = trigger
        self._poll_seconds = max(1.0, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # self._triggered[user][task][hhmm] = "YYYY-MM-DD"
        self._triggered: Dict[str, Dict[str, Dict[str, str]]] = {}

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="naukri-scheduler", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _get_config(self, user: str) -> Dict[str, SchedulerConfig]:
        cfg = self._get_config_store(user).load()
        return {
            "naukri": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_naukri", False)),
                times=normalize_times(cfg.get("schedule_times", [])),
            ),
            "bot": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_bot", False)),
                times=normalize_times(cfg.get("bot_schedule_times", [])),
            ),
            "linkedin": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_linkedin", False)),
                times=normalize_times(cfg.get("linkedin_schedule_times", [])),
            ),
            "intl_linkedin": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_intl_linkedin", False)),
                times=normalize_times(cfg.get("intl_linkedin_schedule_times") or cfg.get("intl_schedule_times", [])),
            ),
            "intl_indeed": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_intl_indeed", False)),
                times=normalize_times(cfg.get("intl_indeed_schedule_times") or cfg.get("intl_schedule_times", [])),
            ),
            "intl_reed": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_intl_reed", False)),
                times=normalize_times(cfg.get("intl_reed_schedule_times") or cfg.get("intl_schedule_times", [])),
            ),
            "intl_crawler": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_intl_crawler", False)),
                times=normalize_times(cfg.get("intl_crawler_schedule_times") or cfg.get("intl_schedule_times", [])),
            ),
            "lead_scraper": SchedulerConfig(
                enabled=bool(cfg.get("schedule_enabled_lead_scraper", False)),
                times=normalize_times(cfg.get("lead_scraper_schedule_times", [])),
            ),
        }

    def _ensure_user_task(self, user: str, task: str) -> None:
        self._triggered.setdefault(user, {})
        self._triggered[user].setdefault(task, {})

    def _run(self) -> None:
        self._log_hub.status("scheduler", "In-app scheduler started.")
        while not self._stop.is_set():
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            hhmm = now.strftime("%H:%M")

            try:
                users = self._get_users()
            except Exception as e:
                self._log_hub.status("scheduler", f"Unable to load users for scheduling: {e}")
                users = []

            for user in users:
                cfgs = self._get_config(user)
                for task, scfg in cfgs.items():
                    self._ensure_user_task(user, task)
                    if not scfg.enabled or hhmm not in scfg.times:
                        continue

                    last_day = self._triggered[user][task].get(hhmm)
                    if last_day == today:
                        continue

                    self._triggered[user][task][hhmm] = today
                    self._log_hub.status(f"{task}_{user}", f"Scheduled run triggered at {hhmm}.")
                    try:
                        self._trigger(user, task)
                    except Exception as e:
                        self._log_hub.status(f"{task}_{user}", f"Scheduled run failed: {e}")

            self._stop.wait(self._poll_seconds)

        self._log_hub.status("scheduler", "In-app scheduler stopped.")
