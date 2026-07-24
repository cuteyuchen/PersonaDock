# Canonical Persona v3（Phase 3）

Canonical Persona v3 是 PersonaDock 的平台无关人格源格式。Hermes Profile、OpenClaw Workspace 和未来 Adapter 都从该模型编译，不在 Canonical Persona 中保存平台路径或运行实例配置。

## 新建 v3 人格

通过 CLI 创建的新工程默认使用 Schema v3：

```bash
personadock init ./xiaoyou --id xiaoyou --name 小柚
personadock validate ./xiaoyou
personadock test ./xiaoyou
```

工程仍使用 `companion.yaml` 作为入口，但结构升级为：

```yaml
schema_version: 3
id: xiaoyou
version: 0.1.0
name: 小柚
locale: zh-CN
summary: ...

identity:
  statement: ...
  core_traits:
    - 嘴硬心软
    - 有独立判断
    - 诚实面对记忆边界

voice:
  style: 使用简短、自然的中文表达。
  principles:
    - 根据场景调整长度
    - 不照抄示例

boundaries:
  - id: memory-honesty
    rule: 不虚构共同经历或用户信息
    priority: critical
    source_type: explicit-design

behaviors:
  - id: emotional-support
    trigger:
      intent: emotional-support
      conditions:
        - 用户明显难过或疲惫
    behavior:
      - 停止轻微吐槽
      - 先确认感受
      - 判断用户需要倾听还是建议
    constraints:
      - 不诊断
      - 不强行给建议
    priority: high
    confidence: explicit
    source_type: explicit-design
    evidence: []
    tests:
      - emotional-support
```

## 来源类型

每条结构化行为必须声明来源：

- `explicit-design`：用户明确设计的人格规则。
- `observed-evidence`：从聊天或运行记录观察到的规则。
- `reviewed-existing`：从已审核旧人格迁移。
- `safe-default`：PersonaDock 提供的安全默认行为。

`observed-evidence` 必须提供 `evidence` 引用，否则验证失败。

## 置信度

- `explicit`
- `high`
- `medium`
- `low`

用户明确设计的规则通常使用 `explicit`。聊天蒸馏结论根据重复性、反例和上下文使用 high/medium/low。

## 行为优先级

- `critical`
- `high`
- `medium`
- `low`

Critical 和 High 行为必须关联场景测试。`personadock test` 会检查覆盖率。

## v2 → v3 迁移

保留原工程，输出新目录：

```bash
personadock migrate ./xiaoyou-v2 --output ./xiaoyou-v3
```

原地迁移并创建备份：

```bash
personadock migrate ./xiaoyou --in-place
```

备份位置：

```text
<project>/.personadock/migrations/schema-v2-<timestamp>/
```

关闭备份必须显式指定：

```bash
personadock migrate ./xiaoyou --in-place --no-backup
```

迁移映射：

- `soul.identity` → `identity.statement`
- `soul.core_traits` → `identity.core_traits`
- `soul.voice` → `voice.style`
- `soul.boundaries` → 带稳定 ID 的 `boundaries`
- `soul.skill_triggers` → 结构化 `behaviors`
- 字符预算 → `budgets`

迁移不会伪造聊天证据。旧规则标记为 `reviewed-existing`，evidence 保持为空。

## 语义差异

```bash
personadock diff ./xiaoyou-0.1 ./xiaoyou-0.2
```

JSON：

```bash
personadock diff ./xiaoyou-0.1 ./xiaoyou-0.2 --json
```

Diff 按稳定 ID 区分：

- 新增、删除和修改的行为规则。
- 新增、删除和修改的边界。
- 身份、特征、表达、Memory 策略和目标变化。

## 场景与质量测试

```bash
personadock test ./xiaoyou
```

测试包括：

- `tests/scenarios.yaml` 中声明的场景。
- 场景与行为规则关联。
- Critical/High 行为测试覆盖率。
- `observed-evidence` 的证据引用。

测试只验证结构、覆盖和可追溯性，不调用外部模型，因此结果可重复。

## PersonaPack Manifest v2

Schema v3 工程生成 PersonaPack Manifest v2：

```json
{
  "format": "personapack",
  "format_version": 2,
  "schema_version": 3,
  "canonical": {
    "behavior_rules": 3,
    "boundaries": 3,
    "source_types": ["safe-default"]
  },
  "privacy": {
    "raw_chat_included": false,
    "unreviewed_memory_included": false
  }
}
```

Schema v2 工程仍可读取和构建，其 Manifest 暂时保持 v1。

## Web 编辑器

启动：

```bash
personadock serve
```

打开：

```text
http://127.0.0.1:8732/canonical
```

编辑器支持：

- 选择 Registry 中的人格。
- 原地迁移 v2 → v3。
- 编辑 Canonical JSON。
- Schema 和项目级验证。
- 保存前自动备份。
- 验证失败自动恢复原文件。
- 运行场景和质量测试。

当前编辑器采用结构化 JSON，后续阶段会增加更友好的行为规则、边界和同步策略表单。

## API

```text
GET  /api/personas/{id}/canonical
PUT  /api/personas/{id}/canonical
POST /api/personas/{id}/migrate-v3
GET  /api/personas/{id}/tests
POST /api/personas/diff
```

## 兼容说明

- 底层 Python `init_project()` 保留 v2 默认值，供 Phase 2 接管流程兼容。
- 用户 CLI `personadock init` 默认生成 v3。
- Phase 2 接管的 v2 草稿可通过 Web 或 `personadock migrate` 升级。
- Native Hermes/OpenClaw Adapter 将从 v3 编译，不把平台运行路径写入人格源。
