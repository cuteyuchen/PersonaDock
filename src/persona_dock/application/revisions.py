from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_dock.core.diff import diff_personas
from persona_dock.core.models import normalize_canonical_persona
from persona_dock.io import dump_yaml
from persona_dock.project import PROJECT_FILE
from persona_dock.registry.database import registry_root


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_bytes(model: dict[str, Any]) -> bytes:
    normalized = normalize_canonical_persona(model)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(model: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(model)).hexdigest()


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    revision_id: str
    persona_id: str
    parent_revision_id: str | None
    created_at: str
    source: str
    summary: str
    content_hash: str
    validation_result: dict[str, Any]
    test_result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RevisionStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = (
            Path(root).expanduser().resolve()
            if root is not None
            else (registry_root() / "revisions").resolve()
        )
        self.root.mkdir(parents=True, exist_ok=True)

    def _persona_root(self, persona_id: str) -> Path:
        if not persona_id or any(value in persona_id for value in ("/", "\\", "..")):
            raise ValueError("unsafe persona id")
        root = self.root / persona_id
        (root / "objects").mkdir(parents=True, exist_ok=True)
        (root / "manifests").mkdir(parents=True, exist_ok=True)
        return root

    def capture(
        self,
        persona_id: str,
        model: dict[str, Any],
        *,
        source: str,
        summary: str = "",
        validation_result: dict[str, Any] | None = None,
        test_result: dict[str, Any] | None = None,
    ) -> RevisionRecord:
        normalized = normalize_canonical_persona(model)
        if normalized["id"] != persona_id:
            raise ValueError("revision Persona ID does not match model")
        payload = _canonical_bytes(normalized)
        content_hash = hashlib.sha256(payload).hexdigest()
        root = self._persona_root(persona_id)
        object_path = root / "objects" / f"{content_hash}.json"
        if not object_path.exists():
            object_path.write_bytes(payload + b"\n")

        latest = self.latest(persona_id)
        record = RevisionRecord(
            revision_id=str(uuid.uuid4()),
            persona_id=persona_id,
            parent_revision_id=latest.revision_id if latest else None,
            created_at=utc_now(),
            source=source,
            summary=summary.strip(),
            content_hash=content_hash,
            validation_result=validation_result or {},
            test_result=test_result or {},
        )
        manifest = root / "manifests" / f"{record.created_at.replace(':', '')}-{record.revision_id}.json"
        manifest.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return record

    def list(self, persona_id: str) -> list[RevisionRecord]:
        root = self._persona_root(persona_id)
        values: list[RevisionRecord] = []
        for path in sorted((root / "manifests").glob("*.json"), reverse=True):
            value = json.loads(path.read_text(encoding="utf-8"))
            values.append(RevisionRecord(**value))
        return values

    def get(self, persona_id: str, revision_id: str) -> RevisionRecord | None:
        for record in self.list(persona_id):
            if record.revision_id == revision_id:
                return record
        return None

    def latest(self, persona_id: str) -> RevisionRecord | None:
        values = self.list(persona_id)
        return values[0] if values else None

    def model(self, persona_id: str, revision_id: str) -> dict[str, Any]:
        record = self.get(persona_id, revision_id)
        if record is None:
            raise KeyError(revision_id)
        path = self._persona_root(persona_id) / "objects" / f"{record.content_hash}.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        return normalize_canonical_persona(json.loads(path.read_text(encoding="utf-8")))

    def diff(
        self,
        before_model: dict[str, Any],
        after_model: dict[str, Any],
    ) -> dict[str, Any]:
        before = normalize_canonical_persona(before_model)
        after = normalize_canonical_persona(after_model)
        with tempfile.TemporaryDirectory(prefix="personadock-revision-diff-") as directory:
            root = Path(directory)
            before_root = root / "before"
            after_root = root / "after"
            before_root.mkdir()
            after_root.mkdir()
            (before_root / PROJECT_FILE).write_text(dump_yaml(before), encoding="utf-8")
            (after_root / PROJECT_FILE).write_text(dump_yaml(after), encoding="utf-8")
            result = diff_personas(before_root, after_root).to_dict()
        result["before_hash"] = canonical_hash(before)
        result["after_hash"] = canonical_hash(after)
        result["risk"] = self._risk(result)
        return result

    @staticmethod
    def _risk(diff: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        level = "low"
        if diff.get("added_boundaries") or diff.get("removed_boundaries") or diff.get("changed_boundaries"):
            level = "high"
            reasons.append("人格边界发生变化")
        if diff.get("added_behaviors") or diff.get("removed_behaviors") or diff.get("changed_behaviors"):
            level = "high"
            reasons.append("行为规则发生变化")
        paths = {item.get("path") for item in diff.get("field_changes", [])}
        if "memory" in paths:
            level = "high"
            reasons.append("Memory Policy 发生变化")
        elif paths & {"identity.statement", "identity.core_traits", "voice.style", "voice.principles"} and level == "low":
            level = "medium"
            reasons.append("身份或表达方式发生变化")
        if not reasons and diff.get("changed"):
            reasons.append("普通字段发生变化")
        if not diff.get("changed"):
            level = "none"
            reasons.append("内容一致")
        return {"level": level, "reasons": reasons}

    @staticmethod
    def restore_plan(
        persona_id: str,
        current_model: dict[str, Any],
        target_revision_id: str,
        target_model: dict[str, Any],
    ) -> dict[str, Any]:
        current_hash = canonical_hash(current_model)
        target_hash = canonical_hash(target_model)
        seed = f"{persona_id}\x1f{current_hash}\x1f{target_revision_id}\x1f{target_hash}"
        plan_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return {
            "persona_id": persona_id,
            "target_revision_id": target_revision_id,
            "current_hash": current_hash,
            "target_hash": target_hash,
            "plan_hash": plan_hash,
            "requires_confirmation": current_hash != target_hash,
        }


__all__ = [
    "RevisionRecord",
    "RevisionStore",
    "canonical_hash",
]
