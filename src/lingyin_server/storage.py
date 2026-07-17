from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any


class Store:
    def __init__(self, database: Path, upload_ttl_hours: int, job_ttl_days: int):
        self.database = database
        self.upload_ttl_seconds = upload_ttl_hours * 3600
        self.job_ttl_seconds = job_ttl_days * 86400
        self._lock = Lock()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    context TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
                """
            )

    def add_upload(self, path: Path, original_name: str, size_bytes: int) -> str:
        upload_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?)",
                (upload_id, str(path), original_name, size_bytes, now, now + self.upload_ttl_seconds),
            )
        return upload_id

    def get_upload(self, upload_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM uploads WHERE id = ? AND expires_at > ?", (upload_id, time.time())
            ).fetchone()
        return dict(row) if row else None

    def delete_upload(self, upload_id: str) -> None:
        row = self.get_upload(upload_id)
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
        if row:
            Path(row["path"]).unlink(missing_ok=True)

    def create_job(self, source_kind: str, source_value: str, context: str) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, 'queued', NULL, NULL, ?, ?)",
                (job_id, source_kind, source_value, context[:2000], now, now),
            )
        return job_id

    def set_status(self, job_id: str, status: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (status, time.time(), job_id))

    def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        payload = json.dumps(result, ensure_ascii=False)
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = 'done', result_json = ?, error = NULL, updated_at = ? WHERE id = ?",
                (payload, time.time(), job_id),
            )

    def set_error(self, job_id: str, message: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = 'error', error = ?, updated_at = ? WHERE id = ?",
                (message[:1000], time.time(), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["result"] = json.loads(payload.pop("result_json")) if payload.get("result_json") else None
        payload.pop("source_value", None)
        payload.pop("context", None)
        return payload

    def job_source(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def recover_pending(self) -> list[str]:
        with self._lock, self._connect() as db:
            db.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
            rows = db.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at").fetchall()
        return [str(row["id"]) for row in rows]

    def cleanup(self) -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            uploads = db.execute("SELECT path FROM uploads WHERE expires_at <= ?", (now,)).fetchall()
            db.execute("DELETE FROM uploads WHERE expires_at <= ?", (now,))
            db.execute("DELETE FROM jobs WHERE updated_at <= ?", (now - self.job_ttl_seconds,))
        for row in uploads:
            Path(row["path"]).unlink(missing_ok=True)

