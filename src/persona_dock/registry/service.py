from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .database import RegistryDatabase, registry_database
from .models import BindingRecord, PersonaRecord, RuntimeInstanceRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stable_instance_id(
    adapter: str,
    transport: str,
    platform_instance_id: str,
    location: str,
) -> str:
    value = "\x1f".join((adapter, transport, platform_instance_id, location))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"personadock:runtime:{value}"))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _persona(row: Any) -> PersonaRecord:
    return PersonaRecord(
        id=row["id"],
        name=row["name"],
        version=row["version"],
        source_path=row["source_path"],
        schema_version=int(row["schema_version"]),
        summary=row["summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _instance(row: Any) -> RuntimeInstanceRecord:
    return RuntimeInstanceRecord(
        id=row["id"],
        adapter=row["adapter"],
        transport=row["transport"],
        platform_instance_id=row["platform_instance_id"],
        display_name=row["display_name"],
        location=row["location"],
        capabilities=json.loads(row["capabilities_json"]),
        metadata=json.loads(row["metadata_json"]),
        managed=bool(row["managed"]),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
    )


def _binding(row: Any) -> BindingRecord:
    return BindingRecord(
        id=row["id"],
        persona_id=row["persona_id"],
        runtime_instance_id=row["runtime_instance_id"],
        adopted=bool(row["adopted"]),
        sync_policy_id=row["sync_policy_id"],
        last_deployed_version=row["last_deployed_version"],
        managed_since=row["managed_since"],
        last_synced_at=row["last_synced_at"],
    )


class RegistryService:
    def __init__(self, database: RegistryDatabase | None = None) -> None:
        self.database = database or registry_database()
        self.database.initialize()

    def register_persona(
        self,
        *,
        persona_id: str,
        name: str,
        version: str,
        source_path: str | Path | None,
        schema_version: int,
        summary: str = "",
    ) -> PersonaRecord:
        now = utc_now()
        source = str(Path(source_path).expanduser().resolve()) if source_path else None
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO personas(
                    id, name, version, source_path, schema_version, summary,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    version = excluded.version,
                    source_path = excluded.source_path,
                    schema_version = excluded.schema_version,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (persona_id, name, version, source, schema_version, summary, now, now),
            )
            row = connection.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        assert row is not None
        return _persona(row)

    def list_personas(self) -> list[PersonaRecord]:
        with self.database.session() as connection:
            rows = connection.execute("SELECT * FROM personas ORDER BY name COLLATE NOCASE, id").fetchall()
        return [_persona(row) for row in rows]

    def get_persona(self, persona_id: str) -> PersonaRecord | None:
        with self.database.session() as connection:
            row = connection.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        return _persona(row) if row else None

    def upsert_runtime_instance(
        self,
        *,
        adapter: str,
        transport: str,
        platform_instance_id: str,
        display_name: str,
        location: str,
        capabilities: dict[str, Any],
        metadata: dict[str, Any],
    ) -> RuntimeInstanceRecord:
        now = utc_now()
        instance_id = stable_instance_id(adapter, transport, platform_instance_id, location)
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO runtime_instances(
                    id, adapter, transport, platform_instance_id, display_name,
                    location, capabilities_json, metadata_json, managed,
                    first_seen_at, last_seen_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(adapter, transport, platform_instance_id, location)
                DO UPDATE SET
                    display_name = excluded.display_name,
                    capabilities_json = excluded.capabilities_json,
                    metadata_json = excluded.metadata_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    instance_id,
                    adapter,
                    transport,
                    platform_instance_id,
                    display_name,
                    location,
                    _json(capabilities),
                    _json(metadata),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM runtime_instances
                WHERE adapter = ? AND transport = ?
                  AND platform_instance_id = ? AND location = ?
                """,
                (adapter, transport, platform_instance_id, location),
            ).fetchone()
        assert row is not None
        return _instance(row)

    def upsert_runtime_instances(
        self,
        values: Iterable[dict[str, Any]],
    ) -> list[RuntimeInstanceRecord]:
        return [self.upsert_runtime_instance(**value) for value in values]

    def list_runtime_instances(
        self,
        *,
        adapter: str | None = None,
        managed: bool | None = None,
    ) -> list[RuntimeInstanceRecord]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if adapter:
            clauses.append("adapter = ?")
            parameters.append(adapter)
        if managed is not None:
            clauses.append("managed = ?")
            parameters.append(int(managed))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM runtime_instances"
                + where
                + " ORDER BY adapter, display_name COLLATE NOCASE, platform_instance_id",
                parameters,
            ).fetchall()
        return [_instance(row) for row in rows]

    def get_runtime_instance(self, instance_id: str) -> RuntimeInstanceRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_instances WHERE id = ?", (instance_id,)
            ).fetchone()
        return _instance(row) if row else None

    def bind(
        self,
        persona_id: str,
        runtime_instance_id: str,
        *,
        adopted: bool = False,
        sync_policy_id: str | None = None,
    ) -> BindingRecord:
        now = utc_now()
        binding_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"personadock:binding:{persona_id}:{runtime_instance_id}",
            )
        )
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO bindings(
                    id, persona_id, runtime_instance_id, adopted,
                    sync_policy_id, managed_since
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(persona_id, runtime_instance_id) DO UPDATE SET
                    adopted = excluded.adopted,
                    sync_policy_id = excluded.sync_policy_id
                """,
                (
                    binding_id,
                    persona_id,
                    runtime_instance_id,
                    int(adopted),
                    sync_policy_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE runtime_instances SET managed = 1 WHERE id = ?",
                (runtime_instance_id,),
            )
            row = connection.execute("SELECT * FROM bindings WHERE id = ?", (binding_id,)).fetchone()
        assert row is not None
        self.journal(
            "instance-bound",
            persona_id=persona_id,
            runtime_instance_id=runtime_instance_id,
            payload={"adopted": adopted, "sync_policy_id": sync_policy_id},
        )
        return _binding(row)

    def list_bindings(self, persona_id: str | None = None) -> list[BindingRecord]:
        query = "SELECT * FROM bindings"
        parameters: tuple[Any, ...] = ()
        if persona_id:
            query += " WHERE persona_id = ?"
            parameters = (persona_id,)
        query += " ORDER BY managed_since, id"
        with self.database.session() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_binding(row) for row in rows]

    def journal(
        self,
        event_type: str,
        *,
        persona_id: str | None = None,
        runtime_instance_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO journal_events(
                    id, event_type, persona_id, runtime_instance_id,
                    payload_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    persona_id,
                    runtime_instance_id,
                    _json(payload or {}),
                    utc_now(),
                ),
            )
        return event_id

    def summary(self) -> dict[str, Any]:
        with self.database.session() as connection:
            counts = {
                "personas": connection.execute("SELECT COUNT(*) FROM personas").fetchone()[0],
                "instances": connection.execute("SELECT COUNT(*) FROM runtime_instances").fetchone()[0],
                "managed_instances": connection.execute(
                    "SELECT COUNT(*) FROM runtime_instances WHERE managed = 1"
                ).fetchone()[0],
                "bindings": connection.execute("SELECT COUNT(*) FROM bindings").fetchone()[0],
                "snapshots": connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
                "journal_events": connection.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0],
            }
        return {"schema_version": self.database.schema_version(), **counts}
