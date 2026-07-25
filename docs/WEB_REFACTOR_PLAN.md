# PersonaDock Web Control Plane 2.0

状态：执行中  
目标版本：PersonaDock 2.0  
执行方式：直接在 `main` 分阶段提交；每个阶段必须独立通过 CI 后再进入下一阶段。

## 执行状态

| 阶段 | 状态 | 主要结果 | 验收 |
|---|---|---|---|
| Phase 0 | 已完成 | 路线、Capability、Job、Revision、AI 与安全契约 | 文档已进入 `main` |
| Phase 1 | 已完成 | Web 2.0 Shell、`/api/v1`、Capability Registry、持久化 Job/SSE、嵌入式资源 | 主分支 bundle 通过 |
| Phase 2 | 已完成 | 共用 Persona Service、安全创建/注册、Runtime Discovery、Adoption、导出和 Web 工作流 | 主分支 bundle `30165667340` 通过 |
| Phase 3 | 进行中 | 编辑、Revision、Diff、测试 | — |
| Phase 4–8 | 未开始 | 按下述路线继续 | — |

Phase 1–2 保留 `/canonical`、`/hermes`、`/openclaw`、`/sync` 和 `/sessions` 兼容页面。新功能不通过 Shell 调用 CLI；CLI `init` 已与 Web 共用 `PersonaApplicationService`。

## 1. 产品目标

PersonaDock Web 2.0 是本地优先的人格控制平面，不是 CLI 的展示壳。最终网页端应覆盖所有公开 CLI Capability，并增加版本、差异、部署计划、冲突审核和 AI 人格生成等更适合图形界面的能力。

核心原则：

1. CLI 与 Web 共用应用服务，不通过 Shell 调用 CLI。
2. 写操作遵循 Plan → Review → Apply，失败可恢复。
3. AI 只生成候选 Revision，不直接覆盖或部署。
4. Persona 工程仍是真实来源；Registry、Revision、Job 只管理索引和历史。
5. 默认不上传聊天，不同步原始 Session/Transcript，不暴露认证和密钥。
6. 前端采用桌面工具式设计：高信息密度、克制色彩、少装饰性卡片和渐变，避免模板化 AI 仪表盘风格。

## 2. 信息架构

主导航：

- 概览
- 人格
- AI 人格工作室
- 差异中心
- 运行实例
- 部署
- Memory 同步
- Session Summary
- PersonaPack 与信任
- 备份
- Character Card
- Adapter 与 Skill
- 任务中心
- 系统设置

Persona 详情子页面：概览、编辑、行为与边界、测试、版本与差异、构建与打包、运行时绑定、部署历史、Memory、Session Summary、备份、活动记录。

## 3. 技术架构

```text
CLI ──────────────┐
Web API ──────────┼→ Application Services → Registry / Domain / Adapter
Scheduled Job ────┘                         → Hermes / OpenClaw / Filesystem
```

应用服务边界：

- `PersonaService`
- `RevisionService`
- `BuildService`
- `PackageService`
- `RuntimeService`
- `DeploymentService`
- `SyncService`
- `SessionService`
- `TrustService`
- `BackupService`
- `CharacterCardService`
- `AdapterService`
- `SkillService`
- `AIStudioService`
- `JobService`
- `AuditService`

API 使用 `/api/v1` 版本前缀。旧 API 在 1.x 兼容期内保留，并逐步委托到相同服务。

前端资源必须随 Python 包和独立可执行程序分发，不依赖公网 CDN。第一步先建立无构建依赖的模块化 SPA Shell；当完整前端工具链加入发布流水线后，再迁移到 Vue 3 + TypeScript，API 和页面契约保持不变。

## 4. Capability 一致性契约

每个公开能力必须注册以下信息：

```text
id
label
category
cli_command
api_route
web_route
destructive
supports_preview
runs_as_job
status
```

CI 必须保证：每个公开 CLI Capability 都有 Web 映射，或有明确的 `web_not_applicable_reason`。

特殊映射：

- `--json` → API 结构化响应
- `--dry-run` → Plan 页面
- `--yes` → 一次性确认令牌
- `--no-browser` → Web 不适用
- CLI 文本日志 → Job Event
- 弃用的 `install` → 不单独制作页面，映射到 `deploy`

## 5. Revision 与 Diff

以下操作创建 Revision：手动保存、AI 生成/修改、Character Card 导入、Runtime Adoption、Migration、Backup Restore、PersonaPack Import、历史恢复。

Revision 至少记录：

```text
revision_id
persona_id
parent_revision_id
created_at
source
summary
content_hash
canonical_snapshot
validation_result
test_result
```

Diff 类型：

- Canonical 语义 Diff
- 任意 Revision Diff
- Hermes/OpenClaw 编译产物 Diff
- 当前 Runtime 与部署计划 Diff
- PersonaPack Manifest/成员 Diff
- Memory 冲突 Diff
- Session Summary 修订 Diff

风险级别：低、中、高、破坏性。Boundary、Critical Behavior、Memory Policy 和所有权变化至少为高风险。

## 6. Job 契约

长任务统一进入 Job Center：发现、接管、构建、打包、签名、备份、恢复、部署、同步、Session、Character Card、AI 生成、批量测试。

状态：

```text
queued
running
waiting-review
success
failed
cancelled
```

Job 持久化事件、进度、输入摘要、输出、错误和关联 Persona/Runtime。实时更新使用 SSE；刷新页面后仍可继续查看。

## 7. AI 人格工作室

Provider：OpenAI Compatible、OpenAI、Anthropic、Gemini、Ollama/本地模型。

模式：

- Create：自然语言设计新 Persona
- Distill：从用户显式选择的记录提取人格证据
- Hybrid：设计要求与聊天证据组合
- Refine：修改已有 Persona

固定流程：

```text
输入 → 结构化生成 → Schema 校验 → 安全检查 → 场景测试
→ 语义 Diff → 用户审核 → 创建 Revision
```

密钥优先保存在系统 Keyring；不可用时进入本地加密 Vault。API 只返回 `secret_ref` 和掩码，不返回 Secret。日志必须过滤 Authorization、API Key 和自定义敏感 Header。

## 8. 安全契约

- 非 Loopback 绑定必须鉴权。
- 浏览器不得读取任意路径；仅允许 Registry、Discovery、配置根目录、Upload、Export、Snapshot、Backup。
- 所有路径执行 `expanduser`、`resolve`、允许根校验、符号链接和文件类型检查。
- 部署、接管、恢复、迁移、批量修改、Memory/Session Apply、AI 修改应用、删除操作必须先生成 Plan。
- Apply 携带 `plan_id`、`plan_hash`、一次性确认令牌；源文件变化后拒绝旧 Plan。
- 原始 Session 双向同步保持关闭。

## 9. 分阶段交付

### Phase 0：路线与契约

- 本文档
- Capability、API、Job、Revision 和安全契约
- 直接主分支提交规则

### Phase 1：SPA 与 API 基础

- 统一 Web Shell、导航、路由和 API Client
- `/api/v1/meta`、Capability Registry、统一错误模型
- Job Store、Job API、SSE
- 旧页面兼容入口
- 静态资源打包和 Web 基础测试

### Phase 2：Persona 生命周期

- Persona 列表、详情、新建、注册
- Discovery、Adoption 向导
- 导入、导出和活动记录

### Phase 3：编辑、Revision、Diff、测试

- 结构化编辑器与源码编辑器
- Revision Store、恢复、语义 Diff
- Validate、Scenario Test、Migration、编译预览

### Phase 4：构建、包、信任、备份

- Build、Pack、Inspect、Public Export
- Keygen、Sign、Verify
- Backup Create/Inspect/Restore
- Character Card、Skill、Adapter 管理

### Phase 5：Runtime 与部署

- Hermes/OpenClaw Runtime 详情
- Local/Docker/SSH
- Deployment Plan、文件 Diff、Apply、Verify、Rollback、Uninstall

### Phase 6：Memory 与 Session 治理

- Policy、Collect、Review、Conflict、Plan、Apply、History
- Reviewed Session Summary 完整工作流

### Phase 7：AI 人格工作室

- Provider 与 Secret Vault
- Create、Distill、Hybrid、Refine
- Streaming、Structured Output、测试、Diff、Revision 草稿

### Phase 8：一致性、安全和发布

- CLI/Web Capability CI
- Playwright 和安全回归
- 性能、可访问性、国际化
- 独立程序和平台矩阵验收

## 10. 阶段完成标准

每个阶段必须：

1. 代码和文档直接提交到 `main`，提交信息带阶段范围。
2. 通过现有 pytest、Python Contract 和 Docker Contract。
3. 新能力有 API 测试；用户工作流有端到端或等效集成测试。
4. 不破坏 1.0 CLI、Registry Schema v3、PersonaPack v2 和 Adapter API 1.x。
5. 不引入公网 CDN、明文 Secret、任意 Shell 或任意路径访问。
6. 更新本文件的执行状态和相关用户文档。

## 11. 最终验收流程

用户无需打开终端即可完成：

```text
配置模型 → 创建/导入 Persona → AI 生成或优化 → 编辑 → Diff → 测试
→ 构建 → 打包 → 签名 → 备份 → 扫描 Runtime → 接管
→ 查看部署 Diff → 部署/验证 → 审核 Memory/Session → 回滚
```

CLI 继续保留，作为自动化、服务器和高级用户接口。
