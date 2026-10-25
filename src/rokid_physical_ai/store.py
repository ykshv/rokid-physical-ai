"""Durable operations: a restart never implies permission to repeat a movement."""

import hashlib
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from .contracts import TaskExecution, TaskState


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pairing(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS task_events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                at REAL NOT NULL, state TEXT NOT NULL, reason TEXT);
        """)
        self.db.commit()

    def recover(self) -> None:
        for task in self.tasks():
            if task.state in (TaskState.EXECUTING, TaskState.PROPOSED):
                self.put(
                    task.model_copy(
                        update={
                            "state": TaskState.UNCERTAIN
                            if task.state == TaskState.EXECUTING
                            else TaskState.CANCELLED,
                            "reason": "server_restarted_manual_reconciliation_required",
                            "updated_at": time.time(),
                        }
                    )
                )

    def put(self, task: TaskExecution) -> None:
        with self.lock, self.db:
            previous = self.db.execute("SELECT body FROM tasks WHERE id=?", (task.id,)).fetchone()
            self.db.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?, ?)", (task.id, task.model_dump_json())
            )
            if (
                previous is None
                or TaskExecution.model_validate_json(previous[0]).state != task.state
            ):
                self.db.execute(
                    "INSERT INTO task_events(task_id,at,state,reason) VALUES (?,?,?,?)",
                    (task.id, task.updated_at, task.state, task.reason),
                )

    def get(self, task_id: str) -> TaskExecution:
        with self.lock:
            row = self.db.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return TaskExecution.model_validate_json(row[0])

    def tasks(self) -> list[TaskExecution]:
        with self.lock:
            rows = self.db.execute("SELECT body FROM tasks").fetchall()
        return [TaskExecution.model_validate_json(row[0]) for row in rows]

    def pairing_code(self) -> str:
        code = secrets.token_urlsafe(24)
        with self.lock, self.db:
            self.db.execute("DELETE FROM pairing WHERE expires < ?", (time.time(),))
            self.db.execute("INSERT INTO pairing VALUES (?, ?)", (digest(code), time.time() + 300))
        return code

    def pair(self, code: str) -> tuple[str, str]:
        device_id, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        with self.lock, self.db:
            deleted = self.db.execute(
                "DELETE FROM pairing WHERE hash=? AND expires > ?", (digest(code), time.time())
            )
            if deleted.rowcount != 1:
                raise ValueError("invalid_or_expired_pairing_code")
            self.db.execute("INSERT INTO devices VALUES (?, ?)", (device_id, digest(token)))
        return device_id, token

    def authenticate(self, token: str) -> str | None:
        with self.lock:
            row = self.db.execute(
                "SELECT id FROM devices WHERE hash=?", (digest(token),)
            ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.db.close()
