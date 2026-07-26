from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from persona_dock.ai import AIPersonaStudio, GenerationStore, ProviderClient, ProviderStore, SecretVault
from persona_dock.application import PersonaApplicationService, RevisionStore
from persona_dock.io import dump_yaml, load_yaml
from persona_dock.project import PROJECT_FILE
from persona_dock.registry import RegistryService
from persona_dock.registry.database import RegistryDatabase
from persona_dock.web import create_app
from persona_dock.web.version import WEB_REFACTOR_PHASE


def test_secret_vault_encrypts_provider_secrets(tmp_path: Path) -> None:
    vault = SecretVault(tmp_path / "secrets")
    secret = "sk-personadock-do-not-store-plaintext"
    vault.set("provider-demo", {"api_key": secret, "headers": {"X-Secret": "header-value"}})

    assert vault.get("provider-demo") == {
        "api_key": secret,
        "headers": {"X-Secret": "header-value"},
    }
    assert secret.encode() not in vault.vault_path.read_bytes()
    assert b"header-value" not in vault.vault_path.read_bytes()
    assert len(vault.key_path.read_bytes()) == 32


def test_provider_store_never_exposes_or_persists_plaintext_secret(tmp_path: Path) -> None:
    vault = SecretVault(tmp_path / "secrets")
    database = tmp_path / "control-plane.db"
    store = ProviderStore(database, vault)
    secret = "provider-key-unique-value"
    provider = store.create(
        name="Local compatible",
        kind="openai-compatible",
        base_url="http://127.0.0.1:8000/v1",
        model="demo-model",
        api_key=secret,
        headers={"X-Private": "private-header"},
    )
    public = provider.to_dict(vault=vault)

    assert public["secret_configured"] is True
    assert "secret_ref" not in public
    assert "api_key" not in public
    assert secret.encode() not in database.read_bytes()
    assert b"private-header" not in database.read_bytes()
    assert secret.encode() not in vault.vault_path.read_bytes()


def test_provider_client_uses_protocol_adapter_without_network(tmp_path: Path) -> None:
    vault = SecretVault(tmp_path / "secrets")
    store = ProviderStore(tmp_path / "control-plane.db", vault)
    provider = store.create(
        name="OpenAI compatible",
        kind="openai-compatible",
        base_url="http://model.local/v1",
        model="persona-model",
        api_key="test-key",
    )
    requests: list[dict[str, object]] = []

    def transport(method, url, headers, body, timeout):
        requests.append(
            {"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout}
        )
        if method == "GET":
            return {"data": [{"id": "persona-model"}, {"id": "other-model"}]}
        return {
            "choices": [{"message": {"content": '{"summary":"generated"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }

    client = ProviderClient(store, transport=transport)
    assert client.list_models(provider.id) == ["other-model", "persona-model"]
    result = client.generate(provider.id, system="system", prompt="prompt")

    assert result["content"] == '{"summary":"generated"}'
    request = requests[-1]
    assert request["url"] == "http://model.local/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["body"]["response_format"] == {"type": "json_object"}


class FakeProviderClient:
    def __init__(self) -> None:
        self.inputs: list[tuple[str, str, str]] = []

    def generate(self, provider_id: str, *, system: str, prompt: str):
        self.inputs.append((provider_id, system, prompt))
        return {
            "content": json.dumps(
                {
                    "summary": "A reviewed AI-generated persona draft.",
                    "identity": {
                        "statement": "A grounded persona generated from explicit design.",
                        "core_traits": ["calm", "specific", "honest"],
                    },
                    "voice": {
                        "style": "Direct and natural.",
                        "principles": ["State uncertainty clearly"],
                    },
                }
            ),
            "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        }


def _studio(tmp_path: Path):
    registry = RegistryService(RegistryDatabase(tmp_path / "registry.db"))
    generations = GenerationStore(tmp_path / "control-plane.db")
    revisions = RevisionStore(tmp_path / "revisions")
    provider = FakeProviderClient()
    return AIPersonaStudio(provider, registry, generations, revisions), registry, generations, revisions, provider


def test_ai_create_generates_valid_draft_without_storing_raw_input(tmp_path: Path) -> None:
    studio, registry, generations, revisions, provider = _studio(tmp_path)
    unique_instruction = "UNIQUE-RAW-PERSONA-INSTRUCTION-DO-NOT-PERSIST"
    unique_evidence = "UNIQUE-RAW-CHAT-EVIDENCE-DO-NOT-PERSIST"

    draft = studio.generate(
        provider_id="fake-provider",
        mode="hybrid",
        instruction=unique_instruction,
        evidence=unique_evidence,
        requested_persona_id="web-persona",
        requested_name="Web Persona",
        locale="zh-CN",
    )

    assert draft.status == "draft"
    assert draft.draft["id"] == "web-persona"
    assert draft.validation["valid"] is True
    assert draft.compile_preview["files"]["targets/hermes/SOUL.md"]
    assert draft.prompt_hash
    database_bytes = generations.path.read_bytes()
    assert unique_instruction.encode() not in database_bytes
    assert unique_evidence.encode() not in database_bytes
    assert provider.inputs and unique_instruction in provider.inputs[0][2]

    applied = studio.apply(draft.id, destination=tmp_path / "personas" / "web-persona")
    assert applied.status == "applied"
    assert applied.applied_persona_id == "web-persona"
    assert registry.get_persona("web-persona") is not None
    assert revisions.latest("web-persona") is not None


def test_ai_refine_rejects_changed_persona_baseline(tmp_path: Path) -> None:
    studio, registry, _, _, _ = _studio(tmp_path)
    created = PersonaApplicationService(registry).create(
        tmp_path / "personas" / "existing",
        persona_id="existing",
        name="Existing",
        locale="zh-CN",
    )
    generation = studio.generate(
        provider_id="fake-provider",
        mode="refine",
        instruction="Make the expression more direct without changing boundaries.",
        persona_id="existing",
    )

    root = Path(created["project"])
    current = load_yaml(root / PROJECT_FILE)
    current["summary"] = "Changed after generation"
    (root / PROJECT_FILE).write_text(dump_yaml(current), encoding="utf-8")

    with pytest.raises(ValueError, match="changed after AI generation"):
        studio.apply(generation.id)


def test_phase_seven_routes_assets_and_secret_boundaries() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    for path in (
        "/api/v1/ai/providers",
        "/api/v1/ai/providers/{provider_id}",
        "/api/v1/ai/providers/{provider_id}/test",
        "/api/v1/ai/providers/{provider_id}/models",
        "/api/v1/ai/generations",
        "/api/v1/ai/generations/{generation_id}",
        "/api/v1/ai/generations/{generation_id}/apply",
    ):
        assert path in paths
    assert WEB_REFACTOR_PHASE >= 7

    root = files("persona_dock")
    html = root.joinpath("web/static/index.html").read_text(encoding="utf-8")
    css = root.joinpath("web/static/ai.css").read_text(encoding="utf-8")
    javascript = root.joinpath("web/static/ai.js").read_text(encoding="utf-8")
    api_source = root.joinpath("web/ai_api.py").read_text(encoding="utf-8")
    provider_source = root.joinpath("ai/providers.py").read_text(encoding="utf-8")

    assert 'href="/assets/ai.css"' in html
    assert 'src="/assets/ai.js"' in html
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "localStorage" not in javascript
    assert "聊天气泡" not in javascript
    assert "输入 APPLY" in javascript
    assert '"input_hash": request_hash' in api_source
    assert '"instruction": request.instruction' not in api_source
    assert '"evidence": request.evidence' not in api_source
    assert 'value.pop("secret_ref", None)' in provider_source
