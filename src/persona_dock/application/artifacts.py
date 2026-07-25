from __future__ import annotations

import base64
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from persona_dock.adapter_registry import AdapterRegistry, adapter_registry
from persona_dock.character_card import (
    export_character_card,
    import_character_card,
    load_character_card,
)
from persona_dock.compiler import compile_project
from persona_dock.package_trust import (
    generate_signing_key,
    sign_package,
    verify_package,
)
from persona_dock.packaging import export_public, inspect_package, pack_project
from persona_dock.private_backup import (
    create_private_backup,
    inspect_private_backup,
    restore_private_backup,
)
from persona_dock.registry import RegistryService
from persona_dock.registry.database import registry_root
from persona_dock.skill_install import TARGETS as SKILL_TARGETS
from persona_dock.skill_install import install_skill

from .personas import PersonaApplicationService

_FIXED_DATE = (2020, 1, 1, 0, 0, 0)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactPathError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactRoots:
    uploads: Path
    exports: Path
    backups: Path
    keys: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "uploads": str(self.uploads),
            "exports": str(self.exports),
            "backups": str(self.backups),
            "keys": str(self.keys),
        }


class ArtifactStore:
    MAX_UPLOAD_BYTES = 16 * 1024 * 1024

    def __init__(self, root: str | Path | None = None) -> None:
        base = (
            Path(root).expanduser().resolve()
            if root is not None
            else registry_root().resolve()
        )
        self.roots = ArtifactRoots(
            uploads=(base / "uploads").resolve(),
            exports=(base / "exports").resolve(),
            backups=(base / "backups").resolve(),
            keys=(base / "keys").resolve(),
        )
        for path in self.roots.__dict__.values():
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def safe_name(value: str, *, fallback: str = "artifact") -> str:
        name = Path(value.strip()).name
        name = _SAFE_NAME.sub("-", name).strip(".-")
        return name[:180] or fallback

    def root(self, category: str) -> Path:
        try:
            return getattr(self.roots, category)
        except AttributeError as error:
            raise ArtifactPathError(f"unsupported artifact category: {category}") from error

    def output(self, category: str, filename: str) -> Path:
        root = self.root(category)
        path = (root / self.safe_name(filename)).resolve()
        self._require_within(path, (root,))
        return path

    def upload(self, filename: str, content: bytes) -> Path:
        if not content:
            raise ArtifactPathError("uploaded file is empty")
        if len(content) > self.MAX_UPLOAD_BYTES:
            raise ArtifactPathError("uploaded file exceeds 16 MiB")
        destination = self.output("uploads", filename)
        destination.write_bytes(content)
        return destination

    def upload_base64(self, filename: str, content_base64: str) -> Path:
        try:
            content = base64.b64decode(content_base64, validate=True)
        except ValueError as error:
            raise ArtifactPathError("uploaded content is not valid base64") from error
        return self.upload(filename, content)

    def resolve(
        self,
        value: str | Path,
        *,
        categories: Iterable[str] = ("uploads", "exports", "backups", "keys"),
        require_file: bool = True,
    ) -> Path:
        path = Path(value).expanduser().resolve()
        allowed = tuple(self.root(category) for category in categories)
        self._require_within(path, allowed)
        if require_file and not path.is_file():
            raise FileNotFoundError(path)
        return path

    @staticmethod
    def _require_within(path: Path, roots: tuple[Path, ...]) -> None:
        for root in roots:
            try:
                path.relative_to(root)
                return
            except ValueError:
                continue
        raise ArtifactPathError("path is outside PersonaDock managed artifact roots")

    def list(self, category: str) -> list[dict[str, Any]]:
        root = self.root(category)
        values: list[dict[str, Any]] = []
        for path in sorted((item for item in root.rglob("*") if item.is_file()), reverse=True):
            stat = path.stat()
            values.append(
                {
                    "category": category,
                    "name": path.name,
                    "path": str(path),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
        return values


def _zip_directory(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), _FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return destination


class ArtifactApplicationService:
    def __init__(
        self,
        registry: RegistryService | None = None,
        store: ArtifactStore | None = None,
        adapters: AdapterRegistry | None = None,
    ) -> None:
        self.registry = registry or RegistryService()
        self.store = store or ArtifactStore()
        self.adapters = adapters or adapter_registry()

    def persona_root(self, persona_id: str) -> Path:
        record = self.registry.get_persona(persona_id)
        if record is None:
            raise KeyError(f"persona is not registered: {persona_id}")
        if not record.source_path:
            raise ValueError("persona has no source project")
        root = Path(record.source_path).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)
        return root

    @staticmethod
    def _manifest(build: Path) -> dict[str, Any]:
        path = build / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def build(self, persona_id: str, *, targets: list[str] | None = None) -> dict[str, Any]:
        root = self.persona_root(persona_id)
        build = compile_project(root, targets=targets)
        manifest = self._manifest(build)
        archive = self.store.output(
            "exports", f"{manifest['id']}-{manifest['version']}-build.zip"
        )
        _zip_directory(build, archive)
        return {
            "persona_id": persona_id,
            "build": str(build),
            "archive": str(archive),
            "manifest": manifest,
            "files": sorted(
                path.relative_to(build).as_posix()
                for path in build.rglob("*")
                if path.is_file()
            ),
        }

    def pack(self, persona_id: str, *, targets: list[str] | None = None) -> dict[str, Any]:
        root = self.persona_root(persona_id)
        record = self.registry.get_persona(persona_id)
        assert record is not None
        destination = self.store.output(
            "exports", f"{persona_id}-{record.version}.personapack"
        )
        package = pack_project(root, destination=destination, targets=targets)
        return {"path": str(package), "manifest": inspect_package(package)}

    def public_export(self, persona_id: str) -> dict[str, Any]:
        root = self.persona_root(persona_id)
        record = self.registry.get_persona(persona_id)
        assert record is not None
        directory = self.store.roots.exports / f"{persona_id}-{record.version}-public"
        output = export_public(root, destination=directory)
        archive = self.store.output(
            "exports", f"{persona_id}-{record.version}-public.zip"
        )
        _zip_directory(output, archive)
        return {
            "directory": str(output),
            "archive": str(archive),
            "manifest": self._manifest(output),
        }

    def inspect_package(self, path: str | Path) -> dict[str, Any]:
        resolved = self.store.resolve(path, categories=("uploads", "exports"))
        return inspect_package(resolved)

    def list_keys(self) -> list[dict[str, str]]:
        values: list[dict[str, str]] = []
        for public_path in sorted(self.store.roots.keys.glob("*.pub")):
            try:
                payload = json.loads(public_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or not payload.get("key_id"):
                continue
            private_path = public_path.with_suffix("")
            values.append(
                {
                    "name": private_path.name,
                    "key_id": str(payload["key_id"]),
                    "public_key": str(public_path),
                    "private_key_available": str(private_path.is_file()).lower(),
                }
            )
        return values

    def create_key(self, name: str) -> dict[str, str]:
        filename = self.store.safe_name(name, fallback="signing-key")
        if not filename.endswith(".pem"):
            filename += ".pem"
        private_path = self.store.output("keys", filename)
        value = generate_signing_key(private_path)
        return {
            "name": private_path.name,
            "key_id": value["key_id"],
            "public_key": value["public_key"],
        }

    def _private_key(self, key_id: str) -> Path:
        for item in self.list_keys():
            if item["key_id"] == key_id:
                public = Path(item["public_key"])
                private = public.with_suffix("")
                if not private.is_file():
                    raise FileNotFoundError(private)
                return private
        raise KeyError("signing key not found")

    def sign(self, package_path: str | Path, *, key_id: str) -> dict[str, Any]:
        package = self.store.resolve(package_path, categories=("uploads", "exports"))
        private = self._private_key(key_id)
        signature = self.store.output("exports", package.name + ".sig.json")
        result = sign_package(package, private, signature_path=signature)
        return {"signature": str(result), "key_id": key_id}

    def verify(
        self,
        package_path: str | Path,
        *,
        signature_path: str | Path | None = None,
        trust_local_keys: bool = True,
    ) -> dict[str, Any]:
        package = self.store.resolve(package_path, categories=("uploads", "exports"))
        signature = (
            self.store.resolve(signature_path, categories=("uploads", "exports"))
            if signature_path
            else None
        )
        trusted = [item["key_id"] for item in self.list_keys()] if trust_local_keys else []
        return verify_package(
            package,
            signature_path=signature,
            trusted_key_ids=trusted,
        ).to_dict()

    def create_backup(self, persona_id: str, *, password: str) -> dict[str, Any]:
        root = self.persona_root(persona_id)
        record = self.registry.get_persona(persona_id)
        assert record is not None
        destination = self.store.output(
            "backups", f"{persona_id}-{record.version}.pdbackup"
        )
        return create_private_backup(root, destination, password=password).to_dict()

    def inspect_backup(self, path: str | Path) -> dict[str, Any]:
        resolved = self.store.resolve(path, categories=("uploads", "backups"))
        return inspect_private_backup(resolved).to_dict()

    def restore_backup(
        self,
        path: str | Path,
        destination: Path,
        *,
        password: str,
    ) -> dict[str, Any]:
        backup = self.store.resolve(path, categories=("uploads", "backups"))
        restored = restore_private_backup(
            backup,
            destination,
            password=password,
            force=False,
        )
        registered = PersonaApplicationService(self.registry).register(restored)
        return {"restored": str(restored), "persona": registered["persona"]}

    def inspect_character_card(self, path: str | Path) -> dict[str, Any]:
        resolved = self.store.resolve(path, categories=("uploads", "exports"))
        return load_character_card(resolved).info().to_dict()

    def import_character_card(
        self,
        path: str | Path,
        destination: Path,
        *,
        persona_id: str | None = None,
        locale: str = "zh-CN",
    ) -> dict[str, Any]:
        card = self.store.resolve(path, categories=("uploads", "exports"))
        project = import_character_card(
            card,
            destination,
            persona_id=persona_id,
            locale=locale,
            force=False,
        )
        registered = PersonaApplicationService(self.registry).register(project)
        return {"project": str(project), "persona": registered["persona"]}

    def export_character_card(
        self,
        persona_id: str,
        *,
        version: int = 3,
        charx: bool = False,
    ) -> dict[str, Any]:
        root = self.persona_root(persona_id)
        suffix = ".charx" if charx else ".json"
        destination = self.store.output(
            "exports", f"{persona_id}-character-card-v{version}{suffix}"
        )
        result = export_character_card(
            root,
            destination,
            version=version,
            charx=charx,
        )
        return {"path": str(result), "card": load_character_card(result).info().to_dict()}

    def adapter_summary(self) -> dict[str, Any]:
        return self.adapters.summary()

    def adapter(self, name: str) -> dict[str, Any]:
        return self.adapters.descriptor(name).to_dict()

    def adapter_doctor(
        self,
        name: str,
        *,
        container: str | None = None,
        ssh_host: str | None = None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if container:
            options["container"] = container
        if ssh_host:
            options["ssh_host"] = ssh_host
        return self.adapters.doctor(name, **options)

    @staticmethod
    def skill_plan(
        target: str,
        *,
        scope: str,
        project_root: Path | None = None,
    ) -> dict[str, Any]:
        if target not in SKILL_TARGETS:
            raise ValueError(f"unsupported skill target: {target}")
        if scope not in {"project", "global"}:
            raise ValueError("scope must be project or global")
        if scope == "project":
            if project_root is None:
                raise ValueError("project scope requires a project root")
            base = project_root / SKILL_TARGETS[target]["project"]
        else:
            base = SKILL_TARGETS[target]["global"]
        output = (base / "persona-builder").expanduser().resolve()
        return {
            "target": target,
            "scope": scope,
            "destination": str(output),
            "exists": output.exists(),
            "replaces_existing": output.exists(),
        }

    @staticmethod
    def install_persona_skill(
        target: str,
        *,
        scope: str,
        project_root: Path | None = None,
    ) -> dict[str, Any]:
        plan = ArtifactApplicationService.skill_plan(
            target,
            scope=scope,
            project_root=project_root,
        )
        destination = None
        if scope == "project":
            assert project_root is not None
            destination = project_root / SKILL_TARGETS[target]["project"]
        result = install_skill(target, scope=scope, destination=destination)
        return {**plan, "installed": str(result)}


__all__ = [
    "ArtifactApplicationService",
    "ArtifactPathError",
    "ArtifactRoots",
    "ArtifactStore",
]
