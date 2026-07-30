# PersonaDock Vue 3 前端迁移

状态：执行中  
目标：用 Vue 3、TypeScript、Vite 和 shadcn-vue 替换 Web Control Plane 2 的原生 JavaScript 前端。  
原则：后端 `/api/v1`、Capability、Plan/Apply、Revision、Job 和安全契约保持不变。

## 技术栈

- Vue 3 Composition API 与 `<script setup>`
- TypeScript
- Vite
- Vue Router Hash History
- Pinia
- TanStack Vue Query
- shadcn-vue 源码组件
- Reka UI
- Tailwind CSS 4
- Lucide Vue
- Vitest
- 后续阶段加入 Playwright 与 Monaco Editor

Node.js 仅用于开发和发布构建。Vite 产物写入：

```text
src/persona_dock/web/static/vue/
```

最终 wheel 和 PyInstaller 独立程序继续不依赖 Node.js。

## 视觉约束

- 桌面管理工具，不做聊天机器人界面。
- 深色窄侧栏与暖灰工作区。
- 低圆角、高信息密度。
- 表格、Diff、窄表单和日志优先。
- 不使用渐变、发光、紫色 AI 模板和大面积营销卡片。
- AI Studio 保持“参数 → 审查 → 应用”结构，不使用聊天气泡。

## 迁移策略

迁移期间：

- 当前稳定原生界面继续位于 `/`。
- Vue 预览入口位于 `/vue`。
- 已迁移页面直接使用现有 API。
- 未迁移的高风险写操作明确跳转到兼容界面，不制作不完整副本。
- Vue 页面通过类型检查、单元测试、Python 契约和独立程序验证后，才替换根入口。

## 阶段

| 阶段 | 状态 | 内容 |
|---|---|---|
| Vue Phase 0 | 已完成 | 工程、Vite、TypeScript、Tailwind 4、shadcn-vue、CI 构建链 |
| Vue Phase 1 | 已完成 | App Shell、Dashboard、Persona 列表、Runtime 列表、Job Center、Settings |
| Vue Phase 2 | 下一阶段 | Persona 新建/注册/详情、Canonical Editor、Revision、Diff、Test |
| Vue Phase 3 | 未开始 | Build、Pack、Trust、Backup、Character Card、Adapter、Skill |
| Vue Phase 4 | 未开始 | Adoption、Deployment Plan/Apply/Rollback、Runtime 详情 |
| Vue Phase 5 | 未开始 | Memory 与 Session Summary 治理 |
| Vue Phase 6 | 未开始 | AI Studio 与 Provider Settings |
| Vue Phase 7 | 未开始 | Playwright、可访问性、性能、切换根入口、删除旧前端 |

Vue Phase 0–1 已通过主分支 bundle `30555536141`：Node/pnpm、TypeScript、Vitest、Vite、完整 pytest、安装脚本、PyInstaller、Vue HTTP 资源验证、PersonaPack 与发布 Artifact 全部成功。

## 当前入口

```text
GET /vue
GET /assets/vue/app.js
GET /assets/vue/app.css
```

健康检查和 `/api/v1/meta` 返回：

```json
{
  "web_frontend": "vue3-shadcn-vue",
  "web_frontend_migration_phase": 1,
  "vue_preview": "/vue"
}
```

## CI 验收

主分支 bundle 按顺序执行：

1. Node 22 与 pnpm 安装。
2. Vue TypeScript 检查。
3. Vitest。
4. Vite 构建。
5. 检查 `index.html`、`app.js` 和 `app.css`。
6. 完整 pytest。
7. 安装脚本检查。
8. PyInstaller 构建。
9. 启动独立程序并通过 HTTP 验证 `/vue` 与静态资源。
10. PersonaPack 和发布产物验收。

## 切换根入口的条件

只有同时满足以下条件，`/` 才从原生前端切换到 Vue：

- 所有 Capability 均有 Vue 页面或明确的兼容例外。
- 高风险写操作继续遵循 Plan → Review → Apply。
- AI、部署、恢复、Memory 和 Session 的浏览器 E2E 通过。
- 独立程序中 Vue 资源验证通过。
- 旧页面迁移到 `/legacy/*` 后仍可在一个兼容周期内访问。
