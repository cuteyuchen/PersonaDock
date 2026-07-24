# PersonaDock 重构与分阶段开发计划

> 状态：批准执行  
> 目标版本：0.2.0 → 1.0.0  
> 核心定位：本地优先、跨 Agent 的人格控制平面（Persona Control Plane）

## 1. 产品重新定位

PersonaDock 不再定位为“把 SOUL、Skill、Memory 复制到 Hermes/OpenClaw 目录的安装器”，而是：

> 将自然语言、聊天记录和既有人格转换为可审核、可测试、可版本化、可导出、可部署、可同步的统一人格，并管理同一人格在 Hermes、OpenClaw 等多个运行实例中的生命周期。

核心工作流：

```text
自然语言 / 聊天记录 / 既有 Hermes Profile / 既有 OpenClaw Agent
                              ↓
                     Canonical Persona
                              ↓
       审核 · 版本 · 测试 · 快照 · 记忆治理 · 同步策略
                              ↓
                         PersonaPack
                              ↓
          Hermes Adapter                OpenClaw Adapter
        Profile Distribution           Workspace Overlay
                              ↓
            多运行实例绑定、导出、同步、回滚和审计
```

PersonaDock 负责：

- 人格创建、聊天蒸馏、混合生成和改进。
- 既有人格发现、接管和标准化。
- 统一人格定义、版本和测试。
- 平台原生格式编译与部署。
- 共享记忆候选、审核、同步和冲突处理。
- 会话摘要的受控同步。
- Web 控制台和 CLI 自动化接口。

PersonaDock 不负责：

- 重新实现 Hermes/OpenClaw 的聊天运行时。
- 管理用户 API Key、模型 Provider 或 Gateway Token。
- 默认复制完整原始会话。
- 把平台运行目录当作人格唯一源。
- 无确认地覆盖平台专属配置、记忆或会话。

## 2. 参考项目与差异化

### 2.1 OpenPersona

参考：Soul / Body / Faculty / Skill 分层、persona 生命周期、导入导出、状态同步、人格切换和 handoff。

PersonaDock 不直接复制其模型，差异化重点为：

- Hermes 与 OpenClaw 的原生实例绑定。
- 从聊天记录进行证据化蒸馏。
- 每条结论保留来源、置信度和审核状态。
- 平台间受控共享记忆，而不是单一运行时内切换。
- Deployment Plan、快照、回滚和冲突治理。
- 本地 Web 控制平面。

### 2.2 Hermes Profile Distribution

参考：

- Profile 是隔离的 Agent 运行实例。
- Distribution 负责 SOUL、Skills、非敏感配置等发行方管理内容。
- Memory、Sessions、认证和本地密钥在安装和更新时保留。
- 使用 Hermes 原生命令创建、安装、更新和验证 Profile。

PersonaDock 的 Hermes Adapter 应优先调用 Hermes CLI，不直接猜测 Windows/Linux/macOS 的内部目录。

### 2.3 OpenClaw Agent Workspace

参考：

- 每个 Agent 有独立 Workspace。
- SOUL.md、IDENTITY.md、USER.md、MEMORY.md、memory/ 和 skills/ 位于 Workspace。
- Sessions、认证、配置和日志位于 State Directory，不属于 Workspace 人格定义。
- Workspace Skills 具有较高优先级。

PersonaDock 应生成 Workspace Overlay，只管理声明归属的文件，不覆盖 AGENTS.md、USER.md、TOOLS.md 和平台状态目录。

### 2.4 Letta AgentFile

参考：

- 可序列化的 Agent 状态。
- 明确的 Memory Block、工具、消息和运行配置边界。
- 导入导出、版本化和可重复测试。

PersonaDock 不默认打包完整运行状态；PersonaPack 保持平台无关，并将运行时状态分为共享、平台本地和不可同步三类。

### 2.5 Character Card / SillyTavern

参考角色描述、示例对话和角色书导入导出。

后续可增加 Character Card V2/V3 Adapter，但 PersonaDock 的核心格式必须保留结构化行为规则、Skill、Memory 审核和部署信息。

## 3. 核心设计原则

1. **Canonical Persona 是唯一人格定义源。**
2. **平台目录是构建产物和运行状态，不是主源。**
3. **先发现、预览和计划，再修改。**
4. **任何写入都生成快照和可审计日志。**
5. **平台原生命令优先，文件复制仅作明确标注的兼容模式。**
6. **人格定义、共享记忆、平台本地记忆和会话必须分层。**
7. **默认审核后同步；用户可以显式开启自动共享。**
8. **敏感数据、外部内容和 Agent 推断默认始终审核。**
9. **完整会话默认不同步；第一阶段只同步摘要。**
10. **Web 与 CLI 调用同一 Core API，不能形成两套逻辑。**

## 4. 目标架构

```text
┌─────────────────────────────────────────────┐
│ Web Console / CLI                           │
│ serve · doctor · discover · adopt · sync    │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ Application Services                        │
│ Registry · Deployment · Review · Sync       │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ Canonical Persona Core                      │
│ Schema · Migration · Diff · Test · Package  │
└───────────────┬─────────────────┬───────────┘
                ↓                 ↓
┌──────────────────────┐  ┌──────────────────────┐
│ Hermes Adapter       │  │ OpenClaw Adapter     │
│ Profile/Distribution │  │ Agent/Workspace      │
└──────────────────────┘  └──────────────────────┘
                ↓                 ↓
┌─────────────────────────────────────────────┐
│ Local Registry / SQLite / Files / Snapshots │
└─────────────────────────────────────────────┘
```

建议源码结构：

```text
src/persona_dock/
├── core/
│   ├── models.py
│   ├── schema.py
│   ├── migration.py
│   ├── diff.py
│   └── testing.py
├── registry/
│   ├── database.py
│   ├── personas.py
│   ├── instances.py
│   ├── snapshots.py
│   └── journal.py
├── adapters/
│   ├── base.py
│   ├── legacy_filesystem.py
│   ├── hermes.py
│   └── openclaw.py
├── deployment/
│   ├── plans.py
│   ├── apply.py
│   ├── verify.py
│   └── rollback.py
├── sync/
│   ├── policies.py
│   ├── memory.py
│   ├── sessions.py
│   ├── conflicts.py
│   └── engine.py
├── web/
│   ├── app.py
│   ├── api/
│   └── static/
├── packaging/
└── cli.py

web/
├── src/
├── package.json
└── vite.config.ts
```

## 5. Canonical Persona v3

### 5.1 工程结构

```text
persona/
├── persona.yaml
├── soul/
│   ├── identity.yaml
│   ├── behavior.yaml
│   ├── boundaries.yaml
│   └── voice.yaml
├── skills/
│   └── persona/
│       ├── SKILL.md
│       └── references/
├── memory/
│   ├── profile.yaml
│   ├── shared.jsonl
│   ├── seed.jsonl
│   └── policy.yaml
├── tests/
│   ├── scenarios.yaml
│   └── regressions.yaml
├── adapters/
│   ├── hermes.yaml
│   └── openclaw.yaml
├── .private/
│   ├── evidence.jsonl
│   ├── normalized.jsonl
│   ├── memory-candidates.jsonl
│   └── design-notes.md
└── .gitignore
```

### 5.2 结构化行为规则

```yaml
- id: emotional-support-001
  trigger:
    intent: emotional_support
    conditions:
      - user_is_clearly_distressed
  behavior:
    - stop_playful_teasing
    - acknowledge_emotion
    - listen_before_suggesting
  constraints:
    - do_not_diagnose
    - do_not_claim_unprovided_memories
  priority: high
  confidence: explicit
  source_type: explicit-design
  evidence:
    - private:evidence-028
  tests:
    - user-is-exhausted
```

来源类型：

- `explicit-design`
- `observed-evidence`
- `reviewed-existing`
- `safe-default`

优先级：

```text
用户当前明确要求
→ 已审核现有人格
→ 高置信聊天证据
→ 中低置信聊天证据
→ 安全默认项
```

### 5.3 Memory 生命周期

```text
平台运行记忆
    ↓ Adapter Pull
Memory Candidate
    ↓ 审核/自动规则
Shared Memory
    ↓ Adapter Compile
Hermes / OpenClaw
```

状态：

- `pending`
- `active`
- `local-only`
- `superseded`
- `conflicted`
- `expired`
- `rejected`

每条共享记忆必须记录：

- Persona ID
- 类型和摘要
- 来源运行时与实例
- 原始内容哈希
- 创建时间
- 审核人/审核方式
- 敏感级别
- 同步范围
- 已传播实例
- 冲突和替代关系

## 6. Persona Registry

默认目录：

```text
~/.personadock/
├── personadock.db
├── personas/
├── artifacts/
├── snapshots/
├── backups/
├── imports/
├── exports/
└── logs/
```

核心实体：

### Persona

- `id`
- `name`
- `version`
- `source_path`
- `schema_version`
- `created_at`
- `updated_at`

### RuntimeInstance

- `id`
- `adapter`
- `transport`（local/docker/remote）
- `platform_instance_id`
- `display_name`
- `location`
- `capabilities`
- `last_seen_at`

### Binding

- `persona_id`
- `runtime_instance_id`
- `managed_since`
- `adopted`
- `sync_policy_id`
- `last_deployed_version`
- `last_synced_at`

### Snapshot

- 原始平台状态快照
- PersonaDock 构建快照
- 部署前快照
- 回滚点

### JournalEvent

不可变记录：发现、接管、导出、部署、同步、审核、冲突处理和回滚。

## 7. Adapter 契约

```python
class PersonaAdapter:
    def doctor(self) -> AdapterDoctorResult: ...
    def discover(self) -> list[RuntimeInstance]: ...
    def inspect(self, instance) -> NativePersonaSnapshot: ...
    def adopt(self, instance) -> AdoptionDraft: ...
    def build(self, persona) -> NativeArtifact: ...
    def plan(self, artifact, instance) -> DeploymentPlan: ...
    def apply(self, plan) -> DeploymentResult: ...
    def verify(self, result) -> VerificationResult: ...
    def export(self, persona, format) -> Path: ...
    def pull_memory(self, instance) -> list[MemoryCandidate]: ...
    def push_memory(self, instance, memories) -> SyncResult: ...
    def pull_session_summaries(self, instance) -> list[SessionSummary]: ...
    def rollback(self, deployment_id) -> None: ...
```

Adapter 必须声明能力：

```yaml
supports:
  discovery: true
  native_deployment: true
  memory_pull: true
  memory_push: true
  session_summary_pull: false
  raw_session_import: false
  docker: true
```

## 8. Discovery 与 Adopt

### 8.1 Discover

```bash
personadock discover
personadock discover --target hermes
personadock discover --target openclaw
```

Web 页面显示：

- 已发现实例
- 是否已管理
- 人格名称和标识
- SOUL/Skill/Memory 状态
- 平台版本
- 可用能力
- 潜在同一人格匹配

### 8.2 Adopt

```bash
personadock adopt --target hermes --profile xiaoyou
personadock adopt --target openclaw --agent-id xiaoyou
```

流程：

1. 只读检查。
2. 保存原始快照。
3. 提取身份、SOUL、Skill、Memory 和平台专属内容。
4. 生成 Canonical Persona 草稿。
5. 未识别内容进入审核队列。
6. 记忆默认作为候选导入。
7. 创建 Persona 和 Binding。
8. 运行验证和差异报告。

同名实例不得自动合并。匹配依据包括 PersonaDock Manifest、人格 ID、名称、SOUL 相似度、Skill ID 和历史绑定。

## 9. 导出与迁移

支持：

```bash
personadock export xiaoyou --format personapack
personadock export xiaoyou --format hermes-profile
personadock export xiaoyou --format openclaw-workspace
```

导出选项：

- 人格定义
- Persona Skill
- 场景测试
- 已审核共享记忆
- 会话摘要
- 平台本地记忆（默认关闭）
- 原始会话（默认关闭，实验）

迁移：

```bash
personadock migrate --from hermes:xiaoyou --to openclaw:xiaoyou
```

实际流程必须经过 Canonical Persona，不允许平台目录直接互拷。

## 10. 同步模型

### 10.1 同步层级

1. **人格定义**：SOUL、身份、行为、边界、Persona Skill。
2. **共享记忆**：经审核或符合自动批准规则的规范化记忆。
3. **会话摘要**：规范化的经历摘要和未完成任务。
4. **完整会话**：实验性，默认关闭。

### 10.2 默认策略

```yaml
definition:
  mode: manual
  conflict_policy: personadock-wins

shared_memory:
  mode: reviewed
  auto_approve:
    source_types:
      - direct-user-statement
    memory_types:
      - preference
      - project-fact
      - shared-decision
  always_review:
    source_types:
      - web-content
      - email-content
      - tool-output
      - agent-inference
    sensitivity:
      - identity
      - health
      - financial
      - location
      - credentials

sessions:
  mode: disabled
  summaries: reviewed
  raw_sessions: disabled

conflicts:
  mode: manual
  prefer_newer: false
```

用户可以显式切换：

- 共享记忆不审核自动同步。
- 会话摘要自动同步。
- 完整会话实验性同步。

高风险选项必须显示明确警告，并写入 Journal。

### 10.3 冲突处理

不能使用简单的“最后写入覆盖”。冲突界面应支持：

- 使用较新内容。
- 保留双方并增加上下文。
- 仅保留在指定平台。
- 修改后接受。
- 拒绝双方。

## 11. Web 控制台

启动：

```bash
personadock serve
```

默认：

```text
http://127.0.0.1:8732
```

远程监听需要显式参数、认证令牌和安全警告。

建议技术栈：

- 后端：FastAPI + Uvicorn。
- 数据：SQLite + 文件制品。
- 前端：React + TypeScript + Vite。
- 事件：初期轮询，后续 WebSocket/SSE。
- Release：前端静态文件嵌入独立可执行程序。

页面：

```text
/dashboard
/discover
/adopt
/personas
/personas/:id
/personas/:id/instances
/personas/:id/memory
/personas/:id/review
/personas/:id/sync
/personas/:id/export
/personas/:id/diff
/personas/:id/history
/settings
/doctor
```

核心功能：

- 创建、导入和接管人格。
- 一键发现 Hermes/OpenClaw。
- 一键接管和批量接管。
- 一键导出 PersonaPack 或平台原生格式。
- 一键同步全部绑定实例。
- 同步前预览和差异。
- 共享记忆审核队列。
- 自动同步、审核同步、禁用同步配置。
- 会话摘要和实验性会话同步配置。
- 冲突处理。
- 快照和回滚。
- 操作日志。

## 12. CLI 目标命令

```text
personadock serve
personadock doctor
personadock discover
personadock adopt
personadock persona list|show|diff
personadock bind|unbind
personadock targets list
personadock deploy --dry-run
personadock export
personadock migrate
personadock sync status|run
personadock memory pull|review|push
personadock rollback
personadock uninstall
personadock status
personadock init|validate|test|build|pack|inspect
personadock skill install
```

旧 `personadock install` 在迁移期保留为兼容入口，内部转为 deployment service，并输出弃用提示。

## 13. 安全模型

- Web 默认只绑定 `127.0.0.1`。
- 远程模式要求令牌；文档推荐反向代理和 HTTPS。
- 不把 API Key、Token、认证文件加入 PersonaPack。
- 导出前执行敏感文件扫描。
- Adapter 文件所有权白名单。
- 所有部署必须先生成 Deployment Plan。
- 所有变更必须有快照或明确说明无法快照。
- 自动记忆同步按来源、类型和敏感级别过滤。
- 外部网页、邮件、工具输出和 Agent 推断默认不可自动传播。
- 完整会话同步标记实验性，并默认不实现写回。

## 14. 分阶段开发计划

每个阶段一个独立分支、PR 和 squash commit。只有本阶段验收通过后才进入下一阶段。

### Phase 0：安全核心与 Web 骨架

提交标题：`feat: establish safe deployment and web control plane foundation`

范围：

- Adapter 基础接口与能力声明。
- DeploymentPlan 数据模型。
- LegacyFilesystemAdapter。
- `doctor`。
- `deploy --dry-run`。
- 不明确目标时禁止静默安装。
- `personadock serve`。
- FastAPI `/api/health`、`/api/doctor`、`/api/plans`。
- 最小 Web 总览和 Doctor 页面。
- 默认本机监听。
- Windows、Linux、Docker 计划测试。

验收：

- 不明确的 Hermes/OpenClaw 目标不会写文件。
- dry-run 与实际计划使用同一逻辑。
- Web 与 CLI 展示同一 Doctor 结果。
- 独立二进制仍能构建。

### Phase 1：Persona Registry 与 Discovery

提交标题：`feat: add persona registry and runtime discovery`

范围：

- SQLite Registry。
- Persona、RuntimeInstance、Binding、Snapshot、Journal 表。
- `persona list/show`。
- `discover`。
- Web 人格列表、发现页面和实例页面。
- Hermes/OpenClaw 只读发现接口。
- 未管理实例标记。

验收：

- 重复扫描幂等。
- 不修改平台文件。
- 本地、Docker 实例可区分。
- 数据库迁移可重复执行。

### Phase 2：Adopt、Snapshot 与 Export

提交标题：`feat: adopt and export existing personas`

范围：

- 既有人格只读快照。
- Adopt 草稿和未识别字段。
- Hermes/OpenClaw SOUL、Identity、Skills、Memory 提取。
- PersonaPack、Hermes Profile、OpenClaw Workspace 导出。
- 批量接管。
- Web 接管向导和导出页面。

验收：

- 接管前始终创建快照。
- 未识别字段不丢失。
- 同名实例不会未经确认合并。
- 导出不包含认证和 Session。

### Phase 3：Canonical Persona v3

提交标题：`feat: introduce canonical persona schema v3`

范围：

- Schema v3。
- 结构化行为规则。
- 来源、置信度、审核状态。
- Memory Candidate。
- v2 → v3 Migration。
- PersonaPack Manifest v2。
- Diff 和场景测试。
- Web 结构化编辑器。

验收：

- v2 工程可迁移。
- 同一输入构建可复现。
- 每条高优先级行为可关联测试。
- 平台路径不进入 Canonical Persona。

### Phase 4：Hermes 原生 Adapter

提交标题：`feat: deploy personas as native Hermes profiles`

范围：

- Hermes CLI 和版本 Doctor。
- Profile 枚举和绑定。
- Profile Distribution 编译。
- 创建、更新、验证、导出和回滚。
- `--profile`、`--activate`。
- Docker 容器内原生命令。
- Hermes Memory Candidate Pull/Push。
- Web Profile 管理。

验收：

- 不覆盖 default Profile，除非用户显式选择。
- 更新不覆盖 Memory、Sessions、`.env` 和认证。
- Windows 不依赖猜测 Hermes 目录。
- Docker 通过 Hermes CLI 部署。

### Phase 5：OpenClaw 原生 Adapter

提交标题：`feat: manage OpenClaw agent workspaces`

范围：

- OpenClaw CLI、配置和 Agent/Workspace 发现。
- Workspace Overlay。
- SOUL、IDENTITY、Persona Skill 映射。
- 不覆盖 AGENTS.md、USER.md、TOOLS.md。
- Memory Markdown Pull/Push 和重建索引。
- Docker/远程 Workspace 支持。
- Web Agent 管理。

验收：

- Workspace 与 State Directory 明确分离。
- 平台专属 Skills 保留。
- 多 Agent 可绑定同一或不同 Persona。
- 更新和回滚不损坏会话状态。

### Phase 6：同步策略与审核中心

提交标题：`feat: add governed cross-runtime memory sync`

范围：

- SyncPolicy。
- Definition Push/Pull。
- Memory Pull、Review、Push。
- 自动批准过滤器。
- 敏感内容规则。
- 去重、来源和传播日志。
- 冲突检测和人工解决。
- Web 策略编辑器、审核中心和同步预览。

验收：

- 默认审核后同步。
- 自动同步可按来源/类型/敏感级别配置。
- 同一记忆不会循环传播。
- 冲突不会静默覆盖。

### Phase 7：会话摘要与高级同步

提交标题：`feat: synchronize reviewed session summaries`

范围：

- SessionSummary Canonical Model。
- Hermes/OpenClaw 摘要拉取接口。
- 手动和自动摘要审核。
- Pending Tasks 和 Emotional Context Handoff。
- 完整会话实验接口，仅做只读导入和预览。
- 多机器加密同步设计预留。

验收：

- 默认不传输原始 Session。
- 摘要保留来源和范围。
- 工具调用和系统消息默认排除。
- 用户可以完全关闭会话相关功能。

### Phase 8：质量、兼容性与 1.0

提交标题：`feat: stabilize PersonaDock control plane for 1.0`

范围：

- Adapter 插件接口。
- Golden Tests。
- 多平台和 Docker 集成矩阵。
- PersonaPack 签名/可信来源预留。
- 公共导出与私有加密备份。
- Character Card 导入导出 Adapter。
- OpenPersona 兼容导入研究。
- 完整迁移和回滚文档。

验收：

- 同一 Persona 可部署到 Hermes 和 OpenClaw。
- 所有部署支持 plan、verify、snapshot 和 rollback。
- 人格升级不覆盖运行时私有状态。
- Schema、PersonaPack 和 Adapter API 有兼容承诺。

## 15. 测试策略

### 单元测试

- Schema、Migration、Diff。
- Registry 和数据库迁移。
- Adapter Plan。
- 文件所有权和冲突处理。
- Memory 去重、来源和策略。
- Web API。

### Golden Tests

```text
fixtures/
├── persona-source/
├── expected-hermes/
├── expected-openclaw/
└── expected-generic/
```

### 集成矩阵

- Windows x64。
- Linux x64。
- Linux ARM64。
- macOS Intel。
- macOS ARM64。
- Docker Linux。

### 安全回归

- 无目标静默写入。
- 密钥和认证误打包。
- Memory 循环同步。
- 外部内容自动传播。
- 平台专属文件误覆盖。
- 回滚失败。

## 16. 版本与兼容策略

- `0.1.x`：旧 PersonaPack 与文件复制安装兼容维护。
- `0.2.0`：Phase 0–1，Web 基础和 Registry。
- `0.3.0`：Phase 2–3，Adopt/Export 和 Schema v3。
- `0.4.0`：Hermes Adapter。
- `0.5.0`：OpenClaw Adapter。
- `0.6.0`：共享记忆同步。
- `0.7.0`：会话摘要。
- `1.0.0`：稳定格式、插件接口和兼容承诺。

旧命令迁移：

- `install` 在两个小版本内映射到 `deploy`。
- 读取 Schema v2 至少支持到 1.0。
- 写出默认使用 Schema v3。
- LegacyFilesystemAdapter 在原生 Adapter 可用后默认关闭，只能显式启用。

## 17. 每阶段提交与合并规范

1. 从最新 `main` 创建阶段分支。
2. 阶段内可以有工作提交，但 PR 最终 squash 为一个阶段提交。
3. PR 描述必须列出范围、排除项、迁移影响和验收结果。
4. 必须通过常规 CI 和五平台 Release dry-run。
5. 阶段完成后更新本文档状态表。
6. 发现计划需要改变时先提交文档修订，再修改实现。

## 18. 状态表

| 阶段 | 状态 | 目标版本 | 合并提交 |
|---|---|---:|---|
| 路线文档 | 进行中 | — | — |
| Phase 0：安全核心与 Web 骨架 | 未开始 | 0.2.0 | — |
| Phase 1：Registry 与 Discovery | 未开始 | 0.2.0 | — |
| Phase 2：Adopt、Snapshot 与 Export | 未开始 | 0.3.0 | — |
| Phase 3：Canonical Persona v3 | 未开始 | 0.3.0 | — |
| Phase 4：Hermes Adapter | 未开始 | 0.4.0 | — |
| Phase 5：OpenClaw Adapter | 未开始 | 0.5.0 | — |
| Phase 6：受控共享记忆同步 | 未开始 | 0.6.0 | — |
| Phase 7：会话摘要 | 未开始 | 0.7.0 | — |
| Phase 8：1.0 稳定化 | 未开始 | 1.0.0 | — |

## 19. 第一执行顺序

当前立即执行：

1. 合并本重构计划。
2. Phase 0：安全部署基础与本地 Web 控制台骨架。
3. Phase 1：Persona Registry 和只读 Discovery。
4. 每个阶段单独提交、验证和合并后再继续。
