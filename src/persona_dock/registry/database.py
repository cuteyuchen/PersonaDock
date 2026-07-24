from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 2


def registry_root() -> Path:
    value = os.environ.get("PERSONADOCK_HOME")
    root = Path(value).expanduser() if value else Path.home() / ".personadock"
    return root.resolve()


def registry_database_path() -> Path:
    return registry_root() / "personadock.db"


_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personas (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    source_path TEXT,
    schema_version INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_instances (
    id TEXT PRIMARY KEY,
    adapter TEXT NOT NULL,
    transport TEXT NOT NULL,
    platform_instance_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    location TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    managed INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(adapter, transport, platform_instance_id, location)
);

CREATE TABLE IF NOT EXISTS bindings (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    runtime_instance_id TEXT NOT NULL REFERENCES runtime_instances(id) ON DELETE CASCADE,
    adopted INTEGER NOT NULL DEFAULT 0,
    sync_policy_id TEXT,
    last_deployed_version TEXT,
    managed_since TEXT NOT NULL,
    last_synced_at TEXT,
    UNIQUE(persona_id, runtime_instance_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    persona_id TEXT REFERENCES personas(id) ON DELETE SET NULL,
    runtime_instance_id TEXT REFERENCES runtime_instances(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    persona_id TEXT REFERENCES personas(id) ON DELETE SET NULL,
    runtime_instance_id TEXT REFERENCES runtime_instances(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_instances_adapter
    ON runtime_instances(adapter, transport);
CREATE INDEX IF NOT EXISTS idx_instances_last_seen
    ON runtime_instances(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_bindings_persona
    ON bindings(persona_id);
CREATE INDEX IF NOT EXISTS idx_journal_created
    ON journal_events(created_at);
"""


_SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_policies (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL UNIQUE REFERENCES personas(id) ON DELETE CASCADE,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    sync_scope TEXT NOT NULL,
    status TEXT NOT NULL,
    source_adapter TEXT,
    source_runtime_instance_id TEXT REFERENCES runtime_instances(id) ON DELETE SET NULL,
    source_record_id TEXT,
    source_path TEXT,
    metadata_json TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(persona_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    existing_item_id TEXT REFERENCES memory_items(id) ON DELETE SET NULL,
    conflict_type TEXT NOT NULL,
    status TEXT NOT NULL,
    resolution TEXT,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(persona_id, candidate_id, conflict_type, existing_item_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS propagation_log (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    memory_item_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    source_runtime_instance_id TEXT REFERENCES runtime_instances(id) ON DELETE SET NULL,
    destination_runtime_instance_id TEXT NOT NULL REFERENCES runtime_instances(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(memory_item_id, destination_runtime_instance_id, content_hash, operation)
);

CREATE INDEX IF NOT EXISTS idx_sync_policy_persona
    ON sync_policies(persona_id);
CREATE INDEX IF NOT EXISTS idx_memory_persona_status
    ON memory_items(persona_id, status, sensitivity);
CREATE INDEX IF NOT EXISTS idx_memory_key
    ON memory_items(persona_id, memory_key);
CREATE INDEX IF NOT EXISTS idx_conflicts_persona_status
    ON sync_conflicts(persona_id, status);
CREATE INDEX IF NOT EXISTS idx_sync_runs_persona_created
    ON sync_runs(persona_id, created_at);
CREATE INDEX IF NOT EXISTS idx_propagation_destination
    ON propagation_log(destination_runtime_instance_id, created_at);
"""


class RegistryDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or registry_database_path()).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(_BASE_SCHEMA)
            current = connection.execute(
                "SELECT value FROM registry_meta WHERE key = 'schema_version'"
            ).fetchone()
            current_version = int(current["value"]) if current is not None else 0
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"registry schema {current_version} is newer than supported {SCHEMA_VERSION}"
                )
            if current_version < 2:
                connection.executescript(_SYNC_SCHEMA)
                current_version = 2
            else:
                connection.executescript(_SYNC_SCHEMA)
            if current is None:
                connection.execute(
                    "INSERT INTO registry_meta(key, value) VALUES('schema_version', ?)",
                    (str(current_version),),
                )
            elif int(current["value"]) != current_version:
                connection.execute(
                    "UPDATE registry_meta SET value = ? WHERE key = 'schema_version'",
                    (str(current_version),),
                )

    def schema_version(self) -> int:
        self.initialize()
        with self.session() as connection:
            row = connection.execute(
                "SELECT value FROM registry_meta WHERE key = 'schema_version'"
            ).fetchone()
            return int(row["value"])


def registry_database(path: Path | None = None) -> RegistryDatabase:
    database = RegistryDatabase(path)
    database.initialize()
    return database
