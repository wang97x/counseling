# Backend 约定

本目录承载 FastAPI、业务包、Yuxi 与持久化。读本文件、源码与测试；陌生或跨服务修改读[架构文档](../ARCHITECTURE.md)，心理辅导修改读[产品约束](../docs/develop-guides/counseling-product-contract.md)。

## 边界与实现

- `server/routers` 处理 HTTP 模型、认证依赖、状态码、端口适配器和响应装配；心理辅导用例进入 `counseling/src/counseling`，通用平台用例进入 `package/yuxi/services`，跨 repository 用例只有一个事务 Owner。
- `server` 只负责应用装配；账号、认证、部门与业务授权属于 `counseling.identity`，AI、Agent、模型、知识和 Run 属于 `yuxi`。Yuxi 只能消费有界身份读取能力，不得拥有用户写入、业务角色解释、部门管理或认证密钥逻辑。心理辅导模型、仓储、用例和新增 DDL 不得放回 Yuxi 命名空间。
- PostgreSQL 拥有 Request、Run、Message、权限和业务终态；Redis/ARQ 只承担投递与短期事件。写入、提交和发布顺序必须显式。
- parser、HTTP、模型/tool JSON、持久化、worker、process、wire 和用户路径是校验边界。权限、路径隔离及副作用在 executor/repository fail-closed。
- AgentRun 状态、lease、输出和终态投影由 repository/service 维护；并发、事务、Schema 和 PostgreSQL 专属语义使用真实 PostgreSQL 验证。
- 心理辅导正式记录与草稿分离；生成、附件和归档绑定有权档案及对应 request/run。个人笔记不进入模型，风险提示不执行自主干预。
- Python 使用 3.12+。保持主流程线性；仅为复用、隔离副作用或降低认知负担拆函数，不新增一次性抽象或静默 fallback。
- Schema 演进必须幂等并有真实 PostgreSQL 测试。新增函数或类使用简洁中文 docstring。

## 验证路由

纯逻辑跑 unit；API、权限和持久化跑 integration；Run、worker、队列、文件与恢复跑 E2E。命令见[测试规范](../docs/develop-guides/testing-guidelines.md)。
