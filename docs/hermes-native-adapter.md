# Hermes 原生 Profile Adapter（Phase 4）

PersonaDock 通过 Hermes CLI 的 Profile Distribution 能力部署人格，不再推测或直接写入 Hermes 内部目录。

## 前置要求

- Hermes CLI 可执行。
- Hermes 版本支持 Profile Distribution，建议 `>=0.12.0`。
- PersonaDock PersonaPack 中包含 Hermes Target。

检查：

```bash
personadock hermes doctor
personadock hermes profiles
```

Docker 中的 Hermes：

```bash
personadock hermes doctor --container hermes-agent
personadock hermes profiles --container hermes-agent
```

## 部署

预览新 Profile：

```bash
personadock deploy ./dist/xiaoyou-0.1.0.personapack \
  --target hermes \
  --profile xiaoyou \
  --dry-run
```

部署并激活：

```bash
personadock deploy ./dist/xiaoyou-0.1.0.personapack \
  --target hermes \
  --profile xiaoyou \
  --activate \
  --yes
```

创建 Hermes 命令 Alias：

```bash
personadock deploy ./dist/xiaoyou-0.1.0.personapack \
  --target hermes \
  --profile xiaoyou \
  --alias \
  --yes
```

Docker：

```bash
personadock deploy ./dist/xiaoyou-0.1.0.personapack \
  --target hermes \
  --profile xiaoyou \
  --container hermes-agent \
  --yes
```

PersonaDock 会将本地 Distribution 临时复制到容器，由容器内的 `hermes profile install` 完成部署。

## 默认 Profile 保护

不指定 `--profile` 时使用 Persona ID 作为 Profile 名称。

Persona ID 为 `default` 时不会隐式部署到 Hermes 默认 Profile。必须明确指定：

```bash
personadock deploy ./default-0.1.0.personapack \
  --target hermes \
  --profile default \
  --yes
```

该操作仍会在计划和 Web 页面中显示显著警告。

## Distribution 内容

PersonaDock 生成的 Hermes Distribution 只包含：

```text
SOUL.md
skills/
distribution.yaml
personadock-manifest.json
```

不会包含：

```text
.env
auth.json
memories/
sessions/
state.db*
logs/
workspace/
plans/
home/
*_cache/
local/
```

`distribution_owned` 也只声明 PersonaDock 生成的文件，因此 Hermes 更新时会保留用户和平台本地内容。

## 更新与快照

Profile 已存在时，流程为：

1. `hermes profile export <profile> -o <snapshot>`。
2. 验证快照文件存在且非空。
3. `hermes profile install <distribution> --name <profile> --force --yes`。
4. 可选执行 `hermes profile use <profile>`。
5. 使用 `profile show` 和 `profile info` 验证。
6. 写入 Registry Binding、部署版本和 Journal。

安装或验证失败时，PersonaDock 删除失败版本并从导出快照恢复。

## 回滚

从快照恢复：

```bash
personadock hermes rollback \
  --profile xiaoyou \
  --snapshot ~/.personadock/snapshots/hermes/xiaoyou/...tar.gz
```

恢复后激活：

```bash
personadock hermes rollback \
  --profile xiaoyou \
  --snapshot ~/.personadock/snapshots/hermes/xiaoyou/...tar.gz \
  --activate
```

不提供快照时，只删除指定 Profile：

```bash
personadock hermes rollback --profile xiaoyou
```

## Memory Candidate Pull

```bash
personadock hermes memory pull xiaoyou --profile xiaoyou
```

PersonaDock 读取 Hermes CLI 报告的 Profile 路径，然后检查：

```text
memories/MEMORY.md
memories/USER.md
```

结果写入：

```text
<persona>/.private/memory-candidates.jsonl
```

候选项始终为：

```yaml
reviewed: false
sensitivity: private
sync_scope: local-only
status: pending
```

重复 Pull 不会重复加入内容相同的候选项。

## 已审核 Memory Push

```bash
personadock hermes memory push xiaoyou \
  --profile xiaoyou \
  --yes
```

只推送：

- `memory/profile.yaml` 中的规范化条目。
- `memory/seed.jsonl` 中 `reviewed: true` 的条目。

PersonaDock 只维护以下区块：

```text
<!-- personadock-shared-memory:start -->
...
<!-- personadock-shared-memory:end -->
```

Hermes 原有记忆内容不会被删除。写入前创建备份，验证失败时恢复原文件。

## Web

启动：

```bash
personadock serve
```

打开：

```text
http://127.0.0.1:8732/hermes
```

页面支持：

- Hermes Doctor。
- Profile 枚举和激活状态。
- 原生部署计划。
- 安装、更新和激活。
- 快照回滚。
- Memory Candidate Pull。
- 已审核共享 Memory Push。
- 本地与 Docker 容器切换。

## 旧文件系统模式

旧模式只作为明确的兼容入口保留：

```bash
personadock deploy package.personapack \
  --target hermes \
  --legacy-filesystem \
  --path /explicit/path \
  --yes
```

没有 `--legacy-filesystem` 时，Hermes 部署默认使用原生 Profile Distribution。
