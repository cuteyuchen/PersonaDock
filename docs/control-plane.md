# PersonaDock 1.0 控制平面

PersonaDock 是本地优先的 AI 人格控制平面。它把 Persona 定义、运行时绑定、部署、Memory 审核、Session Summary 交接、快照和回滚统一到同一套 Core API，并同时提供 CLI 与本地 Web 控制台。

## 核心架构

```text
CLI / Web Console
        ↓
Application Services
Registry · Adoption · Deployment · Review · Sync · Session
        ↓
Canonical Persona Core
Schema · Migration · Diff · Test · Package · Trust
        ↓
Hermes Adapter                  OpenClaw Adapter
Profile Distribution            Agent / Workspace Overlay
        ↓
Local Registry · Persona Projects · Snapshots · Journal
```

## 数据边界

### PersonaDock 管理

- Canonical Persona Schema v3。
- Persona Skill 和 PersonaDock 所有权文件。
- 已审核的共享 Memory。
- 已审核的 Session Summary Handoff。
- Runtime Binding、Snapshot、Journal、冲突和传播记录。
- PersonaPack Manifest v2、签名和私有工程备份。

### PersonaDock 不管理

- API Key、OAuth、Provider 或 Gateway Token。
- Hermes/OpenClaw 的认证文件和运行时 State。
- 原始 Session、Transcript、工具调用和内部推理。
- OpenClaw 的 `AGENTS.md`、`USER.md`、`TOOLS.md` 等平台专属文件。
- 非 PersonaDock 所有权的 Skills 和 Memory 内容。

## 安全工作流

所有平台写入遵循：

```text
Doctor / Discovery
        ↓
Deployment Plan
        ↓
用户确认或 --yes
        ↓
Snapshot
        ↓
Apply
        ↓
Verify
        ↓
Registry Binding + Journal
        ↓
失败时 Rollback
```

不可信或不明确的目标不会被静默选中。Hermes 和 OpenClaw 默认使用平台原生 CLI；文件系统部署只能通过显式兼容模式使用。

## 环境诊断

```bash
personadock doctor
personadock doctor --json
personadock adapter list
personadock adapter doctor hermes --json
personadock adapter doctor openclaw --json
```

Doctor 会显示：

- PersonaDock、Python/独立程序和系统信息。
- Hermes/OpenClaw 命令与版本是否可用。
- Adapter 能力和 Transport。
- 宿主机 CLI 不可用时，Docker 中唯一可用的 Hermes/OpenClaw 容器；多个候选会明确报告歧义。
- 本机目标是否可信且唯一。
- 需要显式参数或人工处理的冲突。

## Persona 与 Runtime Registry

```bash
personadock persona list
personadock discover
personadock instances
personadock instances --unmanaged
```

Registry 默认位于：

```text
~/.personadock/personadock.db
```

可以通过 `PERSONADOCK_HOME` 指向其他状态目录。Registry 保存 Persona、Runtime Instance、Binding、Snapshot 元数据、Journal、Memory Review 和 Session Summary 记录，不保存原始会话。

## 部署

Hermes：

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --profile xiaoyou \
  --dry-run --json

personadock deploy ./persona.personapack \
  --target hermes \
  --profile xiaoyou \
  --yes
```

OpenClaw：

```bash
personadock deploy ./persona.personapack \
  --target openclaw \
  --agent xiaoyou \
  --dry-run --json

personadock deploy ./persona.personapack \
  --target openclaw \
  --agent xiaoyou \
  --yes
```

`personadock install` 仍作为 1.x 迁移别名保留，但新文档和自动化应使用 `deploy`。

## Memory 与 Session Summary

Memory：

```bash
personadock sync collect xiaoyou
personadock sync candidates xiaoyou --status pending
personadock sync review approve <item-id> --scope shared
personadock sync plan xiaoyou
personadock sync apply xiaoyou --yes
```

Session Summary：

```bash
personadock session collect xiaoyou
personadock session list xiaoyou --status pending
personadock session review approve <summary-id> --scope shared
personadock session plan xiaoyou
personadock session apply xiaoyou --yes
```

默认自动批准关闭；冲突阻止传播；来源回声关闭；原始 Session/Transcript 同步始终关闭。

## Web 控制台

```bash
personadock serve
```

页面：

```text
http://127.0.0.1:8732/
http://127.0.0.1:8732/canonical
http://127.0.0.1:8732/hermes
http://127.0.0.1:8732/openclaw
http://127.0.0.1:8732/sync
http://127.0.0.1:8732/sessions
```

Web 和 CLI 使用同一 Registry 与服务层，不维护两套部署或同步逻辑。

## 非本机监听

绑定非 Loopback 地址必须配置 Bearer Token：

```bash
personadock serve \
  --host 0.0.0.0 \
  --token "replace-with-a-long-random-token"
```

也可以使用：

```bash
export PERSONADOCK_WEB_TOKEN="replace-with-a-long-random-token"
personadock serve --host 0.0.0.0
```

远程访问应放在 HTTPS 反向代理后。PersonaDock 1.0 不提供多用户身份系统或云端托管控制平面。

## 相关文档

- [完整文档索引](README.md)
- [Registry 与运行实例发现](registry-discovery.md)
- [Hermes 原生 Adapter](hermes-native-adapter.md)
- [OpenClaw 原生 Adapter](openclaw-native-adapter.md)
- [受控 Memory 同步](governed-sync.md)
- [Reviewed Session Summaries](session-summaries.md)
- [迁移与回滚](migration-and-rollback.md)
