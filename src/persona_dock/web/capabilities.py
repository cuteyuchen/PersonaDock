from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

CapabilityStatus = Literal["ready", "legacy", "planned"]


@dataclass(frozen=True, slots=True)
class WebCapability:
    id: str
    label: str
    category: str
    cli_command: str | None
    api_route: str | None
    web_route: str | None
    status: CapabilityStatus
    destructive: bool = False
    supports_preview: bool = False
    runs_as_job: bool = False
    web_not_applicable_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


CAPABILITIES: tuple[WebCapability, ...] = (
    WebCapability("system.health", "控制面健康状态", "system", None, "/api/health", "#/overview", "ready"),
    WebCapability("system.doctor", "系统诊断", "system", "doctor", "/api/doctor", "#/overview", "ready"),
    WebCapability("system.serve", "启动 Web 控制面", "system", "serve", None, None, "ready", web_not_applicable_reason="Web 进程自身不能再次启动 Web 服务"),
    WebCapability("persona.init", "新建 Persona", "persona", "init", "/api/v1/personas", "#/personas", "ready"),
    WebCapability("persona.distill", "蒸馏 Persona", "persona", "distill", "/api/v1/ai/distill", "#/ai-studio", "planned", runs_as_job=True),
    WebCapability("persona.validate", "验证 Persona", "persona", "validate", "/api/v1/personas/{persona_id}/validation", "#/personas/{persona_id}/tests", "ready", runs_as_job=True),
    WebCapability("persona.migrate", "迁移 Canonical Schema", "persona", "migrate", "/api/v1/personas/{persona_id}/migrate-v3", "#/personas/{persona_id}/editor", "ready", destructive=True, supports_preview=True),
    WebCapability("persona.diff", "语义差异", "persona", "diff", "/api/personas/diff", "#/diff", "ready", supports_preview=True),
    WebCapability("persona.test", "场景测试", "persona", "test", "/api/v1/personas/{persona_id}/tests", "#/personas/{persona_id}/tests", "ready", runs_as_job=True),
    WebCapability("persona.compile-preview", "编译预览", "persona", None, "/api/v1/personas/{persona_id}/compile-preview", "#/personas/{persona_id}/editor", "ready", supports_preview=True),
    WebCapability("persona.list", "Persona 列表", "persona", "persona list", "/api/v1/personas", "#/personas", "ready"),
    WebCapability("persona.show", "Persona 详情", "persona", "persona show", "/api/v1/personas/{persona_id}", "#/personas/{persona_id}", "ready"),
    WebCapability("persona.register", "注册现有工程", "persona", "persona register", "/api/v1/personas/register", "#/personas", "ready"),
    WebCapability("persona.export", "导出 Persona", "persona", "export", "/api/v1/personas/{persona_id}/exports", "#/personas/{persona_id}", "ready", runs_as_job=True),
    WebCapability("persona.export-public", "导出公开工程", "persona", "export-public", "/api/v1/personas/{persona_id}/public-export", "#/personas/{persona_id}/packages", "planned", runs_as_job=True),
    WebCapability("persona.build", "构建目标产物", "package", "build", "/api/v1/personas/{persona_id}/builds", "#/personas/{persona_id}/packages", "planned", runs_as_job=True),
    WebCapability("persona.pack", "创建 PersonaPack", "package", "pack", "/api/v1/personas/{persona_id}/packages", "#/personas/{persona_id}/packages", "planned", runs_as_job=True),
    WebCapability("package.inspect", "检查 PersonaPack", "package", "inspect", "/api/v1/packages/inspect", "#/packages", "planned"),
    WebCapability("runtime.discover", "发现 Runtime", "runtime", "discover", "/api/v1/runtimes/discover", "#/runtimes", "ready", runs_as_job=True),
    WebCapability("runtime.instances", "Runtime 列表", "runtime", "instances", "/api/instances", "#/runtimes", "ready"),
    WebCapability("runtime.adopt", "接管已有 Runtime", "runtime", "adopt", "/api/v1/adoptions", "#/runtimes", "ready", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("deployment.plan", "部署计划", "deployment", "deploy --dry-run", "/api/plans/deploy", "#/deployments", "legacy", supports_preview=True),
    WebCapability("deployment.apply", "部署 Persona", "deployment", "deploy", "/api/v1/deployments", "#/deployments", "planned", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("deployment.install-alias", "旧安装命令", "deployment", "install", None, "#/deployments", "legacy", destructive=True, web_not_applicable_reason="install 是 deploy 的弃用兼容别名"),
    WebCapability("deployment.rollback", "回滚部署", "deployment", "rollback", "/api/v1/deployments/{deployment_id}/rollback", "#/deployments", "planned", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("deployment.uninstall", "卸载部署", "deployment", "uninstall", "/api/v1/deployments/{deployment_id}", "#/deployments", "planned", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("deployment.status", "旧部署状态", "deployment", "status", "/api/v1/deployments/legacy", "#/deployments", "planned"),
    WebCapability("sync.memory", "受控 Memory 同步", "sync", "sync", "/api/sync", "#/memory", "legacy", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("sync.sessions", "Reviewed Session Summary", "session", "session", "/api/sessions", "#/sessions", "legacy", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("adapter.list", "Adapter 列表", "adapter", "adapter list", "/api/v1/adapters", "#/adapters", "planned"),
    WebCapability("adapter.show", "Adapter 详情", "adapter", "adapter show", "/api/v1/adapters/{adapter_name}", "#/adapters/{adapter_name}", "planned"),
    WebCapability("adapter.doctor", "Adapter 诊断", "adapter", "adapter doctor", "/api/v1/adapters/{adapter_name}/doctor", "#/adapters/{adapter_name}", "planned", runs_as_job=True),
    WebCapability("skill.install", "安装 persona-builder Skill", "skill", "skill install", "/api/v1/skills/install", "#/skills", "planned", destructive=True, supports_preview=True),
    WebCapability("trust.keygen", "生成签名密钥", "trust", "trust keygen", "/api/v1/trust/keys", "#/trust", "planned", destructive=True),
    WebCapability("trust.sign", "签名 PersonaPack", "trust", "trust sign", "/api/v1/trust/signatures", "#/trust", "planned", runs_as_job=True),
    WebCapability("trust.verify", "验证 PersonaPack", "trust", "trust verify", "/api/v1/trust/verify", "#/trust", "planned", runs_as_job=True),
    WebCapability("backup.create", "创建加密备份", "backup", "backup create", "/api/v1/backups", "#/backups", "planned", runs_as_job=True),
    WebCapability("backup.inspect", "检查加密备份", "backup", "backup inspect", "/api/v1/backups/inspect", "#/backups", "planned"),
    WebCapability("backup.restore", "恢复加密备份", "backup", "backup restore", "/api/v1/backups/restore", "#/backups", "planned", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("character-card.inspect", "检查 Character Card", "character-card", "character-card inspect", "/api/v1/character-cards/inspect", "#/character-cards", "planned"),
    WebCapability("character-card.import", "导入 Character Card", "character-card", "character-card import", "/api/v1/character-cards/import", "#/character-cards", "planned", destructive=True, supports_preview=True, runs_as_job=True),
    WebCapability("character-card.export", "导出 Character Card", "character-card", "character-card export", "/api/v1/character-cards/export", "#/character-cards", "planned", runs_as_job=True),
    WebCapability("ai.create", "AI 创建 Persona", "ai", None, "/api/v1/ai/generations", "#/ai-studio", "planned", runs_as_job=True),
    WebCapability("ai.refine", "AI 优化 Persona", "ai", None, "/api/v1/ai/generations", "#/ai-studio", "planned", supports_preview=True, runs_as_job=True),
    WebCapability("revision.list", "Revision 历史", "revision", None, "/api/v1/personas/{persona_id}/revisions", "#/personas/{persona_id}/revisions", "ready"),
    WebCapability("revision.diff", "Revision 差异", "revision", None, "/api/v1/personas/{persona_id}/diff", "#/personas/{persona_id}/revisions", "ready", supports_preview=True),
    WebCapability("revision.restore", "恢复 Revision", "revision", None, "/api/v1/personas/{persona_id}/revisions/{revision_id}/restore", "#/personas/{persona_id}/revisions", "ready", destructive=True, supports_preview=True),
    WebCapability("jobs.list", "任务中心", "job", None, "/api/v1/jobs", "#/jobs", "ready"),
)


def list_capabilities(*, status: CapabilityStatus | None = None) -> list[dict[str, object]]:
    values = CAPABILITIES
    if status is not None:
        values = tuple(item for item in values if item.status == status)
    return [item.to_dict() for item in values]


def capability_summary() -> dict[str, int]:
    result = {"total": len(CAPABILITIES), "ready": 0, "legacy": 0, "planned": 0}
    for item in CAPABILITIES:
        result[item.status] += 1
    return result


def validate_capabilities() -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    for item in CAPABILITIES:
        if item.id in ids:
            errors.append(f"duplicate capability id: {item.id}")
        ids.add(item.id)
        if item.cli_command and not item.web_route and not item.web_not_applicable_reason:
            errors.append(f"CLI capability has no Web mapping: {item.id}")
        if item.status == "ready" and item.web_route and not item.api_route:
            errors.append(f"ready Web capability has no API route: {item.id}")
    return errors


__all__ = [
    "CAPABILITIES",
    "CapabilityStatus",
    "WebCapability",
    "capability_summary",
    "list_capabilities",
    "validate_capabilities",
]
