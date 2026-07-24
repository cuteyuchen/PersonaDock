from __future__ import annotations

from dataclasses import dataclass, replace
from importlib import metadata as importlib_metadata
from typing import Any, Callable, Iterable

from persona_dock.adapters.base import (
    ADAPTER_API_VERSION,
    ADAPTER_ENTRY_POINT_GROUP,
    AdapterDescriptor,
    PersonaAdapter,
    validate_adapter_contract,
)
from persona_dock.adapters.hermes import HermesAdapter
from persona_dock.adapters.legacy_filesystem import LegacyFilesystemAdapter
from persona_dock.adapters.openclaw import OpenClawAdapter


AdapterFactory = Callable[..., PersonaAdapter]


def _hermes_factory(**options: Any) -> PersonaAdapter:
    adapter = HermesAdapter(**options)
    adapter.display_name = "Hermes Agent"
    adapter.transports = ("local", "docker")
    return adapter


def _openclaw_factory(**options: Any) -> PersonaAdapter:
    adapter = OpenClawAdapter(**options)
    adapter.display_name = "OpenClaw"
    adapter.transports = ("local", "docker", "ssh")
    return adapter


def _generic_factory(**_: Any) -> PersonaAdapter:
    adapter = LegacyFilesystemAdapter("generic")
    adapter.display_name = "Generic filesystem"
    adapter.transports = ("local", "docker")
    return adapter


@dataclass(frozen=True)
class RegisteredAdapter:
    name: str
    factory: AdapterFactory
    builtin: bool
    metadata: dict[str, Any]


class AdapterRegistry:
    """Registry for built-in and entry-point-provided PersonaDock Adapters."""

    def __init__(self, *, load_plugins: bool = True) -> None:
        self._adapters: dict[str, RegisteredAdapter] = {}
        self._plugin_errors: list[dict[str, str]] = []
        self.register(
            "hermes",
            _hermes_factory,
            builtin=True,
            metadata={"platform": "Hermes Agent", "contract": "native-profile"},
        )
        self.register(
            "openclaw",
            _openclaw_factory,
            builtin=True,
            metadata={"platform": "OpenClaw", "contract": "native-agent-workspace"},
        )
        self.register(
            "generic-filesystem",
            _generic_factory,
            builtin=True,
            metadata={"platform": "Generic filesystem", "contract": "compatibility"},
        )
        if load_plugins:
            self.load_entry_points()

    def register(
        self,
        name: str,
        factory: AdapterFactory,
        *,
        builtin: bool = False,
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> None:
        normalized = name.strip().lower()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("Adapter registry name must be a non-empty token")
        if normalized in self._adapters and not replace:
            raise ValueError(f"Adapter is already registered: {normalized}")
        if not callable(factory):
            raise TypeError("Adapter factory must be callable")
        self._adapters[normalized] = RegisteredAdapter(
            name=normalized,
            factory=factory,
            builtin=builtin,
            metadata=dict(metadata or {}),
        )

    def load_entry_points(self) -> None:
        try:
            values = importlib_metadata.entry_points()
            entry_points: Iterable[Any]
            if hasattr(values, "select"):
                entry_points = values.select(group=ADAPTER_ENTRY_POINT_GROUP)
            else:  # pragma: no cover - compatibility with older importlib metadata
                entry_points = values.get(ADAPTER_ENTRY_POINT_GROUP, ())
        except Exception as error:  # plugin discovery must never break core startup
            self._plugin_errors.append(
                {"entry_point": ADAPTER_ENTRY_POINT_GROUP, "error": str(error)}
            )
            return
        for entry_point in entry_points:
            try:
                loaded = entry_point.load()
                factory: AdapterFactory
                if isinstance(loaded, PersonaAdapter):
                    factory = lambda loaded=loaded, **_: loaded
                elif isinstance(loaded, type) and issubclass(loaded, PersonaAdapter):
                    factory = loaded
                elif callable(loaded):
                    factory = loaded
                else:
                    raise TypeError(
                        "entry point must load a PersonaAdapter, subclass, or factory"
                    )
                self.register(
                    entry_point.name,
                    factory,
                    builtin=False,
                    metadata={
                        "entry_point": f"{entry_point.group}:{entry_point.name}",
                        "distribution": getattr(
                            getattr(entry_point, "dist", None), "name", None
                        ),
                    },
                )
                # Plugins requiring constructor arguments must expose a zero-argument factory.
                self.create(entry_point.name)
            except Exception as error:
                self._adapters.pop(str(entry_point.name).strip().lower(), None)
                self._plugin_errors.append(
                    {"entry_point": str(entry_point.name), "error": str(error)}
                )

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def create(self, name: str, **options: Any) -> PersonaAdapter:
        normalized = name.strip().lower()
        try:
            registered = self._adapters[normalized]
        except KeyError as error:
            raise KeyError(f"Adapter is not registered: {normalized}") from error
        adapter = registered.factory(**options)
        validate_adapter_contract(adapter)
        return adapter

    def descriptor(self, name: str, **options: Any) -> AdapterDescriptor:
        normalized = name.strip().lower()
        registered = self._adapters.get(normalized)
        if registered is None:
            raise KeyError(f"Adapter is not registered: {normalized}")
        adapter = self.create(normalized, **options)
        metadata = {
            **registered.metadata,
            "registry_name": normalized,
            "adapter_api": ADAPTER_API_VERSION,
        }
        descriptor = adapter.descriptor(
            builtin=registered.builtin, metadata=metadata
        )
        return replace(descriptor, name=normalized)

    def descriptors(self) -> list[AdapterDescriptor]:
        values: list[AdapterDescriptor] = []
        for name in self.names():
            try:
                values.append(self.descriptor(name))
            except Exception as error:
                self._plugin_errors.append({"entry_point": name, "error": str(error)})
        return values

    def doctor(self, name: str, **options: Any) -> dict[str, Any]:
        adapter = self.create(name, **options)
        return {
            "descriptor": self.descriptor(name, **options).to_dict(),
            "doctor": adapter.doctor().to_dict(),
        }

    @property
    def plugin_errors(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(value) for value in self._plugin_errors)

    def summary(self) -> dict[str, Any]:
        return {
            "adapter_api_version": ADAPTER_API_VERSION,
            "entry_point_group": ADAPTER_ENTRY_POINT_GROUP,
            "adapters": [descriptor.to_dict() for descriptor in self.descriptors()],
            "plugin_errors": list(self.plugin_errors),
        }


def adapter_registry(*, load_plugins: bool = True) -> AdapterRegistry:
    # Importing Session runtime applies Phase 7 capability declarations before
    # descriptors are serialized. The import is intentionally local to avoid a
    # CLI dependency cycle during module initialization.
    try:
        import persona_dock.session_runtime  # noqa: F401
    except ImportError:
        pass
    return AdapterRegistry(load_plugins=load_plugins)
