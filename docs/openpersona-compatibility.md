# OpenPersona 兼容性研究

本页记录 PersonaDock 1.0 对 OpenPersona 的兼容性研究结论。当前阶段不声称完整实现 OpenPersona 导入/导出。

## 结论

OpenPersona 和 PersonaDock 都把人格定义与运行时实现分离，但抽象层级不同：

- PersonaDock：Canonical Persona、Behavior、Boundary、Skill、Reviewed Memory、Runtime Binding。
- OpenPersona：Soul、Body、Faculty、Skill，以及运行时或演化相关状态。

可以稳定映射人格定义和 Skill，但不能在不丢失语义的情况下自动映射所有 Body、Faculty、Evolution 或运行时状态。

## 可映射部分

| OpenPersona 概念 | PersonaDock |
|---|---|
| Soul Identity | `identity.statement` |
| Soul Traits | `identity.core_traits` |
| Soul Expression | `voice` |
| Soul Rules/Constraints | `boundaries`、`behaviors` |
| Skill Pack | `skills/persona/` 或额外 Skills |
| Persona Metadata | `id`、`name`、`version`、`summary` |
| Static examples | Skill References |

导入这些内容时应标记为 `reviewed-existing`，保留原始文件和来源，而不是声称内容已经由用户重新审核。

## 不能自动等价映射

### Body

OpenPersona Body 可能描述外观、媒介或具身属性。PersonaDock Canonical Persona 没有通用 Body 模型。

建议：

- 静态描述保存到 Skill Reference。
- 不把外观描述自动转换成行为规则。
- 平台专属呈现由未来 Display/Avatar Adapter 负责。

### Faculty

Faculty 可能代表能力、工具或认知模块。PersonaDock 的 Skill 与平台工具配置并不等价。

建议：

- 文本型能力说明可以进入 Skill。
- 需要权限、凭据或工具调用的 Faculty 必须由目标平台配置。
- 不导入认证、Token 或外部服务 Secret。

### Evolution / Runtime State

演化状态、会话状态、运行历史和运行时 Memory 不能直接写入 Canonical Persona。

建议：

- 稳定、可审核事实进入 Memory Candidate。
- 会话交接进入 Session Summary Review。
- 原始状态只做私有备份或平台原生快照。
- 未审核状态不跨运行时传播。

## PersonaPack 与 OpenPersona 包

PersonaPack Manifest v2 可以在未来增加一个可选兼容块：

```json
{
  "compatibility": {
    "openpersona": {
      "profile": "definition-only",
      "lossy_fields": ["body", "faculty-runtime", "evolution-state"]
    }
  }
}
```

PersonaDock 1.0 不写入该块，也不把 OpenPersona 包伪装成 PersonaPack。

## 推荐导入流程

1. 只读检查 OpenPersona Metadata 和目录结构。
2. 展示可映射和不可映射字段。
3. 把原始包保存到 `.private/imports/openpersona/`。
4. 创建 Canonical Persona v3 草稿。
5. 将 Soul/Skill 标记为 `reviewed-existing`。
6. 将潜在事实放入 Memory Candidate，而不是直接批准。
7. 运行 `validate`、`test` 和语义 Diff。
8. 用户确认后再部署到 Hermes/OpenClaw。

## 暂不实现的原因

PersonaDock 1.0 不提供自动 OpenPersona 导入命令，原因是：

- 公开实现仍在演进。
- Body/Faculty 的语义不够稳定，容易产生看似成功但实际丢失含义的转换。
- Evolution 和运行时状态涉及隐私、来源和冲突模型。
- Character Card 已覆盖当前更成熟的跨工具静态人格交换需求。

未来实现前必须增加：

- 固定版本 Fixture。
- 字段级兼容矩阵。
- Loss Report。
- Round-trip Golden Test。
- Secret/Runtime State 排除测试。
