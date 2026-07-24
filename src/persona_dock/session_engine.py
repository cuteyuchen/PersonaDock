from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.openclaw import OpenClawAdapter
from persona_dock.hermes_memory import push_hermes_shared_memory
from persona_dock.io import write_jsonl
from persona_dock.openclaw_memory import push_openclaw_shared_memory
from persona_dock.project import PROJECT_FILE
from persona_dock.registry import RegistryService
from persona_dock.session_models import (
    SessionPropagationPlan,
    SessionSummaryRecord,
    render_session_handoff,
    session_summary_content_hash,
    session_summary_fingerprint,
)
from persona_dock.session_registry import SessionSummaryRegistry, utc_now
from persona_dock.session_sources import (
    HermesSessionSource,
    OpenClawSessionSource,
    SessionSummaryDraft,
)
from persona_dock.sync_models import SENSITIVITY_RANK, classify_sensitivity


class SessionSummaryError(RuntimeError):
    """Raised when a governed Session Summary operation cannot be completed."""


class SessionSummaryEngine:
    def __init__(self, registry: RegistryService | None = None) -> None:
        self.registry = registry or RegistryService()
        self.session = SessionSummaryRegistry(self.registry)

    def _project(self, persona_id: str) -> Path:
        persona = self.registry.get_persona(persona_id)
        if persona is None:
            raise SessionSummaryError(f"persona is not registered: {persona_id}")
        if not persona.source_path:
            raise SessionSummaryError(f"persona has no source project: {persona_id}")
        project = Path(persona.source_path).expanduser().resolve()
        if not (project / PROJECT_FILE).is_file():
            raise SessionSummaryError(
                f"persona project is missing {PROJECT_FILE}: {project}"
            )
        return project

    def _binding_instances(self, persona_id: str) -> list[tuple[Any, Any]]:
        values: list[tuple[Any, Any]] = []
        for binding in self.registry.list_bindings(persona_id):
            instance = self.registry.get_runtime_instance(binding.runtime_instance_id)
            if instance is not None:
                values.append((binding, instance))
        return values

    @staticmethod
    def _transport_options(instance: Any) -> dict[str, Any]:
        metadata = instance.metadata if isinstance(instance.metadata, dict) else {}
        if instance.transport == "docker":
            return {"container": metadata.get("container") or metadata.get("container_name")}
        if instance.transport == "ssh":
            return {"ssh_host": metadata.get("ssh_host") or metadata.get("host")}
        return {}

    def _source_for_instance(self, instance: Any):
        options = self._transport_options(instance)
        if instance.adapter == "hermes":
            return HermesSessionSource(
                HermesAdapter(container=options.get("container")),
                instance.platform_instance_id,
            )
        if instance.adapter == "openclaw":
            return OpenClawSessionSource(
                OpenClawAdapter(
                    container=options.get("container"),
                    ssh_host=options.get("ssh_host"),
                ),
                instance.platform_instance_id,
            )
        raise SessionSummaryError(
            f"runtime adapter does not support Session Summaries: {instance.adapter}"
        )

    def _auto_approve(self, persona_id: str, record: SessionSummaryRecord) -> bool:
        policy = self.session.get_policy(persona_id).config
        auto = policy["auto_approve"]
        if policy["mode"] != "automatic" or not auto["enabled"]:
            return False
        if auto["source_adapters"] and record.source_adapter not in auto["source_adapters"]:
            return False
        if record.generated_by not in auto["generated_by"]:
            return False
        return SENSITIVITY_RANK[record.sensitivity] <= SENSITIVITY_RANK[
            auto["max_sensitivity"]
        ]

    def _ingest_draft(
        self,
        persona_id: str,
        draft: SessionSummaryDraft,
        *,
        runtime_instance_id: str | None,
    ) -> tuple[SessionSummaryRecord, bool, bool]:
        fingerprint = session_summary_fingerprint(
            persona_id=persona_id,
            source_adapter=draft.source_adapter,
            source_session_id=draft.source_session_id,
            summary=draft.summary,
        )
        record, created = self.session.upsert_summary(
            persona_id=persona_id,
            fingerprint=fingerprint,
            source_adapter=draft.source_adapter,
            source_runtime_instance_id=runtime_instance_id,
            source_session_id=draft.source_session_id,
            source_title=draft.source_title,
            started_at=draft.started_at,
            ended_at=draft.ended_at,
            summary=draft.summary,
            pending_tasks=draft.pending_tasks,
            emotional_context=draft.emotional_context,
            sensitivity=draft.sensitivity,
            sync_scope="local-only",
            status="pending",
            generated_by=draft.generated_by,
            metadata=draft.metadata,
        )
        approved = False
        if created and self._auto_approve(persona_id, record):
            record = self.approve(
                record.id,
                reviewer="session-policy:auto",
                sync_scope="shared",
            )
            approved = True
        return record, created, approved

    def collect(self, persona_id: str) -> dict[str, Any]:
        self._project(persona_id)
        policy = self.session.get_policy(persona_id).config
        if policy["mode"] == "disabled" or not policy["collect"]["enabled"]:
            raise SessionSummaryError("Session Summary collection is disabled by policy")
        allowed = set(policy["collect"]["adapters"])
        limit = int(policy["collect"]["max_items_per_runtime"])
        results: list[dict[str, Any]] = []
        for _binding, instance in self._binding_instances(persona_id):
            if instance.adapter not in allowed:
                continue
            try:
                drafts = self._source_for_instance(instance).collect(limit=limit)
            except Exception as error:
                results.append(
                    {
                        "runtime_instance_id": instance.id,
                        "adapter": instance.adapter,
                        "status": "failed",
                        "error": str(error),
                    }
                )
                continue
            created = 0
            approved = 0
            for draft in drafts:
                _, was_created, was_approved = self._ingest_draft(
                    persona_id,
                    draft,
                    runtime_instance_id=instance.id,
                )
                created += int(was_created)
                approved += int(was_approved)
            results.append(
                {
                    "runtime_instance_id": instance.id,
                    "adapter": instance.adapter,
                    "platform_instance_id": instance.platform_instance_id,
                    "status": "success",
                    "discovered": len(drafts),
                    "created": created,
                    "auto_approved": approved,
                }
            )
        self.registry.journal(
            "session-summaries-collected",
            persona_id=persona_id,
            payload={"results": results},
        )
        return {"persona_id": persona_id, "results": results}

    def add_manual(
        self,
        persona_id: str,
        *,
        summary: str,
        title: str,
        pending_tasks: list[str] | None = None,
        emotional_context: dict[str, Any] | None = None,
        sensitivity: str = "internal",
    ) -> SessionSummaryRecord:
        self._project(persona_id)
        text = summary.strip()
        if not text:
            raise SessionSummaryError("manual Session Summary cannot be empty")
        draft = SessionSummaryDraft(
            source_adapter="manual",
            source_session_id=f"manual-{uuid.uuid4()}",
            source_title=title.strip() or "Manual summary",
            started_at=None,
            ended_at=None,
            summary=text[:4000],
            pending_tasks=tuple(pending_tasks or ()),
            emotional_context=dict(emotional_context or {}),
            sensitivity=classify_sensitivity(text, sensitivity),
            generated_by="manual",
            metadata={"manual": True},
        )
        record, _, _ = self._ingest_draft(
            persona_id, draft, runtime_instance_id=None
        )
        return record

    def _canonical_records(self, persona_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "source_session_id": item.source_session_id,
                "source_title": item.source_title,
                "source_adapter": item.source_adapter,
                "source_runtime_instance_id": item.source_runtime_instance_id,
                "started_at": item.started_at,
                "ended_at": item.ended_at,
                "summary": item.summary,
                "pending_tasks": list(item.pending_tasks),
                "emotional_context": item.emotional_context,
                "sensitivity": item.sensitivity,
                "sync_scope": item.sync_scope,
                "reviewed": True,
                "reviewed_at": item.reviewed_at,
                "reviewed_by": item.reviewed_by,
                "fingerprint": item.fingerprint,
            }
            for item in self.session.list_summaries(persona_id, status="approved")
        ]

    def _write_canonical(self, persona_id: str) -> Path:
        project = self._project(persona_id)
        path = project / "memory" / "session-summaries.jsonl"
        write_jsonl(path, self._canonical_records(persona_id))
        return path

    def approve(
        self,
        summary_id: str,
        *,
        reviewer: str,
        sync_scope: str = "shared",
    ) -> SessionSummaryRecord:
        if sync_scope not in {"local-only", "shared"}:
            raise SessionSummaryError("Session Summary scope must be local-only or shared")
        record = self.session.update_status(
            summary_id,
            "approved",
            reviewer=reviewer,
            sync_scope=sync_scope,
        )
        path = self._write_canonical(record.persona_id)
        self.registry.journal(
            "session-summary-approved",
            persona_id=record.persona_id,
            runtime_instance_id=record.source_runtime_instance_id,
            payload={
                "summary_id": record.id,
                "reviewer": reviewer,
                "sync_scope": sync_scope,
                "canonical_path": str(path),
            },
        )
        return record

    def reject(
        self,
        summary_id: str,
        *,
        reviewer: str,
        reason: str | None = None,
    ) -> SessionSummaryRecord:
        current = self.session.get_summary(summary_id)
        if current is None:
            raise SessionSummaryError(f"Session Summary not found: {summary_id}")
        record = self.session.update_status(
            summary_id,
            "rejected",
            reviewer=reviewer,
            metadata_patch={"rejection_reason": reason} if reason else None,
        )
        self._write_canonical(record.persona_id)
        self.registry.journal(
            "session-summary-rejected",
            persona_id=record.persona_id,
            runtime_instance_id=record.source_runtime_instance_id,
            payload={"summary_id": record.id, "reviewer": reviewer, "reason": reason},
        )
        return record

    def plan(self, persona_id: str) -> SessionPropagationPlan:
        self._project(persona_id)
        policy = self.session.get_policy(persona_id).config
        approved = [
            item
            for item in self.session.list_summaries(persona_id, status="approved")
            if item.sync_scope == "shared"
        ]
        actions: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        if policy["mode"] == "disabled" or not policy["propagation"]["enabled"]:
            return SessionPropagationPlan(
                id=str(uuid.uuid4()),
                persona_id=persona_id,
                policy=policy,
                actions=(),
                skipped=tuple(
                    {"summary_id": item.id, "reason": "propagation-disabled"}
                    for item in approved
                ),
                warnings=("Session Summary propagation is disabled by policy.",),
                created_at=utc_now(),
            )
        for _binding, instance in self._binding_instances(persona_id):
            if instance.adapter not in {"hermes", "openclaw"}:
                continue
            if not instance.capabilities.get("memory_push", False):
                skipped.append(
                    {
                        "runtime_instance_id": instance.id,
                        "reason": "runtime-does-not-support-memory-push",
                    }
                )
                continue
            pending: list[dict[str, Any]] = []
            for item in approved:
                content_hash = session_summary_content_hash(item)
                if (
                    not policy["propagation"]["echo_to_source"]
                    and item.source_runtime_instance_id == instance.id
                ):
                    skipped.append(
                        {
                            "summary_id": item.id,
                            "runtime_instance_id": instance.id,
                            "reason": "source-echo-disabled",
                        }
                    )
                    continue
                if self.session.propagated(item.id, instance.id, content_hash):
                    skipped.append(
                        {
                            "summary_id": item.id,
                            "runtime_instance_id": instance.id,
                            "reason": "already-propagated",
                        }
                    )
                    continue
                pending.append(
                    {
                        "summary_id": item.id,
                        "content_hash": content_hash,
                        "handoff": render_session_handoff(item),
                    }
                )
            if pending:
                actions.append(
                    {
                        "runtime_instance_id": instance.id,
                        "adapter": instance.adapter,
                        "transport": instance.transport,
                        "platform_instance_id": instance.platform_instance_id,
                        "location": instance.location,
                        "summaries": pending,
                    }
                )
        return SessionPropagationPlan(
            id=str(uuid.uuid4()),
            persona_id=persona_id,
            policy=policy,
            actions=tuple(actions),
            skipped=tuple(skipped),
            warnings=(
                "Only reviewed summaries are propagated; raw sessions and transcripts remain outside PersonaDock.",
            ),
            created_at=utc_now(),
        )

    def _push_instance(self, persona_id: str, instance: Any) -> dict[str, Any]:
        options = self._transport_options(instance)
        if instance.adapter == "hermes":
            if instance.transport == "ssh":
                raise SessionSummaryError("Hermes Session Summary push does not support SSH")
            return push_hermes_shared_memory(
                persona_id,
                profile=instance.platform_instance_id,
                container=options.get("container"),
                registry=self.registry,
            )
        if instance.adapter == "openclaw":
            return push_openclaw_shared_memory(
                persona_id,
                agent_id=instance.platform_instance_id,
                container=options.get("container"),
                ssh_host=options.get("ssh_host"),
                registry=self.registry,
            )
        raise SessionSummaryError(f"unsupported destination adapter: {instance.adapter}")

    def apply(self, plan: SessionPropagationPlan) -> dict[str, Any]:
        fresh = self.plan(plan.persona_id)
        results: list[dict[str, Any]] = []
        for action in fresh.actions:
            instance = self.registry.get_runtime_instance(action["runtime_instance_id"])
            if instance is None:
                continue
            try:
                result = self._push_instance(plan.persona_id, instance)
            except Exception as error:
                for summary in action["summaries"]:
                    item = self.session.get_summary(summary["summary_id"])
                    self.session.record_propagation(
                        persona_id=plan.persona_id,
                        session_summary_id=summary["summary_id"],
                        source_runtime_instance_id=(
                            item.source_runtime_instance_id if item else None
                        ),
                        destination_runtime_instance_id=instance.id,
                        content_hash=summary["content_hash"],
                        status="failed",
                        details={"error": str(error)},
                    )
                results.append(
                    {
                        "runtime_instance_id": instance.id,
                        "status": "failed",
                        "error": str(error),
                    }
                )
                continue
            for summary in action["summaries"]:
                item = self.session.get_summary(summary["summary_id"])
                self.session.record_propagation(
                    persona_id=plan.persona_id,
                    session_summary_id=summary["summary_id"],
                    source_runtime_instance_id=(
                        item.source_runtime_instance_id if item else None
                    ),
                    destination_runtime_instance_id=instance.id,
                    content_hash=summary["content_hash"],
                    status="success",
                    details={"push_result": result},
                )
            results.append(
                {
                    "runtime_instance_id": instance.id,
                    "status": "success",
                    "summary_count": len(action["summaries"]),
                    "push_result": result,
                }
            )
        statuses = {item["status"] for item in results}
        status = (
            "success"
            if not results or statuses == {"success"}
            else "failed"
            if statuses == {"failed"}
            else "partial"
        )
        self.registry.journal(
            "session-summary-sync-applied",
            persona_id=plan.persona_id,
            payload={"plan_id": fresh.id, "status": status, "results": results},
        )
        return {
            "persona_id": plan.persona_id,
            "plan_id": fresh.id,
            "status": status,
            "results": results,
        }

    def raw_preview(
        self,
        persona_id: str,
        runtime_instance_id: str,
        session_id: str,
        *,
        confirmed_experimental: bool,
    ) -> dict[str, Any]:
        policy = self.session.get_policy(persona_id).config
        if not confirmed_experimental:
            raise SessionSummaryError("raw preview requires explicit experimental confirmation")
        if not policy["raw_preview"]["enabled"]:
            raise SessionSummaryError("raw Session preview is disabled by policy")
        instance = self.registry.get_runtime_instance(runtime_instance_id)
        if instance is None:
            raise SessionSummaryError(f"runtime instance not found: {runtime_instance_id}")
        if not any(
            binding.runtime_instance_id == runtime_instance_id
            for binding in self.registry.list_bindings(persona_id)
        ):
            raise SessionSummaryError("runtime instance is not bound to this Persona")
        source = self._source_for_instance(instance)
        raw = policy["raw_preview"]
        value = source.raw_preview(
            session_id,
            max_messages=int(raw["max_messages"]),
            max_chars=int(raw["max_chars"]),
        )
        self.registry.journal(
            "raw-session-previewed",
            persona_id=persona_id,
            runtime_instance_id=runtime_instance_id,
            payload={
                "session_id": session_id,
                "adapter": instance.adapter,
                "message_count": len(value.get("messages", [])),
                "persisted": False,
            },
        )
        return value

    def dashboard(self, persona_id: str) -> dict[str, Any]:
        value = self.session.dashboard(persona_id)
        value["plan"] = self.plan(persona_id).to_dict()
        return value
