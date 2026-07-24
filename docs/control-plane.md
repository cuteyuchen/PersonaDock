# PersonaDock Control Plane（Phase 0）

Phase 0 建立了安全部署计划、本地 Web 控制台和共享 Doctor 服务。

## 环境诊断

```bash
personadock doctor
personadock doctor --json
```

Doctor 会显示：

- PersonaDock 和系统信息。
- Hermes/OpenClaw 命令是否可用。
- 是否检测到唯一可信的数据目录或 Workspace。
- 当前 Adapter 能力。
- 需要显式 `--path` 的情况。

PersonaDock 不再因为没有提供路径就直接写入 `~/.hermes`。Windows 下会检查 `%LOCALAPPDATA%\hermes` 和用户目录候选，但只有存在可信 Hermes 标志文件时才会选中。

## 部署预览

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --path /srv/hermes \
  --dry-run
```

Windows：

```powershell
personadock deploy .\persona.personapack `
  --target hermes `
  --path "$env:LOCALAPPDATA\hermes" `
  --dry-run
```

预览会列出：

- PersonaPack ID 和版本。
- Adapter 和目标解析来源。
- 将创建或替换的每个文件。
- 明确保留的平台状态。
- Legacy Filesystem Adapter 警告。

确认无误后执行：

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --path /srv/hermes
```

非交互环境必须显式允许：

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --path /srv/hermes \
  --yes
```

旧命令仍可使用，但会显示弃用提示：

```bash
personadock install ...
```

## Docker 兼容模式

原生 Hermes/OpenClaw Docker Adapter 尚未实现。Phase 0 的 Legacy Filesystem Adapter 要求显式指定容器内绝对路径：

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --container hermes-app \
  --path /root/.hermes \
  --dry-run
```

不提供 `--path` 会直接停止，避免把平台目录猜错。

## 本地 Web 控制台

```bash
personadock serve
```

默认地址：

```text
http://127.0.0.1:8732
```

当前页面提供：

- 服务健康状态。
- 系统和 PersonaDock 版本。
- Hermes/OpenClaw/Generic Adapter Doctor。
- 已检测目标和路径来源。
- Phase 0 安全规则。

API：

```text
GET  /api/health
GET  /api/doctor
POST /api/plans/deploy
GET  /api/docs
```

### 远程监听

绑定非本机地址必须设置令牌：

```bash
personadock serve \
  --host 0.0.0.0 \
  --token "replace-with-a-long-random-token"
```

也可以使用环境变量：

```bash
export PERSONADOCK_WEB_TOKEN="replace-with-a-long-random-token"
personadock serve --host 0.0.0.0
```

远程部署建议放在 HTTPS 反向代理后面。Phase 0 不提供完整远程用户系统。

## 当前限制

- Hermes Profile Distribution Adapter 尚未启用。
- OpenClaw Agent Workspace Adapter 尚未启用。
- Persona Registry、Discovery、Adopt、Export 和 Sync 属于后续阶段。
- 当前部署仍通过 Legacy Filesystem Adapter，但必须经过计划和可信目标解析。
