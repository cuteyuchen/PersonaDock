# Character Card 兼容性

PersonaDock 1.0 提供 Character Card 导入/导出 Adapter，用于迁移人格定义，不把 Character Card 当作 Memory、Session 或现实人物档案。

## 支持格式

导入：

- Character Card V1 JSON。
- Character Card V2 JSON。
- Character Card V3 JSON。
- PNG `chara` / `ccv3` 文本 Metadata。
- CHARX 根目录 `card.json`。

导出：

- Character Card V2 JSON。
- Character Card V3 JSON。
- Character Card V3 CHARX。

PersonaDock 当前不生成新的角色 PNG 图片；已有 PNG 可以导入 Metadata，再导出为 JSON 或 CHARX。

## 检查

```bash
personadock character-card inspect ./rin.json --json
personadock character-card inspect ./rin.png --json
personadock character-card inspect ./rin.charx --json
```

## 导入

```bash
personadock character-card import ./rin.json ./rin-persona \
  --id rin \
  --locale zh-CN
```

导入后运行：

```bash
personadock validate ./rin-persona
personadock test ./rin-persona
personadock build ./rin-persona
```

## 映射

| Character Card | Canonical Persona v3 |
|---|---|
| `name` | `name` |
| `description` | `identity.statement` 和 `summary` |
| `personality` | `identity.statement`、`identity.core_traits` |
| `scenario` | 中优先级导入场景 Behavior |
| `system_prompt` | `voice.style` 与 Character Card Reference |
| `post_history_instructions` | `voice.style` 与 Reference |
| `first_mes` | Character Card Reference |
| `mes_example` | Character Card Reference |
| `alternate_greetings` | Character Card Reference |
| `creator_notes` | Character Card Reference |
| `extensions` | `.private/imports/character-card.json` 原样保留 |

导入规则：

- 明确字段标记为 `reviewed-existing` 来源。
- 缺失字段不自动推断。
- 不从示例消息推断用户事实或共享经历。
- PersonaDock 自带的 Memory Honesty、关系和专业边界继续保留。
- 原卡完整 JSON 保存在 `.private/imports/`，不会进入默认 PersonaPack。

## 导出 V2

```bash
personadock character-card export ./rin-persona \
  --output ./rin-v2.json \
  --card-version 2
```

## 导出 V3 JSON

```bash
personadock character-card export ./rin-persona \
  --output ./rin-v3.json \
  --card-version 3
```

## 导出 CHARX

```bash
personadock character-card export ./rin-persona \
  --output ./rin.charx \
  --card-version 3 \
  --charx
```

## PersonaDock Extension

导出卡会加入：

```json
{
  "extensions": {
    "personadock": {
      "schema_version": 3,
      "persona_id": "rin",
      "persona_version": "0.1.0",
      "adapter_api": "1.x",
      "memory_included": false,
      "raw_sessions_included": false
    }
  }
}
```

未知第三方 Extension 会保留，并与 `personadock` Extension 合并。

## 隐私边界

Character Card 导出默认不包含：

- `memory/seed.jsonl`
- `.private/`
- Session Summary
- 原始聊天
- Runtime Credentials
- Hermes/OpenClaw State

需要完整私有迁移时使用加密 Private Backup，而不是 Character Card。
