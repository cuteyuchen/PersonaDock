from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from persona_dock.registry import RegistryService
from persona_dock.sync_models import (
    DEFAULT_SYNC_POLICY,
    MemoryItemRecord,
    SyncConflictRecord,
    SyncPolicyRecord,
    deep_merge_policy,
    validate_policy,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _policy(row: sqlite3.Row) -> SyncPolicyRecord:
    return SyncPolicyRecord(
        id=str(row["id"]),
        persona_id=str(row["persona_id"]),
        config=json.loads(row["config_json"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _memory(row: sqlite3.Row) -> MemoryItemRecord:
    return MemoryItemRecord(
        id=str(row["id"]),
        persona_id=str(row["persona_id"]),
        fingerprint=str(row["fingerprint"]),
        memory_key=str(row["memory_key"]),
        memory_type=str(row["memory_type"]),
        summary=str(row["summary"]),
        sensitivity=str(row["sensitivity"]),
        sync_scope=str(row["sync_scope"]),
        status=str(row["status"]),
        source_adapter=str(row["source_adapter"]) if row["source_adapter"] else None,
        source_runtime_instance_id=(
            str(row["source_runtime_instance_id"])
            if row["source_runtime_instance_id"]
            else None
        ),
        source_record_id=str(row["source_record_id"]) if row["source_record_id"] else None,
        source_path=str(row["source_path"]) if row["source_path"] else None,
        metadata=json.loads(row["metadata_json"]),
        reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] else None,
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _conflict(row: sqlite3.Row) -> SyncConflictRecord:
    return SyncConflictRecord(
        id=str(row["id"]),
        persona_id=str(row["persona_id"]),
        candidate_id=str(row["candidate_id"]),
        existing_item_id=str(row["existing_item_id"]) if row["existing_item_id"] else None,
        conflict_type=str(row["conflict_type"]),
        status=str(row["status"]),
        resolution=str(row["resolution"]) if row["resolution"] else None,
        details=json.loads(row["details_json"]),
        created_at=str(row["created_at"]),
        resolved_at=str(row["resolved_at"]) if row["resolved_at"] else None,
    )


class SyncRegistry:
    def __init__(self, registry: RegistryService | None = None) -> None:
        self.registry = registry or RegistryService()
        self.registry.database.initialize()

    def get_policy(self, persona_id: str) -> SyncPolicyRecord:
        if self.registry.get_persona(persona_id) is None:
            raise ValueError(f"persona is not registered: {persona_id}")
        with self.registry.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM sync_policies WHERE persona_id = ?",
                (persona_id,),
            ).fetchone()
            if row is not None:
                return _policy(row)
            now = _utc_now()
            policy_id = str(uuid.uuid4())
            config = validate_policy(DEFAULT_SYNC_POLICY)
            connection.execute(
                """
                INSERT INTO sync_policies(id, persona_id, config_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    persona_id,
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sync_policies WHERE id = ?",
                (policy_id,),
            ).fetchone()
            assert row is not None
            return _policy(row)

    def set_policy(
        self,
        persona_id: str,
        config: dict[str, Any],
        *,
        replace: bool = False,
    ) -> SyncPolicyRecord:
        current = self.get_policy(persona_id)
        resolved = validate_policy(
            config if replace else deep_merge_policy(current.config, config)
        )
        now = _utc_now()
        with self.registry.database.session() as connection:
            connection.execute(
                "UPDATE sync_policies SET config_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(resolved, ensure_ascii=False, sort_keys=True),
                    now,
                    current.id,
                ),
            )
        self.registry.journal(
            "sync-policy-updated",
            persona_id=persona_id,
            payload={"policy_id": current.id, "config": resolved},
        )
        return self.get_policy(persona_id)

    def upsert_memory_item(
        self,
        *,
        persona_id: str,
        fingerprint: str,
        memory_key: str,
        memory_type: str,
        summary: str,
        sensitivity: str,
        sync_scope: str,
        status: str,
        source_adapter: str | None,
        source_runtime_instance_id: str | None,
        source_record_id: str | None,
        source_path: str | None,
        metadata: dict[str, Any],
        reviewed_at: str | None = None,
        reviewed_by: str | None = None,
    ) -> tuple[MemoryItemRecord, bool]:
        now = _utc_now()
        item_id = str(uuid.uuid4())
        with self.registry.database.session() as connection:
            existing = connection.execute(
                "SELECT * FROM memory_items WHERE persona_id = ? AND fingerprint = ?",
                (persona_id, fingerprint),
            ).fetchone()
            if existing is not None:
                return _memory(existing), False
            connection.execute(
                """
                INSERT INTO memory_items(
                    id, persona_id, fingerprint, memory_key, memory_type, summary,
                    sensitivity, sync_scope, status, source_adapter,
                    source_runtime_instance_id, source_record_id, source_path,
                    metadata_json, reviewed_at, reviewed_by, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    persona_id,
                    fingerprint,
                    memory_key,
                    memory_type,
                    summary,
                    sensitivity,
                    sync_scope,
                    status,
                    source_adapter,
                    source_runtime_instance_id,
                    source_record_id,
                    source_path,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    reviewed_at,
                    reviewed_by,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            assert row is not None
            return _memory(row), True

    def get_memory_item(self, item_id: str) -> MemoryItemRecord | None:
        with self.registry.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        return _memory(row) if row is not None else None

    def list_memory_items(
        self,
        persona_id: str,
        *,
        status: str | None = None,
        sensitivity: str | None = None,
        source_adapter: str | None = None,
    ) -> list[MemoryItemRecord]:
        clauses = ["persona_id = ?"]
        values: list[Any] = [persona_id]
        if status:
            clauses.append("status = ?")
            values.append(status)
        if sensitivity:
            clauses.append("sensitivity = ?")
            values.append(sensitivity)
        if source_adapter:
            clauses.append("source_adapter = ?")
            values.append(source_adapter)
        query = (
            "SELECT * FROM memory_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at, id"
        )
        with self.registry.database.session() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [_memory(row) for row in rows]

    def approved_by_key(
        self,
        persona_id: str,
        memory_key: str,
        *,
        excluding_fingerprint: str | None = None,
    ) -> list[MemoryItemRecord]:
        query = "SELECT * FROM memory_items WHERE persona_id = ? AND memory_key = ? AND status = 'approved'"
        values: list[Any] = [persona_id, memory_key]
        if excluding_fingerprint:
            query += " AND fingerprint != ?"
            values.append(excluding_fingerprint)
        query += " ORDER BY updated_at DESC"
        with self.registry.database.session() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [_memory(row) for row in rows]

    def update_memory_status(
        self,
        item_id: str,
        status: str,
        *,
        reviewed_by: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
        memory_key: str | None = None,
    ) -> MemoryItemRecord:
        current = self.get_memory_item(item_id)
        if current is None:
            raise ValueError(f"memory item not found: {item_id}")
        metadata = dict(current.metadata)
        if metadata_patch:
            metadata.update(metadata_patch)
        now = _utc_now()
        reviewed_at = now if status in {"approved", "rejected", "superseded"} else current.reviewed_at
        with self.registry.database.session() as connection:
            connection.execute(
                """
                UPDATE memory_items
                SET status = ?, reviewed_at = ?, reviewed_by = ?, metadata_json = ?,
                    memory_key = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    reviewed_at,
                    reviewed_by or current.reviewed_by,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    memory_key or current.memory_key,
                    now,
                    item_id,
                ),
            )
        value = self.get_memory_item(item_id)
        assert value is not None
        return value

    def create_conflict(
        self,
        *,
        persona_id: str,
        candidate_id: str,
        existing_item_id: str | None,
        conflict_type: str,
        details: dict[str, Any],
    ) -> SyncConflictRecord:
        conflict_id = str(uuid.uuid4())
        now = _utc_now()
        with self.registry.database.session() as connection:
            existing = connection.execute(
                """
                SELECT * FROM sync_conflicts
                WHERE persona_id = ? AND candidate_id = ? AND conflict_type = ?
                  AND existing_item_id IS ?
                """,
                (persona_id, candidate_id, conflict_type, existing_item_id),
            ).fetchone()
            if existing is not None:
                return _conflict(existing)
            connection.execute(
                """
                INSERT INTO sync_conflicts(
                    id, persona_id, candidate_id, existing_item_id, conflict_type,
                    status, resolution, details_json, created_at, resolved_at
                ) VALUES(?, ?, ?, ?, ?, 'pending', NULL, ?, ?, NULL)
                """,
                (
                    conflict_id,
                    persona_id,
                    candidate_id,
                    existing_item_id,
                    conflict_type,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sync_conflicts WHERE id = ?",
                (conflict_id,),
            ).fetchone()
            assert row is not None
            return _conflict(row)

    def get_conflict(self, conflict_id: str) -> SyncConflictRecord | None:
        with self.registry.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM sync_conflicts WHERE id = ?",
                (conflict_id,),
            ).fetchone()
        return _conflict(row) if row is not None else None

    def list_conflicts(
        self,
        persona_id: str,
        *,
        status: str | None = None,
    ) -> list[SyncConflictRecord]:
        query = "SELECT * FROM sync_conflicts WHERE persona_id = ?"
        values: list[Any] = [persona_id]
        if status:
            query += " AND status = ?"
            values.append(status)
        query += " ORDER BY created_at, id"
        with self.registry.database.session() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [_conflict(row) for row in rows]

    def resolve_conflict(self, conflict_id: str, resolution: str) -> SyncConflictRecord:
        current = self.get_conflict(conflict_id)
        if current is None:
            raise ValueError(f"sync conflict not found: {conflict_id}")
        with self.registry.database.session() as connection:
            connection.execute(
                """
                UPDATE sync_conflicts
                SET status = 'resolved', resolution = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resolution, _utc_now(), conflict_id),
            )
        result = self.get_conflict(conflict_id)
        assert result is not None
        return result

    def unresolved_conflict_item_ids(self, persona_id: str) -> set[str]:
        with self.registry.database.session() as connection:
            rows = connection.execute(
                """
                SELECT candidate_id FROM sync_conflicts
                WHERE persona_id = ? AND status = 'pending'
                """,
                (persona_id,),
            ).fetchall()
        return {str(row["candidate_id"]) for row in rows}

    def was_propagated(
        self,
        memory_item_id: str,
        destination_runtime_instance_id: str,
        content_hash: str,
        operation: str = "memory-push",
    ) -> bool:
        with self.registry.database.session() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM propagation_log
                WHERE memory_item_id = ? AND destination_runtime_instance_id = ?
                  AND content_hash = ? AND operation = ? AND status = 'success'
                """,
                (
                    memory_item_id,
                    destination_runtime_instance_id,
                    content_hash,
                    operation,
                ),
            ).fetchone()
        return row is not None

    def record_propagation(
        self,
        *,
        persona_id: str,
        memory_item_id: str,
        source_runtime_instance_id: str | None,
        destination_runtime_instance_id: str,
        content_hash: str,
        operation: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        with self.registry.database.session() as connection:
            connection.execute(
                """
                INSERT INTO propagation_log(
                    id, persona_id, memory_item_id, source_runtime_instance_id,
                    destination_runtime_instance_id, content_hash, operation,
                    status, details_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_item_id, destination_runtime_instance_id, content_hash, operation)
                DO UPDATE SET status = excluded.status,
                              details_json = excluded.details_json,
                              created_at = excluded.created_at
                """,
                (
                    str(uuid.uuid4()),
                    persona_id,
                    memory_item_id,
                    source_runtime_instance_id,
                    destination_runtime_instance_id,
                    content_hash,
                    operation,
                    status,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    _utc_now(),
                ),
            )

    def propagated_back_to_source(
        self,
        persona_id: str,
        source_runtime_instance_id: str,
        content_hash: str,
    ) -> bool:
        with self.registry.database.session() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM propagation_log
                WHERE persona_id = ? AND destination_runtime_instance_id = ?
                  AND content_hash = ? AND status = 'success'
                """,
                (persona_id, source_runtime_instance_id, content_hash),
            ).fetchone()
        return row is not None

    def create_run(
        self,
        *,
        persona_id: str,
        operation: str,
        plan: dict[str, Any],
    ) -> str:
        run_id = str(uuid.uuid4())
        with self.registry.database.session() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs(
                    id, persona_id, operation, status, plan_json,
                    result_json, created_at, completed_at
                ) VALUES(?, ?, ?, 'planned', ?, '{}', ?, NULL)
                """,
                (
                    run_id,
                    persona_id,
                    operation,
                    json.dumps(plan, ensure_ascii=False, sort_keys=True),
                    _utc_now(),
                ),
            )
        return run_id

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> None:
        with self.registry.database.session() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET status = ?, result_json = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    _utc_now(),
                    run_id,
                ),
            )

    def list_runs(self, persona_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.registry.database.session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sync_runs
                WHERE persona_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (persona_id, limit),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "persona_id": str(row["persona_id"]),
                "operation": str(row["operation"]),
                "status": str(row["status"]),
                "plan": json.loads(row["plan_json"]),
                "result": json.loads(row["result_json"]),
                "created_at": str(row["created_at"]),
                "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
            }
            for row in rows
        ]

    def propagation_log(self, persona_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.registry.database.session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM propagation_log
                WHERE persona_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (persona_id, limit),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "persona_id": str(row["persona_id"]),
                "memory_item_id": str(row["memory_item_id"]),
                "source_runtime_instance_id": (
                    str(row["source_runtime_instance_id"])
                    if row["source_runtime_instance_id"]
                    else None
                ),
                "destination_runtime_instance_id": str(row["destination_runtime_instance_id"]),
                "content_hash": str(row["content_hash"]),
                "operation": str(row["operation"]),
                "status": str(row["status"]),
                "details": json.loads(row["details_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def update_binding_sync_time(self, binding_ids: Iterable[str]) -> None:
        values = list(binding_ids)
        if not values:
            return
        now = _utc_now()
        with self.registry.database.session() as connection:
            connection.executemany(
                "UPDATE bindings SET last_synced_at = ? WHERE id = ?",
                [(now, value) for value in values],
            )
