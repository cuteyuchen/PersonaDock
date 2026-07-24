from __future__ import annotations

import base64
import json
import re
import struct
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from persona_dock.compiler import compile_soul
from persona_dock.io import dump_yaml, load_yaml
from persona_dock.project import PROJECT_FILE, init_project


class CharacterCardError(RuntimeError):
    """Raised when a Character Card cannot be parsed, imported, or exported."""


@dataclass(frozen=True)
class CharacterCardInfo:
    path: str
    container: str
    spec: str
    spec_version: str
    name: str
    character_version: str
    creator: str
    tags: tuple[str, ...]
    extensions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "container": self.container,
            "spec": self.spec,
            "spec_version": self.spec_version,
            "name": self.name,
            "character_version": self.character_version,
            "creator": self.creator,
            "tags": list(self.tags),
            "extensions": list(self.extensions),
        }


@dataclass(frozen=True)
class CharacterCardDocument:
    raw: dict[str, Any]
    data: dict[str, Any]
    container: str
    path: Path

    @property
    def spec(self) -> str:
        return str(self.raw.get("spec") or "chara_card_v1")

    @property
    def spec_version(self) -> str:
        return str(self.raw.get("spec_version") or "1.0")

    def info(self) -> CharacterCardInfo:
        tags = self.data.get("tags")
        extensions = self.data.get("extensions")
        return CharacterCardInfo(
            path=str(self.path),
            container=self.container,
            spec=self.spec,
            spec_version=self.spec_version,
            name=str(self.data.get("name") or "Unnamed Character"),
            character_version=str(self.data.get("character_version") or ""),
            creator=str(self.data.get("creator") or ""),
            tags=tuple(str(value) for value in tags) if isinstance(tags, list) else (),
            extensions=tuple(sorted(str(key) for key in extensions))
            if isinstance(extensions, dict)
            else (),
        )


def _normalize_card(payload: Any, *, path: Path, container: str) -> CharacterCardDocument:
    if not isinstance(payload, dict):
        raise CharacterCardError("Character Card root must be an object")
    if isinstance(payload.get("data"), dict):
        data = dict(payload["data"])
        raw = dict(payload)
    else:
        # Character Card V1 places fields at the root.
        data = dict(payload)
        raw = {
            "spec": "chara_card_v1",
            "spec_version": "1.0",
            "data": data,
        }
    name = str(data.get("name") or "").strip()
    if not name:
        raise CharacterCardError("Character Card name is missing")
    data["name"] = name
    for key in (
        "description",
        "personality",
        "scenario",
        "first_mes",
        "mes_example",
        "creator_notes",
        "system_prompt",
        "post_history_instructions",
        "creator",
        "character_version",
    ):
        value = data.get(key)
        data[key] = str(value) if value is not None else ""
    for key in ("alternate_greetings", "tags"):
        value = data.get(key)
        data[key] = [str(item) for item in value] if isinstance(value, list) else []
    if not isinstance(data.get("extensions"), dict):
        data["extensions"] = {}
    raw["data"] = data
    return CharacterCardDocument(raw=raw, data=data, container=container, path=path)


def _png_chunks(data: bytes):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CharacterCardError("invalid PNG signature")
    cursor = 8
    while cursor + 12 <= len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        chunk_type = data[cursor + 4 : cursor + 8]
        chunk_data = data[cursor + 8 : cursor + 8 + length]
        cursor += 12 + length
        if len(chunk_data) != length:
            raise CharacterCardError("truncated PNG metadata chunk")
        yield chunk_type, chunk_data
        if chunk_type == b"IEND":
            break


def _png_text_values(data: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for chunk_type, chunk in _png_chunks(data):
        try:
            if chunk_type == b"tEXt":
                keyword, text = chunk.split(b"\x00", 1)
                values[keyword.decode("latin-1")] = text.decode("latin-1")
            elif chunk_type == b"zTXt":
                keyword, rest = chunk.split(b"\x00", 1)
                if not rest or rest[0] != 0:
                    continue
                values[keyword.decode("latin-1")] = zlib.decompress(rest[1:]).decode(
                    "utf-8"
                )
            elif chunk_type == b"iTXt":
                parts = chunk.split(b"\x00", 5)
                if len(parts) != 6:
                    continue
                keyword, compressed, method, _language, _translated, text = parts
                if compressed == b"\x01" and method == b"\x00":
                    text = zlib.decompress(text)
                values[keyword.decode("latin-1")] = text.decode("utf-8")
        except (ValueError, UnicodeDecodeError, zlib.error):
            continue
    return values


def _load_png(path: Path) -> CharacterCardDocument:
    values = _png_text_values(path.read_bytes())
    encoded = values.get("ccv3") or values.get("chara")
    if not encoded:
        raise CharacterCardError("PNG does not contain ccv3 or chara metadata")
    try:
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CharacterCardError("PNG Character Card metadata is invalid") from error
    return _normalize_card(payload, path=path, container="png")


def _load_charx(path: Path) -> CharacterCardDocument:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "card.json" not in names:
            raise CharacterCardError("CHARX archive is missing root card.json")
        for member in archive.infolist():
            value = Path(member.filename)
            if value.is_absolute() or ".." in value.parts:
                raise CharacterCardError(f"unsafe CHARX path: {member.filename}")
        try:
            payload = json.loads(archive.read("card.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CharacterCardError("CHARX card.json is invalid") from error
    return _normalize_card(payload, path=path, container="charx")


def load_character_card(path: Path) -> CharacterCardDocument:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    suffix = resolved.suffix.lower()
    if suffix in {".charx", ".zip"}:
        return _load_charx(resolved)
    if suffix == ".png":
        return _load_png(resolved)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CharacterCardError("Character Card JSON is invalid") from error
    return _normalize_card(payload, path=resolved, container="json")


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        digest = __import__("hashlib").sha256(value.encode("utf-8")).hexdigest()[:10]
        slug = f"character-{digest}"
    return slug[:63].strip("-")


def _traits(personality: str) -> list[str]:
    values = [
        value.strip(" -*\t")
        for value in re.split(r"[\n,，;；]+", personality)
        if value.strip(" -*\t")
    ]
    return values[:12]


def _reference_markdown(data: dict[str, Any]) -> str:
    sections = ["# Imported Character Card", ""]
    for key, title in (
        ("description", "Description"),
        ("personality", "Personality"),
        ("scenario", "Scenario"),
        ("system_prompt", "System Prompt"),
        ("post_history_instructions", "Post-History Instructions"),
        ("first_mes", "First Message"),
        ("mes_example", "Message Examples"),
        ("creator_notes", "Creator Notes"),
    ):
        value = str(data.get(key) or "").strip()
        if value:
            sections.extend([f"## {title}", "", value, ""])
    alternate = data.get("alternate_greetings")
    if isinstance(alternate, list) and alternate:
        sections.extend(
            ["## Alternate Greetings", "", *[f"- {value}" for value in alternate], ""]
        )
    sections.extend(
        [
            "> Imported content is reviewed-existing source material. PersonaDock does not infer missing memories, relationships, or facts from this card.",
            "",
        ]
    )
    return "\n".join(sections).strip() + "\n"


def import_character_card(
    card_path: Path,
    destination: Path,
    *,
    persona_id: str | None = None,
    locale: str = "en-US",
    force: bool = False,
) -> Path:
    document = load_character_card(card_path)
    data = document.data
    resolved_id = persona_id or _slug(data["name"])
    project = init_project(
        destination,
        resolved_id,
        data["name"],
        locale=locale,
        force=force,
        schema_version=3,
    )
    value = load_yaml(project / PROJECT_FILE)
    description = str(data.get("description") or "").strip()
    personality = str(data.get("personality") or "").strip()
    scenario = str(data.get("scenario") or "").strip()
    system_prompt = str(data.get("system_prompt") or "").strip()
    post_history = str(data.get("post_history_instructions") or "").strip()
    identity_parts = [part for part in (description, personality) if part]
    if identity_parts:
        value["identity"]["statement"] = "\n\n".join(identity_parts)[:6000]
    traits = _traits(personality)
    if traits:
        value["identity"]["core_traits"] = traits
    voice_parts = [part for part in (system_prompt, post_history) if part]
    if voice_parts:
        value["voice"]["style"] = "\n\n".join(voice_parts)[:4000]
    value["summary"] = (
        description[:500]
        if description
        else f"Imported Character Card for {data['name']}."
    )
    if scenario:
        value["behaviors"].append(
            {
                "id": "character-card-scenario",
                "trigger": {
                    "intent": "character-card-scenario",
                    "conditions": [scenario[:1000]],
                },
                "behavior": ["Read references/character-card.md before responding in this scenario"],
                "constraints": ["Do not invent memories or facts missing from the imported card"],
                "priority": "medium",
                "confidence": "explicit",
                "source_type": "reviewed-existing",
                "evidence": [],
                "tests": [],
            }
        )
    value["skill"]["description"] = (
        f"Imported Character Card behavior and expression reference for {data['name']}."
    )
    (project / PROJECT_FILE).write_text(dump_yaml(value), encoding="utf-8")
    (project / "skills/persona/references/character-card.md").write_text(
        _reference_markdown(data), encoding="utf-8"
    )
    import_root = project / ".private/imports"
    import_root.mkdir(parents=True, exist_ok=True)
    (import_root / "character-card.json").write_text(
        json.dumps(document.raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (import_root / "metadata.json").write_text(
        json.dumps(
            {
                "source_path": str(document.path),
                "container": document.container,
                "spec": document.spec,
                "spec_version": document.spec_version,
                "unknown_extensions_preserved": sorted(data.get("extensions", {})),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return project


def _imported_data(project: Path) -> dict[str, Any]:
    path = project / ".private/imports/character-card.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return dict(payload["data"])
    return dict(payload) if isinstance(payload, dict) else {}


def export_character_card(
    project: Path,
    destination: Path,
    *,
    version: int = 3,
    charx: bool = False,
) -> Path:
    root = project.expanduser().resolve()
    value = load_yaml(root / PROJECT_FILE)
    if int(value.get("schema_version", 0)) != 3:
        raise CharacterCardError("Character Card export requires Canonical Persona schema v3")
    imported = _imported_data(root)
    identity = value["identity"]
    voice = value["voice"]
    extensions = dict(imported.get("extensions") or {})
    extensions["personadock"] = {
        "schema_version": 3,
        "persona_id": value["id"],
        "persona_version": value["version"],
        "adapter_api": "1.x",
        "memory_included": False,
        "raw_sessions_included": False,
    }
    data = {
        "name": value["name"],
        "description": identity["statement"],
        "personality": ", ".join(str(item) for item in identity["core_traits"]),
        "scenario": str(imported.get("scenario") or ""),
        "first_mes": str(imported.get("first_mes") or ""),
        "mes_example": str(imported.get("mes_example") or ""),
        "creator_notes": str(imported.get("creator_notes") or value["summary"]),
        "system_prompt": compile_soul(value),
        "post_history_instructions": str(
            imported.get("post_history_instructions") or voice["style"]
        ),
        "alternate_greetings": list(imported.get("alternate_greetings") or []),
        "tags": list(imported.get("tags") or ["personadock"]),
        "creator": str(imported.get("creator") or "PersonaDock"),
        "character_version": str(value["version"]),
        "extensions": extensions,
    }
    if version == 2:
        payload = {"spec": "chara_card_v2", "spec_version": "2.0", "data": data}
    elif version == 3:
        payload = {"spec": "chara_card_v3", "spec_version": "3.0", "data": data}
    else:
        raise CharacterCardError("Character Card export version must be 2 or 3")
    resolved = destination.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if charx or resolved.suffix.lower() == ".charx":
        if resolved.suffix.lower() != ".charx":
            resolved = resolved.with_suffix(".charx")
        with zipfile.ZipFile(resolved, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo("card.json", (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(
                info,
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
            )
    else:
        resolved.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return resolved
