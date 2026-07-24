# PersonaDock 1.0

**PersonaDock 是一个本地优先的 AI 人格控制平面。**

它使用 Canonical Persona v3 管理人格定义、Skill、已审核 Memory 和 Session Summary，并通过原生 Adapter 安全部署到 Hermes 与 OpenClaw。PersonaDock 不托管云端人格服务，不自动上传聊天，不把认证、原始 Session 或运行时 State 打进 PersonaPack。

## 1.0 能力

- Canonical Persona Schema v3。
- Persona Registry、Runtime Discovery、Binding、Snapshot 和 Journal。
- Hermes 原生 Profile Distribution：Plan、Apply、Verify、Snapshot、Rollback。
- OpenClaw 原生 Agent/Workspace Overlay：本机、Docker、SSH。
- Review-first 跨运行时 Memory 同步。
- Reviewed Session Summary 交接；原始 Session 同步关闭。
- PersonaPack Manifest v2、确定性归档和分离式 Ed25519 签名。
- Scrypt + AES-256-GCM 私有工程备份。
- Character Card V1/V2/V3、PNG Metadata 和 CHARX 兼容。
- 稳定 Adapter API `1.0` 和第三方 Entry Point 插件机制。
- 本地 Web 控制台。
- Linux x86_64/ARM64、macOS Intel/Apple Silicon、Windows x86_64 独立程序。

## 安装

PersonaDock 通过 GitHub Release 发布独立可执行文件，不要求用户预装 Python。

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh | sh
```

安装固定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh \
  | sh -s -- --version v1.0.0
```

默认路径：

```text
~/.local/bin/personadock
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.ps1 | iex
```

安装固定版本：

```powershell
$env:PERSONADOCK_VERSION = "v1.0.0"
irm https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.ps1 | iex
```

默认路径：

```text
%LOCALAPPDATA%\Programs\PersonaDock\personadock.exe
```

### 验证

```bash
personadock --version
personadock doctor --json
personadock adapter list
```

安装脚本会下载对应平台资产和 `SHA256SUMS`，验证哈希后再安装。

## 创建 Persona

安装统一的 `persona-builder` Skill：

```bash
personadock skill install --target codex --scope global
personadock skill install --target claude --scope global
personadock skill install --target opencode --scope global
```

该 Skill 自动选择内部模式：

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

工程结构：

```text
xiaoyou/
├── companion.yaml
├── skills/persona/
├── memory/
│   ├── seed.jsonl
│   ├── session-summaries.jsonl
│   └── policy.yaml
├── tests/scenarios.yaml
└── .private/
```

`.private/` 保存原始资料、证据和未审核候选，不进入默认 PersonaPack。

## 打包 PersonaPack

```bash
personadock build ./xiaoyou
personadock pack ./xiaoyou --output ./xiaoyou.personapack
personadock inspect ./xiaoyou.personapack
```

PersonaPack 只包含 Adapter 所有权定义文件和已审核的允许内容，不包含运行时认证、原始 Session、Transcript 或 State。

## PersonaPack 签名

生成 Ed25519 Key：

```bash
personadock trust keygen ~/.config/personadock/signing.pem
```

签名：

```bash
personadock trust sign ./xiaoyou.personapack \
  --key ~/.config/personadock/signing.pem
```

验证完整性和可信 Key：

```bash
personadock trust verify ./xiaoyou.personapack \
  --signature ./xiaoyou.personapack.sig.json \
  --trusted-key ~/.config/personadock/signing.pem.pub \
  --json
```

签名文件中携带的公钥不会自动被信任；可信 Key 必须由用户显式提供。

## 部署到 Hermes

先预览：

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

更新既有 Profile 前会创建 Hermes 原生导出快照；失败时自动恢复。Memory、Sessions、`.env` 和认证不属于 Persona Definition 所有权。

## 部署到 OpenClaw

预览既有 Agent：

```bash
personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --dry-run --json
```

创建新 Agent 需要显式 Workspace：

```bash
personadock deploy ./xiaoyou.personapack \
  --target openclaw \
  --agent xiaoyou \
  --workspace ~/.openclaw/workspace-xiaoyou \
  --yes
```

PersonaDock 只管理 `SOUL.md`、`IDENTITY.md`、一个 Persona Skill 和所有权 Manifest。`AGENTS.md`、`USER.md`、`TOOLS.md`、Memory、Agent State、Auth 和 Sessions 保留。

## Memory 同步

```bash
personadock sync collect xiaoyou
personadock sync candidates xiaoyou --status pending
personadock sync plan xiaoyou
```

批准后应用：

```bash
personadock sync review approve <memory-item-id> --reviewer user
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
```

恢复：

```bash
personadock backup restore ./xiaoyou-private.pdbackup ./xiaoyou-restored
```

私有备份包含 Persona 工程和 `.private/`，使用 Scrypt + AES-256-GCM；它只读取 Persona 工程，不扫描 Hermes/OpenClaw 运行时状态。

## Character Card

导入 V2/V3 JSON、PNG Metadata 或 CHARX：

```bash
personadock character-card import ./rin.json ./rin-persona --id rin
```

导出 V3 JSON：

```bash
personadock character-card export ./rin-persona \
  --output ./rin-v3.json \
  --card-version 3
```

导出 CHARX：

```bash
personadock character-card export ./rin-persona \
  --output ./rin.charx \
  --charx
```

未知 Character Card Extensions 会保存在私有导入记录中并在导出时恢复。Memory 和 Session 不进入 Character Card。

## Web 控制台

```bash
personadock serve
```

默认页面：

```text
http://127.0.0.1:8732/
http://127.0.0.1:8732/canonical
http://127.0.0.1:8732/hermes
http://127.0.0.1:8732/openclaw
http://127.0.0.1:8732/sync
http://127.0.0.1:8732/sessions
```

非 Loopback 绑定必须配置 Bearer Token。

## Adapter 插件

查看稳定 API：

```bash
personadock adapter list --json
personadock adapter show hermes --json
```

第三方 Python 包可以注册：

```toml
[project.entry-points."personadock.adapters"]
my-runtime = "my_package.adapter:MyAdapter"
```

插件必须实现 `PersonaAdapter` API `1.x`。Major 不匹配时拒绝加载，插件失败不会影响内置 Adapter。

## 文档

- [Canonical Persona v3](docs/canonical-persona-v3.md)
- [Hermes 原生 Adapter](docs/hermes-native-adapter.md)
- [OpenClaw 原生 Adapter](docs/openclaw-native-adapter.md)
- [受控 Memory 同步](docs/governed-memory-sync.md)
- [Session Summary](docs/session-summaries.md)
- [1.0 兼容承诺](docs/compatibility.md)
- [信任与私有备份](docs/trust-and-private-backup.md)
- [Character Card 兼容](docs/character-card-compatibility.md)
- [OpenPersona 研究](docs/openpersona-compatibility.md)
- [迁移与回滚](docs/migration-and-rollback.md)

## 1.0 验收矩阵

每个发布候选必须通过：

- 完整 pytest。
- Python 3.10–3.13 Contract Matrix。
- 真实 Docker Hermes/OpenClaw Contract。
- Linux x86_64 / ARM64。
- macOS Intel / Apple Silicon。
- Windows x86_64。
- 独立程序真实签名、备份、恢复和 Character Card 工作流。
- Release 资产 SHA-256 汇总。

## License

MIT
