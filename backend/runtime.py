from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def is_cloud_runtime() -> bool:
    """True when the app is running on Vercel/serverless-style hosting."""
    return _truthy(os.getenv("NAUKRI_CLOUD_MODE")) or os.getenv("VERCEL") == "1"


def runtime_name() -> str:
    if os.getenv("VERCEL") == "1":
        return "vercel"
    if is_cloud_runtime():
        return "cloud"
    return "local"


def data_root(repo_root: Path) -> Path:
    """Return the writable data directory for this runtime.

    Local desktop installs keep the historical repo-local data directory so macOS
    and Windows scheduling behavior remains unchanged. Vercel/serverless
    functions cannot rely on repo-local writes, so they use /tmp unless an
    explicit NAUKRI_DATA_ROOT is provided.
    """
    configured = os.getenv("NAUKRI_DATA_ROOT") or os.getenv("NAUKRI_STORAGE_DIR")
    if configured:
        return Path(configured).expanduser()
    if is_cloud_runtime():
        return Path("/tmp") / "naukri_automation_suite" / "data"
    return Path(repo_root) / "data"


def cloud_features() -> dict[str, Any]:
    cloud = is_cloud_runtime()
    return {
        "runtime": runtime_name(),
        "cloud": cloud,
        "serverless": cloud,
        "persistent_filesystem": not cloud,
        "websockets": not cloud,
        "in_process_scheduler": not cloud,
        "system_cron": not cloud,
        "shutdown_endpoint": not cloud,
        "subprocess_tasks": (not cloud) or _truthy(os.getenv("NAUKRI_ENABLE_CLOUD_SUBPROCESSES")),
        "cloud_subprocesses_enabled": _truthy(os.getenv("NAUKRI_ENABLE_CLOUD_SUBPROCESSES")),
        "vercel_runs_enabled": _truthy(os.getenv("NAUKRI_ENABLE_VERCEL_RUNS")),
    }


def unsupported_detail(feature: str) -> str:
    return (
        f"{feature} is not available in Vercel/serverless mode. "
        "The hosted dashboard remains usable, but long-running browser automation, "
        "local subprocesses, local cron, WebSockets, and server shutdown are desktop/worker features."
    )
