from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .core.models import normalize_canonical_persona
from .io import load_jsonl, load_yaml, sha256_file, write_jsonl
from .project import PROJECT_FILE, find_project, validate_project


def _bullets(values: list[Any]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _compile_soul_v2(project: dict[str, Any]) -> str:
    soul = project["soul"]
    skill_id = project["skill"]["id"]
    triggers = soul.get("skill_triggers", [])
    boundaries = soul.get("boundaries", [])
    traits = soul.get("core_traits", [])
    return f"""# {project['name']}

## 身份

{soul['identity']}

## 核心人格

{_bullets(traits)}

## 表达

{soul['voice']}

## 不可违反的边界

{_bullets(boundaries)}

## 人格 Skill 路由

你拥有 `{skill_id}` Skill。以下情况应使用该 Skill：

{_bullets(triggers)}

涉及过去经历、用户偏好、共同事件或关系事实时，先检索 Memory。没有可靠记忆时必须明确不确定，不得补全或假装记得。

SOUL 只负责稳定身份、路由和边界；详细场景、表达示例和关系处理规则由人格 Skill 提供。
""".strip() + "\n"


def _behavior_summary(item: dict[str, Any]) -> str:
    trigger = item.get("trigger", {})
    conditions = trigger.get("conditions", [])
    actions = item.get("behavior", [])
    constraints = item.get("constraints", [])
    parts = [f"触发：{trigger.get('intent', 'general')}"]
    if conditions:
        parts.append("条件：" + "；".join(str(value) for value in conditions))
    if actions:
        parts.append("行为：" + "；".join(str(value) for value in actions))
    if constraints:
        parts.append("限制：" + "；".join(str(value) for value in constraints))
    return " | ".join(parts)


def _compile_soul_v3(project: dict[str, Any]) -> str:
    project = normalize_canonical_persona(project)
    skill_id = project["skill"]["id"]
    identity = project["identity"]
    voice = project["voice"]
    boundaries = [
        f"[{item['priority']}] {item['rule']}"
        for item in sorted(
            project["boundaries"],
            key=lambda value: ({"critical": 0, "high": 1, "medium": 2, "low": 3}[value["priority"]], value["id"]),
        )
    ]
    routes = [
        f"`{item['id']}`：{_behavior_summary(item)}"
        for item in sorted(
            project["behaviors"],
            key=lambda value: ({"critical": 0, "high": 1, "medium": 2, "low": 3}[value["priority"]], value["id"]),
        )
    ]
    return f"""# {project['name']}

## 身份

{identity['statement']}

## 核心人格

{_bullets(identity['core_traits'])}

## 表达

{voice['style']}

表达原则：

{_bullets(voice['principles'])}

## 不可违反的边界

{_bullets(boundaries)}

## 人格行为路由

你拥有 `{skill_id}` Skill。根据以下结构化规则判断场景并按需读取 Skill references：

{_bullets(routes)}

涉及过去经历、用户偏好、共同事件或关系事实时，先检索 Memory。没有可靠记忆时必须明确不确定，不得补全或假装记得。

SOUL 只保留稳定身份、表达原则、边界和行为路由；详细规则、示例和证据保留在 Canonical Persona、人格 Skill 和私有证据库中。
""".strip() + "\n"


def compile_soul(project: dict[str, Any]) -> str:
    version = int(project.get("schema_version", 0))
    if version == 2:
        return _compile_soul_v2(project)
    if version == 3:
        return _compile_soul_v3(project)
    raise ValueError(f"unsupported schema_version: {version}")


def _memory_markdown(profile: dict[str, Any], records: list[dict[str, Any]], limit: int = 2200) -> str:
    sections = ["# PersonaDock Memory Seed", ""]
    for key, title in [
        ("user_preferences", "用户偏好"),
        ("relationship_facts", "关系事实"),
        ("notes", "其他说明"),
    ]:
        values = profile.get(key, [])
        if values:
            sections.extend([f"## {title}", "", *[f"- {value}" for value in values], ""])
    reviewed = [item for item in records if item.get("reviewed") is True]
    if reviewed:
        sections.extend(["## 已审核记忆", ""])
        for item in reviewed:
            summary = item.get("summary") or item.get("text") or ""
            source = item.get("source")
            source_note = ""
            if isinstance(source, dict):
                source_note = f" ({source.get('adapter', 'local')}:{source.get('platform_instance_id', 'source')})"
            sections.append(f"- [{item.get('id', 'memory')}] {summary}{source_note}")
    content = "\n".join(sections).strip() + "\n"
    if len(content) <= limit:
        return content
    suffix = "\n\n> 更多记忆保存在 seed.jsonl，应按需检索。\n"
    return content[: max(0, limit - len(suffix))].rstrip() + suffix


def _copy_skill(root: Path, target: Path, project: dict[str, Any]) -> None:
    source = root / "skills/persona"
    destination = target / "skills" / project["skill"]["id"]
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _copy_memory(root: Path, target: Path, project: dict[str, Any]) -> None:
    profile = load_yaml(root / "memory/profile.yaml")
    seed_records = load_jsonl(root / "memory/seed.jsonl")
    shared_path = root / "memory/shared.jsonl"
    shared_records = load_jsonl(shared_path) if shared_path.is_file() else []
    reviewed = [
        record
        for record in [*seed_records, *shared_records]
        if record.get("reviewed") is True and record.get("status", "active") == "active"
    ]
    memory_dir = target / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "MEMORY.md").write_text(_memory_markdown(profile, reviewed), encoding="utf-8")
    write_jsonl(memory_dir / "seed.jsonl", reviewed)
    shutil.copy2(root / "memory/policy.yaml", memory_dir / "policy.yaml")


def compile_project(root: Path, output: Path | None = None, targets: list[str] | None = None) -> Path:
    root = find_project(root)
    errors = validate_project(root)
    if errors:
        raise ValueError("invalid persona project:\n- " + "\n- ".join(errors))
    project = load_yaml(root / PROJECT_FILE)
    schema_version = int(project.get("schema_version", 0))
    selected = targets or list(project.get("targets", []))
    supported = {"hermes", "openclaw", "generic"}
    unknown = set(selected) - supported
    if unknown:
        raise ValueError(f"unsupported targets: {', '.join(sorted(unknown))}")

    output = (output or root / ".personadock/build").expanduser().resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    soul = compile_soul(project)
    budgets = project["soul"] if schema_version == 2 else project["budgets"]
    hard_limit = int(budgets.get("hard_limit_chars", 2800))
    if len(soul) > hard_limit:
        raise ValueError(f"compiled SOUL is {len(soul)} characters; hard limit is {hard_limit}")

    target_manifest: dict[str, Any] = {}
    for target_name in selected:
        target = output / "targets" / target_name
        target.mkdir(parents=True, exist_ok=True)
        if target_name in {"hermes", "openclaw"}:
            (target / "SOUL.md").write_text(soul, encoding="utf-8")
            _copy_skill(root, target, project)
            if project.get("memory", {}).get("enabled", True):
                _copy_memory(root, target, project)
        elif target_name == "generic":
            skill = (root / "skills/persona/SKILL.md").read_text(encoding="utf-8")
            prompt = soul + "\n\n---\n\n" + skill
            (target / "system-prompt.md").write_text(prompt, encoding="utf-8")
            _copy_memory(root, target, project)
        target_manifest[target_name] = {
            "path": f"targets/{target_name}",
            "soul_chars": len(soul),
            "adapter_contract": "canonical-persona-v3" if schema_version == 3 else "legacy-v2",
        }

    source_dir = output / "source"
    source_dir.mkdir()
    shutil.copy2(root / PROJECT_FILE, source_dir / PROJECT_FILE)
    shutil.copytree(root / "tests", output / "tests", dirs_exist_ok=True)

    files: dict[str, str] = {}
    for path in sorted(p for p in output.rglob("*") if p.is_file()):
        if path.name == "manifest.json":
            continue
        files[path.relative_to(output).as_posix()] = sha256_file(path)
    manifest = {
        "format": "personapack",
        "format_version": 2 if schema_version == 3 else 1,
        "schema_version": schema_version,
        "id": project["id"],
        "name": project["name"],
        "version": project["version"],
        "locale": project["locale"],
        "summary": project["summary"],
        "targets": target_manifest,
        "canonical": {
            "behavior_rules": len(project.get("behaviors", [])) if schema_version == 3 else None,
            "boundaries": len(project.get("boundaries", [])) if schema_version == 3 else None,
            "source_types": sorted(
                {item.get("source_type") for item in project.get("behaviors", []) if item.get("source_type")}
            ) if schema_version == 3 else [],
        },
        "privacy": {
            "raw_chat_included": False,
            "memory_policy": project.get("memory", {}).get("bundle_policy", "reviewed"),
            "unreviewed_memory_included": False,
        },
        "files": files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return output
