# Docker 与远程运行时部署

PersonaDock 1.0 默认通过平台原生 CLI 部署 Persona，而不是直接向猜测的数据目录复制文件：

- Hermes：本机或 Docker 内的 Profile Distribution。
- OpenClaw：本机、Docker 或 SSH 上的 Agent/Workspace Overlay。

新命令统一使用 `personadock deploy`。`personadock install` 只是 1.x 迁移兼容别名。

## 前置检查

Docker：

```bash
docker version
personadock hermes doctor --container hermes-agent
personadock openclaw doctor --container openclaw
```

SSH OpenClaw：

```bash
personadock openclaw doctor --ssh-host user@example.com
```

要求：

- Docker CLI 可用，目标容器正在运行。
- 容器中安装对应 Hermes/OpenClaw CLI。
- 当前用户可执行 `docker exec` 和 `docker cp`。
- SSH 目标可以无交互执行 OpenClaw CLI 和必要文件操作。
- Docker 与 SSH 不能同时用于同一个 OpenClaw 操作。

## Hermes Docker 部署

查看容器内 Profile：

```bash
personadock hermes profiles --container hermes-agent
```

预览：

```bash
personadock deploy ./xiaoyou.personapack \
  --target hermes \
  --profile xiaoyou \
  --container hermes-agent \
  --dry-run --json
```

应用：

```bash
personadock deploy ./xiaoyou.personapack \
  --target hermes \
  --profile xiaoyou \
  --container hermes-agent \
  --yes
```

PersonaDock 把临时 Distribution 复制到容器，再由容器内的 `hermes profile install` 完成部署。更新现有 Profile 前会执行原生导出快照；验证失败时恢复快照。

不会进入 Distribution：

```text
.env
认证
memories/
sessions/
state.db*
logs/
cache/
local/
```

## OpenClaw Docker 部署

查看 Agent、Workspace 与 State 边界：

```bash
personadock openclaw agents --container openclaw
```

更新已有 Agent：

```bash
personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --container openclaw \
  --dry-run --json

personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --container openclaw \
  --yes
```

新建 Agent 必须提供容器内绝对 Workspace：

```bash
personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --workspace /home/openclaw/workspace-xiaoyou \
  --container openclaw \
  --yes
```

PersonaDock 只管理 Workspace 中由所有权 Manifest 声明的 Persona 文件。`agentDir`、Auth、Sessions、Transcripts、Routing 和平台 State 不属于写入目标。

## OpenClaw SSH 部署

检查远程 Agent：

```bash
personadock openclaw agents --ssh-host user@example.com
```

更新已有 Agent：

```bash
personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --ssh-host user@example.com \
  --dry-run --json

personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --ssh-host user@example.com \
  --yes
```

新建远程 Agent 时，`--workspace` 必须是远程主机上的绝对 POSIX 路径。

## Bind Mount 与 Named Volume

原生 Adapter 只要求容器内 CLI 能访问其运行数据；底层数据可以来自 bind mount 或 named volume。

推荐使用持久卷并保持稳定容器名称：

- 容器重建后，Profile/Agent/Workspace 和平台 State 仍然存在。
- PersonaDock Registry 使用稳定的容器和平台实例标识恢复 Binding。
- 快照、Journal 和部署记录保存在 PersonaDock 主机的 `PERSONADOCK_HOME`。

不建议把重要运行状态只放在容器临时文件系统中。

## Memory 与 Session Summary

Docker/SSH 实例可以进入受控同步，但规则与本机相同：

```bash
personadock sync collect xiaoyou
personadock sync plan xiaoyou
personadock sync apply xiaoyou --yes

personadock session collect xiaoyou
personadock session plan xiaoyou
personadock session apply xiaoyou --yes
```

- Memory 和 Session Summary 默认进入审核队列。
- 来源回声和重复目标写入受到抑制。
- 原始 Session、Transcript、系统消息、工具调用和认证不跨运行时同步。
- 临时导出在解析后删除。

## 回滚

Hermes：

```bash
personadock hermes rollback \
  --profile xiaoyou \
  --snapshot <snapshot-path> \
  --container hermes-agent
```

OpenClaw：

```bash
personadock openclaw rollback \
  --agent xiaoyou \
  --snapshot <snapshot-path> \
  --container openclaw
```

SSH OpenClaw 使用与部署相同的 `--ssh-host`。回滚只恢复 PersonaDock 所有权文件，不应覆盖平台认证、Session 或 State。

## Legacy Filesystem 兼容模式

旧的目录直写实现仍为 1.x 迁移保留，但默认关闭。只有无法使用平台原生 CLI 时才显式启用，并必须提供确认过的绝对路径：

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --legacy-filesystem \
  --container hermes-agent \
  --path /explicit/path \
  --dry-run
```

兼容模式不应成为新部署的默认方案。它使用旧安装状态、rollback、uninstall 记录，因此操作时必须保持相同的 target、container 和 path。

## 相关文档

- [Hermes 原生 Adapter](hermes-native-adapter.md)
- [OpenClaw 原生 Adapter](openclaw-native-adapter.md)
- [迁移与回滚](migration-and-rollback.md)
- [控制平面总览](control-plane.md)
