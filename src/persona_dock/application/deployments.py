from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.openclaw import OpenClawAdapter
from persona_dock.hermes_deployment import (
    apply_hermes_deployment,
    plan_hermes_deployment,
    rollback_hermes_deployment,
)
from persona_dock.openclaw_deployment import (
    apply_openclaw_deployment,
    plan_openclaw_deployment,
    rollback_openclaw_deployment,
)
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root

from .artifacts import ArtifactApplicationService, ArtifactStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_plan(value: dict[str, Any]) -> dict[str, Any]:
    stable = deepcopy(value)
    stable.pop("id", None)
    stable.pop("snapshot_path", None)
    stable.pop("commands", None)
    artifact = stable.get("artifact")
    if isinstance(artifact, dict):
        artifact.pop("path", None)
    return stable


def semantic_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_dump(_stable_plan(value)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeploymentRecord:
    id: str
    kind: str
    status: str
    request: dict[str, Any]
    plan: dict[str, Any]
    semantic_hash: str
    output: dict[str, Any]
    error: str | None
    created_at: str
    updated_at: str
    applied_at: str | None
    rolled_back_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_deployment_plans (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    output_json TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_at TEXT,
    rolled_back_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_web_deployments_created
    ON web_deployment_plans(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_web_deployments_status
    ON web_deployment_plans(status, created_at DESC);
"""


class DeploymentPlanChangedError(RuntimeError):
    pass


class DeploymentStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path).expanduser().resolve()
            if path is not None
            else (registry_root() / "control-plane.db").resolve()
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> DeploymentRecord:
        return DeploymentRecord(
            id=str(row["id"]),
            kind=str(row["kind"]),
            status=str(row["status"]),
            request=_load(row["request_json"], {}),
            plan=_load(row["plan_json"], {}),
            semantic_hash=str(row["semantic_hash"]),
            output=_load(row["output_json"], {}),
            error=row["error"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            applied_at=row["applied_at"],
            rolled_back_at=row["rolled_back_at"],
        )

    def create(
        self,
        *,
        kind: str,
        request: dict[str, Any],
        plan: dict[str, Any],
        confirmation_token: str,
    ) -> DeploymentRecord:
        plan_id = str(plan["id"])
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO web_deployment_plans(
                    id, kind, status, request_json, plan_json, semantic_hash,
                    token_hash, output_json, created_at, updated_at
                ) VALUES(?, ?, 'planned', ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    plan_id,
                    kind,
                    _dump(request),
                    _dump(plan),
                    semantic_hash(plan),
                    _token_hash(confirmation_token),
                    now,
                    now,
                ),
            )
        value = self.get(plan_id)
        assert value is not None
        return value

    def get(self, plan_id: str) -> DeploymentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM web_deployment_plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return self._record(row) if row else None

    def list(self, *, limit: int = 100) -> list[DeploymentRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM web_deployment_plans ORDER BY created_at DESC, id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [self._record(row) for row in rows]

    def token_matches(self, record: DeploymentRecord, token: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT token_hash FROM web_deployment_plans WHERE id = ?", (record.id,)
            ).fetchone()
        return bool(row) and hmac.compare_digest(str(row["token_hash"]), _token_hash(token))

    def update(
        self,
        plan_id: str,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> DeploymentRecord:
        current = self.get(plan_id)
        if current is None:
            raise KeyError(plan_id)
        now = utc_now()
        applied_at = current.applied_at
        rolled_back_at = current.rolled_back_at
        if status == "applied":
            applied_at = applied_at or now
        if status == "rolled-back":
            rolled_back_at = rolled_back_at or now
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE web_deployment_plans SET
                    status = ?, output_json = ?, error = ?, updated_at = ?,
                    applied_at = ?, rolled_back_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    _dump(current.output if output is None else output),
                    error,
                    now,
                    applied_at,
                    rolled_back_at,
                    plan_id,
                ),
            )
        value = self.get(plan_id)
        assert value is not None
        return value


class DeploymentApplicationService:
    def __init__(
        self,
        registry: RegistryService | None = None,
        artifacts: ArtifactApplicationService | None = None,
        store: DeploymentStore | None = None,
        *,
        hermes_planner: Callable[..., Any] = plan_hermes_deployment,
        hermes_applier: Callable[..., Any] = apply_hermes_deployment,
        hermes_rollback: Callable[..., Any] = rollback_hermes_deployment,
        openclaw_planner: Callable[..., Any] = plan_openclaw_deployment,
        openclaw_applier: Callable[..., Any] = apply_openclaw_deployment,
        openclaw_rollback: Callable[..., Any] = rollback_openclaw_deployment,
    ) -> None:
        self.registry = registry or RegistryService()
        self.artifacts = artifacts or ArtifactApplicationService(
            self.registry, ArtifactStore()
        )
        self.store = store or DeploymentStore()
        self.hermes_planner = hermes_planner
        self.hermes_applier = hermes_applier
        self.hermes_rollback = hermes_rollback
        self.openclaw_planner = openclaw_planner
        self.openclaw_applier = openclaw_applier
        self.openclaw_rollback = openclaw_rollback

    def _package(self, request: dict[str, Any]) -> Path:
        package_path = request.get("package_path")
        persona_id = request.get("persona_id")
        target = str(request["target"])
        if package_path:
            return self.artifacts.store.resolve(
                str(package_path), categories=("uploads", "exports")
            )
        if not persona_id:
            raise ValueError("deployment plan requires persona_id or package_path")
        packed = self.artifacts.pack(str(persona_id), targets=[target])
        return Path(str(packed["path"]))

    def _render(self, request: dict[str, Any]) -> tuple[str, Any]:
        target = str(request["target"])
        package = self._package(request)
        if target == "hermes":
            container = request.get("container") or None
            adapter = HermesAdapter(container=container)
            plan = self.hermes_planner(
                package,
                profile=request.get("profile") or None,
                profile_explicit=bool(request.get("profile")),
                activate=bool(request.get("activate")),
                alias=bool(request.get("alias")),
                container=container,
                adapter=adapter,
            )
            return target, plan
        if target == "openclaw":
            container = request.get("container") or None
            ssh_host = request.get("ssh_host") or None
            adapter = OpenClawAdapter(container=container, ssh_host=ssh_host)
            plan = self.openclaw_planner(
                package,
                agent=request.get("agent") or None,
                agent_explicit=bool(request.get("agent")),
                workspace=request.get("workspace") or None,
                model=request.get("model") or None,
                bindings=tuple(request.get("bindings") or ()),
                take_ownership=bool(request.get("take_ownership")),
                container=container,
                ssh_host=ssh_host,
                adapter=adapter,
            )
            return target, plan
        raise ValueError(f"unsupported native deployment target: {target}")

    def create_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        kind, plan = self._render(request)
        rendered = plan.to_dict()
        confirmation_token = secrets.token_urlsafe(32)
        record = self.store.create(
            kind=kind,
            request=request,
            plan=rendered,
            confirmation_token=confirmation_token,
        )
        return {
            "deployment": record.to_dict(),
            "confirmation_token": confirmation_token,
        }

    def apply(self, plan_id: str, *, confirmation_token: str) -> dict[str, Any]:
        record = self.store.get(plan_id)
        if record is None:
            raise KeyError(plan_id)
        if record.status != "planned":
            raise ValueError(f"deployment plan is not applicable: {record.status}")
        if not self.store.token_matches(record, confirmation_token):
            raise PermissionError("deployment confirmation token is invalid")

        kind, refreshed = self._render(record.request)
        refreshed_dict = refreshed.to_dict()
        if kind != record.kind or semantic_hash(refreshed_dict) != record.semantic_hash:
            raise DeploymentPlanChangedError(
                "deployment inputs or runtime state changed; create a new plan"
            )

        self.store.update(plan_id, status="applying")
        try:
            if kind == "hermes":
                adapter = HermesAdapter(container=record.request.get("container") or None)
                result = self.hermes_applier(
                    refreshed, adapter=adapter, registry=self.registry
                ).to_dict()
            else:
                adapter = OpenClawAdapter(
                    container=record.request.get("container") or None,
                    ssh_host=record.request.get("ssh_host") or None,
                )
                result = self.openclaw_applier(
                    refreshed, adapter=adapter, registry=self.registry
                ).to_dict()
        except Exception as error:
            self.store.update(plan_id, status="failed", error=str(error))
            raise
        applied = self.store.update(plan_id, status="applied", output=result)
        return applied.to_dict()

    def rollback(self, deployment_id: str) -> dict[str, Any]:
        record = self.store.get(deployment_id)
        if record is None:
            raise KeyError(deployment_id)
        if record.status != "applied":
            raise ValueError(f"deployment cannot be rolled back: {record.status}")
        output = record.output
        request = record.request
        try:
            if record.kind == "hermes":
                result = self.hermes_rollback(
                    profile=str(output["profile"]),
                    snapshot=output.get("snapshot_path"),
                    container=request.get("container") or None,
                    activate=bool(request.get("activate")),
                    registry=self.registry,
                )
            else:
                result = self.openclaw_rollback(
                    agent=str(output["agent"]),
                    snapshot=output.get("snapshot_path"),
                    workspace=output.get("workspace"),
                    delete_agent=bool(output.get("created_agent") and not output.get("snapshot_path")),
                    container=request.get("container") or None,
                    ssh_host=request.get("ssh_host") or None,
                    registry=self.registry,
                )
        except Exception as error:
            self.store.update(deployment_id, status="rollback-failed", error=str(error))
            raise
        value = self.store.update(
            deployment_id,
            status="rolled-back",
            output={**output, "rollback": result},
        )
        return value.to_dict()

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.store.list(limit=limit)]

    def get(self, deployment_id: str) -> dict[str, Any] | None:
        value = self.store.get(deployment_id)
        return value.to_dict() if value else None


__all__ = [
    "DeploymentApplicationService",
    "DeploymentPlanChangedError",
    "DeploymentRecord",
    "DeploymentStore",
    "semantic_hash",
]
