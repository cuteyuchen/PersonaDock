# OpenClaw 原生 Agent / Workspace Adapter（Phase 5）

PersonaDock 通过 OpenClaw CLI 管理 Agent，并只把 Persona Overlay 写入 CLI 返回或用户显式指定的 Workspace。`agentDir`、认证、Sessions、Transcripts 和 Memory Index 属于 OpenClaw State，不是 Workspace，也不是 PersonaDock 的写入目标。

## 检查环境

本机：

```bash
personadock openclaw doctor
personadock openclaw agents
```

Docker：

```bash
personadock openclaw doctor --container openclaw
personadock openclaw agents --container openclaw
```

SSH：

```bash
personadock openclaw doctor --ssh-host user@example.com
personadock openclaw agents --ssh-host user@example.com
```

Docker 与 SSH 不能同时使用。

## Workspace 与 State Directory

`personadock openclaw agents` 会分别显示：

```text
workspace: 由 Agent 使用的 Markdown、Skills 和 Memory 工作区
state:     agentDir；保存认证、Sessions、Transcripts 和平台状态
```

PersonaDock 只向 Workspace 写入受所有权 Manifest 管理的文件，不直接访问 State Directory。

## 新建 Agent

新 Agent 必须显式提供绝对 Workspace，PersonaDock 不猜测默认路径：

```bash
personadock deploy ./dist/xiaoyou-0.1.0.personapack \
  --target openclaw \
  --agent xiaoyou \
  --workspace /srv/openclaw/workspace-xiaoyou \
  --model openai/gpt-5.6-sol \
  --bind telegram:ops \
  --dry-run
```

应用：

```bash
personadock deploy ./dist/xiaoyou-0.1.0.personapack \
  --target openclaw \
  --agent xiaoyou \
  --workspace /srv/openclaw/workspace-xiaoyou \
  --yes
```

PersonaDock 调用：

```text
openclaw agents add <agent> --workspace <absolute-path> --non-interactive --json
openclaw agents set-identity --agent <agent> --from-identity --json
openclaw agents list --json --bindings
```

Agent State Directory 由 OpenClaw 创建和管理。

## 更新现有 Agent

现有 Agent 的 Workspace 必须来自 `openclaw agents list --json`。显式传入 `--workspace` 时必须与 CLI 返回值一致，否则拒绝部署。

```bash
personadock deploy package.personapack \
  --target openclaw \
  --agent xiaoyou \
  --yes
```

更新前会快照 PersonaDock 已拥有的 Workspace 路径，然后写入并逐文件验证 SHA-256。

## 主 Agent 保护

Persona ID 为 `main` 时不会隐式部署到 OpenClaw 主 Agent。必须明确指定：

```bash
personadock deploy main.personapack \
  --target openclaw \
  --agent main \
  --yes
```

主 Agent 不能通过 PersonaDock 删除。

## Overlay 所有权

PersonaDock Overlay 只包含：

```text
SOUL.md
IDENTITY.md
skills/<persona-skill>/
personadock-manifest.json
```

默认保留：

```text
AGENTS.md
USER.md
TOOLS.md
HEARTBEAT.md
BOOTSTRAP.md
MEMORY.md
memory/
DREAMS.md
其他 Workspace Skills
agentDir
认证与 OAuth Token
Sessions 与 Transcripts
Routing 和 Memory Index
```

Workspace 没有 PersonaDock Manifest 时，若已存在 SOUL、IDENTITY 或同名 Persona Skill，部署会停止。审核计划后可显式接管：

```bash
personadock deploy package.personapack \
  --target openclaw \
  --agent xiaoyou \
  --take-ownership \
  --yes
```

## Docker 与 SSH

Docker：

```bash
personadock deploy package.personapack \
  --target openclaw \
  --agent xiaoyou \
  --container openclaw \
  --yes
```

SSH：

```bash
personadock deploy package.personapack \
  --target openclaw \
  --agent xiaoyou \
  --ssh-host user@example.com \
  --yes
```

远程新 Agent 的 Workspace 必须是绝对 POSIX 路径。

## 回滚

恢复 Workspace 快照：

```bash
personadock openclaw rollback \
  --agent xiaoyou \
  --snapshot ~/.personadock/snapshots/openclaw/xiaoyou/...
```

删除 PersonaDock 创建的 Agent：

```bash
personadock openclaw rollback \
  --agent xiaoyou \
  --delete-agent
```

删除通过 OpenClaw CLI 执行，由 OpenClaw 处理其 Workspace、State 和 Sessions 的安全迁移。主 Agent 不允许删除。

## Memory Pull

```bash
personadock openclaw memory pull xiaoyou --agent xiaoyou
```

读取：

```text
MEMORY.md
memory/*.md
```

输出到：

```text
<persona>/.private/memory-candidates.jsonl
```

所有候选项均为：

```yaml
reviewed: false
sensitivity: private
sync_scope: local-only
status: pending
```

不会读取 Sessions 或 Transcripts。

## 已审核 Memory Push

```bash
personadock openclaw memory push xiaoyou \
  --agent xiaoyou \
  --yes
```

只写入已审核共享记忆，并保留原有 `MEMORY.md` 内容。PersonaDock 管理区块为：

```text
<!-- personadock-shared-memory:start -->
...
<!-- personadock-shared-memory:end -->
```

写入后执行：

```text
openclaw memory index --agent <agent> --force
```

索引失败时恢复原 `MEMORY.md` 并再次索引原内容。

## Web

```bash
personadock serve
```

打开：

```text
http://127.0.0.1:8732/openclaw
```

页面支持 Doctor、Agent/Workspace/State 查看、部署计划、新建或更新 Agent、所有权接管、Docker/SSH、回滚和 Memory 操作。

## 旧文件系统模式

旧直写模式只通过显式兼容参数启用：

```bash
personadock deploy package.personapack \
  --target openclaw \
  --legacy-filesystem \
  --path /explicit/workspace \
  --yes
```
