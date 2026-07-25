from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from persona_dock.registry import RegistryService
from persona_dock.session_models import (
    SessionDocument,
    SessionSummaryDraft,
    SessionSummaryRecord,
    build_session_summary,
    parse_session_export,
)
from persona_dock.session_registry import SessionRegistry
from persona_dock.session_sources import export_runtime_session
from persona_dock.sync_engine import SyncEngine, SyncError
from persona_dock.sync_models import SENSITIVITY_RANK, memory_fingerprint, memory_key
from persona_dock.sync_registry import SyncRegistry, _utc_now


class SessionSummaryError(RuntimeError):
    """Raised when a session summary operation violates policy or provenance rules."""


def _summary_memory_text(
    record: SessionSummaryRecord,
    policy: dict[str, Any],
) -> str:
    settings = policy.get("session_summaries", {})
    sections = [record.summary]
    if settings.get("include_decisions") and record.decisions:
        sections.append("已确认决策：\n" + "\n".join(f"- {value}" for value in record.decisions))
    if settings.get("include_pending_tasks") and record.pending_tasks:
        sections.append("待继续事项：\n" + "\n".join(f"- {value}" for value in record.pending_tasks))
    if settings.get("include_emotional_context") and record.emotional_context:
        sections.append("情绪上下文：" + "、".join(record.emotional_context))
    return "\n\n".join(sections).strip()


class SessionSummaryEngine:
    def __init__(
        self,
        registry: RegistryService | None = None,
        session_registry: SessionRegistry | None = None,
        sync_registry: SyncRegistry | None = None,
    ) -> None:
        self.registry = registry or RegistryService()
        self.sessions = session_registry or SessionRegistry(self.registry)
        self.sync = sync_registry or SyncRegistry(self.registry)
        self.memory = SyncEngine(self.registry, self.sync)

    def _settings(self, persona_id: str) -> dict[str, Any]:
        return dict(self.sync.get_policy(persona_id).config.get("session_summaries", {}))

    def preview_file(
        self,
        path: str | Path,
        *,
        session_id: str | None = None,
        max_turns: int | None = None,
        include_emotional_context: bool = False,
    ) -> dict[str, Any]:
        documents = parse_session_export(path, session_id=session_id)
        drafts = [
            build_session_summary(
                document,
                max_turns=max_turns or 20,
                include_emotional_context=include_emotional_context,
            )
            for document in documents
        ]
        return {
            "source": str(Path(path).expanduser().resolve()),
            "raw_persisted": False,
            "documents": [document.to_dict(include_messages=True) for document in documents],
            "summaries": [draft.to_dict() for draft in drafts],
        }

    def import_file(
        self,
        persona_id: str,
        path: str | Path,
        *,
        source_adapter: str = "file",
        runtime_instance_id: str | None = None,
        session_id: str | None = None,
        source_kind: str = "manual-file",
    ) -> dict[str, Any]:
        settings = self._settings(persona_id)
        if settings.get("mode") == "disabled":
            raise SessionSummaryError("session summaries are disabled by policy")
        if settings.get("raw_session_import") == "disabled":
            raise SessionSummaryError("raw session import is disabled by policy")
        allowed = set(str(value) for value in settings.get("source_adapters", []))
        if source_adapter not in allowed:
            raise SessionSummaryError(
                f"session source adapter is not allowed by policy: {source_adapter}"
            )
        instance = None
        if runtime_instance_id:
            instance = self.registry.get_runtime_instance(runtime_instance_id)
            if instance is None:
                raise SessionSummaryError(f"runtime instance not found: {runtime_instance_id}")
            if instance.adapter != source_adapter:
                raise SessionSummaryError("runtime instance adapter does not match session source")
            if not any(
                binding.runtime_instance_id == runtime_instance_id
                for binding in self.registry.list_bindings(persona_id)
            ):
                raise SessionSummaryError("runtime instance is not bound to this persona")

        documents = parse_session_export(path, session_id=session_id)
        result: dict[str, Any] = {
            "persona_id": persona_id,
            "source_adapter": source_adapter,
            "runtime_instance_id": runtime_instance_id,
            "seen": len(documents),
            "created": 0,
            "duplicates": 0,
            "auto_approved": 0,
            "summary_ids": [],
            "raw_persisted": False,
        }
        for document in documents:
            draft = build_session_summary(
                document,
                max_turns=int(settings.get("max_turns") or 20),
                include_emotional_context=bool(settings.get("include_emotional_context")),
            )
            record, created = self.sessions.upsert_summary(
                persona_id=persona_id,
                source_adapter=source_adapter,
                source_runtime_instance_id=runtime_instance_id,
                draft=draft,
                status="pending",
                sync_scope="local-only",
                metadata={
                    "source_kind": source_kind,
                    "runtime": instance.to_dict() if instance else None,
                },
            )
            self.sessions.record_import(
                persona_id=persona_id,
                source_adapter=source_adapter,
                source_runtime_instance_id=runtime_instance_id,
                source_session_id=document.session_id,
                transcript_hash=document.transcript_hash,
                source_kind=source_kind,
                source_reference=Path(path).name,
                message_count=document.original_message_count,
                filtered_message_count=document.filtered_message_count,
                metadata={
                    "raw_persisted": False,
                    "system_messages_included": False,
                    "tool_messages_included": False,
                },
            )
            result["summary_ids"].append(record.id)
            if not created:
                result["duplicates"] += 1
                continue
            result["created"] += 1
            maximum = str(settings.get("max_sensitivity") or "internal")
            should_auto = (
                settings.get("mode") == "automatic"
                and settings.get("auto_approve") is True
                and SENSITIVITY_RANK[record.sensitivity] <= SENSITIVITY_RANK[maximum]
            )
            if should_auto:
                self.approve(record.id, reviewer="policy", sync_scope="shared")
                result["auto_approved"] += 1
        self.registry.journal(
            "session-import-completed",
            persona_id=persona_id,
            runtime_instance_id=runtime_instance_id,
            payload=result,
        )
        return result

    def collect_native(
        self,
        persona_id: str,
        runtime_instance_id: str,
        session_identifier: str,
    ) -> dict[str, Any]:
        instance = self.registry.get_runtime_instance(runtime_instance_id)
        if instance is None:
            raise SessionSummaryError(f"runtime instance not found: {runtime_instance_id}")
        if not any(
            binding.runtime_instance_id == runtime_instance_id
            for binding in self.registry.list_bindings(persona_id)
        ):
            raise SessionSummaryError("runtime instance is not bound to this persona")
        if instance.adapter not in {"hermes", "openclaw"}:
            raise SessionSummaryError(f"unsupported session source adapter: {instance.adapter}")
        with tempfile.TemporaryDirectory(prefix="personadock-session-") as directory:
            exported = export_runtime_session(
                instance,
                session_identifier,
                Path(directory),
            )
            result = self.import_file(
                persona_id,
                exported.path,
                source_adapter=instance.adapter,
                runtime_instance_id=runtime_instance_id,
                session_id=session_identifier if instance.adapter == "hermes" else None,
                source_kind="native-export",
            )
            result["export"] = {
                **exported.to_dict(),
                "path": None,
                "temporary_file_deleted": True,
            }
            return result

    def approve(
        self,
        summary_id: str,
        *,
        reviewer: str = "user",
        sync_scope: str = "shared",
    ) -> SessionSummaryRecord:
        record = self.sessions.get(summary_id)
        if record is None:
            raise SessionSummaryError(f"session summary not found: {summary_id}")
        if record.status == "approved":
            return record
        if sync_scope not in {"local-only", "shared"}:
            raise SessionSummaryError("session summary sync scope must be local-only or shared")
        policy = self.sync.get_policy(record.persona_id).config
        text = _summary_memory_text(record, policy)
        metadata = {
            "memory_key": f"session:{record.source_adapter}:{record.source_session_id}",
            "session_summary_id": record.id,
            "source_session_id": record.source_session_id,
            "source_title": record.source_title,
            "transcript_hash": record.transcript_hash,
            "summary_hash": record.summary_hash,
            "pending_tasks": list(record.pending_tasks),
            "decisions": list(record.decisions),
            "emotional_context": list(record.emotional_context),
            "source": {
                "adapter": record.source_adapter,
                "runtime_instance_id": record.source_runtime_instance_id,
            },
        }
        item, _ = self.sync.upsert_memory_item(
            persona_id=record.persona_id,
            fingerprint=memory_fingerprint(text, "session-summary"),
            memory_key=memory_key(text, "session-summary", metadata),
            memory_type="session-summary",
            summary=text,
            sensitivity=record.sensitivity,
            sync_scope=sync_scope,
            status="pending",
            source_adapter=record.source_adapter,
            source_runtime_instance_id=record.source_runtime_instance_id,
            source_record_id=record.source_session_id,
            source_path=None,
            metadata=metadata,
        )
        try:
            approved_item = self.memory.approve(
                item.id,
                reviewer=reviewer,
                sync_scope=sync_scope,
            )
        except SyncError as error:
            raise SessionSummaryError(str(error)) from error
        return self.sessions.update_status(
            summary_id,
            "approved",
            reviewer=reviewer,
            sync_scope=sync_scope,
            memory_item_id=approved_item.id,
            metadata_patch={
                "review": {
                    "decision": "approved",
                    "reviewer": reviewer,
                    "reviewed_at": _utc_now(),
                }
            },
        )

    def reject(
        self,
        summary_id: str,
        *,
        reviewer: str = "user",
        reason: str | None = None,
    ) -> SessionSummaryRecord:
        return self.sessions.update_status(
            summary_id,
            "rejected",
            reviewer=reviewer,
            metadata_patch={
                "review": {
                    "decision": "rejected",
                    "reviewer": reviewer,
                    "reason": reason,
                    "reviewed_at": _utc_now(),
                }
            },
        )

    def dashboard(self, persona_id: str) -> dict[str, Any]:
        policy = self.sync.get_policy(persona_id).config
        return {
            "persona_id": persona_id,
            "policy": policy.get("session_summaries", {}),
            "counts": self.sessions.counts(persona_id),
            "summaries": [value.to_dict() for value in self.sessions.list(persona_id)],
            "raw_sessions_persisted": False,
            "system_messages_synchronized": False,
            "tool_messages_synchronized": False,
        }
