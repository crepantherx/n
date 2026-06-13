from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


def main():
    # When executed as `python backend/server.py`, Python puts `backend/` on sys.path
    # which breaks `import backend.*`. Ensure repo root is importable.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from backend.app import app  # noqa: WPS433 (runtime import is intentional)

    host = os.getenv("NAUKRI_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("NAUKRI_WEB_PORT") or "8787")
    uvicorn.run(app, host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
