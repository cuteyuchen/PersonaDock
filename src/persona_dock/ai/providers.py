from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from persona_dock.registry.database import registry_root

from .secrets import SecretVault


PROVIDER_KINDS = {
    "openai",
    "openai-compatible",
    "anthropic",
    "gemini",
    "ollama",
}

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openai-compatible": "http://127.0.0.1:8000/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "ollama": "http://127.0.0.1:11434",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    id: str
    name: str
    kind: str
    base_url: str
    model: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: int
    structured_output: bool
    secret_ref: str
    created_at: str
    updated_at: str

    def to_dict(self, *, vault: SecretVault | None = None) -> dict[str, Any]:
        value = asdict(self)
        value.pop("secret_ref", None)
        value["secret_configured"] = bool(vault and vault.has(self.secret_ref))
        return value


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_providers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    temperature REAL NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    timeout_seconds INTEGER NOT NULL,
    structured_output INTEGER NOT NULL,
    secret_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_providers_name ON ai_providers(name COLLATE NOCASE);
"""


class ProviderStore:
    def __init__(
        self,
        path: str | Path | None = None,
        vault: SecretVault | None = None,
    ) -> None:
        self.path = (
            Path(path).expanduser().resolve()
            if path is not None
            else (registry_root() / "control-plane.db").resolve()
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.vault = vault or SecretVault()
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> ProviderRecord:
        return ProviderRecord(
            id=str(row["id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            base_url=str(row["base_url"]),
            model=str(row["model"]),
            temperature=float(row["temperature"]),
            max_output_tokens=int(row["max_output_tokens"]),
            timeout_seconds=int(row["timeout_seconds"]),
            structured_output=bool(row["structured_output"]),
            secret_ref=str(row["secret_ref"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _validate(
        *,
        name: str,
        kind: str,
        base_url: str | None,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        resolved_kind = kind.strip().lower()
        if resolved_kind not in PROVIDER_KINDS:
            raise ValueError(f"unsupported AI provider kind: {kind}")
        resolved_name = name.strip()
        if not resolved_name or len(resolved_name) > 120:
            raise ValueError("provider name must be 1-120 characters")
        resolved_model = model.strip()
        if not resolved_model or len(resolved_model) > 240:
            raise ValueError("provider model must be 1-240 characters")
        resolved_url = (base_url or DEFAULT_BASE_URLS[resolved_kind]).strip().rstrip("/")
        parsed = urllib.parse.urlparse(resolved_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("provider base URL must be an http or https URL")
        if not 0 <= float(temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if not 64 <= int(max_output_tokens) <= 131072:
            raise ValueError("max output tokens must be between 64 and 131072")
        if not 1 <= int(timeout_seconds) <= 600:
            raise ValueError("timeout must be between 1 and 600 seconds")
        return {
            "name": resolved_name,
            "kind": resolved_kind,
            "base_url": resolved_url,
            "model": resolved_model,
            "temperature": float(temperature),
            "max_output_tokens": int(max_output_tokens),
            "timeout_seconds": int(timeout_seconds),
        }

    def create(
        self,
        *,
        name: str,
        kind: str,
        base_url: str | None,
        model: str,
        temperature: float = 0.4,
        max_output_tokens: int = 4096,
        timeout_seconds: int = 90,
        structured_output: bool = True,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> ProviderRecord:
        value = self._validate(
            name=name,
            kind=kind,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
        provider_id = str(uuid.uuid4())
        secret_ref = f"ai-provider-{provider_id}"
        now = utc_now()
        if api_key or headers:
            self.vault.set(
                secret_ref,
                {
                    "api_key": (api_key or "").strip(),
                    "headers": {str(key): str(item) for key, item in (headers or {}).items()},
                },
            )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_providers(
                    id, name, kind, base_url, model, temperature,
                    max_output_tokens, timeout_seconds, structured_output,
                    secret_ref, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    value["name"],
                    value["kind"],
                    value["base_url"],
                    value["model"],
                    value["temperature"],
                    value["max_output_tokens"],
                    value["timeout_seconds"],
                    int(bool(structured_output)),
                    secret_ref,
                    now,
                    now,
                ),
            )
        result = self.get(provider_id)
        assert result is not None
        return result

    def update(
        self,
        provider_id: str,
        *,
        name: str,
        kind: str,
        base_url: str | None,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: int,
        structured_output: bool,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        clear_secret: bool = False,
    ) -> ProviderRecord:
        current = self.get(provider_id)
        if current is None:
            raise KeyError(provider_id)
        value = self._validate(
            name=name,
            kind=kind,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
        if clear_secret:
            self.vault.delete(current.secret_ref)
        elif api_key is not None or headers is not None:
            previous = self.vault.get(current.secret_ref) or {}
            self.vault.set(
                current.secret_ref,
                {
                    "api_key": (api_key if api_key is not None else previous.get("api_key", "")).strip(),
                    "headers": headers if headers is not None else previous.get("headers", {}),
                },
            )
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ai_providers SET
                    name = ?, kind = ?, base_url = ?, model = ?,
                    temperature = ?, max_output_tokens = ?, timeout_seconds = ?,
                    structured_output = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    value["name"],
                    value["kind"],
                    value["base_url"],
                    value["model"],
                    value["temperature"],
                    value["max_output_tokens"],
                    value["timeout_seconds"],
                    int(bool(structured_output)),
                    now,
                    provider_id,
                ),
            )
        result = self.get(provider_id)
        assert result is not None
        return result

    def get(self, provider_id: str) -> ProviderRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ai_providers WHERE id = ?",
                (provider_id,),
            ).fetchone()
        return self._record(row) if row else None

    def list(self) -> list[ProviderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ai_providers ORDER BY name COLLATE NOCASE, created_at"
            ).fetchall()
        return [self._record(row) for row in rows]

    def delete(self, provider_id: str) -> bool:
        current = self.get(provider_id)
        if current is None:
            return False
        with self._connect() as connection:
            connection.execute("DELETE FROM ai_providers WHERE id = ?", (provider_id,))
        self.vault.delete(current.secret_ref)
        return True

    def secret(self, provider: ProviderRecord) -> dict[str, Any]:
        return self.vault.get(provider.secret_ref) or {}


class ProviderRequestError(RuntimeError):
    pass


Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None, int], dict[str, Any]]


def _http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    timeout: int,
) -> dict[str, Any]:
    payload = None if body is None else _dump(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Accept": "application/json", **headers},
    )
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        raw = error.read(64 * 1024)
        try:
            detail = json.loads(raw.decode("utf-8"))
            message = detail.get("error", detail)
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = raw.decode("utf-8", errors="replace")[:1000]
        raise ProviderRequestError(f"provider returned HTTP {error.code}: {message}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ProviderRequestError(f"provider request failed: {error}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderRequestError("provider returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ProviderRequestError("provider response must be a JSON object")
    return value


class ProviderClient:
    def __init__(
        self,
        store: ProviderStore,
        transport: Transport = _http_json,
    ) -> None:
        self.store = store
        self.transport = transport

    @staticmethod
    def _headers(provider: ProviderRecord, secret: dict[str, Any]) -> dict[str, str]:
        custom = secret.get("headers") if isinstance(secret.get("headers"), dict) else {}
        headers = {str(key): str(value) for key, value in custom.items()}
        api_key = str(secret.get("api_key") or "").strip()
        if provider.kind in {"openai", "openai-compatible"} and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        elif provider.kind == "anthropic" and api_key:
            headers["x-api-key"] = api_key
            headers.setdefault("anthropic-version", "2023-06-01")
        elif provider.kind == "gemini" and api_key:
            headers["x-goog-api-key"] = api_key
        return headers

    @staticmethod
    def _join(base_url: str, suffix: str) -> str:
        return base_url.rstrip("/") + "/" + suffix.lstrip("/")

    def list_models(self, provider_id: str) -> list[str]:
        provider = self.store.get(provider_id)
        if provider is None:
            raise KeyError(provider_id)
        secret = self.store.secret(provider)
        headers = self._headers(provider, secret)
        if provider.kind in {"openai", "openai-compatible", "anthropic", "gemini"}:
            value = self.transport(
                "GET",
                self._join(provider.base_url, "models"),
                headers,
                None,
                provider.timeout_seconds,
            )
            records = value.get("data") if provider.kind in {"openai", "openai-compatible", "anthropic"} else value.get("models")
            if not isinstance(records, list):
                return []
            models: list[str] = []
            for item in records:
                if not isinstance(item, dict):
                    continue
                name = item.get("id") or item.get("name")
                if name:
                    models.append(str(name).removeprefix("models/"))
            return sorted(set(models))
        value = self.transport(
            "GET",
            self._join(provider.base_url, "api/tags"),
            headers,
            None,
            provider.timeout_seconds,
        )
        records = value.get("models")
        if not isinstance(records, list):
            return []
        return sorted(
            {
                str(item.get("name"))
                for item in records
                if isinstance(item, dict) and item.get("name")
            }
        )

    def test(self, provider_id: str) -> dict[str, Any]:
        provider = self.store.get(provider_id)
        if provider is None:
            raise KeyError(provider_id)
        models = self.list_models(provider_id)
        return {
            "available": True,
            "provider_id": provider.id,
            "kind": provider.kind,
            "configured_model": provider.model,
            "model_visible": provider.model in models if models else None,
            "models": models[:200],
        }

    def generate(self, provider_id: str, *, system: str, prompt: str) -> dict[str, Any]:
        provider = self.store.get(provider_id)
        if provider is None:
            raise KeyError(provider_id)
        secret = self.store.secret(provider)
        headers = self._headers(provider, secret)
        if provider.kind in {"openai", "openai-compatible"}:
            body: dict[str, Any] = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": provider.temperature,
                "max_tokens": provider.max_output_tokens,
            }
            if provider.structured_output:
                body["response_format"] = {"type": "json_object"}
            value = self.transport(
                "POST",
                self._join(provider.base_url, "chat/completions"),
                headers,
                body,
                provider.timeout_seconds,
            )
            choices = value.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ProviderRequestError("provider response has no choices")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            usage = value.get("usage") if isinstance(value.get("usage"), dict) else {}
        elif provider.kind == "anthropic":
            value = self.transport(
                "POST",
                self._join(provider.base_url, "messages"),
                headers,
                {
                    "model": provider.model,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": provider.temperature,
                    "max_tokens": provider.max_output_tokens,
                },
                provider.timeout_seconds,
            )
            blocks = value.get("content")
            content = "\n".join(
                str(block.get("text"))
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
            ) if isinstance(blocks, list) else None
            usage = value.get("usage") if isinstance(value.get("usage"), dict) else {}
        elif provider.kind == "gemini":
            generation_config: dict[str, Any] = {
                "temperature": provider.temperature,
                "maxOutputTokens": provider.max_output_tokens,
            }
            if provider.structured_output:
                generation_config["responseMimeType"] = "application/json"
            value = self.transport(
                "POST",
                self._join(
                    provider.base_url,
                    f"models/{urllib.parse.quote(provider.model, safe='')}:generateContent",
                ),
                headers,
                {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": generation_config,
                },
                provider.timeout_seconds,
            )
            candidates = value.get("candidates")
            candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
            response_content = candidate.get("content") if isinstance(candidate, dict) else {}
            parts = response_content.get("parts") if isinstance(response_content, dict) else []
            content = "\n".join(
                str(part.get("text"))
                for part in parts
                if isinstance(part, dict) and part.get("text")
            ) if isinstance(parts, list) else None
            usage = value.get("usageMetadata") if isinstance(value.get("usageMetadata"), dict) else {}
        else:
            value = self.transport(
                "POST",
                self._join(provider.base_url, "api/chat"),
                headers,
                {
                    "model": provider.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "format": "json" if provider.structured_output else "",
                    "options": {
                        "temperature": provider.temperature,
                        "num_predict": provider.max_output_tokens,
                    },
                },
                provider.timeout_seconds,
            )
            message = value.get("message") if isinstance(value.get("message"), dict) else {}
            content = message.get("content")
            usage = {
                "prompt_tokens": value.get("prompt_eval_count"),
                "completion_tokens": value.get("eval_count"),
            }
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("provider returned empty model content")
        return {
            "content": content.strip(),
            "usage": usage,
            "provider_id": provider.id,
            "provider_kind": provider.kind,
            "model": provider.model,
        }


__all__ = [
    "DEFAULT_BASE_URLS",
    "PROVIDER_KINDS",
    "ProviderClient",
    "ProviderRecord",
    "ProviderRequestError",
    "ProviderStore",
]
