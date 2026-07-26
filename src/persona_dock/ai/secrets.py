from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from persona_dock.registry.database import registry_root


class SecretVaultError(RuntimeError):
    pass


class SecretVault:
    FORMAT = "personadock-secret-vault"
    VERSION = 1
    ASSOCIATED_DATA = b"PersonaDock Secret Vault v1"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = (
            Path(root).expanduser().resolve()
            if root is not None
            else (registry_root() / "secrets").resolve()
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.key_path = self.root / "master.key"
        self.vault_path = self.root / "vault.json"
        self._key = self._load_or_create_key()

    @staticmethod
    def _chmod_private(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            value = self.key_path.read_bytes()
            if len(value) != 32:
                raise SecretVaultError("secret vault master key is invalid")
            self._chmod_private(self.key_path)
            return value
        value = os.urandom(32)
        try:
            with self.key_path.open("xb") as stream:
                stream.write(value)
        except FileExistsError:
            value = self.key_path.read_bytes()
        if len(value) != 32:
            raise SecretVaultError("secret vault master key is invalid")
        self._chmod_private(self.key_path)
        return value

    def _decode(self) -> dict[str, Any]:
        if not self.vault_path.exists():
            return {}
        try:
            envelope = json.loads(self.vault_path.read_text(encoding="utf-8"))
            if envelope.get("format") != self.FORMAT:
                raise SecretVaultError("unsupported secret vault format")
            if int(envelope.get("version", 0)) != self.VERSION:
                raise SecretVaultError("unsupported secret vault version")
            nonce = base64.b64decode(str(envelope["nonce"]), validate=True)
            ciphertext = base64.b64decode(str(envelope["ciphertext"]), validate=True)
            plaintext = AESGCM(self._key).decrypt(
                nonce,
                ciphertext,
                self.ASSOCIATED_DATA,
            )
            value = json.loads(plaintext.decode("utf-8"))
        except SecretVaultError:
            raise
        except (OSError, KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError, InvalidTag) as error:
            raise SecretVaultError(
                "secret vault authentication failed or the vault is damaged"
            ) from error
        if not isinstance(value, dict):
            raise SecretVaultError("secret vault payload must be an object")
        return value

    def _write(self, values: dict[str, Any]) -> None:
        plaintext = json.dumps(
            values,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            plaintext,
            self.ASSOCIATED_DATA,
        )
        envelope = {
            "format": self.FORMAT,
            "version": self.VERSION,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        payload = (
            json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        fd, temporary_name = tempfile.mkstemp(
            prefix="vault-",
            suffix=".json",
            dir=self.root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._chmod_private(temporary)
            os.replace(temporary, self.vault_path)
            self._chmod_private(self.vault_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_ref(ref: str) -> str:
        value = ref.strip()
        if not value or len(value) > 240 or any(character in value for character in ("/", "\\", "..")):
            raise ValueError("unsafe secret reference")
        return value

    def set(self, ref: str, value: dict[str, Any]) -> None:
        reference = self._validate_ref(ref)
        if not isinstance(value, dict) or not value:
            raise ValueError("secret payload must be a non-empty object")
        values = self._decode()
        values[reference] = value
        self._write(values)

    def get(self, ref: str) -> dict[str, Any] | None:
        reference = self._validate_ref(ref)
        value = self._decode().get(reference)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise SecretVaultError("secret payload has unsupported shape")
        return dict(value)

    def delete(self, ref: str) -> bool:
        reference = self._validate_ref(ref)
        values = self._decode()
        if reference not in values:
            return False
        values.pop(reference)
        self._write(values)
        return True

    def has(self, ref: str) -> bool:
        return self._validate_ref(ref) in self._decode()

    def refs(self) -> tuple[str, ...]:
        return tuple(sorted(str(key) for key in self._decode()))


__all__ = ["SecretVault", "SecretVaultError"]
