from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.openclaw import OpenClawAdapter
from persona_dock.hermes_deployment import (
    apply_hermes_deployment,
    plan_hermes_deployment,
)
from persona_dock.hermes_memory import (
    pull_hermes_memory_candidates,
    push_hermes_shared_memory,
)
from persona_dock.io import load_jsonl, load_yaml, write_jsonl
from persona_dock.openclaw_deployment import (
    apply_openclaw_deployment,
    plan_openclaw_deployment,
)
from persona_dock.openclaw_memory import (
    pull_openclaw_memory_candidates,
    push_openclaw_shared_memory,
)
from persona_dock.packaging import pack_project
from persona_dock.project import PROJECT_FILE
from persona_dock.registry import RegistryService
from persona_dock.registry.models import BindingRecord, RuntimeInstanceRecord
from persona_dock.sync_models import (
    SENSITIVITY_RANK,
    MemoryItemRecord,
    SyncPlan,
    classify_sensitivity,
    memory_fingerprint,
    memory_key,
)
from persona_dock.sync_registry import SyncRegistry, _utc_now


class SyncError(RuntimeError):
    """Raised when a governed synchronization operation cannot be completed."""


def _persona_project(registry: RegistryService, persona_id: str) -> Path:
    persona = registry.get_persona(persona_id)
    if persona is None:
        raise SyncError(f"persona is not registered: {persona_id}")
    if not persona.source_path:
        raise SyncError(f"persona has no source project: {persona_id}")
    project = Path(persona.source_path).expanduser().resolve()
    if not (project / PROJECT_FILE).is_file():
        raise SyncError(f"persona project is missing {PROJECT_FILE}: {project}")
    return project


def _candidate_source(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("source")
    return dict(value) if isinstance(value, dict) else {}


def _source_runtime_id(
    registry: RegistryService,
    source: dict[str, Any],
) -> str | None:
    explicit = source.get("runtime_instance_id")
    if explicit and registry.get_runtime_instance(str(explicit)) is not None:
        return str(explicit)
    adapter = str(source.get("adapter") or "")
    platform_id = str(
        source.get("platform_instance_id")
        or source.get("profile")
        or source.get("agent")
        or ""
    )
    if not adapter or not platform_id:
        return None
    candidates = registry.list_runtime_instances(adapter=adapter)
    transport = str(source.get("transport") or "")
    for instance in candidates:
        if instance.platform_instance_id != platform_id:
            continue
        if transport and instance.transport != transport:
            continue
        return instance.id
    return None


def _candidate_type(record: dict[str, Any]) -> str:
    value = str(record.get("memory_type") or record.get("type") or "note")
    aliases = {
        "imported-memory-document": "document",
        "hermes-memory": "document",
        "openclaw-memory-document": "document",
    }
    return aliases.get(value, value)[:64]


def _seed_record(item: MemoryItemRecord) -> dict[str, Any]:
    source = item.metadata.get("source")
    source_refs: list[str] = []
    if item.source_path:
        source_refs.append(item.source_path)
    if item.source_record_id:
        source_refs.append(item.source_record_id)
    return {
        "id": f"sync-{item.fingerprint[:20]}",
        "summary": item.summary,
        "type": item.memory_type,
        "reviewed": True,
        "sensitivity": item.sensitivity,
        "sync_scope": item.sync_scope,
        "source": source or item.source_adapter or "personadock-sync",
        "source_refs": source_refs,
        "sync": {
            "memory_item_id": item.id,
            "fingerprint": item.fingerprint,
            "memory_key": item.memory_key,
            "approved_at": item.reviewed_at,
            "approved_by": item.reviewed_by,
        },
    }


class SyncEngine:
    def __init__(
        self,
        registry: RegistryService | None = None,
        sync_registry: SyncRegistry | None = None,
    ) -> None:
        self.registry = registry or RegistryService()
        self.sync = sync_registry or SyncRegistry(self.registry)

    def import_reviewed_memory(self, persona_id: str) -> dict[str, int]:
        project = _persona_project(self.registry, persona_id)
        inserted = 0
        existing = 0
        seed_path = project / "memory" / "seed.jsonl"
        for record in load_jsonl(seed_path):
            if record.get("reviewed") is not True:
                continue
            summary = str(record.get("summary") or record.get("text") or "").strip()
            if not summary:
                continue
            memory_type = str(record.get("type") or "note")[:64]
            metadata = {
                "canonical_seed": True,
                "source": record.get("source"),
                "source_refs": record.get("source_refs", []),
                "original": record,
            }
            item, created = self.sync.upsert_memory_item(
                persona_id=persona_id,
                fingerprint=memory_fingerprint(summary, memory_type),
                memory_key=memory_key(summary, memory_type, record),
                memory_type=memory_type,
                summary=summary,
                sensitivity=classify_sensitivity(
                    summary,
                    str(record.get("sensitivity") or "internal"),
                ),
                sync_scope=str(record.get("sync_scope") or "shared"),
                status="approved",
                source_adapter=None,
                source_runtime_instance_id=None,
                source_record_id=str(record.get("id") or "") or None,
                source_path="memory/seed.jsonl",
                metadata=metadata,
                reviewed_at=str(record.get("reviewed_at") or _utc_now()),
                reviewed_by=str(record.get("reviewed_by") or "project"),
            )
            if created:
                inserted += 1
            else:
                existing += 1

        profile = load_yaml(project / "memory" / "profile.yaml")
        for category in ("user_preferences", "relationship_facts", "notes"):
            values = profile.get(category, [])
            if not isinstance(values, list):
                continue
            for value in values:
                summary = str(value).strip()
                if not summary:
                    continue
                memory_type = category.removesuffix("s")
                item, created = self.sync.upsert_memory_item(
                    persona_id=persona_id,
                    fingerprint=memory_fingerprint(summary, memory_type),
                    memory_key=f"profile:{category}:{memory_fingerprint(summary, memory_type)[:20]}",
                    memory_type=memory_type,
                    summary=summary,
                    sensitivity=classify_sensitivity(summary, "internal"),
                    sync_scope="shared",
                    status="approved",
                    source_adapter=None,
                    source_runtime_instance_id=None,
                    source_record_id=None,
                    source_path="memory/profile.yaml",
                    metadata={"canonical_profile": True, "category": category},
                    reviewed_at=_utc_now(),
                    reviewed_by="project",
                )
                if created:
                    inserted += 1
                else:
                    existing += 1
        return {"inserted": inserted, "existing": existing}

    def _should_auto_approve(
        self,
        policy: dict[str, Any],
        item: MemoryItemRecord,
        *,
        has_conflict: bool,
    ) -> bool:
        if policy.get("mode") != "automatic":
            return False
        auto = policy.get("auto_approve", {})
        if not auto.get("enabled") or has_conflict:
            return False
        sources = set(str(value) for value in auto.get("source_adapters", []))
        types = set(str(value) for value in auto.get("memory_types", []))
        if sources and item.source_adapter not in sources:
            return False
        if types and item.memory_type not in types:
            return False
        maximum = str(auto.get("max_sensitivity") or "internal")
        return SENSITIVITY_RANK[item.sensitivity] <= SENSITIVITY_RANK[maximum]

    def ingest_candidate_file(self, persona_id: str) -> dict[str, Any]:
        project = _persona_project(self.registry, persona_id)
        path = project / ".private" / "memory-candidates.jsonl"
        records = load_jsonl(path)
        policy = self.sync.get_policy(persona_id).config
        result = {
            "source": str(path),
            "seen": len(records),
            "inserted": 0,
            "duplicates": 0,
            "loop_suppressed": 0,
            "conflicts": 0,
            "auto_approved": 0,
            "auto_rejected": 0,
        }
        for record in records:
            summary = str(record.get("summary") or record.get("text") or "").strip()
            if not summary:
                continue
            source = _candidate_source(record)
            source_runtime_id = _source_runtime_id(self.registry, source)
            memory_type = _candidate_type(record)
            fingerprint = memory_fingerprint(summary, memory_type)
            if (
                source_runtime_id
                and self.sync.propagated_back_to_source(
                    persona_id,
                    source_runtime_id,
                    fingerprint,
                )
            ):
                result["loop_suppressed"] += 1
                continue
            metadata = {
                "source": source,
                "original": record,
                "provenance": {
                    "ingested_at": _utc_now(),
                    "source_adapter": source.get("adapter"),
                    "source_runtime_instance_id": source_runtime_id,
                },
            }
            item, created = self.sync.upsert_memory_item(
                persona_id=persona_id,
                fingerprint=fingerprint,
                memory_key=memory_key(summary, memory_type, record),
                memory_type=memory_type,
                summary=summary,
                sensitivity=classify_sensitivity(
                    summary,
                    str(record.get("sensitivity") or "internal"),
                ),
                sync_scope=str(record.get("sync_scope") or "local-only"),
                status="pending",
                source_adapter=str(source.get("adapter") or "") or None,
                source_runtime_instance_id=source_runtime_id,
                source_record_id=str(record.get("id") or "") or None,
                source_path=str(source.get("path") or "") or None,
                metadata=metadata,
            )
            if not created:
                result["duplicates"] += 1
                continue
            result["inserted"] += 1
            existing = self.sync.approved_by_key(
                persona_id,
                item.memory_key,
                excluding_fingerprint=item.fingerprint,
            )
            has_conflict = bool(existing)
            if existing:
                result["conflicts"] += 1
                conflict = self.sync.create_conflict(
                    persona_id=persona_id,
                    candidate_id=item.id,
                    existing_item_id=existing[0].id,
                    conflict_type="same-key-different-content",
                    details={
                        "candidate": item.to_dict(),
                        "existing": existing[0].to_dict(),
                    },
                )
                strategy = policy.get("conflicts", {}).get("strategy", "manual")
                if strategy == "keep-existing":
                    self.reject(item.id, reviewer="policy", reason="conflict-keep-existing")
                    self.sync.resolve_conflict(conflict.id, "keep-existing")
                    result["auto_rejected"] += 1
                    continue
                if strategy == "keep-both" and policy.get("mode") == "automatic":
                    self.sync.resolve_conflict(conflict.id, "keep-both")
                    item = self.sync.update_memory_status(
                        item.id,
                        "pending",
                        memory_key=f"{item.memory_key}:{item.fingerprint[:12]}",
                    )
                    has_conflict = False
            if self._should_auto_approve(policy, item, has_conflict=has_conflict):
                self.approve(item.id, reviewer="policy")
                result["auto_approved"] += 1
        self.registry.journal(
            "sync-candidates-ingested",
            persona_id=persona_id,
            payload=result,
        )
        return result

    def collect(self, persona_id: str) -> dict[str, Any]:
        project = _persona_project(self.registry, persona_id)
        policy = self.sync.get_policy(persona_id).config
        if policy.get("mode") == "disabled" or not policy.get("pull", {}).get("enabled"):
            return {
                "persona_id": persona_id,
                "disabled": True,
                "platform_results": [],
                "ingest": self.ingest_candidate_file(persona_id),
            }
        adapters = set(policy.get("pull", {}).get("adapters", []))
        platform_results: list[dict[str, Any]] = []
        for binding in self.registry.list_bindings(persona_id):
            instance = self.registry.get_runtime_instance(binding.runtime_instance_id)
            if instance is None or instance.adapter not in adapters:
                continue
            if instance.capabilities.get("memory_pull") is not True:
                platform_results.append(
                    {
                        "instance_id": instance.id,
                        "adapter": instance.adapter,
                        "status": "skipped",
                        "reason": "memory_pull capability unavailable",
                    }
                )
                continue
            try:
                if instance.adapter == "hermes":
                    value = pull_hermes_memory_candidates(
                        persona_id,
                        profile=instance.platform_instance_id,
                        container=instance.metadata.get("container"),
                        registry=self.registry,
                    )
                elif instance.adapter == "openclaw":
                    value = pull_openclaw_memory_candidates(
                        persona_id,
                        agent_id=instance.platform_instance_id,
                        container=instance.metadata.get("container"),
                        ssh_host=instance.metadata.get("ssh_host"),
                        registry=self.registry,
                    )
                else:
                    continue
                platform_results.append(
                    {
                        "instance_id": instance.id,
                        "adapter": instance.adapter,
                        "status": "success",
                        "result": value,
                    }
                )
            except Exception as error:
                platform_results.append(
                    {
                        "instance_id": instance.id,
                        "adapter": instance.adapter,
                        "status": "failed",
                        "error": str(error),
                    }
                )
        ingest = self.ingest_candidate_file(persona_id)
        result = {
            "persona_id": persona_id,
            "project": str(project),
            "platform_results": platform_results,
            "ingest": ingest,
        }
        self.registry.journal(
            "sync-collection-completed",
            persona_id=persona_id,
            payload=result,
        )
        return result

    def approve(
        self,
        item_id: str,
        *,
        reviewer: str = "user",
        sync_scope: str | None = None,
        force_conflict: bool = False,
    ) -> MemoryItemRecord:
        item = self.sync.get_memory_item(item_id)
        if item is None:
            raise SyncError(f"memory item not found: {item_id}")
        if item.status == "approved":
            return item
        unresolved = {
            conflict.candidate_id
            for conflict in self.sync.list_conflicts(item.persona_id, status="pending")
        }
        if item.id in unresolved and not force_conflict:
            raise SyncError(
                "memory item has an unresolved conflict; resolve it before approval"
            )
        resolved_scope = sync_scope or (
            "shared" if item.sync_scope == "local-only" else item.sync_scope
        )
        approved = self.sync.update_memory_status(
            item.id,
            "approved",
            reviewed_by=reviewer,
            metadata_patch={"review": {"decision": "approved", "reviewer": reviewer}},
        )
        if approved.sync_scope != resolved_scope:
            with self.registry.database.session() as connection:
                connection.execute(
                    "UPDATE memory_items SET sync_scope = ?, updated_at = ? WHERE id = ?",
                    (resolved_scope, _utc_now(), approved.id),
                )
            approved = self.sync.get_memory_item(approved.id)
            assert approved is not None
        project = _persona_project(self.registry, approved.persona_id)
        seed_path = project / "memory" / "seed.jsonl"
        records = load_jsonl(seed_path)
        if not any(
            record.get("sync", {}).get("fingerprint") == approved.fingerprint
            or memory_fingerprint(
                str(record.get("summary") or record.get("text") or ""),
                str(record.get("type") or "note"),
            )
            == approved.fingerprint
            for record in records
            if str(record.get("summary") or record.get("text") or "").strip()
        ):
            records.append(_seed_record(approved))
            write_jsonl(seed_path, records)
        self.registry.journal(
            "sync-memory-approved",
            persona_id=approved.persona_id,
            runtime_instance_id=approved.source_runtime_instance_id,
            payload=approved.to_dict(),
        )
        return approved

    def reject(
        self,
        item_id: str,
        *,
        reviewer: str = "user",
        reason: str | None = None,
    ) -> MemoryItemRecord:
        item = self.sync.update_memory_status(
            item_id,
            "rejected",
            reviewed_by=reviewer,
            metadata_patch={
                "review": {
                    "decision": "rejected",
                    "reviewer": reviewer,
                    "reason": reason,
                }
            },
        )
        self.registry.journal(
            "sync-memory-rejected",
            persona_id=item.persona_id,
            runtime_instance_id=item.source_runtime_instance_id,
            payload=item.to_dict(),
        )
        return item

    def _remove_seed_fingerprint(self, item: MemoryItemRecord) -> None:
        project = _persona_project(self.registry, item.persona_id)
        seed_path = project / "memory" / "seed.jsonl"
        records = load_jsonl(seed_path)
        retained: list[dict[str, Any]] = []
        for record in records:
            summary = str(record.get("summary") or record.get("text") or "").strip()
            record_type = str(record.get("type") or "note")
            fingerprint = (
                memory_fingerprint(summary, record_type) if summary else ""
            )
            sync_fingerprint = str(record.get("sync", {}).get("fingerprint") or "")
            if item.fingerprint in {fingerprint, sync_fingerprint}:
                continue
            retained.append(record)
        write_jsonl(seed_path, retained)

    def resolve_conflict(
        self,
        conflict_id: str,
        resolution: str,
        *,
        reviewer: str = "user",
    ) -> dict[str, Any]:
        if resolution not in {"keep-existing", "replace", "keep-both"}:
            raise SyncError("resolution must be keep-existing, replace, or keep-both")
        conflict = self.sync.get_conflict(conflict_id)
        if conflict is None:
            raise SyncError(f"sync conflict not found: {conflict_id}")
        if conflict.status == "resolved":
            return conflict.to_dict()
        candidate = self.sync.get_memory_item(conflict.candidate_id)
        if candidate is None:
            raise SyncError("conflict candidate no longer exists")
        existing = (
            self.sync.get_memory_item(conflict.existing_item_id)
            if conflict.existing_item_id
            else None
        )
        if resolution == "keep-existing":
            self.reject(candidate.id, reviewer=reviewer, reason="conflict-keep-existing")
        elif resolution == "replace":
            if existing:
                self._remove_seed_fingerprint(existing)
                self.sync.update_memory_status(
                    existing.id,
                    "superseded",
                    reviewed_by=reviewer,
                    metadata_patch={"superseded_by": candidate.id},
                )
            self.approve(candidate.id, reviewer=reviewer, force_conflict=True)
        else:
            self.sync.update_memory_status(
                candidate.id,
                "pending",
                memory_key=f"{candidate.memory_key}:{candidate.fingerprint[:12]}",
            )
            self.approve(candidate.id, reviewer=reviewer, force_conflict=True)
        resolved = self.sync.resolve_conflict(conflict_id, resolution)
        self.registry.journal(
            "sync-conflict-resolved",
            persona_id=resolved.persona_id,
            payload={**resolved.to_dict(), "reviewer": reviewer},
        )
        return resolved.to_dict()

    def _definition_actions(
        self,
        persona_id: str,
        bindings: Iterable[BindingRecord],
        policy: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if policy.get("definition_sync", {}).get("push") == "disabled":
            return []
        persona = self.registry.get_persona(persona_id)
        assert persona is not None
        actions: list[dict[str, Any]] = []
        for binding in bindings:
            instance = self.registry.get_runtime_instance(binding.runtime_instance_id)
            if instance is None or instance.adapter not in {"hermes", "openclaw"}:
                continue
            if binding.last_deployed_version == persona.version:
                continue
            actions.append(
                {
                    "type": "definition-push",
                    "binding_id": binding.id,
                    "runtime_instance_id": instance.id,
                    "adapter": instance.adapter,
                    "transport": instance.transport,
                    "platform_instance_id": instance.platform_instance_id,
                    "current_version": binding.last_deployed_version,
                    "target_version": persona.version,
                    "requires_confirmation": True,
                    "definition_pull": "snapshot-review",
                }
            )
        return actions

    def plan(self, persona_id: str) -> SyncPlan:
        self.import_reviewed_memory(persona_id)
        policy_record = self.sync.get_policy(persona_id)
        policy = policy_record.config
        bindings = self.registry.list_bindings(persona_id)
        conflicts = self.sync.list_conflicts(persona_id, status="pending")
        conflict_items = {value.candidate_id for value in conflicts}
        approved = self.sync.list_memory_items(persona_id, status="approved")
        definition_actions = self._definition_actions(persona_id, bindings, policy)
        actions: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        warnings: list[str] = []
        if policy.get("mode") == "disabled" or not policy.get("push", {}).get("enabled"):
            warnings.append("Memory synchronization is disabled by policy.")
        else:
            adapters = set(policy.get("push", {}).get("adapters", []))
            echo_to_source = bool(policy.get("push", {}).get("echo_to_source"))
            for binding in bindings:
                instance = self.registry.get_runtime_instance(binding.runtime_instance_id)
                if instance is None or instance.adapter not in adapters:
                    continue
                if instance.capabilities.get("memory_push") is not True:
                    skipped.append(
                        {
                            "runtime_instance_id": instance.id,
                            "reason": "memory_push capability unavailable",
                        }
                    )
                    continue
                for item in approved:
                    if item.sync_scope == "local-only":
                        skipped.append(
                            {
                                "memory_item_id": item.id,
                                "runtime_instance_id": instance.id,
                                "reason": "local-only scope",
                            }
                        )
                        continue
                    if item.id in conflict_items:
                        skipped.append(
                            {
                                "memory_item_id": item.id,
                                "runtime_instance_id": instance.id,
                                "reason": "unresolved conflict",
                            }
                        )
                        continue
                    if (
                        not echo_to_source
                        and item.source_runtime_instance_id == instance.id
                    ):
                        skipped.append(
                            {
                                "memory_item_id": item.id,
                                "runtime_instance_id": instance.id,
                                "reason": "source echo disabled",
                            }
                        )
                        continue
                    if self.sync.was_propagated(
                        item.id,
                        instance.id,
                        item.fingerprint,
                    ):
                        skipped.append(
                            {
                                "memory_item_id": item.id,
                                "runtime_instance_id": instance.id,
                                "reason": "already propagated",
                            }
                        )
                        continue
                    actions.append(
                        {
                            "type": "memory-push",
                            "memory_item_id": item.id,
                            "fingerprint": item.fingerprint,
                            "summary": item.summary,
                            "sensitivity": item.sensitivity,
                            "sync_scope": item.sync_scope,
                            "source_runtime_instance_id": item.source_runtime_instance_id,
                            "binding_id": binding.id,
                            "runtime_instance_id": instance.id,
                            "adapter": instance.adapter,
                            "transport": instance.transport,
                            "platform_instance_id": instance.platform_instance_id,
                        }
                    )
        plan = SyncPlan(
            id=str(uuid.uuid4()),
            persona_id=persona_id,
            policy=policy,
            definition_actions=tuple(definition_actions),
            memory_actions=tuple(actions),
            skipped=tuple(skipped),
            conflicts=tuple(value.to_dict() for value in conflicts),
            warnings=tuple(warnings),
            created_at=_utc_now(),
        )
        self.sync.create_run(
            persona_id=persona_id,
            operation="preview",
            plan=plan.to_dict(),
        )
        return plan

    def _push_memory_destination(
        self,
        persona_id: str,
        instance: RuntimeInstanceRecord,
    ) -> dict[str, Any]:
        if instance.adapter == "hermes":
            return push_hermes_shared_memory(
                persona_id,
                profile=instance.platform_instance_id,
                container=instance.metadata.get("container"),
                registry=self.registry,
            )
        if instance.adapter == "openclaw":
            return push_openclaw_shared_memory(
                persona_id,
                agent_id=instance.platform_instance_id,
                container=instance.metadata.get("container"),
                ssh_host=instance.metadata.get("ssh_host"),
                registry=self.registry,
            )
        raise SyncError(f"unsupported memory destination adapter: {instance.adapter}")

    def _push_definition(
        self,
        persona_id: str,
        instance: RuntimeInstanceRecord,
        package: Path,
    ) -> dict[str, Any]:
        if instance.adapter == "hermes":
            adapter = HermesAdapter(container=instance.metadata.get("container"))
            plan = plan_hermes_deployment(
                package,
                profile=instance.platform_instance_id,
                profile_explicit=True,
                container=instance.metadata.get("container"),
                adapter=adapter,
            )
            return apply_hermes_deployment(
                plan,
                adapter=adapter,
                registry=self.registry,
            ).to_dict()
        if instance.adapter == "openclaw":
            adapter = OpenClawAdapter(
                container=instance.metadata.get("container"),
                ssh_host=instance.metadata.get("ssh_host"),
            )
            plan = plan_openclaw_deployment(
                package,
                agent=instance.platform_instance_id,
                agent_explicit=True,
                workspace=instance.location,
                container=instance.metadata.get("container"),
                ssh_host=instance.metadata.get("ssh_host"),
                adapter=adapter,
            )
            return apply_openclaw_deployment(
                plan,
                adapter=adapter,
                registry=self.registry,
            ).to_dict()
        raise SyncError(f"unsupported definition destination adapter: {instance.adapter}")

    def apply(
        self,
        plan: SyncPlan,
        *,
        include_definitions: bool = False,
    ) -> dict[str, Any]:
        current = self.plan(plan.persona_id)
        if current.conflicts:
            raise SyncError("unresolved conflicts block synchronization")
        run_id = self.sync.create_run(
            persona_id=plan.persona_id,
            operation="apply",
            plan=current.to_dict(),
        )
        result: dict[str, Any] = {
            "run_id": run_id,
            "persona_id": plan.persona_id,
            "memory_destinations": [],
            "definition_destinations": [],
            "failures": [],
        }
        actions_by_instance: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for action in current.memory_actions:
            actions_by_instance[str(action["runtime_instance_id"])].append(action)
        successful_bindings: set[str] = set()
        for instance_id, actions in actions_by_instance.items():
            instance = self.registry.get_runtime_instance(instance_id)
            if instance is None:
                result["failures"].append(
                    {"runtime_instance_id": instance_id, "error": "instance not found"}
                )
                continue
            try:
                value = self._push_memory_destination(plan.persona_id, instance)
                result["memory_destinations"].append(
                    {
                        "runtime_instance_id": instance.id,
                        "adapter": instance.adapter,
                        "status": "success",
                        "result": value,
                        "memory_items": [action["memory_item_id"] for action in actions],
                    }
                )
                for action in actions:
                    self.sync.record_propagation(
                        persona_id=plan.persona_id,
                        memory_item_id=str(action["memory_item_id"]),
                        source_runtime_instance_id=action.get("source_runtime_instance_id"),
                        destination_runtime_instance_id=instance.id,
                        content_hash=str(action["fingerprint"]),
                        operation="memory-push",
                        status="success",
                        details={
                            "adapter": instance.adapter,
                            "platform_instance_id": instance.platform_instance_id,
                            "sync_run_id": run_id,
                        },
                    )
                    successful_bindings.add(str(action["binding_id"]))
            except Exception as error:
                result["failures"].append(
                    {
                        "runtime_instance_id": instance.id,
                        "adapter": instance.adapter,
                        "operation": "memory-push",
                        "error": str(error),
                    }
                )
                for action in actions:
                    self.sync.record_propagation(
                        persona_id=plan.persona_id,
                        memory_item_id=str(action["memory_item_id"]),
                        source_runtime_instance_id=action.get("source_runtime_instance_id"),
                        destination_runtime_instance_id=instance.id,
                        content_hash=str(action["fingerprint"]),
                        operation="memory-push",
                        status="failed",
                        details={"error": str(error), "sync_run_id": run_id},
                    )
        self.sync.update_binding_sync_time(successful_bindings)

        if include_definitions and current.definition_actions:
            project = _persona_project(self.registry, plan.persona_id)
            package = pack_project(project)
            for action in current.definition_actions:
                instance = self.registry.get_runtime_instance(
                    str(action["runtime_instance_id"])
                )
                if instance is None:
                    continue
                try:
                    value = self._push_definition(
                        plan.persona_id,
                        instance,
                        package,
                    )
                    result["definition_destinations"].append(
                        {
                            "runtime_instance_id": instance.id,
                            "adapter": instance.adapter,
                            "status": "success",
                            "result": value,
                        }
                    )
                except Exception as error:
                    result["failures"].append(
                        {
                            "runtime_instance_id": instance.id,
                            "adapter": instance.adapter,
                            "operation": "definition-push",
                            "error": str(error),
                        }
                    )
        status = "success" if not result["failures"] else (
            "partial" if result["memory_destinations"] or result["definition_destinations"] else "failed"
        )
        result["status"] = status
        self.sync.complete_run(run_id, status=status, result=result)
        self.registry.journal(
            "sync-apply-completed",
            persona_id=plan.persona_id,
            payload=result,
        )
        return result

    def dashboard(self, persona_id: str) -> dict[str, Any]:
        policy = self.sync.get_policy(persona_id)
        pending = self.sync.list_memory_items(persona_id, status="pending")
        approved = self.sync.list_memory_items(persona_id, status="approved")
        rejected = self.sync.list_memory_items(persona_id, status="rejected")
        conflicts = self.sync.list_conflicts(persona_id, status="pending")
        plan = self.plan(persona_id)
        return {
            "persona_id": persona_id,
            "policy": policy.to_dict(),
            "counts": {
                "pending": len(pending),
                "approved": len(approved),
                "rejected": len(rejected),
                "conflicts": len(conflicts),
                "memory_actions": len(plan.memory_actions),
                "definition_actions": len(plan.definition_actions),
            },
            "pending": [value.to_dict() for value in pending],
            "conflicts": [value.to_dict() for value in conflicts],
            "plan": plan.to_dict(),
            "runs": self.sync.list_runs(persona_id, limit=20),
            "propagation": self.sync.propagation_log(persona_id, limit=50),
        }
