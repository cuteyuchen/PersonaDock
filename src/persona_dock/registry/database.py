from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1


def registry_root() -> Path:
    value = os.environ.get("PERSONADOCK_HOME")
    root = Path(value).expanduser() if value else Path.home() / ".personadock"
    return root.resolve()


def registry_database_path() -> Path:
    return registry_root() / "personadock.db"


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
            connection.executescript(
                """
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
            )
            current = connection.execute(
                "SELECT value FROM registry_meta WHERE key = 'schema_version'"
            ).fetchone()
            if current is None:
                connection.execute(
                    "INSERT INTO registry_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(current["value"]) > SCHEMA_VERSION:
                raise RuntimeError(
                    f"registry schema {current['value']} is newer than supported {SCHEMA_VERSION}"
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
