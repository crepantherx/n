from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Set


@dataclass(frozen=True)
class LogEvent:
    ts: float
    task: str
    line: str
    kind: str = "log"  # "log" | "status"

    def to_json(self) -> Dict[str, Any]:
        return {"ts": self.ts, "task": self.task, "line": self.line, "kind": self.kind}


class LogHub:
    def __init__(self, *, max_history: int = 3000):
        self._lock = threading.Lock()
        self._history: Deque[LogEvent] = deque(maxlen=max_history)
        self._clients: Set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending: Deque[Dict[str, Any]] = deque()
        self._flush_scheduled: bool = False

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def history(self, *, limit: int = 500) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._history)[-max(0, limit) :]
        return [e.to_json() for e in items]

    def clear_user_history(self, user: str) -> None:
        user_suffix = f"_{user}"
        with self._lock:
            # Keep items that do NOT belong to this user
            new_history = [
                e for e in self._history 
                if not e.task.endswith(user_suffix)
            ]
            self._history = deque(new_history, maxlen=self._history.maxlen)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def _flush(self) -> None:
        """
        Flush a bounded amount of pending log events to websocket client queues.

        Important: This must run on the event loop thread.
        """

        loop = asyncio.get_running_loop()
        drained = 0
        max_drain = 300

        while drained < max_drain:
            with self._lock:
                if not self._pending:
                    self._flush_scheduled = False
                    return
                payload = self._pending.popleft()
                clients = list(self._clients)

            if not clients:
                # No connected clients; drop pending (clients will hydrate via history on reconnect).
                with self._lock:
                    self._pending.clear()
                    self._flush_scheduled = False
                return

            for q in clients:
                try:
                    if q.full():
                        continue
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    # Client can't keep up (tab in background / slow machine). Drop.
                    pass
                except Exception:
                    pass

            drained += 1

        # Still pending: yield to the event loop and continue next tick.
        # Use a tiny delay so we don't starve HTTP handlers when logs are very chatty.
        loop.call_later(0.02, self._flush)

    def publish(self, event: LogEvent) -> None:
        with self._lock:
            self._history.append(event)
            loop = self._loop
            has_clients = bool(self._clients)

        if loop is None or not has_clients:
            return

        payload = event.to_json()

        try:
            schedule = False
            with self._lock:
                self._pending.append(payload)
                # Hard cap to avoid unbounded growth if a client is slow.
                while len(self._pending) > 5000:
                    self._pending.popleft()

                if not self._flush_scheduled:
                    self._flush_scheduled = True
                    schedule = True

            if schedule:
                loop.call_soon_threadsafe(self._flush)
        except Exception:
            # Event loop is gone/shutting down.
            pass

    def log(self, task: str, line: str) -> None:
        self.publish(LogEvent(ts=time.time(), task=task, line=line, kind="log"))

    def status(self, task: str, line: str) -> None:
        self.publish(LogEvent(ts=time.time(), task=task, line=line, kind="status"))
