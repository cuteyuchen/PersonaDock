from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AdapterCapabilities:
    discovery: bool = False
    native_deployment: bool = False
    filesystem_deployment: bool = False
    memory_pull: bool = False
    memory_push: bool = False
    session_summary_pull: bool = False
    raw_session_import: bool = False
    docker: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class AdapterDoctorResult:
    adapter: str
    available: bool
    executable: str | None
    version: str | None
    status: str
    message: str
    capabilities: AdapterCapabilities
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["capabilities"] = self.capabilities.to_dict()
        return value


class PersonaAdapter(ABC):
    """Stable contract used by CLI, Web, and future registry services."""

    name: str

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        raise NotImplementedError

    @abstractmethod
    def doctor(self) -> AdapterDoctorResult:
        raise NotImplementedError

    @abstractmethod
    def plan_deployment(
        self,
        package: str,
        *,
        destination: str | None = None,
        container: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError
