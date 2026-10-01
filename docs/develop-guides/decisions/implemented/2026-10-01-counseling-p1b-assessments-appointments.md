# 固定量表与内部预约闭环

状态：implemented
类型：feature
Owner：backend/counseling/src/counseling/assessments/service.py
取代：无

## 问题

档案驱动 AI 文书之外，辅导员还需要保存可复核的固定版本量表结果，并在同一权限、事务与审计边界内维护只供机构内部使用的预约状态。

## 决策

- 首个固定量表是 PHQ-9 v1。服务端拥有题目顺序、严格整数答案、总分与分段规则；结果冻结量表代码、版本、答案、总分和分段，不改变风险投影，也不构成诊断。
- 施测只允许负责人录入和读取。创建在持锁的 active 档案事务内使用稳定 request_id 幂等；结果由数据库触发器禁止更新和删除。
- 内部预约保存起止时间、方式、地点/说明、状态和乐观版本。创建时意图单独冻结用于长期幂等比较；当前预约可改期，并按 scheduled 到 arrived 到 completed，或 scheduled 到 no_show/canceled 收敛，终态不恢复。
- 创建、修改、状态迁移和包含量表答案或预约备注的列表读取都追加不含正文的审计事件。工作台调用真实 API、从 PostgreSQL 回读，并把 UTC 时间按客户端时区展示。
- 系统不接入来访者门户、外部日历、短信、自动通知、在线填写、通用量表编辑器或自动风险处置。

量表流程由 `counseling.assessments` 拥有，预约流程由 `counseling.appointments` 拥有，持久化约束由 counseling schema migration 拥有，页面装配由 counseling Web domain 拥有。

## 替代方案

- 只保存总分或允许前端提交总分：无法复核可信计分，拒绝。
- 建设可配置量表和通用预约工作流：当前没有消费者，拒绝。
- 写入外部日历：引入未授权外部副作用，拒绝。

## 后果

- counseling schema v7 为预约增加创建意图快照并回填 v6 数据，v8 由数据库触发器拒绝修改快照字段。
- PHQ-9 分数不自动改变风险等级或代替辅导员判断；规则变化必须新增量表版本，不能原地修改历史语义。
- 时间输入必须带时区，数据库保存 UTC 无时区值，API 输出 UTC，客户端负责本地化。
- 当前范围只覆盖机构内部档案工作台；外部日历、通知和来访者自助入口需要新的决策与授权边界。

## 验证

- `cd backend && uv run ruff check counseling/src/counseling/storage/schema.py counseling/src/counseling/assessments/service.py counseling/src/counseling/appointments/service.py test/unit/storage/test_counseling_schema.py test/integration/storage/test_counseling_schema_postgres.py test/integration/api/test_counseling_p1b_api.py`：通过。
- `cd backend && uv run --group test pytest -q test/unit/services/test_counseling_assessments.py test/unit/storage/test_counseling_schema.py test/unit/architecture/test_counseling_package_boundary.py`：31 passed。
- `docker compose exec -T api pytest -q test/integration/storage/test_counseling_schema_postgres.py test/integration/api/test_counseling_p1b_api.py test/integration/api/test_counseling_minimal_workflow_api.py`：5 passed，覆盖 v6→v8、严格输入、并发幂等、越权、结案后重放、改期后重放、取消终态、审计与数据库不可变。
- `cd web && node --test test/unit/counselingBoundary.test.js`：5 passed；`eslint . --max-warnings=0` 与 `vite build` 通过。
- 尚未执行真实浏览器交互与真实模型生成质量 Gate；这两项不改变当前 P1B 后端协议和持久化实现事实。
