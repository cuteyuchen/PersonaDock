# PersonaDock Vue 3 前端迁移

状态：功能迁移完成，进入稳定维护  
目标：用 Vue 3、TypeScript、Vite 和 shadcn-vue 替换 Web Control Plane 2 的原生 JavaScript 主界面。  
原则：后端 `/api/v1`、Capability、Plan/Apply、Revision、Job 和安全契约保持不变。

## 技术栈

- Vue 3 Composition API 与 `<script setup>`
- TypeScript
- Vite
- Vue Router Hash History
- Pinia
- TanStack Vue Query
- shadcn-vue 源码组件与 Reka UI
- Tailwind CSS 4
- Lucide Vue
- VeeValidate + Zod
- Monaco Editor
- Vitest + Vue Test Utils
- Playwright + axe-core

Node.js 只用于开发、测试和发布构建。Vite 产物写入：

```text
src/persona_dock/web/static/vue/
```

最终 wheel 与 PyInstaller 独立程序不依赖 Node.js。

## 视觉约束

- 桌面管理工具，不做聊天机器人界面。
- 深色窄侧栏与暖灰工作区。
- 低圆角、高信息密度。
- 表格、Diff、窄表单和日志优先。
- 不使用渐变、发光、紫色 AI 模板和大面积营销卡片。
- AI Studio 保持“参数 → 审查 → 应用”，不使用聊天气泡。

## 最终入口

```text
GET /                  # Vue 主控制面
GET /vue               # Vue 兼容别名
GET /legacy            # 原生界面，一个兼容周期
GET /assets/vue/app.js
GET /assets/vue/app.css
```

健康检查与 `/api/v1/meta` 返回：

```json
{
  "web_frontend": "vue3-shadcn-vue",
  "web_frontend_migration_phase": 7,
  "vue_preview": "/vue"
}
```

## 阶段结果

| 阶段 | 状态 | 内容 |
|---|---|---|
| Vue Phase 0 | 已完成 | 工程、Vite、TypeScript、Tailwind 4、shadcn-vue、CI 构建链 |
| Vue Phase 1 | 已完成 | App Shell、Dashboard、Persona 列表、Runtime 列表、Job Center、Settings |
| Vue Phase 2 | 已完成 | Persona 生命周期、Canonical/Monaco、Revision、Diff、Validation、Scenario Test、Compile Preview、Migration |
| Vue Phase 3 | 已完成 | Build、Pack、Trust、Backup、Character Card、Adapter、Skill |
| Vue Phase 4 | 已完成 | Adoption、Runtime 详情、Deployment Plan/Apply/Rollback |
| Vue Phase 5 | 已完成 | Memory 与 Session Summary Policy、Review、Conflict、Plan/Apply 与历史 |
| Vue Phase 6 | 已完成 | AI Studio、Provider Vault、Create/Distill/Hybrid/Refine 与显式 APPLY |
| Vue Phase 7 | 已完成 | Playwright、axe-core、性能预算、根入口切换与 `/legacy` 兼容入口 |

## 核心实现

### Persona 与编辑

- 新建、注册和安全 Persona Root 限制。
- 结构化字段与 Monaco JSON 共用完整 Canonical v3 模型。
- 保存自动完成校验、场景测试、语义 Diff、Revision 与 Journal。
- Vue 提交携带 `expected_content_hash`，陈旧草稿返回 409。
- Revision 恢复必须先生成 Preview，并使用 Plan Hash 应用。

### Artifact、信任与兼容

- 构建目标产物、PersonaPack 与公开工程导出。
- Manifest 检查、Ed25519 密钥、签名与验证。
- AES-256-GCM 私有备份创建、检查和恢复；密码不进入 Job。
- Character Card v2/v3、PNG 与 CHARX 检查、导入和导出。
- Adapter Doctor 与 persona-builder Skill Plan/Install。

### Runtime 与部署

- Runtime 能力、元数据和 Managed 状态详情。
- Adoption Preview 与显式接管。
- Hermes Profile 和 OpenClaw Agent/Workspace 原生部署表单。
- 一次性确认令牌不写入 Job；Apply 前重新计算语义计划。
- 部署历史、详情和显式 Rollback。

### Memory 与 Session Summary

- Policy JSON、候选收集、敏感性与同步范围审核。
- Memory 冲突支持 keep-existing、replace、keep-both。
- Plan、传播历史和显式 Apply。
- Session Summary 支持手工脱敏摘要、审核和传播。
- 原始 Session 或 Transcript 不进入共享同步链路。

### AI Studio

- OpenAI、OpenAI-compatible、Anthropic、Gemini 与 Ollama Provider。
- Secret 只写入本地 AES-256-GCM Vault，API 不回显。
- Provider 测试和模型列表。
- Create、Distill、Hybrid 与 Refine。
- Job 只记录输入哈希，不保存 instruction/evidence 原文。
- 审查 Canonical、semantic diff、risk、validation、tests 与 compile preview。
- APPLY 前检查 Refine base Revision，过期草稿被拒绝。

## CI 验收

主分支 bundle 按顺序执行：

1. Node 22 与 pnpm 安装。
2. Vue TypeScript 检查。
3. Vitest。
4. Vite 构建及静态资源检查。
5. Playwright Chromium 浏览器流程。
6. axe-core 严重级可访问性检查。
7. 前端静态资源 8 MiB 发布预算。
8. 完整 pytest。
9. 安装脚本检查。
10. PyInstaller 构建与真实 HTTP 资源验证。
11. PersonaPack、校验和与发布 Artifact 验收。

## 兼容期

原生界面不再是默认入口，只通过 `/legacy` 提供一个兼容周期。它继续共用相同 API 和 Registry，不形成第二套领域状态。兼容期结束后可以删除原生 HTML、CSS 和 JavaScript，但不得删除稳定 API 或 1.0 数据兼容能力。
