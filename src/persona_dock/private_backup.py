from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from persona_dock.io import load_yaml
from persona_dock.project import PROJECT_FILE, find_project


MAGIC = b"PERSONADOCK-PRIVATE-BACKUP\n"
FORMAT_VERSION = 1
DEFAULT_EXCLUDES = (
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    "__pycache__",
    "dist",
    ".personadock/build",
)


class PrivateBackupError(RuntimeError):
    """Raised when a private backup cannot be created, verified, or restored."""


@dataclass(frozen=True)
class PrivateBackupInfo:
    path: str
    format: str
    format_version: int
    persona_id: str
    persona_version: str
    created_at: str
    algorithm: str
    kdf: str
    archive_sha256: str
    file_count: int
    includes_private_project_data: bool
    excludes_runtime_state: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "format": self.format,
            "format_version": self.format_version,
            "persona_id": self.persona_id,
            "persona_version": self.persona_version,
            "created_at": self.created_at,
            "algorithm": self.algorithm,
            "kdf": self.kdf,
            "archive_sha256": self.archive_sha256,
            "file_count": self.file_count,
            "includes_private_project_data": self.includes_private_project_data,
            "excludes_runtime_state": self.excludes_runtime_state,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _excluded(relative: Path, excludes: Iterable[str]) -> bool:
    normalized = relative.as_posix()
    for value in excludes:
        candidate = value.strip("/")
        if normalized == candidate or normalized.startswith(candidate + "/"):
            return True
        if relative.name == candidate and "/" not in candidate:
            return True
    return False


def _project_files(root: Path, excludes: Iterable[str]) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not _excluded(path.relative_to(root), excludes)
    )


def _archive_project(root: Path, excludes: Iterable[str]) -> tuple[bytes, int]:
    stream = io.BytesIO()
    files = _project_files(root, excludes)
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, path.read_bytes())
    return stream.getvalue(), len(files)


def _derive_key(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    if not password:
        raise PrivateBackupError("private backup password cannot be empty")
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(
        password.encode("utf-8")
    )


def _encode_header(header: dict[str, Any]) -> bytes:
    return json.dumps(
        header,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_container(path: Path) -> tuple[dict[str, Any], bytes, bytes]:
    data = path.read_bytes()
    if not data.startswith(MAGIC):
        raise PrivateBackupError("not a PersonaDock private backup")
    cursor = len(MAGIC)
    if len(data) < cursor + 4:
        raise PrivateBackupError("private backup header is truncated")
    header_size = struct.unpack(">I", data[cursor : cursor + 4])[0]
    cursor += 4
    if header_size <= 0 or header_size > 1024 * 1024:
        raise PrivateBackupError("private backup header length is invalid")
    header_bytes = data[cursor : cursor + header_size]
    ciphertext = data[cursor + header_size :]
    if len(header_bytes) != header_size or not ciphertext:
        raise PrivateBackupError("private backup payload is truncated")
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PrivateBackupError("private backup header is invalid") from error
    if not isinstance(header, dict):
        raise PrivateBackupError("private backup header must be an object")
    return header, header_bytes, ciphertext


def create_private_backup(
    project: Path,
    destination: Path,
    *,
    password: str,
    excludes: Iterable[str] = DEFAULT_EXCLUDES,
) -> PrivateBackupInfo:
    root = find_project(project)
    persona = load_yaml(root / PROJECT_FILE)
    archive, file_count = _archive_project(root, tuple(excludes))
    archive_sha256 = hashlib.sha256(archive).hexdigest()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    n, r, p = 2**15, 8, 1
    header = {
        "format": "personadock-private-backup",
        "format_version": FORMAT_VERSION,
        "created_at": _utc_now(),
        "persona": {
            "id": str(persona.get("id", "unknown")),
            "version": str(persona.get("version", "unknown")),
        },
        "encryption": {
            "algorithm": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode("ascii"),
        },
        "kdf": {
            "algorithm": "scrypt",
            "salt": base64.b64encode(salt).decode("ascii"),
            "n": n,
            "r": r,
            "p": p,
            "length": 32,
        },
        "archive": {
            "format": "zip",
            "sha256": archive_sha256,
            "file_count": file_count,
        },
        "privacy": {
            "includes_private_project_data": True,
            "excludes_runtime_credentials": True,
            "excludes_runtime_sessions": True,
            "excludes_runtime_state": True,
            "source_scope": "persona-project-only",
        },
        "excluded_paths": list(excludes),
    }
    header_bytes = _encode_header(header)
    key = _derive_key(password, salt, n=n, r=r, p=p)
    ciphertext = AESGCM(key).encrypt(nonce, archive, header_bytes)
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes + ciphertext
    )
    return inspect_private_backup(destination)


def inspect_private_backup(path: Path) -> PrivateBackupInfo:
    resolved = path.expanduser().resolve()
    header, _, _ = _read_container(resolved)
    if header.get("format") != "personadock-private-backup":
        raise PrivateBackupError("unsupported private backup format")
    if int(header.get("format_version", 0)) != FORMAT_VERSION:
        raise PrivateBackupError(
            f"unsupported private backup version: {header.get('format_version')}"
        )
    persona = header.get("persona") if isinstance(header.get("persona"), dict) else {}
    encryption = (
        header.get("encryption") if isinstance(header.get("encryption"), dict) else {}
    )
    kdf = header.get("kdf") if isinstance(header.get("kdf"), dict) else {}
    archive = header.get("archive") if isinstance(header.get("archive"), dict) else {}
    privacy = header.get("privacy") if isinstance(header.get("privacy"), dict) else {}
    return PrivateBackupInfo(
        path=str(resolved),
        format=str(header["format"]),
        format_version=int(header["format_version"]),
        persona_id=str(persona.get("id", "unknown")),
        persona_version=str(persona.get("version", "unknown")),
        created_at=str(header.get("created_at", "")),
        algorithm=str(encryption.get("algorithm", "unknown")),
        kdf=str(kdf.get("algorithm", "unknown")),
        archive_sha256=str(archive.get("sha256", "")),
        file_count=int(archive.get("file_count", 0)),
        includes_private_project_data=bool(
            privacy.get("includes_private_project_data", False)
        ),
        excludes_runtime_state=bool(privacy.get("excludes_runtime_state", False)),
    )


def decrypt_private_backup(path: Path, *, password: str) -> tuple[dict[str, Any], bytes]:
    resolved = path.expanduser().resolve()
    header, header_bytes, ciphertext = _read_container(resolved)
    encryption = header.get("encryption")
    kdf = header.get("kdf")
    if not isinstance(encryption, dict) or not isinstance(kdf, dict):
        raise PrivateBackupError("private backup cryptographic metadata is missing")
    if encryption.get("algorithm") != "AES-256-GCM" or kdf.get("algorithm") != "scrypt":
        raise PrivateBackupError("unsupported private backup cryptographic algorithm")
    try:
        salt = base64.b64decode(str(kdf["salt"]), validate=True)
        nonce = base64.b64decode(str(encryption["nonce"]), validate=True)
        key = _derive_key(
            password,
            salt,
            n=int(kdf["n"]),
            r=int(kdf["r"]),
            p=int(kdf["p"]),
        )
        archive = AESGCM(key).decrypt(nonce, ciphertext, header_bytes)
    except (KeyError, ValueError, InvalidTag) as error:
        raise PrivateBackupError(
            "private backup authentication failed; password is wrong or the file was modified"
        ) from error
    expected = str(header.get("archive", {}).get("sha256", ""))
    actual = hashlib.sha256(archive).hexdigest()
    if expected != actual:
        raise PrivateBackupError("private backup archive digest mismatch")
    return header, archive


def _validate_archive(archive: zipfile.ZipFile) -> None:
    for member in archive.infolist():
        value = Path(member.filename)
        if value.is_absolute() or ".." in value.parts:
            raise PrivateBackupError(f"unsafe private backup path: {member.filename}")
        if member.is_dir():
            continue
        mode = member.external_attr >> 16
        if mode and not mode & 0o100000 and member.create_system == 3:
            # Refuse unusual Unix file types; normal files use 0100000 when present.
            file_type = mode & 0o170000
            if file_type not in {0, 0o100000}:
                raise PrivateBackupError(
                    f"unsupported private backup member type: {member.filename}"
                )


def restore_private_backup(
    path: Path,
    destination: Path,
    *,
    password: str,
    force: bool = False,
) -> Path:
    _, payload = decrypt_private_backup(path, password=password)
    target = destination.expanduser().resolve()
    if target.exists():
        if not force and any(target.iterdir()):
            raise PrivateBackupError(
                "restore destination is not empty; pass force=True to replace it"
            )
        if force:
            shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        _validate_archive(archive)
        archive.extractall(target)
    if not (target / PROJECT_FILE).is_file():
        shutil.rmtree(target, ignore_errors=True)
        raise PrivateBackupError("restored backup does not contain a PersonaDock project")
    return target
