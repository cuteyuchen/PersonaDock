from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from persona_dock.packaging import inspect_package


SIGNATURE_FORMAT = "personapack-detached-signature"
SIGNATURE_VERSION = 1


class PackageTrustError(RuntimeError):
    """Raised when PersonaPack signing or trust validation fails."""


@dataclass(frozen=True)
class PackageVerification:
    package: str
    package_sha256: str
    integrity: str
    compatibility: str
    signature: str
    trusted: bool
    key_id: str | None
    errors: tuple[str, ...]
    manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["errors"] = list(self.errors)
        return value


def _key_id(public_bytes: bytes) -> str:
    return "ed25519:" + hashlib.sha256(public_bytes).hexdigest()


def generate_signing_key(
    private_key_path: Path,
    *,
    public_key_path: Path | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    private_path = private_key_path.expanduser().resolve()
    public_path = (
        public_key_path.expanduser().resolve()
        if public_key_path
        else private_path.with_suffix(private_path.suffix + ".pub")
    )
    for path in (private_path, public_path):
        if path.exists() and not overwrite:
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    private_path.write_bytes(private_bytes)
    try:
        private_path.chmod(0o600)
    except OSError:
        pass
    public_path.write_text(
        json.dumps(
            {
                "format": "personapack-ed25519-public-key",
                "version": 1,
                "key_id": _key_id(public_bytes),
                "public_key": base64.b64encode(public_bytes).decode("ascii"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "private_key": str(private_path),
        "public_key": str(public_path),
        "key_id": _key_id(public_bytes),
    }


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        value = serialization.load_pem_private_key(
            path.expanduser().resolve().read_bytes(), password=None
        )
    except (OSError, ValueError, TypeError) as error:
        raise PackageTrustError("could not load Ed25519 private key") from error
    if not isinstance(value, Ed25519PrivateKey):
        raise PackageTrustError("signing key is not an Ed25519 private key")
    return value


def sign_package(
    package: Path,
    private_key_path: Path,
    *,
    signature_path: Path | None = None,
) -> Path:
    resolved = package.expanduser().resolve()
    info = inspect_package(resolved)
    if info.get("integrity") != "ok":
        raise PackageTrustError("cannot sign a PersonaPack with failed integrity")
    payload = resolved.read_bytes()
    private = _load_private_key(private_key_path)
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature = private.sign(payload)
    value = {
        "format": SIGNATURE_FORMAT,
        "format_version": SIGNATURE_VERSION,
        "algorithm": "Ed25519",
        "package": resolved.name,
        "package_sha256": hashlib.sha256(payload).hexdigest(),
        "key_id": _key_id(public_bytes),
        "public_key": base64.b64encode(public_bytes).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    destination = (
        signature_path.expanduser().resolve()
        if signature_path
        else resolved.with_suffix(resolved.suffix + ".sig.json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def load_trusted_key_ids(paths: Iterable[Path]) -> set[str]:
    values: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PackageTrustError(f"could not read trusted key file: {resolved}") from error
        if isinstance(payload, dict) and payload.get("key_id"):
            values.add(str(payload["key_id"]))
        elif isinstance(payload, list):
            values.update(str(item) for item in payload)
        else:
            raise PackageTrustError(f"trusted key file has unsupported shape: {resolved}")
    return values


def _compatibility(manifest: dict[str, Any]) -> tuple[str, list[str]]:
    errors: list[str] = []
    if manifest.get("format") != "personapack":
        errors.append("unsupported package format")
    format_version = int(manifest.get("format_version", 0))
    schema_version = int(manifest.get("schema_version", 0))
    if format_version not in {1, 2}:
        errors.append(f"unsupported PersonaPack format version: {format_version}")
    if schema_version not in {2, 3}:
        errors.append(f"unsupported Canonical Persona schema version: {schema_version}")
    compatibility = manifest.get("compatibility")
    if compatibility is not None and not isinstance(compatibility, dict):
        errors.append("manifest compatibility metadata must be an object")
    return ("compatible" if not errors else "incompatible"), errors


def verify_package(
    package: Path,
    *,
    signature_path: Path | None = None,
    trusted_key_ids: Iterable[str] = (),
) -> PackageVerification:
    resolved = package.expanduser().resolve()
    manifest = inspect_package(resolved)
    errors = list(manifest.get("integrity_errors", []))
    compatibility, compatibility_errors = _compatibility(manifest)
    errors.extend(compatibility_errors)
    package_bytes = resolved.read_bytes()
    digest = hashlib.sha256(package_bytes).hexdigest()
    signature_status = "unsigned"
    trusted = False
    key_id: str | None = None
    if signature_path is not None:
        try:
            signature_payload = json.loads(
                signature_path.expanduser().resolve().read_text(encoding="utf-8")
            )
            if not isinstance(signature_payload, dict):
                raise PackageTrustError("signature document must be an object")
            if signature_payload.get("format") != SIGNATURE_FORMAT:
                raise PackageTrustError("unsupported signature document format")
            if int(signature_payload.get("format_version", 0)) != SIGNATURE_VERSION:
                raise PackageTrustError("unsupported signature document version")
            if signature_payload.get("algorithm") != "Ed25519":
                raise PackageTrustError("unsupported signature algorithm")
            if signature_payload.get("package_sha256") != digest:
                raise PackageTrustError("signature package digest does not match")
            public_bytes = base64.b64decode(
                str(signature_payload["public_key"]), validate=True
            )
            signature = base64.b64decode(
                str(signature_payload["signature"]), validate=True
            )
            public = Ed25519PublicKey.from_public_bytes(public_bytes)
            public.verify(signature, package_bytes)
            key_id = _key_id(public_bytes)
            if signature_payload.get("key_id") != key_id:
                raise PackageTrustError("signature key ID does not match public key")
            trusted_set = {str(value) for value in trusted_key_ids}
            trusted = key_id in trusted_set
            signature_status = "valid-trusted" if trusted else "valid-untrusted-key"
        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            ValueError,
            InvalidSignature,
            PackageTrustError,
        ) as error:
            signature_status = "invalid"
            errors.append(str(error))
    integrity = str(manifest.get("integrity", "failed"))
    return PackageVerification(
        package=str(resolved),
        package_sha256=digest,
        integrity=integrity,
        compatibility=compatibility,
        signature=signature_status,
        trusted=trusted,
        key_id=key_id,
        errors=tuple(errors),
        manifest=manifest,
    )
