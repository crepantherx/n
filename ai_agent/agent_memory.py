#!/usr/bin/env python3
"""
Agent Memory — SQLite-backed persistent memory for the AI job application agent.

Tracks:
  - Applied jobs (deduplication + audit trail)
  - Agent decisions (why it applied/skipped each job)
  - Run history (stats per cycle)

Zero external dependencies — uses Python's built-in sqlite3 module.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [memory] {msg}")


# ---------------------------------------------------------------------------
# Default DB path
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(os.getenv("NAUKRI_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))) / "agent_memory.db"


class AgentMemory:
    """
    Thread-safe SQLite memory for the AI agent.

    Stores applied jobs, decisions, and run history.
    Each method creates its own connection for thread safety.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe)."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent reads
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS applied_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT NOT NULL,
                        url_hash TEXT NOT NULL,
                        title TEXT DEFAULT '',
                        company TEXT DEFAULT '',
                        platform TEXT DEFAULT '',
                        match_score REAL DEFAULT 0,
                        status TEXT DEFAULT 'applied',
                        cover_letter TEXT DEFAULT '',
                        jd_summary TEXT DEFAULT '',
                        applied_at TEXT NOT NULL,
                        UNIQUE(url_hash)
                    );

                    CREATE TABLE IF NOT EXISTS agent_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_url TEXT NOT NULL,
                        job_title TEXT DEFAULT '',
                        company TEXT DEFAULT '',
                        platform TEXT DEFAULT '',
                        decision TEXT NOT NULL,
                        match_score REAL DEFAULT 0,
                        reasoning TEXT DEFAULT '',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS agent_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform TEXT DEFAULT '',
                        start_time TEXT NOT NULL,
                        end_time TEXT DEFAULT '',
                        jobs_found INTEGER DEFAULT 0,
                        jobs_analyzed INTEGER DEFAULT 0,
                        jobs_applied INTEGER DEFAULT 0,
                        jobs_skipped INTEGER DEFAULT 0,
                        jobs_error INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'running'
                    );

                    CREATE TABLE IF NOT EXISTS review_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_url TEXT NOT NULL,
                        job_title TEXT DEFAULT '',
                        company TEXT DEFAULT '',
                        platform TEXT DEFAULT '',
                        match_score REAL DEFAULT 0,
                        reasoning TEXT DEFAULT '',
                        jd_text TEXT DEFAULT '',
                        cover_letter TEXT DEFAULT '',
                        status TEXT DEFAULT 'pending',
                        created_at TEXT NOT NULL,
                        reviewed_at TEXT DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS idx_applied_hash ON applied_jobs(url_hash);
                    CREATE INDEX IF NOT EXISTS idx_decisions_url ON agent_decisions(job_url);
                    CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status);
                """)
                conn.commit()
                _log(f"Database initialized: {self.db_path}")
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # URL hashing (for dedup)
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_url(url: str) -> str:
        """Create a stable hash for a job URL (strips query params for dedup)."""
        import hashlib
        # Normalize: strip trailing slash, lowercase
        normalized = url.rstrip("/").lower().split("?")[0]
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Applied Jobs
    # ------------------------------------------------------------------

    def was_already_applied(self, url: str) -> bool:
        """Check if we already applied to this job URL."""
        url_hash = self._hash_url(url)
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM applied_jobs WHERE url_hash = ?", (url_hash,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def log_application(
        self,
        url: str,
        title: str = "",
        company: str = "",
        platform: str = "",
        match_score: float = 0,
        cover_letter: str = "",
        jd_summary: str = "",
        status: str = "applied",
    ) -> None:
        """Record a successful job application."""
        url_hash = self._hash_url(url)
        now = datetime.now().isoformat()

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO applied_jobs
                       (url, url_hash, title, company, platform, match_score,
                        status, cover_letter, jd_summary, applied_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (url, url_hash, title, company, platform, match_score,
                     status, cover_letter, jd_summary, now),
                )
                conn.commit()
                _log(f"Logged application: {company} — {title}")
            finally:
                conn.close()

    def get_applied_jobs(self, limit: int = 100, platform: str = "") -> list[dict]:
        """Get recent applied jobs."""
        conn = self._get_conn()
        try:
            if platform:
                rows = conn.execute(
                    "SELECT * FROM applied_jobs WHERE platform = ? ORDER BY applied_at DESC LIMIT ?",
                    (platform, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM applied_jobs ORDER BY applied_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Agent Decisions
    # ------------------------------------------------------------------

    def log_decision(
        self,
        job_url: str,
        decision: str,
        *,
        job_title: str = "",
        company: str = "",
        platform: str = "",
        match_score: float = 0,
        reasoning: str = "",
    ) -> None:
        """Record an agent decision (APPLY/SKIP/REVIEW)."""
        now = datetime.now().isoformat()

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO agent_decisions
                       (job_url, job_title, company, platform, decision,
                        match_score, reasoning, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job_url, job_title, company, platform, decision,
                     match_score, reasoning, now),
                )
                conn.commit()
            finally:
                conn.close()

    def get_decisions(self, limit: int = 100, platform: str = "") -> list[dict]:
        """Get recent agent decisions."""
        conn = self._get_conn()
        try:
            if platform:
                rows = conn.execute(
                    "SELECT * FROM agent_decisions WHERE platform = ? ORDER BY created_at DESC LIMIT ?",
                    (platform, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_decisions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Run History
    # ------------------------------------------------------------------

    def start_run(self, platform: str = "") -> int:
        """Start a new agent run and return its ID."""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "INSERT INTO agent_runs (platform, start_time) VALUES (?, ?)",
                    (platform, now),
                )
                conn.commit()
                run_id = cursor.lastrowid
                _log(f"Started run #{run_id} on {platform}")
                return run_id
            finally:
                conn.close()

    def update_run(self, run_id: int, **kwargs) -> None:
        """Update run stats."""
        allowed = {
            "jobs_found", "jobs_analyzed", "jobs_applied",
            "jobs_skipped", "jobs_error", "status", "end_time",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [run_id]

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    f"UPDATE agent_runs SET {set_clause} WHERE id = ?",
                    values,
                )
                conn.commit()
            finally:
                conn.close()

    def end_run(self, run_id: int, **kwargs) -> None:
        """End a run and set final stats."""
        kwargs["end_time"] = datetime.now().isoformat()
        kwargs["status"] = kwargs.get("status", "completed")
        self.update_run(run_id, **kwargs)
        _log(f"Ended run #{run_id}")

    def get_runs(self, limit: int = 20) -> list[dict]:
        """Get recent runs."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY start_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Review Queue
    # ------------------------------------------------------------------

    def queue_for_review(
        self,
        job_url: str,
        *,
        job_title: str = "",
        company: str = "",
        platform: str = "",
        match_score: float = 0,
        reasoning: str = "",
        jd_text: str = "",
        cover_letter: str = "",
    ) -> int:
        """Add a job to the review queue. Returns the queue item ID."""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """INSERT INTO review_queue
                       (job_url, job_title, company, platform, match_score,
                        reasoning, jd_text, cover_letter, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                    (job_url, job_title, company, platform, match_score,
                     reasoning, jd_text, cover_letter, now),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_review_queue(self, status: str = "pending") -> list[dict]:
        """Get review queue items by status."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM review_queue WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def approve_review(self, item_id: int) -> None:
        """Approve a queued job for application."""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE review_queue SET status = 'approved', reviewed_at = ? WHERE id = ?",
                    (now, item_id),
                )
                conn.commit()
            finally:
                conn.close()

    def reject_review(self, item_id: int) -> None:
        """Reject a queued job."""
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE review_queue SET status = 'rejected', reviewed_at = ? WHERE id = ?",
                    (now, item_id),
                )
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate stats for the dashboard."""
        conn = self._get_conn()
        try:
            total_applied = conn.execute(
                "SELECT COUNT(*) FROM applied_jobs"
            ).fetchone()[0]

            today = datetime.now().strftime("%Y-%m-%d")
            today_applied = conn.execute(
                "SELECT COUNT(*) FROM applied_jobs WHERE applied_at LIKE ?",
                (f"{today}%",),
            ).fetchone()[0]

            total_skipped = conn.execute(
                "SELECT COUNT(*) FROM agent_decisions WHERE decision = 'SKIP'"
            ).fetchone()[0]

            total_reviewed = conn.execute(
                "SELECT COUNT(*) FROM agent_decisions"
            ).fetchone()[0]

            avg_score = conn.execute(
                "SELECT AVG(match_score) FROM applied_jobs WHERE match_score > 0"
            ).fetchone()[0] or 0

            pending_reviews = conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status = 'pending'"
            ).fetchone()[0]

            # Platform breakdown
            platform_stats = {}
            for row in conn.execute(
                "SELECT platform, COUNT(*) as cnt FROM applied_jobs GROUP BY platform"
            ).fetchall():
                platform_stats[row["platform"]] = row["cnt"]

            # Recent runs
            last_run = conn.execute(
                "SELECT * FROM agent_runs ORDER BY start_time DESC LIMIT 1"
            ).fetchone()

            return {
                "total_applied": total_applied,
                "today_applied": today_applied,
                "total_skipped": total_skipped,
                "total_analyzed": total_reviewed,
                "avg_match_score": round(avg_score, 1),
                "pending_reviews": pending_reviews,
                "by_platform": platform_stats,
                "last_run": dict(last_run) if last_run else None,
            }
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mem = AgentMemory()
    print("Stats:", json.dumps(mem.get_stats(), indent=2))
    print(f"DB at: {mem.db_path}")
