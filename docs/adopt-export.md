# 接管、快照与导出（Phase 2）

Phase 2 允许 PersonaDock 管理 Hermes 和 OpenClaw 中已经存在的人格。

## 1. 扫描现有实例

```bash
personadock discover
personadock instances --unmanaged
```

每个实例会显示稳定的 Registry ID：

```text
hermes    xiaoyou    unmanaged  小柚
  local://C:\Users\yuchen\AppData\Local\hermes\profiles\xiaoyou
  registry-id: 4e18...
```

## 2. 接管预览

```bash
personadock adopt \
  --instance 4e18... \
  --dry-run
```

预览包含：

- 来源平台和实例。
- 建议的 Persona ID。
- PersonaDock 工程目标目录。
- 将创建的只读快照。
- 检测到的 Skills。
- 选中的 Persona Skill。
- Memory 候选文档数量。
- Persona ID 冲突。

预览不会创建快照、工程或 Binding。

## 3. 接管人格

```bash
personadock adopt --instance 4e18...
```

自动化环境：

```bash
personadock adopt --instance 4e18... --yes
```

指定 ID、名称或目录：

```bash
personadock adopt \
  --instance 4e18... \
  --id xiaoyou \
  --name 小柚 \
  --destination D:\PersonaDock\personas\xiaoyou
```

接管顺序：

1. 保存平台人格文件的只读快照。
2. 创建 PersonaDock v2 草稿工程。
3. 保留原始 SOUL 和 Skill。
4. 选择一个明显的人格 Skill 作为规范 Skill。
5. 将其他 Skills 保存到 `.private/imported-skills/`。
6. 将现有 Memory 写入 `.private/memory-candidates.jsonl`。
7. Memory Candidate 默认 `reviewed=false`、`local-only`。
8. 创建 Persona Registry 记录和实例 Binding。
9. 将运行实例标记为已管理。

Canonical Persona v3 的结构化迁移属于 Phase 3；Phase 2 首先确保可逆接管和原始信息保留。

## 4. 快照

默认位置：

```text
~/.personadock/snapshots/<adapter>/<instance>/<timestamp-id>/
├── content/
└── snapshot-manifest.json
```

快照包含人格相关内容及 SHA-256：

Hermes：

- `SOUL.md`
- `config.yaml`
- `skills/`
- `memories/MEMORY.md`
- `memories/USER.md`

OpenClaw：

- `SOUL.md`
- `IDENTITY.md`
- `AGENTS.md`
- `USER.md`
- `TOOLS.md`
- `MEMORY.md`
- `skills/`
- `memory/`

永不包含：

- `.env`
- API Key 和 Token 文件
- Credentials/Auth
- Sessions
- Logs
- Cache/临时目录

这些文件在接管过程中也不会被修改。

## 5. 同名 Persona

PersonaDock 不会仅凭同名自动合并：

```text
persona ID already exists: xiaoyou
```

确认两个实例属于同一人格后，可以显式绑定：

```bash
personadock adopt \
  --instance <instance-id> \
  --id xiaoyou \
  --link-existing
```

`--link-existing` 不替换现有 Persona 定义，只创建快照、Memory Candidate 和 Binding。

## 6. 批量接管

接管全部未管理实例：

```bash
personadock adopt --all-unmanaged --dry-run
personadock adopt --all-unmanaged --yes
```

也可以重复指定实例：

```bash
personadock adopt \
  --instance <hermes-id> \
  --instance <openclaw-id> \
  --yes
```

发生 Persona ID 冲突时不会自动合并，需要分别确认。

## 7. 导出 PersonaPack

```bash
personadock export xiaoyou \
  --format personapack
```

指定路径：

```bash
personadock export xiaoyou \
  --format personapack \
  --output ./xiaoyou.personapack
```

## 8. 导出 Hermes Profile

```bash
personadock export xiaoyou \
  --format hermes-profile
```

输出 ZIP，包含：

- `SOUL.md`
- Persona Skill
- `distribution.yaml`

默认不包含 Memory、Sessions、`.env` 或认证文件。

## 9. 导出 OpenClaw Workspace Overlay

```bash
personadock export xiaoyou \
  --format openclaw-workspace
```

输出 ZIP，包含：

- `SOUL.md`
- Persona Skill
- `personadock-manifest.json`

默认不包含：

- `AGENTS.md`
- `USER.md`
- `TOOLS.md`
- Memory
- Sessions
- Credentials
- 平台专属 Skills

这些内容在后续部署时应保留。

## 10. 导出已审核 Memory

平台原生导出默认不包含 Memory。明确需要时：

```bash
personadock export xiaoyou \
  --format hermes-profile \
  --include-memory
```

未审核的 `.private/memory-candidates.jsonl` 永远不会进入导出包。

## 11. Web 控制台

```bash
personadock serve
```

Web 中可以：

- 一键扫描 Hermes/OpenClaw。
- 对未管理实例执行“快照并接管”。
- 查看接管预览并确认。
- 一键导出 PersonaPack。
- 一键导出 Hermes 原生包。
- 一键导出 OpenClaw Workspace Overlay。

远程模式下，导出下载同样要求 Bearer Token。
