# PersonaDock 1.0 维护审计

审计基线：`main` 提交 `637a5a573e31474a77fc3bcd2ae98824098923ff`。

## 分支与 PR 结论

### 已合并开发线

Phase 0–8 以及 1.0 完成标记已经通过 PR #14–#23 以 squash 方式进入 `main`。这些 PR 的原始开发分支即使仍保留，也不应再次执行普通 merge；重复合并会重新引入已 squash 的提交和旧阶段状态。

### PR #24

PR #24 `phase-7/session-summaries` 未合并。它从 Phase 6 基线重新实现另一套 Phase 7，在审计时相对 `main`：

- ahead 20 commits
- behind 3 commits
- merge base 为 Phase 6 提交 `bb68484257182a6e9c0dd659b66d3a303cb9ba2c`

主线已经包含 PR #21 的 Session Summary、PR #22 的 1.0 稳定化以及 PR #23 的完成状态。PR #24 还会把 CLI 入口、阶段状态和部分 Session 模型切回较早方案，因此判定为废弃重复分支，不合并其代码。

## 废弃代码检查

### 已删除的历史实现

- `CompanionVault` 包、Schema、旧安装器和文档已在 PR #6 删除。
- 独立 `persona-distiller` Skill 已在 PR #8/#11 删除。
- 当前仓库中的相关字符串只用于 CI/CODEOWNERS 防回归检查，不是运行时代码。

### 保留的兼容代码

以下内容仍被调用，不能按“死代码”删除：

- `personadock install`：`deploy` 的弃用别名，用于 1.x 迁移兼容。
- Legacy Filesystem Adapter：默认关闭，只能通过显式兼容参数使用。
- `src/persona_dock/installer.py`：仍为 legacy rollback、uninstall、status 和文件部署计划提供实现。
- `cli.py → canonical_cli.py → hermes_cli.py → openclaw_cli.py → sync_cli.py → session_cli.py → stable_cli.py`：这是当前 argparse 命令组合链，不是多份废弃 CLI。
- Schema v2 读取和 v2 → v3 迁移：属于 1.0 兼容承诺。

### 技术债务但非废弃代码

- `session_runtime.py` 通过替换 Session Engine 绑定和补充 Adapter capability 复用成熟 CLI。它有测试覆盖，但后续可以在 1.1 内部重构为显式依赖注入。
- 分阶段 CLI 组合层较深。1.x 内不宜删除公共命令；可在保持命令和输出兼容的前提下逐步扁平化。

### 静态扫描

- 未发现 `TODO`、`FIXME` 或 `XXX` 遗留标记。
- 未发现可直接删除且没有引用的明确运行时模块。

## 废弃文档检查

本次发现并处理：

- `control-plane.md`：仍停留在 Phase 0，并把 Registry、原生 Adapter 和同步写成未实现。
- `registry-discovery.md`：仍把接管、Docker/远程、Memory 和 Binding 写成后续能力。
- `docker-install.md`：仍以弃用的 `install` 和直接目录写入为主，没有体现原生 Hermes/OpenClaw Adapter。
- `README.md`：Memory 同步文档链接指向不存在的 `governed-memory-sync.md`。
- `PHASE_STATUS.md`：Phase 2 合并提交哈希错误。
- `REFACTOR_PLAN.md`：历史状态表与 1.0 当前状态冲突。
- `site/index.html`：仍只描述早期 Persona Builder/安装器定位。

这些内容在本维护分支中更新为 1.0 当前行为；历史路线只保留为归档摘要，最终状态统一由 `PHASE_STATUS.md` 管理。

## 后续清理规则

1. 合并功能 PR 后删除开发分支，避免 squash 后的旧分支持续与 `main` 分叉。
2. 关闭但未合并的重复 PR 必须在 PR 描述中标明替代 PR/提交。
3. 每次发布运行文档关键字检查：`未实现`、`后续阶段`、`personadock install`、错误文档路径和旧版本号。
4. 只有确认引用为零、兼容承诺不再要求、测试和发布工作流均通过后，才能删除兼容代码。
