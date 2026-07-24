from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from persona_dock.core.models import load_canonical_persona
from persona_dock.io import load_yaml
from persona_dock.project import find_project


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    passed: bool
    message: str
    linked_behaviors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersonaTestReport:
    project: str
    passed: int
    failed: int
    results: tuple[ScenarioResult, ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "passed": self.passed,
            "failed": self.failed,
            "ok": self.ok,
            "results": [item.to_dict() for item in self.results],
        }


def _scenario_file(root: Path) -> dict[str, Any]:
    path = root / "tests" / "scenarios.yaml"
    if not path.is_file():
        return {"schema_version": 1, "scenarios": []}
    return load_yaml(path)


def run_persona_tests(root: Path) -> PersonaTestReport:
    root = find_project(root)
    persona = load_canonical_persona(root)
    scenarios = _scenario_file(root).get("scenarios", [])
    behaviors = {item["id"]: item for item in persona["behaviors"]}
    boundaries = {item["id"]: item for item in persona["boundaries"]}
    results: list[ScenarioResult] = []

    for raw in scenarios:
        if not isinstance(raw, dict):
            continue
        scenario_id = str(raw.get("id", "scenario"))
        linked = tuple(
            sorted(
                item["id"]
                for item in persona["behaviors"]
                if scenario_id in item.get("tests", [])
            )
        )
        required_behaviors = tuple(str(item) for item in raw.get("requires_behaviors", []))
        required_boundaries = tuple(str(item) for item in raw.get("requires_boundaries", []))
        missing_behaviors = [item for item in required_behaviors if item not in behaviors]
        missing_boundaries = [item for item in required_boundaries if item not in boundaries]
        require_link = bool(raw.get("require_behavior_link", True))
        failures: list[str] = []
        if require_link and not linked and not required_behaviors:
            failures.append("no behavior rule links this scenario")
        if missing_behaviors:
            failures.append("missing behaviors: " + ", ".join(missing_behaviors))
        if missing_boundaries:
            failures.append("missing boundaries: " + ", ".join(missing_boundaries))

        results.append(
            ScenarioResult(
                id=scenario_id,
                passed=not failures,
                message="passed" if not failures else "; ".join(failures),
                linked_behaviors=linked,
            )
        )

    # Global quality checks are represented as stable synthetic scenarios.
    high_priority_without_tests = [
        item["id"]
        for item in persona["behaviors"]
        if item.get("priority") in {"high", "critical"} and not item.get("tests")
    ]
    results.append(
        ScenarioResult(
            id="coverage-high-priority-behaviors",
            passed=not high_priority_without_tests,
            message=(
                "passed"
                if not high_priority_without_tests
                else "high-priority behaviors without tests: " + ", ".join(high_priority_without_tests)
            ),
            linked_behaviors=tuple(high_priority_without_tests),
        )
    )
    missing_evidence = [
        item["id"]
        for item in persona["behaviors"]
        if item.get("source_type") == "observed-evidence" and not item.get("evidence")
    ]
    results.append(
        ScenarioResult(
            id="evidence-observed-behaviors",
            passed=not missing_evidence,
            message=(
                "passed"
                if not missing_evidence
                else "observed behaviors without evidence: " + ", ".join(missing_evidence)
            ),
            linked_behaviors=tuple(missing_evidence),
        )
    )

    passed = sum(1 for item in results if item.passed)
    failed = len(results) - passed
    return PersonaTestReport(
        project=str(root),
        passed=passed,
        failed=failed,
        results=tuple(results),
    )
