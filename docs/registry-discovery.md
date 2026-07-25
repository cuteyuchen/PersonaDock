# Persona Registry 与运行实例发现

PersonaDock 1.0 使用本地 SQLite Registry 管理 Persona、运行实例、绑定、快照、审核和传播状态。Discovery 是只读入口；Adopt、原生部署和同步在发现结果之上建立受管理关系。

## Registry 位置

默认数据库：

```text
~/.personadock/personadock.db
```

自定义状态目录：

```bash
export PERSONADOCK_HOME=/srv/personadock
```

Windows PowerShell：

```powershell
$env:PERSONADOCK_HOME = "D:\PersonaDock"
```

Registry Schema v3 主要记录：

- Persona 与 Canonical 工程路径。
- Runtime Instance 与 Adapter/Transport 能力。
- Persona ↔ Runtime Binding。
- Snapshot 元数据和不可变 Journal Event。
- Sync Policy、Memory Item、Conflict、Sync Run 与 Propagation Log。
- Session Summary Policy、Review 与 Propagation 记录。

Registry 不保存 API Key、OAuth Token、原始 Session、Transcript 或平台 State。

## Persona 注册

`init`、`build` 和 `pack` 会注册或更新工程：

```bash
personadock init ./xiaoyou --id xiaoyou --name 小柚
personadock persona list
personadock persona show xiaoyou
```

注册已有工程：

```bash
personadock persona register ./xiaoyou
```

机器可读输出：

```bash
personadock persona list --json
personadock persona show xiaoyou --json
```

相同 Persona ID 会更新名称、版本、摘要和源路径，不会创建重复记录。

## 本机只读发现

扫描支持的平台：

```bash
personadock discover
personadock discover --target hermes
personadock discover --target openclaw
personadock discover --json
```

Discovery 保证：

- 不创建、更新或删除 Profile/Agent。
- 不修改 SOUL、Skill、Memory、Session 或配置。
- 优先使用平台 CLI 返回的身份和路径。
- 相同平台实例重复扫描保持稳定 Registry ID。
- 只更新可观察元数据和 `last_seen_at`。
- 不读取认证、Session Store 或 Transcript 内容。

## Hermes 发现

优先调用：

```text
hermes profile list
hermes profile show <name>
hermes profile info <name>
```

CLI 不可用时，只对可信标志目录执行只读兼容检查。Windows 候选包括 `%LOCALAPPDATA%\hermes`，但 PersonaDock 不会仅凭常见路径就把目录当作可信写入目标。

## OpenClaw 发现

优先调用：

```text
openclaw agents list --json --bindings
```

Registry 分开保存：

- Agent ID 与显示身份。
- Workspace。
- `agentDir`/State 的只读元数据边界。
- Channel Binding。
- Adapter 能力和 Transport。

PersonaDock 不把 Workspace 与 `agentDir` 混为一体，也不直接读取 State 内的认证、Sessions 或 Transcripts。

## 查看运行实例

```bash
personadock instances
personadock instances --adapter hermes
personadock instances --adapter openclaw
personadock instances --unmanaged
personadock instances --managed
personadock instances --json
```

新发现的实例默认为 `unmanaged`。完成 Adopt 或原生部署后，PersonaDock 创建 Binding 并将其纳入受管理生命周期。

## 接管现有人格

```bash
personadock adopt --instance <runtime-instance-id> --dry-run
personadock adopt --instance <runtime-instance-id> --yes
```

Adopt 会先创建快照，再生成 Persona 草稿、未审核 Memory Candidate 和 Binding。相同名称不会被自动视为同一 Persona；确认后使用 `--link-existing` 显式绑定。

完整流程见 [接管、快照与导出](adopt-export.md)。

## Docker 与 SSH 实例

PersonaDock 1.0 支持：

- Hermes：本机和 Docker 原生 Profile Adapter。
- OpenClaw：本机、Docker 和 SSH Agent/Workspace Adapter。

这些实例通过原生 Adapter Doctor、枚举和部署命令登记。PersonaDock 不会在网络或 Docker 主机中无范围地自动扫描所有容器/主机。

示例：

```bash
personadock hermes profiles --container hermes-agent
personadock openclaw agents --container openclaw
personadock openclaw agents --ssh-host user@example.com
```

参见 [Docker 与远程运行时](docker-install.md)。

## Web 控制台

```bash
personadock serve
```

总览页面和 API 支持：

- Registry 统计与 Persona 列表。
- 一键本机只读发现。
- Runtime Instance 和管理状态。
- Adopt 预览与确认。
- Binding、Snapshot 和 Journal 查询。

主要 API：

```text
GET  /api/registry
GET  /api/personas
GET  /api/personas/{persona_id}
GET  /api/instances
GET  /api/instances/{instance_id}
POST /api/discover
```

## 运行边界

- 本机 Discovery 不等于自动接管或自动部署。
- Docker/SSH 需要用户明确提供容器或 SSH 目标。
- 同名实例不会自动合并。
- 未审核 Memory 和 Session Summary 不会进入共享传播。
- 原始 Session/Transcript 永不进入 Registry。
