from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


class TargetResolutionError(ValueError):
    """Raised when PersonaDock cannot select a deployment target safely."""


@dataclass(frozen=True)
class DetectedTarget:
    target: str
    path: Path
    source: str
    confidence: int
    evidence: tuple[str, ...]
    candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["path"] = str(self.path)
        return value


_HERMES_MARKERS = (
    "SOUL.md",
    "config.yaml",
    "skills",
    "memories",
    "profiles",
    "sessions",
    "state.db",
)

_OPENCLAW_MARKERS = (
    "AGENTS.md",
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "MEMORY.md",
    "memory",
    "skills",
)


def _expanded(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def _marker_evidence(path: Path, markers: Iterable[str]) -> tuple[str, ...]:
    return tuple(marker for marker in markers if (path / marker).exists())


def _rank_candidates(
    target: str,
    values: list[tuple[Path, str, int, tuple[str, ...]]],
) -> DetectedTarget:
    unique: dict[str, tuple[Path, str, int, tuple[str, ...]]] = {}
    for path, source, score, evidence in values:
        key = os.path.normcase(str(path))
        current = unique.get(key)
        if current is None or score > current[2]:
            unique[key] = (path, source, score, evidence)

    ranked = sorted(unique.values(), key=lambda item: (-item[2], str(item[0])))
    credible = [item for item in ranked if item[2] >= 40]
    rendered = tuple(f"{path} [{source}, score={score}]" for path, source, score, _ in ranked)

    if not credible:
        detail = "; ".join(rendered) if rendered else "no existing candidate contained agent markers"
        raise TargetResolutionError(
            f"could not safely detect the {target} data directory ({detail}); "
            "run `personadock doctor` and pass an explicit --path"
        )

    if len(credible) > 1 and credible[0][2] == credible[1][2]:
        raise TargetResolutionError(
            f"multiple equally credible {target} directories were found: "
            + "; ".join(rendered)
            + "; pass an explicit --path"
        )

    path, source, score, evidence = credible[0]
    return DetectedTarget(
        target=target,
        path=path,
        source=source,
        confidence=score,
        evidence=evidence,
        candidates=rendered,
    )


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def detect_hermes_target() -> DetectedTarget:
    explicit = os.environ.get("HERMES_HOME")
    if explicit:
        return DetectedTarget(
            target="hermes",
            path=_expanded(explicit),
            source="HERMES_HOME",
            confidence=100,
            evidence=("explicit environment override",),
        )

    home = Path.home()
    candidates: list[tuple[Path, str, int, tuple[str, ...]]] = []
    paths: list[tuple[Path, str]] = [(home / ".hermes", "home-layout")]
    if platform.system().lower() == "windows" and os.environ.get("LOCALAPPDATA"):
        paths.insert(0, (_expanded(os.environ["LOCALAPPDATA"]) / "hermes", "windows-local-app-data"))

    for raw_path, source in paths:
        path = raw_path.resolve()
        if not path.exists():
            continue
        evidence = _marker_evidence(path, _HERMES_MARKERS)
        score = 20 + len(evidence) * 12
        if "SOUL.md" in evidence or "config.yaml" in evidence:
            score += 20
        candidates.append((path, source, score, evidence))

    return _rank_candidates("Hermes", candidates)


def _openclaw_config_workspace() -> Path | None:
    executable = shutil.which("openclaw")
    if executable:
        result = _run([executable, "config", "get", "agents.defaults.workspace"])
        if result and result.returncode == 0:
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if lines:
                value = lines[-1].strip().strip('"\'')
                if value and value.lower() not in {"null", "undefined"}:
                    return _expanded(value)

    state_dir = _expanded(os.environ.get("OPENCLAW_STATE_DIR", "~/.openclaw"))
    config_path = _expanded(os.environ.get("OPENCLAW_CONFIG_PATH", state_dir / "openclaw.json"))
    if not config_path.is_file():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = config.get("agents", {}).get("defaults", {}).get("workspace")
    return _expanded(value) if isinstance(value, str) and value.strip() else None


def detect_openclaw_target() -> DetectedTarget:
    explicit = os.environ.get("OPENCLAW_WORKSPACE_DIR")
    if explicit:
        return DetectedTarget(
            target="openclaw",
            path=_expanded(explicit),
            source="OPENCLAW_WORKSPACE_DIR",
            confidence=100,
            evidence=("explicit environment override",),
        )

    candidates: list[tuple[Path, str, int, tuple[str, ...]]] = []
    configured = _openclaw_config_workspace()
    if configured:
        evidence = _marker_evidence(configured, _OPENCLAW_MARKERS)
        candidates.append((configured, "openclaw-config", 85 + len(evidence), evidence))

    state_dir = _expanded(os.environ.get("OPENCLAW_STATE_DIR", "~/.openclaw"))
    profile = os.environ.get("OPENCLAW_PROFILE", "default").strip() or "default"
    fallback = state_dir / ("workspace" if profile == "default" else f"workspace-{profile}")
    if fallback.exists():
        evidence = _marker_evidence(fallback, _OPENCLAW_MARKERS)
        score = 20 + len(evidence) * 12
        if "SOUL.md" in evidence or "AGENTS.md" in evidence:
            score += 20
        candidates.append((fallback.resolve(), "openclaw-workspace-markers", score, evidence))

    return _rank_candidates("OpenClaw", candidates)


def detect_local_target(target: str) -> DetectedTarget:
    if target == "hermes":
        return detect_hermes_target()
    if target == "openclaw":
        return detect_openclaw_target()
    if target == "generic":
        return DetectedTarget(
            target="generic",
            path=(Path.home() / ".personadock" / "agents" / "generic").resolve(),
            source="personadock-managed",
            confidence=100,
            evidence=("PersonaDock-owned directory",),
        )
    raise ValueError(f"unsupported target: {target}")


def resolve_local_target(target: str, destination: str | Path | None) -> DetectedTarget:
    if destination is not None:
        return DetectedTarget(
            target=target,
            path=_expanded(destination),
            source="explicit-path",
            confidence=100,
            evidence=("--path",),
        )
    return detect_local_target(target)
