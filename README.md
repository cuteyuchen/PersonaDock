# PersonaDock 1.1

**PersonaDock 是一个本地优先的 AI 人格控制平面。**

它把自然语言、聊天记录和既有 Hermes/OpenClaw 人格转换为可审核、可测试、可版本化、可导出、可部署和可同步的 Canonical Persona。PersonaDock 不托管云端人格服务，不自动上传聊天，也不会把认证、原始 Session、Transcript 或运行时 State 打进 PersonaPack。

## 核心能力

- Vue 3 + TypeScript 桌面控制面，覆盖 Persona、Artifact、Runtime、治理和 AI 工作流。
- Canonical Persona Schema v3、Monaco 编辑器、Revision、语义 Diff 与确定性场景测试。
- Persona Registry、Runtime Discovery、Binding、Snapshot 和 Journal。
- Hermes 原生 Profile Distribution 部署、验证和回滚。
- OpenClaw 原生 Agent/Workspace 部署，支持本机、Docker 和 SSH。
- Review-first 跨运行时 Memory 同步、冲突处理和循环抑制。
- Reviewed Session Summary 交接；原始 Session/Transcript 同步关闭。
- PersonaPack Manifest v2、严格完整性验证和分离式 Ed25519 签名。
- Scrypt + AES-256-GCM 私有 Persona 工程备份。
- Character Card V1/V2/V3、PNG Metadata 和 CHARX 兼容。
- OpenAI、OpenAI-compatible、Anthropic、Gemini 与 Ollama AI Studio。
- Adapter API 1.0 与第三方 Entry Point 插件。
- Linux x86_64/ARM64、macOS Intel/Apple Silicon、Windows x86_64 独立程序。

## 安装

PersonaDock 通过 GitHub Release 发布独立可执行文件，不要求预装 Python。

Linux / macOS：

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh | sh
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.ps1 | iex
```

安装固定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh \
  | sh -s -- --version v1.1.0
```

```powershell
$env:PERSONADOCK_VERSION = "v1.1.0"
irm https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.ps1 | iex
```

验证：

```bash
personadock --version
personadock doctor --json
personadock adapter list
```

安装脚本会下载对应平台资产和 `SHA256SUMS`，校验后再安装。

## 创建 Persona

安装统一的 `persona-builder` Skill：

```bash
personadock skill install --target codex --scope global
personadock skill install --target claude --scope global
personadock skill install --target opencode --scope global
```

该 Skill 自动选择：

| 模式 | 输入 |
|---|---|
| Create | 自然语言人格设计 |
| Distill | 用户明确选择的聊天记录 |
| Hybrid | 设计要求 + 聊天证据 |
| Refine | 修改已有 PersonaDock 工程 |

也可以直接创建 Canonical v3 工程：

```bash
personadock init ./xiaoyou --id xiaoyou --name 小柚
personadock validate ./xiaoyou
personadock test ./xiaoyou
```

工程中的 `.private/` 保存原始资料、证据和未审核候选，不进入默认 PersonaPack。

## 打包与信任

```bash
personadock build ./xiaoyou
personadock pack ./xiaoyou --output ./xiaoyou.personapack
personadock inspect ./xiaoyou.personapack
```

生成签名密钥并签名：

```bash
personadock trust keygen ~/.config/personadock/signing.pem
personadock trust sign ./xiaoyou.personapack \
  --key ~/.config/personadock/signing.pem
```

验证完整性、兼容性和可信 Key：

```bash
personadock trust verify ./xiaoyou.personapack \
  --signature ./xiaoyou.personapack.sig.json \
  --trusted-key ~/.config/personadock/signing.pem.pub \
  --json
```

签名中携带的公钥不会自动被信任，可信 Key 必须由用户显式提供。

## 部署到 Hermes

预览：

```bash
personadock deploy ./xiaoyou.personapack \
  --target hermes \
  --profile xiaoyou \
  --dry-run --json
```

应用：

```bash
personadock deploy ./xiaoyou.personapack \
  --target hermes \
  --profile xiaoyou \
  --activate \
  --yes
```

更新前会创建 Hermes 原生导出快照，失败时自动恢复。Memory、Sessions、`.env` 和认证不属于 Persona Definition 所有权。

Docker：

```bash
personadock deploy ./xiaoyou.personapack \
  --target hermes \
  --profile xiaoyou \
  --container hermes-agent \
  --yes
```

## 部署到 OpenClaw

更新已有 Agent：

```bash
personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --dry-run --json

personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --yes
```

创建新 Agent 必须提供绝对 Workspace：

```bash
personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --workspace ~/.openclaw/workspace-xiaoyou \
  --yes
```

PersonaDock 只管理 `SOUL.md`、`IDENTITY.md`、一个 Persona Skill 和所有权 Manifest。`AGENTS.md`、`USER.md`、`TOOLS.md`、Memory、Agent State、Auth 和 Sessions 保留。

Docker/SSH 示例见 [Docker 与远程运行时](docs/docker-install.md)。

## Memory 同步

```bash
personadock sync collect xiaoyou
personadock sync candidates xiaoyou --status pending
personadock sync review approve <memory-item-id> --reviewer user --scope shared
personadock sync plan xiaoyou
personadock sync apply xiaoyou --yes
```

默认规则：

- 自动批准关闭。
- 私密/受限内容不自动传播。
- 冲突不静默覆盖。
- 来源回声默认关闭。
- 已传播内容不重复写入同一目标。

## Session Summary

```bash
personadock session collect xiaoyou
personadock session list xiaoyou --status pending
personadock session review approve <summary-id> --scope shared
personadock session plan xiaoyou
personadock session apply xiaoyou --yes
```

原始 Session/Transcript 同步始终关闭。实验性预览默认关闭，并要求策略启用和单次 `--experimental` 确认；系统消息、工具调用、工具结果和内部推理被排除。

## 私有加密备份

```bash
export PERSONADOCK_BACKUP_PASSWORD='a-long-unique-password'
personadock backup create ./xiaoyou \
  --output ./xiaoyou-private.pdbackup

personadock backup restore \
  ./xiaoyou-private.pdbackup \
  ./xiaoyou-restored
```

备份使用 Scrypt + AES-256-GCM，只读取 Persona 工程，不扫描 Hermes/OpenClaw 运行时状态。签名私钥不会被自动加入备份。

## Character Card

```bash
personadock character-card import ./rin.json ./rin-persona --id rin

personadock character-card export ./rin-persona \
  --output ./rin-v3.json \
  --card-version 3

personadock character-card export ./rin-persona \
  --output ./rin.charx \
  --charx
```

未知 Extensions 会在私有导入记录中保存并在导出时恢复。Memory 和 Session 不进入 Character Card。

## Web 控制台

```bash
personadock serve
```

```text
http://127.0.0.1:8732/           Vue 3 主控制面
http://127.0.0.1:8732/vue        Vue 兼容别名
http://127.0.0.1:8732/legacy     旧界面兼容入口
```

主要 Vue 工作区使用 Hash Router，例如：

```text
http://127.0.0.1:8732/#/personas
http://127.0.0.1:8732/#/deployments
http://127.0.0.1:8732/#/memory
http://127.0.0.1:8732/#/sessions
http://127.0.0.1:8732/#/ai-studio
```

非 Loopback 绑定必须配置 Bearer Token。

## Adapter 插件

```bash
personadock adapter list --json
personadock adapter show hermes --json
```

第三方 Python 包可以注册：

```toml
[project.entry-points."personadock.adapters"]
my-runtime = "my_package.adapter:MyAdapter"
```

插件必须实现 Adapter API `1.x`。Major 不匹配时拒绝加载，单个插件失败不会影响内置 Adapter。

## 文档

完整导航：[docs/README.md](docs/README.md)

常用文档：

- [控制平面总览](docs/control-plane.md)
- [Vue 3 前端迁移](docs/VUE_FRONTEND_MIGRATION.md)
- [Canonical Persona v3](docs/canonical-persona-v3.md)
- [Registry 与运行实例发现](docs/registry-discovery.md)
- [Hermes 原生 Adapter](docs/hermes-native-adapter.md)
- [OpenClaw 原生 Adapter](docs/openclaw-native-adapter.md)
- [受控 Memory 同步](docs/governed-sync.md)
- [Reviewed Session Summaries](docs/session-summaries.md)
- [1.0 兼容承诺](docs/compatibility.md)
- [发布流程](docs/publishing.md)
- [迁移与回滚](docs/migration-and-rollback.md)
- [维护审计](docs/maintenance-audit.md)

## 发布验收矩阵

每个发布候选必须通过：

- Vue TypeScript、Vitest、Vite、Playwright 与 axe-core。
- 完整 pytest。
- Python 3.10–3.13 Contract Matrix。
- 真实 Docker Hermes/OpenClaw Contract。
- Linux x86_64 / ARM64。
- macOS Intel / Apple Silicon。
- Windows x86_64。
- 独立程序签名、备份、恢复、Character Card 和 Vue HTTP 工作流。
- Release 资产 SHA-256 汇总。

## License

MIT
