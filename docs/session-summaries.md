# Reviewed Session Summaries（Phase 7）

PersonaDock 的 Session Summary 是经过审核的会话交接记录，不是原始 Session、Transcript 或聊天记录的副本。

## 安全默认值

- 默认策略为 `review`。
- 自动批准默认关闭。
- 原始 Session 同步始终关闭。
- 实验性原始预览默认关闭。
- 系统消息、工具调用、工具结果和内部推理不进入摘要或预览。
- 预览内容经过脱敏和长度限制，且不写入 PersonaDock Registry。
- 只有 `approved + shared` 的摘要会传播到绑定运行时。
- 来源运行时默认不回写同一摘要。
- 已成功传播到目标的同一内容不会重复发送。

## 数据模型

每条 Session Summary 保存：

- 来源 Adapter 和 Runtime Instance。
- 平台 Session/Transcript ID 与标题。
- 开始和结束时间（平台提供时）。
- 摘要正文。
- Pending Tasks。
- Emotional Context。
- 敏感度和同步范围。
- 生成方式：`platform`、`deterministic` 或 `manual`。
- 审核状态、审核人和审核时间。
- 内容指纹与传播日志。

审核后的完整结构镜像到：

```text
memory/session-summaries.jsonl
```

其中 `shared` 摘要还会以 PersonaDock 所有权记录镜像到：

```text
memory/seed.jsonl
```

这样 Hermes/OpenClaw 可以复用现有的 Memory 快照、验证、索引和失败恢复链路。其他 Memory 记录不会被删除或改写。

## 来源

### Hermes

PersonaDock 优先读取 Hermes CLI 提供的 Session 摘要字段。没有平台摘要时，本机 Hermes 可以显式导出仅用户提示、脱敏后的 JSONL，再生成确定性草稿。

确定性草稿：

- 只使用用户消息。
- 不调用外部模型。
- 不包含系统消息、工具调用和工具结果。
- Pending Tasks 和 Emotional Context 仅从用户明确措辞中保守提取。
- 仍然进入人工审核队列。

Docker Hermes 如果没有平台摘要，不会自动导出完整会话生成草稿。

### OpenClaw

PersonaDock 读取 OpenClaw 已物化的 Transcript Summary。持久 Session 元数据和 Transcript 导出被视为不同数据源。

默认采集不会读取 Transcript 的完整消息事件。

### Manual

用户可以手动提供摘要、待办和情绪交接：

```bash
personadock session add xiaoyou \
  --title "部署交接" \
  --summary "Windows 构建已经通过，下一步检查发布资产。" \
  --task "检查 SHA256SUMS"
```

## CLI

查看策略：

```bash
personadock session policy show xiaoyou
```

采集绑定运行时的摘要：

```bash
personadock session collect xiaoyou
```

查看待审核项：

```bash
personadock session list xiaoyou --status pending
```

批准并允许共享：

```bash
personadock session review approve <summary-id> \
  --reviewer user \
  --scope shared
```

仅本地批准：

```bash
personadock session review approve <summary-id> \
  --scope local-only
```

拒绝：

```bash
personadock session review reject <summary-id> \
  --reason "包含不应跨运行时传播的上下文"
```

预览传播：

```bash
personadock session plan xiaoyou
```

显式应用：

```bash
personadock session apply xiaoyou --yes
```

## 策略

默认策略：

```yaml
schema_version: 1
mode: review
collect:
  enabled: true
  adapters: [hermes, openclaw]
  max_items_per_runtime: 20
auto_approve:
  enabled: false
  source_adapters: []
  generated_by: [platform, manual]
  max_sensitivity: internal
propagation:
  enabled: true
  reviewed_only: true
  echo_to_source: false
raw_preview:
  enabled: false
  redact: true
  max_messages: 50
  max_chars: 20000
```

启用自动批准必须同时：

1. 将 `mode` 设为 `automatic`。
2. 将 `auto_approve.enabled` 设为 `true`。
3. 明确允许来源 Adapter、生成方式和最高敏感度。

`private` 和 `restricted` 摘要不应在常规策略中自动批准。

## 实验性原始预览

原始预览不是同步功能，只用于单次检查平台导出的已过滤内容。它需要双重确认：

1. 策略中启用 `raw_preview.enabled`。
2. 每次命令显式传入 `--experimental`。

```bash
personadock session preview xiaoyou \
  <runtime-instance-id> \
  <session-or-transcript-id> \
  --experimental --json
```

预览结果：

- 只保留用户和助手消息。
- 排除系统、工具和内部推理角色。
- 应用 Secret 脱敏。
- 受消息数和字符数限制。
- 不写入 Session Summary 表、Memory 或 PersonaPack。

## Web

启动本地控制台：

```bash
personadock serve
```

打开：

```text
http://127.0.0.1:8732/sessions
```

Web 审核中心支持：

- 采集摘要。
- 添加手动摘要。
- 查看来源、敏感度、待办和情绪上下文。
- 批准为 shared 或 local-only。
- 拒绝摘要。
- 预览并应用传播计划。
- 双重确认的实验性原始预览。

## 明确不支持

Phase 7 不提供：

- 原始 Session 同步。
- Transcript 同步。
- 系统消息或工具记录传播。
- 后台定时采集。
- 未审核摘要的跨运行时传播。
- 云端会话存储服务。
