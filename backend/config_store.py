from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .runtime import data_root, is_cloud_runtime

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = data_root(REPO_ROOT)
CONFIG_FILE = Path(os.getenv("NAUKRI_CONFIG_PATH", str((DATA_ROOT if is_cloud_runtime() else REPO_ROOT) / "config.json")))
ENV_FILE = REPO_ROOT / ".env"

HHMM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")

DEFAULT_CONFIG: dict[str, Any] = {
    "email": "",
    "password": "",
    "resume_path": "",
    "job_titles": "ML Engineer, AI Engineer, Software Engineer",
    "ctc_inr": "2500000",

    "linkedin_email": "",
    "linkedin_password": "",
    "linkedin_phone": "",
    "reed_email": "",
    "reed_password": "",

    "ui_headless_naukri": True,
    "ui_headless_bot": True,
    "ui_headless_linkedin": True,
    "ui_headless_intl_linkedin": True,
    "ui_headless_intl_indeed": True,
    "ui_headless_intl_reed": True,
    "ui_headless_intl_crawler": True,
    "ui_headless_lead_scraper": True,

    "schedule_times": [],
    "bot_schedule_times": [],
    "linkedin_schedule_times": [],
    "intl_schedule_times": [],  # legacy shared key
    "intl_linkedin_schedule_times": [],
    "intl_indeed_schedule_times": [],
    "intl_reed_schedule_times": [],
    "intl_crawler_schedule_times": [],
    "lead_scraper_schedule_times": [],

    "schedule_enabled_naukri": False,
    "schedule_enabled_bot": False,
    "schedule_enabled_linkedin": False,
    "schedule_enabled_intl_linkedin": False,
    "schedule_enabled_intl_indeed": False,
    "schedule_enabled_intl_reed": False,
    "schedule_enabled_intl_crawler": False,
    "schedule_enabled_lead_scraper": False,

    "region_naukri": "Indian",
    "region_bot": "Indian",
    "region_linkedin": "Indian",
    "region_intl_linkedin": "European",
    "region_intl_indeed": "European",
    "region_intl_reed": "European",
    "region_intl_crawler": "European",
}

SCHEDULE_TIME_KEYS = {
    "schedule_times",
    "bot_schedule_times",
    "linkedin_schedule_times",
    "intl_schedule_times",
    "intl_linkedin_schedule_times",
    "intl_indeed_schedule_times",
    "intl_reed_schedule_times",
    "intl_crawler_schedule_times",
    "lead_scraper_schedule_times",
}

ENV_TO_CONFIG = {
    "NAUKRI_EMAIL": "email",
    "NAUKRI_PASSWORD": "password",
    "JOB_TITLES": "job_titles",
    "NAUKRI_JOB_TITLES": "job_titles",
    "RESUME_PATH": "resume_path",
    "LINKEDIN_EMAIL": "linkedin_email",
    "LINKEDIN_PASSWORD": "linkedin_password",
    "LINKEDIN_PHONE": "linkedin_phone",
    "REED_EMAIL": "reed_email",
    "REED_PASSWORD": "reed_password",
    "CTC_INR": "ctc_inr",
}


def _load_env_file() -> dict[str, str]:
    env_vals: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env_vals
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_vals[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env_vals


def normalize_hhmm(value: Any) -> Optional[str]:
    if value is None:
        return None
    match = HHMM_RE.match(str(value))
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def normalize_times(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values: Iterable[Any] = values.split(",")
    elif isinstance(values, Iterable):
        raw_values = values
    else:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        normalized = normalize_hhmm(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return sorted(result)



def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "y"}:
            return True
        if normalized in {"0", "false", "no", "off", "n", ""}:
            return False
    return default

def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update(data or {})

    # Backward compatibility: older builds used one shared intl_schedule_times key.
    legacy_intl = normalize_times(merged.get("intl_schedule_times"))
    for key in ("intl_linkedin_schedule_times", "intl_indeed_schedule_times", "intl_reed_schedule_times", "intl_crawler_schedule_times"):
        if not merged.get(key) and legacy_intl:
            merged[key] = list(legacy_intl)

    for key in SCHEDULE_TIME_KEYS:
        merged[key] = normalize_times(merged.get(key))

    for key, default in DEFAULT_CONFIG.items():
        if isinstance(default, bool):
            merged[key] = _to_bool(merged.get(key), default)
        elif isinstance(default, str):
            merged[key] = str(merged.get(key, default) or "")

    return merged


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False


def resolve_config_path(raw_path: Any, *, config_path: Path) -> Path:
    raw = str(raw_path or "").strip().replace("\\ ", " ").replace("\\~", "~")
    if not raw:
        return Path("")
    expanded = Path(os.path.expandvars(raw)).expanduser()
    if expanded.is_absolute():
        return expanded
    # Configs are per-user, so relative paths should travel with that user's data directory.
    return (config_path.parent / expanded).resolve()


def portable_config_path(path: Path, *, config_path: Path) -> str:
    try:
        path = Path(path).expanduser().resolve()
        base = config_path.parent.resolve()
        if _is_relative_to(path, base):
            return str(path.relative_to(base))
    except Exception:
        pass
    return str(path)


@dataclass
class ConfigStore:
    path: Path = CONFIG_FILE

    @classmethod
    def for_user(cls, user_slug: str) -> "ConfigStore":
        return cls(path=DATA_ROOT / "users" / user_slug / "config.json")

    def load(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except Exception:
                data = {}

        env_vals = _load_env_file()
        for env_name, key in ENV_TO_CONFIG.items():
            value = os.getenv(env_name) or env_vals.get(env_name)
            if value and not data.get(key):
                data[key] = value
                data[f"_{key}_source"] = ".env"
                if "PASSWORD" in env_name:
                    data[f"_{key}_set_via_env"] = True

        return _merge_defaults(data)

    def save(self, data: dict[str, Any]) -> None:
        clean = {k: v for k, v in (data or {}).items() if not str(k).startswith("_")}
        merged = _merge_defaults(clean)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)
