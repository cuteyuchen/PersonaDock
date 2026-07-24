from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


ADAPTER_API_VERSION = "1.0"
ADAPTER_ENTRY_POINT_GROUP = "personadock.adapters"


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


@dataclass(frozen=True)
class AdapterDescriptor:
    """Serializable compatibility record for one Adapter implementation."""

    name: str
    display_name: str
    api_version: str
    implementation: str
    builtin: bool
    transports: tuple[str, ...]
    capabilities: AdapterCapabilities
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["transports"] = list(self.transports)
        value["capabilities"] = self.capabilities.to_dict()
        return value


class PersonaAdapter(ABC):
    """Stable Adapter API used by CLI, Web, Registry, and external plugins.

    PersonaDock 1.x guarantees backward compatibility for methods declared by
    this class and for the serialized fields of ``AdapterDescriptor``. New
    optional capabilities may be added during the 1.x line, but existing fields
    will not be removed or change meaning.
    """

    name: str
    api_version = ADAPTER_API_VERSION
    display_name: str | None = None
    transports: tuple[str, ...] = ("local",)

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

    def descriptor(
        self,
        *,
        builtin: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> AdapterDescriptor:
        implementation = f"{type(self).__module__}:{type(self).__qualname__}"
        return AdapterDescriptor(
            name=self.name,
            display_name=self.display_name or self.name,
            api_version=self.api_version,
            implementation=implementation,
            builtin=builtin,
            transports=tuple(self.transports),
            capabilities=self.capabilities,
            metadata=dict(metadata or {}),
        )


def adapter_api_major(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid Adapter API version: {version!r}") from error


def validate_adapter_contract(adapter: PersonaAdapter) -> None:
    if not isinstance(adapter, PersonaAdapter):
        raise TypeError("Adapter factory must return a PersonaAdapter instance")
    name = str(getattr(adapter, "name", "")).strip()
    if not name or any(character.isspace() for character in name):
        raise ValueError("Adapter name must be a non-empty token without whitespace")
    if adapter_api_major(adapter.api_version) != adapter_api_major(ADAPTER_API_VERSION):
        raise ValueError(
            f"Adapter {name} uses incompatible API {adapter.api_version}; "
            f"PersonaDock requires {ADAPTER_API_VERSION}.x-compatible API"
        )
    capabilities = adapter.capabilities
    if not isinstance(capabilities, AdapterCapabilities):
        raise TypeError(f"Adapter {name} capabilities must be AdapterCapabilities")
    doctor = adapter.doctor
    planner = adapter.plan_deployment
    if not callable(doctor) or not callable(planner):
        raise TypeError(f"Adapter {name} does not implement the stable Adapter API")
