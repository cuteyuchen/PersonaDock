# 受控跨运行时同步（Phase 6）

PersonaDock Phase 6 将 Hermes 与 OpenClaw 的平台原语统一成审核优先的同步引擎。默认行为不是自动双向复制，而是：

```text
运行时 Pull
  → 未审核 Candidate
  → 敏感度与来源分类
  → 去重 / 冲突检测
  → 用户或白名单策略批准
  → Canonical Memory
  → 生成目标传播计划
  → 用户确认
  → 平台 Push
  → 传播日志与循环抑制
```

原始 Session、Transcript、认证和平台 State 不进入本阶段同步。

## Registry Schema v2

新增表：

```text
sync_policies
memory_items
sync_conflicts
sync_runs
propagation_log
```

每条候选或已审核记忆记录：

- Persona ID。
- 内容指纹。
- 稳定 Memory Key。
- 类型与摘要。
- 敏感度。
- 同步作用域。
- 审核状态。
- 来源 Adapter 和 Runtime Instance。
- 来源记录与文件。
- 审核者和时间。
- 完整 Provenance 元数据。

Registry v1 数据库启动时自动迁移到 v2，原 Persona、Instance、Binding、Snapshot 和 Journal 数据保持不变。

## 默认 SyncPolicy

首次访问 Persona 的同步功能时创建安全默认策略：

```yaml
schema_version: 1
mode: review
pull:
  enabled: true
  adapters: [hermes, openclaw]
push:
  enabled: true
  adapters: [hermes, openclaw]
  reviewed_only: true
  echo_to_source: false
auto_approve:
  enabled: false
  source_adapters: []
  memory_types: []
  max_sensitivity: internal
conflicts:
  strategy: manual
definition_sync:
  push: manual
  pull: snapshot-review
```

查看：

```bash
personadock sync policy show xiaoyou
```

更新局部策略：

```bash
personadock sync policy set xiaoyou \
  --config-json '{"mode":"review","pull":{"enabled":true}}'
```

使用 YAML/JSON 文件替换完整策略：

```bash
personadock sync policy set xiaoyou \
  --file ./sync-policy.yaml \
  --replace
```

## 自动批准

只有同时满足以下条件才自动批准：

- `mode: automatic`。
- `auto_approve.enabled: true`。
- 来源 Adapter 在白名单中。
- Memory Type 在白名单中；空列表表示不限制类型。
- 实际敏感度不高于 `max_sensitivity`。
- 没有冲突。

示例：只自动批准 Hermes 的低敏感度 Preference：

```yaml
mode: automatic
auto_approve:
  enabled: true
  source_adapters: [hermes]
  memory_types: [preference]
  max_sensitivity: internal
```

默认策略不会自动批准任何候选。

## 敏感度

支持：

```text
public < internal < private < restricted
```

PersonaDock 不会降低来源声明的敏感度，并会对以下内容自动升级：

- API Key、Token、Password、Secret 和私钥 → `restricted`。
- 邮箱、电话号码、医疗、银行和身份证信息 → `private`。

敏感度只影响是否允许自动审批；用户仍可在审核中心明确决定保留或拒绝。

## Pull 与候选导入

从所有绑定且声明 `memory_pull` 能力的运行时收集：

```bash
personadock sync collect xiaoyou
```

Hermes 使用：

```text
memories/MEMORY.md
memories/USER.md
```

OpenClaw 使用：

```text
MEMORY.md
memory/*.md
```

平台原语先写入：

```text
<persona>/.private/memory-candidates.jsonl
```

统一引擎再将候选导入 Registry。完全相同的 Persona、类型和规范化内容只保留一条。

查看候选：

```bash
personadock sync candidates xiaoyou --status pending
personadock sync candidates xiaoyou --sensitivity restricted
personadock sync candidates xiaoyou --source-adapter openclaw
```

## 审核

批准并共享：

```bash
personadock sync review approve <item-id> \
  --reviewer thomas \
  --scope shared
```

批准但不传播：

```bash
personadock sync review approve <item-id> \
  --scope local-only
```

拒绝：

```bash
personadock sync review reject <item-id> \
  --reason "包含未经确认的个人信息"
```

批准后写入 Persona 工程的：

```text
memory/seed.jsonl
```

记录包含内容指纹、Memory Key、来源、审核者和审核时间。

## 冲突

具有相同显式 Memory Key、但内容不同的候选与现有已批准记忆会产生冲突。默认策略下，冲突阻止批准和同步。

查看：

```bash
personadock sync conflicts xiaoyou --status pending
```

保留现有：

```bash
personadock sync review resolve <conflict-id> \
  --resolution keep-existing
```

候选替换现有：

```bash
personadock sync review resolve <conflict-id> \
  --resolution replace
```

两者并存：

```bash
personadock sync review resolve <conflict-id> \
  --resolution keep-both
```

`replace` 会把旧 Registry 项标记为 `superseded`，从 Canonical Seed 移除旧内容，再批准新候选。

## 同步预览

```bash
personadock sync plan xiaoyou
```

计划包含：

- 需要更新的人格定义 Binding。
- 每条已审核 Memory 到每个目标 Runtime 的传播。
- 因本地作用域、来源回声、能力不足或已传播而跳过的操作。
- 未解决冲突。
- 策略警告。

Definition Pull 不会直接覆盖 Canonical Persona。它保持 `snapshot-review` 模式，必须通过 Snapshot / Adopt / Diff 流程人工审核。

## 应用同步

只同步已审核 Memory：

```bash
personadock sync apply xiaoyou --yes
```

同时部署过期的 Canonical Persona Definition：

```bash
personadock sync apply xiaoyou \
  --definitions \
  --yes
```

Definition Push 使用已经完成验收的平台原生 Adapter：

- Hermes Profile Distribution。
- OpenClaw Agent / Workspace Overlay。

应用时重新生成最新计划。存在未解决冲突时整个同步操作停止。

## 循环抑制

PersonaDock 使用两层机制：

1. 平台 Pull 会移除 PersonaDock 自己管理的 Memory 区块。
2. `propagation_log` 记录每个 Memory Item、目标 Runtime、内容 Hash 和操作结果。

默认 `echo_to_source: false`，来自某个 Runtime 的候选批准后不会立即推回同一来源。已成功传播到目标的相同内容也不会重复传播。

## 失败处理

每个目标运行时独立执行：

- 平台 Push 前由原生 Adapter 创建文件或 Profile 快照。
- 写入后验证内容。
- OpenClaw 重建 Memory Index。
- 失败时平台原语恢复原文件或 Profile。
- `sync_runs` 记录 `success`、`partial` 或 `failed`。
- `propagation_log` 记录每条内容在每个目标的结果。

一个目标失败不会伪造其他目标成功。

## 状态与审计

```bash
personadock sync status xiaoyou
```

JSON：

```bash
personadock sync status xiaoyou --json
```

包括：

- 当前策略。
- Pending / Approved / Rejected 数量。
- 冲突。
- 最新计划。
- 同步运行历史。
- 传播历史。

所有策略、审核、冲突和应用操作同时写入 PersonaDock Journal。

## Web 审核中心

```bash
personadock serve
```

打开：

```text
http://127.0.0.1:8732/sync
```

支持：

- 选择 Persona。
- 平台 Pull。
- 编辑和验证 SyncPolicy。
- 按状态查看候选。
- 查看来源、敏感度、作用域和 Memory Key。
- 批准为 Shared 或 Local-only。
- 拒绝候选。
- 三种冲突解决策略。
- Definition 与 Memory 传播预览。
- 明确确认应用。
- 查看 Sync Run 与 Propagation Log。

## 本阶段明确不支持

```text
原始 Session 同步
Transcript 同步
认证或 OAuth Token 同步
平台 State Directory 同步
无审核的默认自动双向同步
后台定时同步
```

Session 摘要将在 Phase 7 作为独立、低风险的数据类型实现。
