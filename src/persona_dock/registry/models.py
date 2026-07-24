from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PersonaRecord:
    id: str
    name: str
    version: str
    source_path: str | None
    schema_version: int
    summary: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeInstanceRecord:
    id: str
    adapter: str
    transport: str
    platform_instance_id: str
    display_name: str
    location: str
    capabilities: dict[str, Any]
    metadata: dict[str, Any]
    managed: bool
    first_seen_at: str
    last_seen_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BindingRecord:
    id: str
    persona_id: str
    runtime_instance_id: str
    adopted: bool
    sync_policy_id: str | None
    last_deployed_version: str | None
    managed_since: str
    last_synced_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryReport:
    scanned_adapters: tuple[str, ...]
    instances: tuple[RuntimeInstanceRecord, ...]
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_adapters": list(self.scanned_adapters),
            "instances": [instance.to_dict() for instance in self.instances],
            "warnings": list(self.warnings),
            "metadata": self.metadata,
        }
