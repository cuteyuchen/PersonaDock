from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from persona_dock import session_cli as _session_cli
from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.openclaw import OpenClawAdapter
from persona_dock.io import load_jsonl, write_jsonl
from persona_dock.session_engine import SessionSummaryEngine as _BaseSessionSummaryEngine
from persona_dock.session_models import render_session_handoff


def _enable_session_capabilities(adapter_class: type[Any]) -> None:
    if getattr(adapter_class, "_personadock_session_capabilities", False):
        return
    original = adapter_class.capabilities.fget
    if original is None:
        return

    def capabilities(self: Any):
        return replace(
            original(self),
            session_summary_pull=True,
            raw_session_import=True,
        )

    adapter_class.capabilities = property(capabilities)
    adapter_class._personadock_session_capabilities = True


_enable_session_capabilities(HermesAdapter)
_enable_session_capabilities(OpenClawAdapter)


class SessionSummaryEngine(_BaseSessionSummaryEngine):
    """Phase 7 engine with an explicit PersonaDock-owned handoff mirror."""

    def _write_canonical(self, persona_id: str) -> Path:
        project = self._project(persona_id)
        approved = self.session.list_summaries(persona_id, status="approved")

        canonical_path = project / "memory" / "session-summaries.jsonl"
        write_jsonl(canonical_path, self._canonical_records(persona_id))

        seed_path = project / "memory" / "seed.jsonl"
        existing = load_jsonl(seed_path)
        preserved = [
            item
            for item in existing
            if item.get("source_type") != "session-summary"
            and not item.get("session_summary_id")
        ]
        handoffs: list[dict[str, Any]] = []
        for item in approved:
            if item.sync_scope != "shared":
                continue
            handoffs.append(
                {
                    "id": f"session-summary-{item.id}",
                    "summary": render_session_handoff(item),
                    "type": "session-summary",
                    "reviewed": True,
                    "sensitivity": item.sensitivity,
                    "sync_scope": "shared",
                    "source_type": "session-summary",
                    "session_summary_id": item.id,
                    "source": {
                        "adapter": item.source_adapter,
                        "runtime_instance_id": item.source_runtime_instance_id,
                        "session_id": item.source_session_id,
                        "title": item.source_title,
                    },
                    "review": {
                        "reviewed_at": item.reviewed_at,
                        "reviewed_by": item.reviewed_by,
                    },
                }
            )
        write_jsonl(seed_path, [*preserved, *handoffs])
        return canonical_path


# Keep the mature Phase 6 CLI parser/renderer and replace only its engine binding.
_session_cli.SessionSummaryEngine = SessionSummaryEngine
build_parser = _session_cli.build_parser
main = _session_cli.main


__all__ = ["SessionSummaryEngine", "build_parser", "main"]
