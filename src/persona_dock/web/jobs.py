from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_dock.registry.database import registry_root

JobStatus = Literal[
    "queued",
    "running",
    "waiting-review",
    "success",
    "failed",
    "cancelled",
]

TERMINAL_JOB_STATUSES = frozenset({"success", "failed", "cancelled"})
JOB_STATUSES = frozenset(
    {"queued", "running", "waiting-review", "success", "failed", "cancelled"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def control_plane_database_path() -> Path:
    return registry_root() / "control-plane.db"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    kind: str
    label: str
    status: JobStatus
    progress: int
    input: dict[str, Any]
    output: dict[str, Any]
    error: str | None
    persona_id: str | None
    runtime_instance_id: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class JobEvent:
    id: int
    job_id: str
    level: str
    message: str
    data: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    error TEXT,
    persona_id TEXT,
    runtime_instance_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS web_job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES web_jobs(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_web_jobs_created
    ON web_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_web_jobs_status
    ON web_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_web_job_events_job
    ON web_job_events(job_id, id);
"""


def _record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        kind=row["kind"],
        label=row["label"],
        status=row["status"],
        progress=int(row["progress"]),
        input=_load(row["input_json"], {}),
        output=_load(row["output_json"], {}),
        error=row["error"],
        persona_id=row["persona_id"],
        runtime_instance_id=row["runtime_instance_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _event(row: sqlite3.Row) -> JobEvent:
    return JobEvent(
        id=int(row["id"]),
        job_id=row["job_id"],
        level=row["level"],
        message=row["message"],
        data=_load(row["data_json"], {}),
        created_at=row["created_at"],
    )


class JobStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else control_plane_database_path()
        self.path = self.path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def create(
        self,
        *,
        kind: str,
        label: str,
        input: dict[str, Any] | None = None,
        persona_id: str | None = None,
        runtime_instance_id: str | None = None,
    ) -> JobRecord:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO web_jobs(
                    id, kind, label, status, progress, input_json, output_json,
                    persona_id, runtime_instance_id, created_at, updated_at
                ) VALUES(?, ?, ?, 'queued', 0, ?, '{}', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    label,
                    _dump(input or {}),
                    persona_id,
                    runtime_instance_id,
                    now,
                    now,
                ),
            )
        self.append_event(job_id, "info", "任务已进入队列", {"status": "queued"})
        value = self.get(job_id)
        assert value is not None
        return value

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM web_jobs WHERE id = ?", (job_id,)).fetchone()
        return _record(row) if row else None

    def list(
        self,
        *,
        limit: int = 50,
        status: JobStatus | None = None,
    ) -> list[JobRecord]:
        limit = max(1, min(int(limit), 200))
        query = "SELECT * FROM web_jobs"
        parameters: list[Any] = []
        if status is not None:
            if status not in JOB_STATUSES:
                raise ValueError(f"unsupported job status: {status}")
            query += " WHERE status = ?"
            parameters.append(status)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_record(row) for row in rows]

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: int | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord:
        current = self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        if status is not None and status not in JOB_STATUSES:
            raise ValueError(f"unsupported job status: {status}")
        next_status = status or current.status
        next_progress = current.progress if progress is None else max(0, min(int(progress), 100))
        now = utc_now()
        started_at = current.started_at
        finished_at = current.finished_at
        if next_status == "running" and started_at is None:
            started_at = now
        if next_status in TERMINAL_JOB_STATUSES:
            finished_at = finished_at or now
            if next_status == "success":
                next_progress = 100
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE web_jobs SET
                    status = ?, progress = ?, output_json = ?, error = ?,
                    updated_at = ?, started_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    next_status,
                    next_progress,
                    _dump(current.output if output is None else output),
                    error,
                    now,
                    started_at,
                    finished_at,
                    job_id,
                ),
            )
        if next_status != current.status:
            self.append_event(job_id, "info", f"任务状态：{next_status}", {"status": next_status})
        value = self.get(job_id)
        assert value is not None
        return value

    def cancel(self, job_id: str) -> JobRecord:
        current = self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        if current.status in TERMINAL_JOB_STATUSES:
            return current
        return self.update(job_id, status="cancelled")

    def append_event(
        self,
        job_id: str,
        level: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> JobEvent:
        if self.get(job_id) is None:
            raise KeyError(job_id)
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO web_job_events(job_id, level, message, data_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (job_id, level, message, _dump(data or {}), now),
            )
            event_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM web_job_events WHERE id = ?", (event_id,)
            ).fetchone()
        assert row is not None
        return _event(row)

    def events(
        self,
        job_id: str,
        *,
        after_id: int = 0,
        limit: int = 500,
    ) -> list[JobEvent]:
        if self.get(job_id) is None:
            raise KeyError(job_id)
        limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM web_job_events
                WHERE job_id = ? AND id > ?
                ORDER BY id ASC LIMIT ?
                """,
                (job_id, max(0, int(after_id)), limit),
            ).fetchall()
        return [_event(row) for row in rows]


__all__ = [
    "JOB_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "JobEvent",
    "JobRecord",
    "JobStatus",
    "JobStore",
    "control_plane_database_path",
]
