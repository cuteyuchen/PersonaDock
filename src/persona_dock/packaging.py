from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .compiler import compile_project
from .io import sha256_file
from .project import find_project

FIXED_DATE = (2020, 1, 1, 0, 0, 0)
PERSONAPACK_FORMAT_VERSION = 2
CANONICAL_SCHEMA_VERSION = 3
ADAPTER_API_COMPATIBILITY = "1.x"


def _write_zip(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def _stabilize_manifest(build: Path) -> dict[str, Any]:
    path = build / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["compatibility"] = {
        "personapack": "2.x" if int(manifest.get("format_version", 0)) == 2 else "1.x",
        "canonical_schema": str(manifest.get("schema_version", "unknown")),
        "adapter_api": ADAPTER_API_COMPATIBILITY,
        "minimum_personadock": "1.0.0" if int(manifest.get("schema_version", 0)) == 3 else "0.1.0",
    }
    manifest["trust"] = {
        "digest_algorithm": "sha256",
        "signature_scheme": "detached-ed25519-v1",
        "signature_required": False,
        "signed": False,
        "note": "Detached signatures cover the complete deterministic PersonaPack archive.",
    }
    manifest["ownership"] = {
        "runtime_private_state_included": False,
        "runtime_credentials_included": False,
        "runtime_sessions_included": False,
        "adapter_managed_files_only": True,
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def pack_project(
    root: Path,
    destination: Path | None = None,
    targets: list[str] | None = None,
) -> Path:
    root = find_project(root)
    build = compile_project(root, targets=targets)
    manifest = _stabilize_manifest(build)
    destination = destination or root / "dist" / f"{manifest['id']}-{manifest['version']}.personapack"
    destination = destination.expanduser().resolve()
    _write_zip(build, destination)
    return destination


def inspect_package(package: Path) -> dict[str, Any]:
    package = package.expanduser().resolve()
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        if "manifest.json" not in names:
            raise ValueError("not a PersonaPack: manifest.json is missing")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        expected = manifest.get("files", {})
        if not isinstance(expected, dict):
            raise ValueError("PersonaPack manifest files must be an object")
        mismatches: list[str] = []
        for name, digest in expected.items():
            if name not in names:
                mismatches.append(f"missing {name}")
                continue
            import hashlib

            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != digest:
                mismatches.append(f"checksum mismatch: {name}")
        expected_names = set(expected) | {"manifest.json"}
        for name in sorted(names - expected_names):
            if name.endswith("/"):
                continue
            mismatches.append(f"unexpected file: {name}")
        manifest["integrity"] = "ok" if not mismatches else "failed"
        manifest["integrity_errors"] = mismatches
    # On Windows a second open can fail while ZipFile still owns the archive
    # handle. Hash the complete package only after leaving the ZIP context.
    manifest["package_sha256"] = sha256_file(package)
    return manifest


def extract_package(package: Path, destination: Path) -> dict[str, Any]:
    info = inspect_package(package)
    if info["integrity"] != "ok":
        raise ValueError("PersonaPack integrity check failed")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as archive:
        for member in archive.infolist():
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe package path: {member.filename}")
        archive.extractall(destination)
    return info


def export_public(root: Path, destination: Path | None = None) -> Path:
    root = find_project(root)
    build = compile_project(root)
    _stabilize_manifest(build)
    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    destination = destination or root / "dist" / f"{manifest['id']}-{manifest['version']}-public"
    destination = destination.expanduser().resolve()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(build, destination)
    for memory_file in destination.glob("targets/*/memory/seed.jsonl"):
        memory_file.write_text("", encoding="utf-8")
    for memory_md in destination.glob("targets/*/memory/MEMORY.md"):
        memory_md.write_text(
            "# Public PersonaPack\n\nPrivate memory was removed.\n", encoding="utf-8"
        )
    manifest_path = destination / "manifest.json"
    public_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public_manifest["privacy"]["memory_policy"] = "none"
    public_manifest["privacy"]["public_export"] = True
    public_manifest["files"] = {
        path.relative_to(destination).as_posix(): sha256_file(path)
        for path in sorted(
            p
            for p in destination.rglob("*")
            if p.is_file() and p.name != "manifest.json"
        )
    }
    manifest_path.write_text(
        json.dumps(public_manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destination
