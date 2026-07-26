# PersonaDock Web Control Plane 2.0

状态：功能实现完成，进入持续维护  
执行方式：全部直接提交到 `main`，每阶段通过主分支 bundle 后进入下一阶段。  
控制面版本：Web Control Plane 2，Refactor Phase 8

## 实施结果

| 阶段 | 状态 | 主要结果 |
|---|---|---|
| Phase 0 | 已完成 | 路线、Capability、Job、Revision、AI 与安全契约 |
| Phase 1 | 已完成 | 统一 Web Shell、`/api/v1`、Capability Registry、持久化 Job/SSE、嵌入式资源 |
| Phase 2 | 已完成 | Persona 创建/注册、Discovery、Adoption、导出与共用应用服务 |
| Phase 3 | 已完成 | Canonical 编辑、内容寻址 Revision、语义 Diff、测试、迁移与编译预览 |
| Phase 4 | 已完成 | Build、PersonaPack、签名、加密备份、Character Card、Adapter 与 Skill |
| Phase 5 | 已完成 | Hermes/OpenClaw 原生部署 Plan/Apply/Verify/Rollback 与部署历史 |
| Phase 6 | 已完成 | Memory/Session Policy、Collect、Review、Conflict、Plan、Apply 与任务记录 |
| Phase 7 | 已完成 | 加密 Provider Secret、Create/Distill/Hybrid/Refine、Diff、测试与 Revision 应用 |
| Phase 8 | 已完成 | CLI/Web parity、安全中间件、请求限制、最终测试与独立程序验收 |

旧 `/canonical`、`/hermes`、`/openclaw`、`/sync` 和 `/sessions` 页面继续作为 1.x 兼容入口。新工作台不通过 Shell 调用 CLI；Web 和 CLI 复用 Persona、Revision、Artifact、Deployment、Adapter 和治理引擎。

## 产品边界

PersonaDock Web 2.0 是本地优先的人格控制平面，不是云端人格托管服务，也不是 CLI 输出查看器。

用户可以不打开终端完成：

```text
配置大模型
→ 创建、注册、导入或接管 Persona
→ AI 生成或优化草稿
→ 审核 Canonical、Diff、测试和编译结果
→ 创建 Revision
→ 构建、打包、签名和备份
→ 扫描 Hermes/OpenClaw Runtime
→ 审核部署计划并部署或回滚
→ 审核 Memory 与 Session Summary
```

始终保持：

- Persona 工程是真实来源。
- AI 只产生候选草稿，不自动覆盖、部署或同步。
- 原始 Session/Transcript 双向同步关闭。
- 写操作可审核、可记录、可恢复。
- API Key、签名私钥和备份密码不进入浏览器状态或普通数据库。

## 前端设计

当前实现采用随 Python 包和独立程序分发的模块化前端，无公网 CDN 和运行时 Node.js 依赖。

视觉原则：

- 偏桌面管理工具，而不是聊天机器人。
- 深色窄侧栏、暖色浅工作区、低圆角。
- 表格、窄表单、Diff 和日志优先。
- 不使用渐变、发光、紫色 AI 模板和大面积营销卡片。
- AI 页面使用“任务参数 → 审查结果 → 明确应用”，不使用聊天气泡。

原路线曾考虑 Vue 3 + TypeScript 和 Playwright。为保持独立程序资源简单、避免引入第二套发布工具链，本轮使用模块化原生前端和 pytest/ASGI/静态契约集成测试完成验收。未来迁移前端工具链时，必须保持现有 `/api/v1`、路由和 Capability 契约。

## 架构

```text
CLI ──────────────┐
Web API ──────────┼→ Application Services → Registry / Domain / Adapter
Job Center ───────┘                         → Hermes / OpenClaw
```

主要服务：

- `PersonaApplicationService`
- `RevisionStore`
- `ArtifactApplicationService`
- `DeploymentApplicationService`
- `SyncEngine`
- `SessionSummaryEngine`
- `AIPersonaStudio`
- `ProviderStore` / `SecretVault`
- `JobStore`

## 页面与能力

### 概览、Persona 与 Revision

- Persona 列表、详情、新建和注册。
- Runtime Discovery 与 Adoption。
- 结构化编辑、JSON 编辑与编译预览。
- 每次保存创建内容寻址 Revision。
- 任意 Revision 语义 Diff、风险提示和恢复计划。
- Validate、Scenario Test 和 Canonical v3 Migration。

### Package、信任与备份

- Generic、Hermes、OpenClaw Build。
- PersonaPack Create/Inspect/Public Export。
- Ed25519 Keygen、Sign、Verify。
- Scrypt + AES-256-GCM 私有备份 Create/Inspect/Restore。
- Character Card V1/V2/V3、PNG 和 CHARX。
- Adapter List/Show/Doctor 与 persona-builder Skill 安装。

### 原生部署

部署页分别调用 Hermes Profile Distribution 与 OpenClaw Agent/Workspace 引擎，不把它们降级成通用文件复制。

流程：

```text
选择 Persona 或 PersonaPack
→ 读取 Runtime
→ 生成计划
→ 显示命令、所有权冲突、保留项和快照
→ 用户确认
→ 重新生成并比较计划哈希
→ Apply
→ 原生 Verify
→ 记录或回滚
```

一次性确认令牌只返回当前页面，数据库仅保存令牌 SHA-256。Runtime、Workspace、所有权或包摘要变化后，旧计划失效。

### Memory 与 Session Summary

- Policy 编辑与验证。
- 从绑定 Runtime Collect。
- Pending/Approved/Rejected 队列。
- Memory 冲突左右对比和显式解决。
- Plan 和确认后 Apply。
- Session 手动摘要。
- 实验性原始 Session 预览需要策略启用和单次 `PREVIEW` 确认，不写入 Registry。

Collect 和 Apply 进入 Job Store；Job 输入不保存原始 Session、摘要正文或聊天证据。

### AI 人格工作室

Provider：

- OpenAI
- OpenAI-compatible
- Anthropic
- Gemini
- Ollama

模式：

- Create
- Distill
- Hybrid
- Refine

固定流程：

```text
输入
→ Provider 结构化生成
→ Canonical v3 合并与正规化
→ Schema/项目校验
→ Scenario Test
→ Hermes/OpenClaw/Generic 编译预览
→ 语义 Diff 与风险级别
→ 用户输入 APPLY
→ 创建或更新 Revision
```

原始设计描述和聊天证据不写入 Job 或 Generation 数据库，只保存输入哈希、Canonical 草稿、评估结果、Provider/Model 和 Token 使用信息。

## Secret Vault

Provider 元数据保存在 `control-plane.db`，只包含 `secret_ref`。API Key 和自定义敏感 Header 整体保存在本地 AES-256-GCM Vault：

```text
~/.personadock/secrets/master.key
~/.personadock/secrets/vault.json
```

- 主密钥和密文分离。
- 文件尽可能设置为 `0600`。
- Provider API 只返回 `secret_configured`。
- 删除 Provider 时同时删除对应 Secret。
- Gemini API Key 通过 Header 发送，不拼进 URL。

## Capability 一致性

`web/parity.py` 直接解析完整 `stable_cli` 顶层命令，并要求每个命令映射到一个或多个现有 Web Capability。新增 CLI 顶层命令但未更新 Web 映射时，CI 会失败。

接口：

```text
GET /api/v1/capabilities
GET /api/v1/parity
GET /api/v1/meta
```

当前 Capability 状态允许 `ready` 和明确标记的 `legacy`；计划项数量为 0。`install` 和旧 Filesystem `uninstall` 继续作为 1.x 兼容命令，不单独复制为原生 Web 功能。

## Web 安全

- 非 Loopback 绑定必须配置 Bearer Token。
- Bearer Token 使用恒定时间比较。
- 默认请求体上限为 24 MiB，可通过 `PERSONADOCK_WEB_MAX_BODY_BYTES` 在 1–128 MiB 范围内调整。
- API 响应默认 `Cache-Control: no-store`。
- 启用 CSP、`nosniff`、`DENY` frame、无 Referrer、Permissions Policy 和同源资源策略。
- 浏览器文件路径限制在 Persona、Upload、Export、Backup、Key 和 Runtime 管理根目录。
- 上传单文件限制为 16 MiB。
- API Key、备份密码和部署确认令牌不写入 Job 日志。

## 验收

每阶段及最终主分支均运行：

- 完整 pytest。
- CLI/Web Capability parity。
- 安全中间件和请求限制测试。
- AI Vault、Provider、草稿、Diff 和 Revision 测试。
- 原生部署 Plan/Apply/Rollback 契约测试。
- Memory/Session 治理边界测试。
- 安装脚本语法检查。
- PyInstaller 独立程序构建与 Web 资源验证。
- 示例 PersonaPack 构建、检查、校验和与 Artifact 上传。

PersonaDock CLI 继续长期保留，作为自动化、服务器和高级用户接口。
