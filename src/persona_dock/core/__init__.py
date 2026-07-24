"""Canonical Persona v3 models, migration, diff, and tests."""

from .diff import diff_personas
from .migration import migrate_project_to_v3
from .models import load_canonical_persona, normalize_canonical_persona
from .testing import run_persona_tests

__all__ = [
    "diff_personas",
    "load_canonical_persona",
    "migrate_project_to_v3",
    "normalize_canonical_persona",
    "run_persona_tests",
]
