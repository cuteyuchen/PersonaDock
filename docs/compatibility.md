# PersonaDock 1.0 兼容性承诺

PersonaDock 1.0 将 Canonical Persona、PersonaPack 和 Adapter API 视为公开兼容边界。Registry 数据库与平台运行时内部文件仍属于实现细节，但升级必须提供自动迁移和失败前停止。

## 版本策略

PersonaDock 应用遵循语义化版本：

- `1.x`：保持本页声明的公开兼容性。
- Minor 版本可以增加可选字段、能力和 Adapter。
- Patch 版本只修复兼容性、安全或实现问题。
- 移除字段、改变既有含义或拒绝旧 1.x 产物需要新的 Major 版本。

Persona 工程中的 `version` 是人格版本，与 PersonaDock 应用版本无关。新建人格仍可从 `0.1.0` 开始。

## Canonical Persona

### 写入

PersonaDock 1.0 默认写入：

```text
schema_version: 3
```

### 读取

PersonaDock 1.x 承诺：

- 读取 Schema v3。
- 读取 Schema v2 并提供显式迁移到 v3。
- 不静默把未知新 Schema 当成旧 Schema。
- 不把平台路径、认证、Session 或 State 写入 Canonical Persona。

Schema v3 的既有必填字段、来源类型、审核状态和行为规则语义在 1.x 中保持兼容。Minor 版本只能增加可选字段。

## PersonaPack

PersonaDock 1.0 默认写入 PersonaPack Manifest v2，并可读取 v1/v2。

Manifest v2 的稳定字段包括：

- `format`、`format_version`、`schema_version`
- `id`、`name`、`version`
- `targets`
- `files`
- `privacy`
- `compatibility`
- `trust`
- `ownership`

1.x 保证：

- 已声明文件必须通过 SHA-256 校验。
- 未在 Manifest 声明的额外归档成员会导致完整性失败。
- 不把运行时认证、原始 Session、Transcript 或 State 打入 PersonaPack。
- 未签名包可以做自洽完整性检查，但不能仅凭自洽哈希证明发布者身份。
- 分离式 Ed25519 签名覆盖完整的确定性 PersonaPack 字节。

## Adapter API

PersonaDock 1.0 Adapter API 版本为：

```text
1.0
```

插件 Entry Point Group：

```text
personadock.adapters
```

稳定公开类型：

- `PersonaAdapter`
- `AdapterCapabilities`
- `AdapterDoctorResult`
- `AdapterDescriptor`
- `ADAPTER_API_VERSION`
- `validate_adapter_contract()`
- `AdapterRegistry`

1.x 保证：

- `PersonaAdapter.capabilities`、`doctor()`、`plan_deployment()` 不移除。
- `AdapterDescriptor` 既有字段不移除或改变含义。
- 新能力只能以可选布尔字段或 Metadata 增加。
- 插件 API Major 不匹配时拒绝加载，不尝试猜测兼容性。
- 插件加载失败不会阻止内置 Hermes/OpenClaw Adapter 启动。

内置传输：

| Adapter | 传输 |
|---|---|
| Hermes | local、docker |
| OpenClaw | local、docker、ssh |
| Generic filesystem | local、docker |

## Registry

Registry Schema 是内部持久化格式。PersonaDock 1.0 当前使用 Schema v3，并自动从 v1/v2 原地迁移。

保证：

- 迁移在事务中执行。
- 旧 Persona、Runtime Instance、Binding、Snapshot 和 Journal 不删除。
- 发现比当前程序更新的 Registry Schema 时停止，而不是降级写入。
- 不支持用旧版 PersonaDock 打开已经升级的新 Registry；降级前应恢复私有备份。

## Web API

1.x 中 `/api/health` 的既有顶层安全标记保持兼容。新增 API 可以加入，但破坏性重命名需要 Major 版本。

Web 默认仅绑定 Loopback。非 Loopback 绑定必须配置 Bearer Token。

## Character Card

1.0 支持：

- Character Card V1/V2/V3 JSON 导入。
- 带 `chara` 或 `ccv3` Metadata 的 PNG 导入。
- CHARX 根目录 `card.json` 导入。
- V2/V3 JSON 导出。
- V3 CHARX 导出。

未知 `extensions` 会保存在私有导入记录中，并在导出时恢复。PersonaDock 不从缺失字段推断记忆、现实关系或用户事实。

## Session 与 Memory

兼容承诺不改变安全默认值：

- Memory 默认审核后同步。
- Session Summary 默认审核后传播。
- 原始 Session/Transcript 同步关闭。
- 实验性原始预览需要策略开启和单次确认。
- 系统消息、工具调用、工具结果与内部推理不传播。

## 兼容性检查

```bash
personadock --version
personadock adapter list
personadock trust verify ./persona.personapack
personadock doctor --json
```

Release 前必须通过：

- Python 3.10–3.13 Contract Matrix。
- Linux x86_64/ARM64。
- macOS Intel/Apple Silicon。
- Windows x86_64。
- 真实 Docker Adapter Contract。
- Golden Contract Tests。
- Release 资产校验和汇总。
