# PersonaDock 1.0 迁移与回滚手册

本手册覆盖应用升级、Canonical Persona 迁移、Registry 迁移、Hermes/OpenClaw 部署回滚、Memory/Session Summary 回滚和降级准备。

## 升级前检查

```bash
personadock --version
personadock doctor --json
personadock persona list --json
personadock instances --json
```

对每个重要 Persona：

```bash
personadock validate ./persona
personadock test ./persona
personadock backup create ./persona \
  --output ./backups/persona-before-upgrade.pdbackup
```

同时保留：

- PersonaPack。
- 签名文件和 Public Key。
- Hermes Profile Export Snapshot。
- OpenClaw Workspace Snapshot。
- `~/.personadock/personadock.db` 的文件级副本。

数据库副本应在 PersonaDock 停止写入时创建。

## 应用升级到 1.0

安装最新版独立程序：

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh | sh
```

Windows：

```powershell
irm https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.ps1 | iex
```

验证：

```bash
personadock --version
personadock adapter list
personadock doctor --json
```

首次启动会把 Registry v1/v2 自动迁移到 v3。发现更高版本 Schema 时会停止。

## Canonical Persona v2 → v3

保留旧工程，输出新目录：

```bash
personadock migrate ./persona-v2 --output ./persona-v3
```

验证：

```bash
personadock validate ./persona-v3
personadock test ./persona-v3
personadock diff ./persona-v2 ./persona-v3
```

原地迁移：

```bash
personadock migrate ./persona --in-place
```

默认备份位置：

```text
<project>/.personadock/migrations/schema-v2-<timestamp>/
```

不建议使用 `--no-backup`。

## Registry 迁移

Registry v3 增加：

- Sync Policy 和 Memory Review。
- Conflict、Sync Run、Propagation Log。
- Session Summary Policy、Review 和 Propagation。

迁移原则：

- 事务执行。
- 旧表和记录保留。
- 不修改 Hermes/OpenClaw 文件。
- 不自动批准 Memory 或 Session Summary。

迁移后检查：

```bash
personadock persona list --json
personadock instances --json
personadock sync status <persona-id> --json
personadock session status <persona-id> --json
```

## Hermes 更新与回滚

部署前预览：

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --profile xiaoyou \
  --dry-run --json
```

部署：

```bash
personadock deploy ./persona.personapack \
  --target hermes \
  --profile xiaoyou \
  --yes
```

PersonaDock 在更新既有 Profile 前通过 Hermes 原生命令创建完整导出快照。验证失败时自动恢复。

显式回滚：

```bash
personadock hermes rollback <snapshot-path> \
  --profile xiaoyou
```

Hermes 回滚不应覆盖：

- `.env`
- Auth
- Memories
- Sessions
- 平台 Local State

## OpenClaw 更新与回滚

部署前预览：

```bash
personadock deploy ./persona.personapack \
  --target openclaw \
  --agent xiaoyou \
  --dry-run --json
```

既有 Workspace 中未被 PersonaDock 管理的 `SOUL.md`、`IDENTITY.md` 或 Persona Skill 不会静默覆盖。接管需要：

```bash
personadock deploy ./persona.personapack \
  --target openclaw \
  --agent xiaoyou \
  --take-ownership \
  --yes
```

显式恢复 Workspace Snapshot：

```bash
personadock openclaw rollback <snapshot-path> \
  --agent xiaoyou
```

新建 Agent 部署失败时，PersonaDock 删除本次新建 Agent。保留的主 Agent `main` 不会隐式删除。

OpenClaw 回滚不应修改：

- `agentDir`
- Auth Profile / OAuth Token
- Sessions / Transcript
- Routing
- 平台索引之外的 State
- 非 PersonaDock Skills

## Memory 同步回滚

Memory Push 前，Hermes/OpenClaw Adapter 都创建目标文件备份。写入或索引失败时恢复原内容。

人工处理错误 Memory：

1. 在 Sync Review 中拒绝或 Supersede 记录。
2. 修改 Canonical `memory/seed.jsonl`。
3. 运行：

```bash
personadock sync plan <persona-id>
personadock sync apply <persona-id> --yes
```

不要直接删除 Propagation Log 来强制重发；应改变记录内容或明确创建新的审核项。

## Session Summary 回滚

Session Summary 与原始 Session 分离。撤销错误摘要：

1. 将摘要拒绝或标记 Superseded。
2. 确认 `memory/session-summaries.jsonl`。
3. 确认 PersonaDock 所有权 Handoff 已从 `memory/seed.jsonl` 移除。
4. 重新运行摘要传播。

原始 Session 和 Transcript 从未被 PersonaDock 同步，因此不属于摘要回滚范围。

## Character Card 迁移回滚

导入前原卡不会被修改。原始字段保存在：

```text
.private/imports/character-card.json
```

放弃导入时删除新建 Persona 工程即可。导出的 Card 不包含 Memory/Session，可安全与私有工程分开管理。

## 降级到旧版 PersonaDock

不建议用旧版本直接打开已经升级到 Registry v3 的状态目录。

安全降级：

1. 停止当前 PersonaDock。
2. 保存当前 Registry 和 Persona 私有备份。
3. 恢复升级前的 `~/.personadock` 副本。
4. 恢复旧版独立程序。
5. 恢复旧版可读取的 Persona 工程或 PersonaPack。
6. 运行旧版 Doctor 和只读检查。

不要手工把 Registry Schema 版本数字改小。

## 灾难恢复顺序

1. 恢复 Persona 私有加密备份。
2. 验证 Canonical Project。
3. 恢复或重新注册 Registry Persona。
4. 只读发现 Runtime Instances。
5. 恢复 Binding。
6. 预览 Definition Deployment。
7. 部署 Definition。
8. 审核并恢复 Memory。
9. 审核并恢复 Session Summary Handoff。
10. 最后检查平台原生 Session 和认证仍存在。

## 验收清单

- [ ] `personadock validate` 成功。
- [ ] `personadock test` 成功。
- [ ] PersonaPack `trust verify` 成功。
- [ ] Hermes/OpenClaw Plan 只修改 PersonaDock 所有权文件。
- [ ] 更新前 Snapshot 存在。
- [ ] Memory、Session、Auth 和 State 未被 Persona Definition 覆盖。
- [ ] 错误密码或修改后的 Backup 无法恢复。
- [ ] 降级演练使用升级前 Registry 副本，而不是修改 Schema 数字。
