# WSL 执行桥接故障回退

状态：implemented
类型：process
Owner：AGENTS.md
取代：无

## 问题

默认沙盒可能在启动 WSL 命令前以 `helper_unknown_error: setup refresh had errors` 失败。当前规则只允许重试并请求重开；当 WSL 与仓库本身正常、但 Codex 沙盒刷新持续失败时，新任务仍会重复停在同一故障，无法读取源码。

## 决策

默认执行失败后先重试一次。若错误仍为执行桥接层故障，允许申请沙盒外授权，但命令继续通过 `wsl.exe` 在 `/home/wang/counseling` 执行，不改用 Windows 文件工具。授权执行仍失败时才报告并请求重开。

## 替代方案

- 保持只重开任务：边界最简单，但同一宿主执行层故障会在新任务中重复出现。
- 改用 Windows 文件工具：可能绕过故障，但会混淆 WSL 源码事实路径，因此拒绝。
- 不经授权直接绕过沙盒：缺少明确授权边界，因此拒绝。

## 后果

相同的沙盒刷新故障不再强制通过新任务重复尝试。回退仍需显式授权，仍由 `wsl.exe` 访问 WSL 事实路径，并且不能扩大用户原始任务范围。授权被拒绝或授权执行仍失败时，任务继续显式停止。

## 验证

- `grep -n -A5 -B1 'helper_unknown_error' AGENTS.md`：Inspected，规则同时包含重试、授权回退、WSL 限定、Windows 工具禁用和最终停止条件。
- `python3 scripts/verify_engineering_contracts.py`：Passed，检查 59 条 decision、5 个 workflow、4 个 AGENTS 文件、107 篇文档、25 个路由和 260 个 Web 源文件。
- `python3 -m unittest scripts.test_verify_engineering_contracts`：Passed，65 个测试通过。
- `git diff --check`：Passed。
- `cd docs && pnpm run build`：Not run，裸 WSL 环境未安装 `pnpm`。
