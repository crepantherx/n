from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os
import signal


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class TaskStatus:
    name: str
    running: bool
    pid: Optional[int]
    started_at: Optional[float]
    last_exit_code: Optional[int]


class TaskRunner:
    def __init__(self, name: str, script_path: Path):
        self.name = name
        self.script_path = script_path
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._started_at: Optional[float] = None
        self._last_exit_code: Optional[int] = None

    def status(self) -> TaskStatus:
        with self._lock:
            p = self._process
            running = bool(p and p.poll() is None)
            return TaskStatus(
                name=self.name,
                running=running,
                pid=p.pid if p else None,
                started_at=self._started_at if running else None,
                last_exit_code=self._last_exit_code if not running else None,
            )

    def start(
        self,
        *,
        args: list[str],
        cwd: Path = REPO_ROOT,
        env: Optional[dict[str, str]] = None,
        on_log_line=None,
        on_exit=None,
    ) -> TaskStatus:
        with self._lock:
            if self._process and self._process.poll() is None:
                raise RuntimeError(f"Task '{self.name}' is already running")

            # Force unbuffered output so logs show up immediately in the web UI.
            cmd = [sys.executable, "-u", str(self.script_path)] + args
            self._started_at = time.time()
            self._last_exit_code = None
            full_env = os.environ.copy()
            full_env["PYTHONUNBUFFERED"] = "1"
            if env:
                full_env.update(env)
            popen_kwargs = {
                "cwd": str(cwd),
                "env": full_env,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "bufsize": 1,
            }
            if os.name == "nt":
                # Give taskkill /T a clean tree to terminate on Windows.
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                # Ensures we can reliably terminate the whole tree (Playwright spawns children).
                popen_kwargs["start_new_session"] = True

            self._process = subprocess.Popen(cmd, **popen_kwargs)

            proc = self._process

            def _reader():
                # Batch stdout lines to avoid overwhelming the server/UI when a task is chatty.
                buf: list[str] = []
                last_flush = time.monotonic()
                flush_interval_s = 0.2
                max_lines_per_flush = 80

                def _flush() -> None:
                    nonlocal buf, last_flush
                    if not buf:
                        last_flush = time.monotonic()
                        return
                    if on_log_line:
                        try:
                            on_log_line("".join(buf))
                        except Exception:
                            pass
                    buf = []
                    last_flush = time.monotonic()

                try:
                    if proc.stdout is not None:
                        for line in proc.stdout:
                            buf.append(line)
                            now = time.monotonic()
                            if len(buf) >= max_lines_per_flush or (now - last_flush) >= flush_interval_s:
                                _flush()
                finally:
                    _flush()
                    try:
                        if proc.stdout is not None:
                            proc.stdout.close()
                    except Exception:
                        pass
                    exit_code = proc.wait()
                    with self._lock:
                        self._last_exit_code = exit_code
                        self._process = None
                        self._started_at = None
                    if on_exit:
                        try:
                            on_exit(exit_code)
                        except Exception:
                            pass

            self._reader_thread = threading.Thread(target=_reader, daemon=True)
            self._reader_thread.start()

        # Return status outside the lock (avoid deadlock on non-reentrant lock).
        return self.status()

    def stop(self) -> TaskStatus:
        with self._lock:
            proc = self._process
            if not proc or proc.poll() is not None:
                # Return status outside the lock (avoid deadlock on non-reentrant lock).
                proc = None
            else:
                try:
                    if os.name != "nt":
                        # Terminate the whole process group (Playwright can leave children).
                        os.killpg(proc.pid, signal.SIGTERM)
                    else:
                        subprocess.run(
                            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass

        if proc is None:
            return self.status()

        # Give it a moment; if it doesn't exit, force kill.
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
            except Exception:
                pass

        return self.status()
