"""Stable platform Adapter API for PersonaDock 1.x."""

from .base import (
    ADAPTER_API_VERSION,
    ADAPTER_ENTRY_POINT_GROUP,
    AdapterCapabilities,
    AdapterDescriptor,
    AdapterDoctorResult,
    PersonaAdapter,
    validate_adapter_contract,
)

__all__ = [
    "ADAPTER_API_VERSION",
    "ADAPTER_ENTRY_POINT_GROUP",
    "AdapterCapabilities",
    "AdapterDescriptor",
    "AdapterDoctorResult",
    "PersonaAdapter",
    "validate_adapter_contract",
]
