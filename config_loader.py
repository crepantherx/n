#!/usr/bin/env python3
"""Configuration loader shared by automation scripts.

Scripts can run from the web dashboard, a system scheduler, or the command line.
This loader keeps those entry points consistent and portable by honoring
NAUKRI_CONFIG_PATH and NAUKRI_DATA_DIR, then resolving relative file paths from
the per-user config directory rather than from the current working directory.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from backend.config_store import DEFAULT_CONFIG, ENV_TO_CONFIG, resolve_config_path
except Exception:  # pragma: no cover - fallback for unusual direct execution
    DEFAULT_CONFIG = {
        "email": "",
        "password": "",
        "resume_path": "",
        "job_titles": "ML Engineer, AI Engineer, Software Engineer",
        "linkedin_email": "",
        "linkedin_password": "",
        "linkedin_phone": "",
        "reed_email": "",
        "reed_password": "",
        "ctc_inr": "2500000",
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

    def resolve_config_path(raw_path: Any, *, config_path: Path) -> Path:
        p = Path(str(raw_path or "").strip()).expanduser()
        return p if p.is_absolute() else (config_path.parent / p).resolve()


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = Path(os.getenv("NAUKRI_CONFIG_PATH", str(SCRIPT_DIR / "config.json"))).expanduser()
ENV_FILE = SCRIPT_DIR / ".env"


def get_data_dir() -> Path:
    data_dir = Path(os.getenv("NAUKRI_DATA_DIR", str(CONFIG_FILE.parent))).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}



def _materialize_resume_from_env() -> str:
    """Decode RESUME_BASE64/RESUME_B64 into the active data dir.

    This keeps cloud workers portable: store the resume as an encrypted secret
    and the runner recreates a temporary file at runtime. Local installs can
    continue using a normal resume_path from the dashboard.
    """
    raw = os.getenv("RESUME_BASE64") or os.getenv("RESUME_B64") or ""
    raw = raw.strip()
    if not raw:
        return ""

    # Accept either a plain base64 payload or a data:...;base64,... URL.
    if "," in raw and raw.split(",", 1)[0].lower().startswith("data:"):
        raw = raw.split(",", 1)[1].strip()

    name = os.getenv("RESUME_FILENAME", "resume.pdf").strip() or "resume.pdf"
    ext = Path(name).suffix.lower()
    if ext not in {".pdf", ".doc", ".docx"}:
        ext = ".pdf"

    try:
        payload = base64.b64decode(raw, validate=True)
    except Exception:
        # Be forgiving of base64 strings copied with whitespace/newlines.
        payload = base64.b64decode("".join(raw.split()))

    dest = get_data_dir() / f"resume{ext}"
    dest.write_bytes(payload)
    return str(dest)

def load_config() -> dict[str, Any]:
    config: dict[str, Any] = dict(DEFAULT_CONFIG)
    load_dotenv(ENV_FILE, override=False)

    data = _load_json(CONFIG_FILE)
    config.update(data)

    # Environment values only fill missing fields. This keeps per-user dashboard
    # settings isolated while still supporting CLI/server deployments.
    for env_name, key in ENV_TO_CONFIG.items():
        value = os.getenv(env_name)
        # A default value is not a user setting. Environment values should
        # override defaults but not override fields explicitly saved in config.json.
        if value and not data.get(key):
            config[key] = value

    if not str(config.get("resume_path") or "").strip():
        resume_from_secret = _materialize_resume_from_env()
        if resume_from_secret:
            config["resume_path"] = resume_from_secret

    resume_path = str(config.get("resume_path") or "").strip()
    if resume_path:
        try:
            config["resume_path"] = str(resolve_config_path(resume_path, config_path=CONFIG_FILE))
        except Exception:
            pass

    try:
        ctc = float(config.get("ctc_inr", 2500000) or 2500000)
    except Exception:
        ctc = 2500000.0

    config["intl_expected_salary_gbp"] = str(int(ctc * 0.0095))
    config["intl_expected_salary_usd"] = str(int(ctc * 0.012))
    config["intl_expected_salary_eur"] = str(int(ctc * 0.011))

    config.setdefault("intl_notice_period", "60 days")
    config.setdefault("intl_visa_status", "Require Sponsorship")
    config.setdefault("intl_schedule_times", [])

    return config
