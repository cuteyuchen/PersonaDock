# PersonaDock 重构阶段状态

本文件是 Phase 0–8 与 PersonaDock 1.0 稳定契约的唯一状态来源。`REFACTOR_PLAN.md` 只保留历史设计摘要，不再维护执行状态。

| 阶段 | 状态 | PR | 合并提交 |
|---|---|---:|---|
| 重构路线文档 | 已完成 | #13 | `f5592eac1c9a0fe7a3341b5420e3382cbb4b6e6b` |
| Phase 0：安全核心与 Web 骨架 | 已完成 | #14 | `35fbc9cca5f259a2b7412383e44976a2e1f54f51` |
| Phase 1：Persona Registry 与 Discovery | 已完成 | #15 | `0b904dc4358f5e9eb88908c12aeb431962f5fe8c` |
| Phase 2：Adopt、Snapshot 与 Export | 已完成 | #16 | `240aa987dd8240e9812573bbccb1384f7d9420c7` |
| Phase 3：Canonical Persona v3 | 已完成 | #17 | `52b08790434e7fa8fcac29b6e81362f2ab459908` |
| Phase 4：Hermes 原生 Adapter | 已完成 | #18 | `18d98b97b17606ad852ae18aaf3f2b322bbdeb84` |
| Phase 5：OpenClaw 原生 Adapter | 已完成 | #19 | `bcfc442359159308759467b943a7176a779a76df` |
| Phase 6：受控共享记忆同步 | 已完成 | #20 | `bb68484257182a6e9c0dd659b66d3a303cb9ba2c` |
| Phase 7：会话摘要 | 已完成 | #21 | `4eadd0381bd28242bd49f1bffade87b97eb31f53` |
| Phase 8：1.0 稳定化 | 已完成 | #22 | `ecce08f1ca76eabec9cbf754526a0e74407ab591` |
| 1.0 完成标记 | 已完成 | #23 | `637a5a573e31474a77fc3bcd2ae98824098923ff` |

## 当前稳定契约

- PersonaDock 应用版本：`1.0.0`
- Canonical Persona Schema：v3
- PersonaPack Manifest：v2
- Adapter API：`1.0`
- Registry Schema：v3
- Python：3.10–3.13
- 独立程序：Linux x86_64/ARM64、macOS Intel/Apple Silicon、Windows x86_64

## 分支说明

PR #24 是基于 Phase 6 的重复 Phase 7 实现，未合并。主线已经通过 PR #21、#22 和 #23 包含更新的 Session Summary 与 1.0 稳定实现，因此 #24 不属于待合并功能。

已 squash 合并的历史 PR 分支不应再次普通 merge；其功能状态以上表中的 `main` 合并提交为准。

## 阶段验收规则

- 常规 CI、独立程序验证、Python 兼容矩阵、真实 Docker Adapter 验收和五平台 Release dry-run 全部成功后，阶段才能标记为完成。
- 平台 Adapter 不得恢复不可信路径的静默写入。
- Memory 和 Session Summary 同步必须保留来源、审核、冲突与传播记录。
- 原始 Session、Transcript、认证和运行时 State 不得进入 PersonaPack 或跨运行时同步。
- 1.x 内必须遵守 Schema、PersonaPack 和 Adapter API 的兼容承诺。
