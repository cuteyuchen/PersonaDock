from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath

import pytest

from persona_dock.compiler import compile_project
from persona_dock.installer import install_package, rollback
from persona_dock.packaging import export_public, inspect_package, pack_project
from persona_dock.project import init_project, validate_project


def reviewed_memory() -> str:
    return json.dumps(
        {
            "id": "mem-1",
            "type": "preference",
            "summary": "用户更喜欢先被倾听，再讨论解决方案。",
            "reviewed": True,
            "sensitivity": "private",
        },
        ensure_ascii=False,
    ) + "\n"


def test_init_validate_build_and_pack(tmp_path: Path) -> None:
    root = init_project(tmp_path / "my-persona", "my-persona", "小岚")
    (root / "memory/seed.jsonl").write_text(reviewed_memory(), encoding="utf-8")

    assert validate_project(root) == []
    build = compile_project(root)
    soul = (build / "targets/hermes/SOUL.md").read_text(encoding="utf-8")
    assert "人格 Skill 路由" in soul
    assert "不得补全或假装记得" in soul
    assert (build / "targets/openclaw/skills/my-persona-persona/SKILL.md").is_file()
    assert (build / "targets/hermes/memory/seed.jsonl").read_text(encoding="utf-8")

    package = pack_project(root)
    assert package.suffix == ".personapack"
    metadata = inspect_package(package)
    assert metadata["integrity"] == "ok"
    assert metadata["id"] == "my-persona"


def test_unreviewed_memory_blocks_build(tmp_path: Path) -> None:
    root = init_project(tmp_path / "persona", "persona", "测试人格")
    candidate = json.loads(reviewed_memory())
    candidate["reviewed"] = False
    (root / "memory/seed.jsonl").write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")
    errors = validate_project(root)
    assert any("explicitly reviewed" in error for error in errors)
    with pytest.raises(ValueError):
        compile_project(root)


def test_public_export_removes_memory(tmp_path: Path) -> None:
    root = init_project(tmp_path / "persona", "persona", "测试人格")
    (root / "memory/seed.jsonl").write_text(reviewed_memory(), encoding="utf-8")
    output = export_public(root)
    assert (output / "targets/hermes/memory/seed.jsonl").read_text(encoding="utf-8") == ""
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["privacy"]["memory_policy"] == "none"


def configure_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import persona_dock.installer as installer

    monkeypatch.setattr(installer, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(installer, "STATE_FILE", tmp_path / "state/state.json")
    monkeypatch.setattr(installer, "BACKUP_ROOT", tmp_path / "state/backups")


def test_install_and_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = init_project(tmp_path / "persona", "persona", "测试人格")
    package = pack_project(root)
    configure_state(tmp_path, monkeypatch)

    destination = tmp_path / "hermes"
    destination.mkdir()
    (destination / "SOUL.md").write_text("old soul\n", encoding="utf-8")

    install_package(package, "hermes", destination)
    assert "人格 Skill 路由" in (destination / "SOUL.md").read_text(encoding="utf-8")
    assert (destination / "skills/persona-persona/SKILL.md").is_file()

    rollback("hermes", destination)
    assert (destination / "SOUL.md").read_text(encoding="utf-8") == "old soul\n"
    assert not (destination / "skills/persona-persona").exists()


def test_install_and_rollback_in_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = init_project(tmp_path / "persona", "persona", "测试人格")
    package = pack_project(root)
    configure_state(tmp_path, monkeypatch)

    import persona_dock.installer as installer

    container_root = tmp_path / "container"
    container_name = "hermes-app"

    def container_path(path: PurePosixPath) -> Path:
        return container_root / str(path).lstrip("/")

    def fake_ensure_container(container: str) -> None:
        assert container == container_name

    def fake_container_home(container: str) -> PurePosixPath:
        assert container == container_name
        return PurePosixPath("/root")

    def fake_exists(container: str, path: PurePosixPath) -> bool:
        assert container == container_name
        return container_path(path).exists()

    def fake_remove(container: str, path: PurePosixPath) -> None:
        assert container == container_name
        target = container_path(path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def fake_mkdir(container: str, path: PurePosixPath) -> None:
        assert container == container_name
        container_path(path).mkdir(parents=True, exist_ok=True)

    def fake_copy_from(container: str, source: PurePosixPath, destination: Path) -> None:
        assert container == container_name
        source_path = container_path(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(source_path, destination)
        else:
            shutil.copy2(source_path, destination)

    def fake_copy_to(container: str, source: Path, destination: PurePosixPath) -> None:
        assert container == container_name
        destination_path = container_path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination_path)
        else:
            shutil.copy2(source, destination_path)

    monkeypatch.setattr(installer, "_ensure_container", fake_ensure_container)
    monkeypatch.setattr(installer, "_container_home", fake_container_home)
    monkeypatch.setattr(installer, "_docker_exists", fake_exists)
    monkeypatch.setattr(installer, "_docker_remove", fake_remove)
    monkeypatch.setattr(installer, "_docker_mkdir", fake_mkdir)
    monkeypatch.setattr(installer, "_docker_copy_from", fake_copy_from)
    monkeypatch.setattr(installer, "_docker_copy_to", fake_copy_to)

    destination = PurePosixPath("/data/hermes")
    existing_soul = container_path(destination / "SOUL.md")
    existing_soul.parent.mkdir(parents=True, exist_ok=True)
    existing_soul.write_text("old docker soul\n", encoding="utf-8")

    installed = install_package(
        package,
        "hermes",
        str(destination),
        container=container_name,
    )
    assert installed == destination
    assert "人格 Skill 路由" in existing_soul.read_text(encoding="utf-8")
    assert container_path(destination / "skills/persona-persona/SKILL.md").is_file()

    restored = rollback(
        "hermes",
        str(destination),
        container=container_name,
    )
    assert restored == destination
    assert existing_soul.read_text(encoding="utf-8") == "old docker soul\n"
    assert not container_path(destination / "skills/persona-persona").exists()
