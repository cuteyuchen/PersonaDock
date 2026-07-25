# PersonaDock 文档索引

本目录对应 PersonaDock `1.0.x`。根目录 `README.md` 提供快速上手；这里按任务组织设计、运行和维护文档。

## 从这里开始

- [控制平面总览](control-plane.md)：当前架构、数据边界、主要工作流和 Web 页面。
- [阶段与稳定契约](PHASE_STATUS.md)：Phase 0–8 的最终合并状态以及 1.0 兼容边界。
- [迁移与回滚](migration-and-rollback.md)：应用、Registry、Persona、Hermes/OpenClaw、Memory 与 Session Summary 的恢复流程。
- [维护审计](maintenance-audit.md)：分支、废弃代码、历史文档和兼容入口的清理结论。

## 创建和管理 Persona

- [Canonical Persona v3](canonical-persona-v3.md)
- [Registry 与运行实例发现](registry-discovery.md)
- [接管、快照与导出](adopt-export.md)

## 部署到运行时

- [Hermes 原生 Profile Adapter](hermes-native-adapter.md)
- [OpenClaw 原生 Agent/Workspace Adapter](openclaw-native-adapter.md)
- [Docker 与远程运行时](docker-install.md)

## Memory 与会话交接

- [受控跨运行时 Memory 同步](governed-sync.md)
- [Reviewed Session Summaries](session-summaries.md)

PersonaDock 不同步原始 Session 或 Transcript。只有经过过滤、脱敏和审核的 Session Summary 才能进入共享 Memory 传播链路。

## 信任、备份与兼容

- [1.0 兼容承诺](compatibility.md)
- [PersonaPack 信任与私有备份](trust-and-private-backup.md)
- [Character Card 兼容](character-card-compatibility.md)
- [OpenPersona 兼容研究](openpersona-compatibility.md)

## 发布与历史

- [发布流程](publishing.md)
- [版本历史](releases.md)
- [历史重构路线](REFACTOR_PLAN.md)

`REFACTOR_PLAN.md` 是 Phase 0–8 的历史设计记录，不再作为当前功能状态来源。当前状态以 `PHASE_STATUS.md`、根目录 `README.md` 和对应功能文档为准。

## 文档维护规则

1. 用户命令优先写 `deploy`；`install` 只作为 1.x 迁移兼容别名出现。
2. Hermes/OpenClaw 默认使用原生 Adapter；Legacy Filesystem 只能在明确兼容章节中出现。
3. Phase 标题可以保留功能来源，但不得把已经完成的后续阶段写成“未实现”。
4. Schema、Manifest、Adapter API 或 Registry Schema 发生变化时，同步更新 `compatibility.md`、`PHASE_STATUS.md` 和 `CHANGELOG.md`。
5. 发布命令、平台矩阵和资产名称必须与 GitHub Actions 工作流保持一致。
