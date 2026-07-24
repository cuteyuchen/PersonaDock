# PersonaDock 重构阶段状态

本文件记录 `docs/REFACTOR_PLAN.md` 的实际执行状态。每个阶段均通过独立 PR 和 squash commit 合并。

| 阶段 | 状态 | PR | 合并提交 |
|---|---|---:|---|
| 重构路线文档 | 已完成 | #13 | `f5592eac1c9a0fe7a3341b5420e3382cbb4b6e6b` |
| Phase 0：安全核心与 Web 骨架 | 已完成 | #14 | `35fbc9cca5f259a2b7412383e44976a2e1f54f51` |
| Phase 1：Persona Registry 与 Discovery | 已完成 | #15 | `0b904dc4358f5e9eb88908c12aeb431962f5fe8c` |
| Phase 2：Adopt、Snapshot 与 Export | 已完成 | #16 | `240aa9871b81acf23e4683f1f9447331c96a78a9` |
| Phase 3：Canonical Persona v3 | 已完成 | #17 | `52b08790434e7fa8fcac29b6e81362f2ab459908` |
| Phase 4：Hermes 原生 Adapter | 已完成 | #18 | `18d98b97b17606ad852ae18aaf3f2b322bbdeb84` |
| Phase 5：OpenClaw 原生 Adapter | 进行中 | #19 | — |
| Phase 6：受控共享记忆同步 | 未开始 | — | — |
| Phase 7：会话摘要 | 未开始 | — | — |
| Phase 8：1.0 稳定化 | 未开始 | — | — |

## 阶段规则

- 只有常规 CI、独立程序验证和五平台 Release dry-run 全部成功后，阶段才能标记为完成。
- 阶段范围发生变化时，先更新 `docs/REFACTOR_PLAN.md` 或本状态文件，再修改实现。
- 平台 Adapter 之前不得恢复不可信路径的静默写入。
- Memory 和 Session 同步之前必须完成来源、审核和冲突模型。
