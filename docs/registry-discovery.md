# Persona Registry 与运行实例发现（Phase 1）

Phase 1 增加了持久化 Persona Registry 和只读 Hermes/OpenClaw Discovery。

## Registry 位置

默认数据库：

```text
~/.personadock/personadock.db
```

测试、便携部署或自定义数据目录：

```bash
export PERSONADOCK_HOME=/srv/personadock
```

Windows PowerShell：

```powershell
$env:PERSONADOCK_HOME = "D:\PersonaDock"
```

Registry 当前包含：

- Persona
- Runtime Instance
- Binding
- Snapshot 元数据
- Journal Event

Phase 1 只实现 Persona 和 Runtime Instance 的主要查询及发现；接管、快照写入和 Binding 向导在 Phase 2 实现。

## 人格注册

`personadock init`、`build` 和 `pack` 会自动注册工程：

```bash
personadock init ./xiaoyou --id xiaoyou --name 小柚
personadock persona list
personadock persona show xiaoyou
```

注册已有 PersonaDock 工程：

```bash
personadock persona register ./xiaoyou
```

机器可读输出：

```bash
personadock persona list --json
personadock persona show xiaoyou --json
```

重复注册相同 ID 会更新版本、名称、摘要和源路径，不会创建重复 Persona。

## 只读发现

扫描全部支持的平台：

```bash
personadock discover
```

仅扫描一个平台：

```bash
personadock discover --target hermes
personadock discover --target openclaw
```

JSON：

```bash
personadock discover --json
```

Discovery 保证：

- 不创建或删除 Profile/Agent。
- 不修改 SOUL、Skill、Memory、Session 或配置。
- 优先使用平台 CLI。
- CLI 不可用时才检查已有目录和标志文件。
- 相同平台实例重复扫描时保持稳定 Registry ID。
- 更新 `last_seen_at`，不重复插入记录。

## Hermes

优先调用：

```text
hermes profile list
hermes profile show <name>
```

CLI 不可用时，只读检查：

```text
$HERMES_HOME
%LOCALAPPDATA%\hermes
~/.hermes
<hermes-home>/profiles/*
```

目录必须含 Hermes 标志内容才会被登记，例如 `SOUL.md`、`config.yaml`、`skills/`、`memories/` 或 `sessions/`。

## OpenClaw

优先调用机器可读命令：

```text
openclaw agents list --json
```

Registry 记录：

- Agent ID
- 显示名称/Identity
- Workspace
- Workspace 文件
- Skill 数量
- Memory 目录状态

CLI 不可用时，只读检查显式 `OPENCLAW_WORKSPACE_DIR` 或默认 Workspace。Phase 1 不读取 Session Store 和认证目录。

## 查看实例

```bash
personadock instances
personadock instances --adapter hermes
personadock instances --adapter openclaw
personadock instances --unmanaged
personadock instances --managed
personadock instances --json
```

Phase 1 扫描出的实例默认为 `unmanaged`。Phase 2 的 Adopt 流程会创建快照、Persona 和 Binding，并把实例标记为已管理。

## Web 控制台

```bash
personadock serve
```

Phase 1 页面提供：

- Registry 统计
- Persona 列表
- 一键只读扫描
- Hermes/OpenClaw 运行实例列表
- 已管理/未管理状态
- Workspace/Profile 路径和发现来源
- Doctor

API：

```text
GET  /api/registry
GET  /api/personas
GET  /api/personas/{persona_id}
GET  /api/instances
GET  /api/instances/{instance_id}
POST /api/discover
```

## 当前限制

- Discovery 只登记本机实例。
- Docker/远程实例的数据模型已经支持 `transport`，自动发现将在平台 Adapter 阶段实现。
- 不提取现有人格为 Canonical Persona。
- 不导入 Memory。
- 不创建 Binding。
- 不执行同步。
