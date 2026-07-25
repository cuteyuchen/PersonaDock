# 会话摘要与跨运行时交接（Phase 7）

PersonaDock 不会在 Hermes 与 OpenClaw 之间复制原始 Session。Phase 7 只同步经过脱敏、过滤和审核的摘要：

```text
原生只读导出 / 本地 JSONL
  → 临时解析
  → 排除 system / tool 消息
  → Token 与密钥脱敏
  → 摘要、决策、待办、可选情绪上下文
  → 用户审核
  → session-summary Memory
  → Phase 6 受控传播
```

原始导出文件不会复制到 `~/.personadock`，Registry 只保存来源 Session ID、内容哈希、消息数量和摘要。

## 默认策略

```yaml
session_summaries:
  mode: review
  source_adapters: [hermes, openclaw]
  auto_approve: false
  max_sensitivity: internal
  max_turns: 20
  include_pending_tasks: true
  include_decisions: true
  include_emotional_context: false
  raw_session_import: preview-only
  include_system_messages: false
  include_tool_messages: false
```

系统消息与工具消息在 Phase 7 中不能开启。原始 Session 只能预览或生成摘要，不能作为跨平台同步对象。

## 本地文件预览

```bash
personadock sessions preview ./session.jsonl --json
```

指定某个 Session：

```bash
personadock sessions preview ./backup.jsonl \
  --session-id 20260724_120000_abcd12
```

预览结果包含脱敏后的用户/助手消息和候选摘要，但不写入 Registry。

## 导入审核队列

```bash
personadock sessions import xiaoyou ./session.jsonl \
  --source-adapter file
```

本地文件导入是用户显式操作。平台来源应优先使用绑定实例的原生命令。

## Hermes 原生收集

Hermes 使用：

```text
hermes sessions export <temporary.jsonl> --session-id <ID>
```

PersonaDock 命令：

```bash
personadock sessions collect xiaoyou \
  --instance <runtime-instance-id> \
  --session-id <Hermes-session-id>
```

Docker 中的临时导出会通过 `docker cp` 读取，然后立即删除容器内与宿主机临时文件。

## OpenClaw 原生收集

OpenClaw 使用：

```text
openclaw sessions export-trajectory \
  --session-key <KEY> \
  --output <temporary-path> \
  --json
```

PersonaDock 命令与 Hermes 相同，`--session-id` 参数填写 OpenClaw Session Key。支持本机、Docker 和 SSH Transport。

## 审核

```bash
personadock sessions list xiaoyou --status pending

personadock sessions review approve <summary-id> \
  --reviewer thomas \
  --scope shared

personadock sessions review reject <summary-id> \
  --reason "不应跨运行时传播"
```

批准后，摘要转换为 `session-summary` Memory，并保留：

- 来源 Adapter 与 Runtime Instance。
- 来源 Session ID 与标题。
- Transcript Hash 与 Summary Hash。
- 决策与待办。
- 敏感度与审核者。

随后使用现有同步预览和应用：

```bash
personadock sync plan xiaoyou
personadock sync apply xiaoyou --yes
```

默认关闭来源回声，因此 Hermes 产生的摘要不会立刻写回同一个 Hermes Profile，只传播到其他绑定实例。

## 情绪上下文

默认不提取情绪上下文。启用后只记录粗粒度标签，例如 `anxious`、`tired`，不保存心理诊断或模型推断。可通过 SyncPolicy 显式启用：

```yaml
session_summaries:
  include_emotional_context: true
```

## 自动批准

只有同时满足以下条件才自动批准：

- `session_summaries.mode: automatic`
- `session_summaries.auto_approve: true`
- 来源在白名单中
- 敏感度不高于 `max_sensitivity`

默认仍为人工审核。包含密钥、Token、PII、医疗或金融信息的来源会提高敏感度，不能通过默认自动批准阈值。

## Web 控制台

```bash
personadock serve
```

打开：

```text
http://127.0.0.1:8732/sessions
```

支持：

- 选择 Persona。
- 选择绑定的 Hermes/OpenClaw 实例。
- 输入 Session ID/Key 并只读收集。
- 预览本地 JSON/JSONL。
- 查看决策和待办。
- 批准为共享或仅本地摘要。
- 拒绝候选。

## 明确不支持

```text
原始 Session 双向同步
系统消息同步
工具调用与工具结果同步
思维链或内部推理同步
认证、Token、附件内容同步
后台自动读取所有历史 Session
```

完整 Session 仅作为显式、临时、只读输入；PersonaDock 的持久化与传播单位始终是经过治理的摘要。
