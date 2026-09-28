# 业务模块拥有用户认证与组织

状态：implemented
类型：architecture
Owner：backend/counseling/src/counseling/identity/__init__.py
取代：无

其中“Yuxi 直接读取 counseling 身份契约”和“保留身份 re-export”的条款，已由
[心理辅导与 Yuxi 端口边界收敛](2026-09-28-counseling-yuxi-port-boundaries.md)取代；其余身份 Owner 决策继续有效。

## 问题

账号、密码与 OIDC 登录、API Key、部门、业务角色和用户管理曾分散在 `yuxi`
包与 `server` 路由中，导致 AI 平台解释业务身份并拥有身份生命周期。

## 决策

- `counseling.identity` 拥有用户、部门、登录/OIDC、API Key、业务角色、组织管理、
  身份审计及其 ORM、repository、service 和 HTTP 实现。
- 现有 `users`、`departments` 等表名以及 `/api/auth/*`、`/api/departments/*`、
  `/api/user/*` wire 契约保持不变；`server` 只装配路由。
- Yuxi 保留 Agent、Run、知识、Skill 与工作区等 AI 能力。AI 链路可以读取
  `counseling.identity` 提供的身份契约和查询结果，但不定义密码、业务角色、部门管理
  或身份写入生命周期。
- counseling Schema v3 拥有当前身份 DDL，把历史 `technical_admin` 转换为
  `super_admin`；历史 Yuxi migration 只保留已发布数据库的线性升级事实。
- 业务角色固定为 `super_admin`、`business_admin`、`counselor`。平台
  `user/admin/superadmin` 仅保留 wire 与 AI 管理兼容语义，不能推导业务权限。
- 初始化种子账号显式写入与用途一致的业务角色，不依赖平台角色回填。兼任角色按能力并集合并，
  `business_admin` 不得降低同一账号已有的 `super_admin` 权限。

## 替代方案

- 只迁移业务角色映射：认证、部门和持久化 Owner 仍在 Yuxi，未采用。
- 在 Yuxi 保留身份 repository 并让 counseling 包装：仍存在两个身份 Owner，未采用。
- 恢复按平台角色自动回填业务权限：会重新建立平台字段到业务授权的隐式关系，未采用。
- 删除全部身份模型 re-export：后续确认仓库内无消费者，并由端口边界决策接受该兼容收窄，已采用。
- 同时改表名、HTTP 路径或拆分微服务：把领域迁移与公开兼容、分布式事务叠加，
  当前没有消费者收益，未采用。

## 后果

- 身份写入和授权规则只有一个业务 Owner；Yuxi 不再提供身份 service、repository、
  router 或业务角色实现。
- Yuxi 的 AI 查询通过自身只读身份端口消费脱敏快照，不直接导入 counseling；
  `server` composition root 装配业务实现，Yuxi 不再保留身份模型 re-export。
- 超级管理不因系统配置身份获得个案正文或个人知识访问；团队知识管理只由显式
  `business_admin` 及共享范围共同决定。
- 旧表名和 HTTP 契约保留，避免用户重新登录或下游同步切换。

## 验证

- `docker compose exec -T api uv run --no-sync --group test pytest -q test/unit`：
  1985 passed，53 skipped。
- 临时 `super_admin` 凭据下运行认证、部门和 API Key 集成测试：30 passed；测试账号
  及关联审计、API Key、CLI 会话已删除。
- counseling Schema、业务角色、个人/团队知识集成集：10 passed，24 项仅因未配置
  通用集成凭据跳过；同一凭据覆盖的身份集已另行全部执行。
- `docker compose exec -T web pnpm run test:unit`：361 passed。
- 前端改动文件定向 ESLint 通过；全量 ESLint 仅剩未改动
  `pdfPreviewAssets.test.js` 的两个既有 `Buffer` `no-undef` 错误。
- Compose 中 API、Worker、PostgreSQL、Redis、MinIO 与 Milvus 最终健康。
- 迁移补完后，架构边界检查、相关 Python 文件 AST 解析、工程契约检查及其 65 个单测、
  前端角色映射 smoke 与 `git diff --check` 通过。
- 种子角色、复合超级管理员路由和 v2→v3 真实 PostgreSQL 回归测试已加入；当前宿主缺少
  Docker、pytest/SQLAlchemy、pnpm 与前端依赖，补完后的后端 unit/integration 和 Web unit 未在本宿主重跑。
