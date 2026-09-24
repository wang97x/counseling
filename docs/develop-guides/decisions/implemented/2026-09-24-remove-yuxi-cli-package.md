# 移除 yuxi-cli 独立包

状态：implemented
类型：simplification
Owner：Makefile
取代：无

## 问题

仓库曾维护、测试并发布 `packages/yuxi-cli` 独立包，同时在依赖审计、Dependabot、发布工作流和当前文档中保留配套入口。该包不再需要，继续保留会增加独立依赖锁、发布凭据边界和测试维护面。

## 决策

仓库不再包含 `packages/yuxi-cli`。只为该包存在的发布工作流、依赖治理装配、当前使用文档及其测试断言一并移除。changelog 与归档决策保留历史事实；后端已有 API 与前端页面继续提供兼容能力，不把独立包下线扩大为服务端公开能力下线。

## 替代方案

- 保留：继续承担包、锁文件、测试和发布维护成本，不满足删除目标。
- 缩小：停止发布但保留源码，会留下没有现行 consumer 的维护表面。
- 替换：当前没有新的 CLI consumer 或替代实现需求，引入替代物没有收益。
- 移除：完整移除独立包及其仓库装配，范围最小且直接满足目标。

## 后果

- 仓库不再构建、测试或发布 Python CLI，也不再为它维护独立锁文件和依赖审计入口。
- 已安装的外部 `yuxi-cli` 不再从本仓库获得新版本；历史发布产物不会因源码删除自动撤回。
- 服务端 CLI 认证与 discovery 能力仍是兼容表面，后续下线需要独立处理公开兼容与持久状态。

## 验证

- `test ! -e packages/yuxi-cli && test ! -e .github/workflows/publish-yuxi-cli.yml`：通过，包与独立发布入口不存在。
- 当前文档、Makefile、workflow、Dependabot 与脚本的负向搜索无旧包引用；changelog、归档和历史决策除外。
- `python3 -m unittest scripts.test_dependency_update_policy scripts.test_release_workflows`：9 项通过。
- `python3 scripts/verify_engineering_contracts.py`：通过。
- `docs/node_modules/.bin/vitepress build docs` 的等价目录内命令通过并完成页面渲染。
- `git diff --check`：通过。

旧能力不存在：包源码、包测试、独立发布工作流、依赖更新与审计装配、当前安装和使用说明均不存在。

重新引入条件：出现明确的 CLI 用户需求、版本兼容承诺、维护 Owner 和可执行发布/测试证据时，以新的 feature 决策重新引入。
