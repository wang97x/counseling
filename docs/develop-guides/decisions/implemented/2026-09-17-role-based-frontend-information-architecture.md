# 按业务角色收敛前端信息架构

状态：implemented
类型：feature
Owner：web/src/utils/frontendAccess.js

## 问题

登录用户原先统一进入通用 Agent 页面，侧栏也向业务角色和超级管理员展示通用新建对话、个人空间等 Yuxi 平台入口。心理辅导业务要求档案成为业务会话的唯一入口，同时保留管理角色的技术运维入口。前端隐藏不是后端授权边界，但导航、默认落点和直接 URL 访问需要表达一致的角色信息架构。

## 决策

由 `frontendAccess` 根据平台角色和业务角色派生前端能力与默认首页，用户 Store、路由守卫、登录跳转、侧栏和页面内技术标签共同消费该事实。

- 辅导员默认进入 `/students`，只显示档案、获授权知识和账户设置。
- 业务管理员默认进入 `/students`，只显示部门档案最小元数据与团队知识入口，不继承技术控制台。
- 超级管理员默认进入 `/dashboard`，保留 Dashboard、用户与部门管理及完整技术管理入口，但不进入通用新建对话或个人空间。
- 未绑定业务角色的平台 `admin` 继续获得技术控制台和平台工作区能力，但不获得超级管理员专属的 Dashboard 与用户管理入口；已映射为 `business_admin` 的账号按业务管理员边界处理。
- 未迁移的 `technical_admin` 身份继续获得技术控制台入口；显式同时拥有该角色的业务管理员才显示技术模块。
- 档案关联会话允许辅导员从带 `student_id` 的 `/agent/:thread_id` 进入，路由通过学生会话列表接口确认 Thread 确实属于当前有权档案；既有平台 `admin` 仍可进入原有平台会话。通用 `/agent` 新建对话、`/workspace` 与 CLI 授权页不向业务管理员或超级管理员开放，不能通过直接 URL 绕过。

所有实际操作仍服从现有后端授权。本记录不迁移 `technical_admin` 数据；辅导员自助建档的后端权限由[辅导员自助建档与档案内助手会话](../proposed/2026-09-17-counselor-owned-record-workflow.md)拥有。

## 替代方案

- 只隐藏侧栏：直接输入 URL 仍会进入不属于该角色的信息架构，登录跳转也继续错误，因此拒绝。
- 删除原 Yuxi 页面：会破坏业务管理员和超级管理员当前需要复用的平台能力，因此拒绝。
- 用前端角色映射同时拥有建档授权：前端不是授权边界；建档权限由后端业务能力与真实 HTTP 测试独立闭合，因此拒绝。

## 后果

- 角色默认首页、导航呈现和路由直达限制由同一能力映射决定，避免组件分别解释角色。
- 原 Yuxi 模块仍保留在代码中，根据角色选择性呈现；本次是信息架构收敛，不是删除平台能力。
- 后端仍是最终授权边界；前端列表、详情和关联会话能力分别收敛，业务管理员不会因可见档案元数据而进入个案正文。
- `/agent/:thread_id` 的档案归属与可见性必须继续由后端校验，前端路由能力不能证明 Thread 所有权。

## 验证

| 验收主张 | 证据 | 结果 |
|---|---|---|
| 三类角色获得约定默认首页与能力 | `web/test/unit/frontendAccess.test.js` | Passed |
| 辅导员、业务管理员和超级管理员不能直达通用对话、工作区或 CLI 授权页；辅导员只能进入接口确认的关联会话 | Vue Router 内存历史负向单测与关联会话单测 | Passed |
| 导航、设置、扩展页和登录跳转消费统一能力 | 相关 Web unit | Passed |
| 前端静态检查与生产构建 | `eslint . --max-warnings=0`、`vite build` | build Passed；lint 在当前依赖环境对全部 Vue 文件报告 `Invalid Version: main` |
| Web 全量单测 | `node --test --test-concurrency=1 "test/**/*.test.js" "test/**/*.spec.js"` | 72/73 通过；唯一失败为 PDF 资产测试监听端口 `EPERM` |
| 文档构建 | `vitepress build` | Passed |
| 工程契约单测 | `python3 -m unittest scripts.test_verify_engineering_contracts` | 64 Passed |
| 工程契约检查 | `python3 scripts/verify_engineering_contracts.py` | Passed |
| Docker 页面验证 | Compose 与真实浏览器 | 未执行：当前宿主没有 Docker 命令 |
