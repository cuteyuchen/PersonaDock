# PersonaDock Phase 0–8 重构路线（历史归档）

> 状态：已完成  
> 目标版本：`0.2.0 → 1.0.0`  
> 完成提交：`637a5a573e31474a77fc3bcd2ae98824098923ff`

本文件曾用于指导 PersonaDock 从文件系统安装器重构为本地优先的人格控制平面。Phase 0–8 已全部完成，当前执行状态以 [PHASE_STATUS.md](PHASE_STATUS.md) 为准；当前使用方式以根目录 `README.md` 和 [文档索引](README.md) 为准。

完整的原始 900 行设计计划仍保存在 Git 历史的提交 `f5592eac1c9a0fe7a3341b5420e3382cbb4b6e6b` 中。本归档只保留已经落地的目标、边界和阶段结果，避免历史“未开始”状态继续误导维护者。

## 产品定位

PersonaDock 1.0 是一个本地优先、跨 Agent 的 Persona Control Plane：

```text
自然语言 / 聊天记录 / 既有 Hermes Profile / 既有 OpenClaw Agent
                              ↓
                     Canonical Persona v3
                              ↓
       审核 · 版本 · 测试 · 快照 · 记忆治理 · 同步策略
                              ↓
                     PersonaPack Manifest v2
                              ↓
          Hermes Adapter             OpenClaw Adapter
                              ↓
          多实例绑定、部署、同步、验证、回滚与审计
```

PersonaDock 负责：

- Persona 创建、聊天蒸馏、混合生成和改进。
- 既有运行时人格发现、接管和标准化。
- Canonical Persona、版本、测试和 PersonaPack。
- Hermes/OpenClaw 原生格式编译和部署。
- 共享 Memory 候选、审核、冲突和传播。
- Reviewed Session Summary 交接。
- 本地 Web 控制台与 CLI。

PersonaDock 不负责：

- 重新实现 Hermes/OpenClaw 聊天运行时。
- 管理模型 Provider、API Key、OAuth 或 Gateway Token。
- 默认复制或同步原始 Session/Transcript。
- 把平台运行目录作为 Persona 唯一主源。
- 无确认覆盖平台专属配置、Memory、Session 或 State。

## 稳定设计原则

1. Canonical Persona 是人格定义主源。
2. 平台目录是构建产物和运行状态，不是主源。
3. 所有写入先发现、预览和生成计划。
4. 部署更新必须可验证、可快照、可回滚、可审计。
5. 原生平台命令优先；Legacy Filesystem 只作为显式兼容模式。
6. Persona Definition、共享 Memory、平台本地 Memory 和 Session 分层管理。
7. Memory 与 Session Summary 默认审核后传播。
8. 敏感内容、外部来源和 Agent 推断不得静默自动共享。
9. 原始 Session/Transcript 不跨运行时同步。
10. Web 与 CLI 调用同一核心服务。

## 已完成阶段

| 阶段 | 交付结果 |
|---|---|
| Phase 0 | 安全部署计划、Doctor、本地 Web 骨架、远程绑定 Token 保护 |
| Phase 1 | SQLite Persona Registry、Runtime Discovery、Persona/Instance 查询 |
| Phase 2 | Adopt、预接管快照、Binding、PersonaPack/Hermes/OpenClaw 导出 |
| Phase 3 | Canonical Persona v3、v2→v3 迁移、Semantic Diff、确定性测试 |
| Phase 4 | Hermes Profile Distribution 原生部署、验证、快照和回滚 |
| Phase 5 | OpenClaw Agent/Workspace 原生部署，本地/Docker/SSH Transport |
| Phase 6 | Review-first 跨运行时 Memory 同步、冲突、去重和循环抑制 |
| Phase 7 | Reviewed Session Summary、脱敏预览、传播和来源回声抑制 |
| Phase 8 | Adapter API 1.0、签名、私有备份、Character Card、Golden/平台矩阵 |

## 1.0 稳定契约

- Canonical Persona Schema v3
- PersonaPack Manifest v2
- Adapter API 1.0
- Registry Schema v3
- Python 3.10–3.13
- Linux x86_64/ARM64、macOS Intel/Apple Silicon、Windows x86_64 独立程序

## 当前架构文档

- [控制平面总览](control-plane.md)
- [Registry 与运行实例发现](registry-discovery.md)
- [Canonical Persona v3](canonical-persona-v3.md)
- [Hermes 原生 Adapter](hermes-native-adapter.md)
- [OpenClaw 原生 Adapter](openclaw-native-adapter.md)
- [受控 Memory 同步](governed-sync.md)
- [Reviewed Session Summaries](session-summaries.md)
- [兼容承诺](compatibility.md)
- [迁移与回滚](migration-and-rollback.md)

任何新的开发路线应创建独立 RFC/roadmap，不再在本历史文件中追加“进行中”状态。
