# 连续服务与人工安全闭环

状态：implemented
类型：feature
Owner：backend/counseling/src/counseling/continuity/service.py
取代：无

## 问题

档案需要在既有咨询记录、人工风险事件、量表和内部预约之外，保存可追溯的辅导方案调整、人工危机处置、内部转介回访，以及不会绕过人工判断的 AI 风险提示。

## 决策

- `counseling.continuity` 拥有追加式方案版本、部门危机协议、人工危机工单事件、内部转介和回访。方案历史与协议历史不可覆盖；工单冻结创建时的协议、负责人和时限，并只由显式人工事件推进。
- 内部转介冻结授权状态与最小材料范围。业务管理员只能读取同部门、不含原因和材料正文的队列元数据，并作出接收或拒绝决定；系统不发送材料或外部通知。
- `counseling.risk_hints` 拥有离线评测和提示人工核实。业务管理员发布评测时直接计算召回率和误报率，只持久化数据集引用、指纹、模型引用、固定阈值和混淆矩阵，不保存样本正文。
- 只有召回率至少 95%、误报率不超过 5%的评测，加上当前有效的部门危机协议，才能创建 `pending_review` 提示。负责人只能采纳或拒绝；采纳不会自动改变学生风险投影、创建人工风险事件或成立危机工单。
- 提示只接受已完成 AI Work Item 的显式 Run 输出，并冻结 Work Item、Run 和输出消息标识；输出模型必须与评测模型一致，消息正文必须满足严格版本化 JSON 契约。
- 正文与个案提示只对当前负责人可见。状态变化和敏感列表读取在 owning service 的同一事务中追加不含正文的审计记录。
- counseling schema v14 持久化 P2 状态：数据库校验评测矩阵与派生指标一致，以唯一应用版本绑定危机事件、冻结转介决定，并冻结提示的 Work Item/Run/消息来源与人工终态。工作台从真实 API 加载提示，负责人按版本提交采纳或拒绝，完成的核实结果进入档案时间线。

方案、工单、转介和回访由 `counseling.continuity` 拥有；评测与提示由 `counseling.risk_hints` 拥有；数据库约束由 counseling schema migration 拥有；页面装配由 counseling Web domain 拥有。

## 替代方案

- 继续用自由文本风险事件和时间线表达全部 P2：无法证明负责人、时限、协议版本、复核和关闭，拒绝。
- 建设通用工作流引擎：当前没有跨业务消费者，且会扩大状态机与权限表面，拒绝。
- 让辅导员自行维护危机协议：协议是部门级治理边界，拒绝。
- AI 提示直接创建风险事件或工单：会混淆模型输出与人工事实并绕过核实，拒绝。

## 后果

- 危机流程只记录机构内部人工事实，不编码临床判断，不替代机构危机预案，也不执行自主干预。
- schema v14 是启动前置条件；DDL 与版本发布在同一事务中完成，应用不会在旧 schema 上自动建表或降级运行。
- v10/v11 若已有无法证明来源的旧提示，或 v12 若已有无法证明应用顺序的旧危机事件，迁移会在修改表结构前显式失败，不伪造历史或静默兼容。
- 评测 fixture 只证明指标算法和 fail-closed 装配。真实模型只有在业务管理员用授权的独立标注集发布通过评测后，才具备相应部门提示的门禁资格。
- 当前范围不包含外部通知、材料发送、来访者入口、自动干预、通用工作流或评测样本存储。

## 验证

| 验收主张 | 失败面 | 直接证据 | 负向案例 | 结果 |
|---|---|---|---|---|
| 方案历史追加且调整可追溯 | 覆盖旧版本或跨档案依据 | P2 真实 HTTP + PostgreSQL 回读 | 跨负责人、不可变历史更新 | 通过 |
| 工单冻结有效协议且只由人工推进 | 无协议创建、非法迁移、并发重放或自动关闭 | P2 真实 HTTP + PostgreSQL 回读 | 缺协议、跳过复核、直接 SQL 绕过、同请求并发重放 | 通过 |
| 转介与回访保留授权和独立状态 | 管理员读到正文或把内部准备当外发 | P2 wire 响应 + PostgreSQL 回读 | 未授权材料、跨角色、直接 SQL 非法状态 | 通过 |
| AI 提示受指标、真实模型输出和协议门禁且只待人工核实 | 指标错误、伪造来源或提示自动改变风险/成立工单 | evaluator unit + 真实 Work Item/Run/输出消息 + P2 HTTP + 数据库回读 | 空/单侧数据、严格布尔、漏标、误报超限、矛盾矩阵直写、低于阈值、模型不匹配、协议缺失、越权、篡改来源、同请求并发重放 | 机制通过；真实独立数据集与真实模型质量未执行，门禁资格未声明 |
| 工作台按档案隔离并刷新回读 | 演示回退、晚到响应或切换污染 | 定向 Web unit 19 passed；ESLint 与生产 build 通过 | 学生切换、重复动作、API 失败边界 | 代码与构建通过；浏览器验收因 Computer Use helper 启动失败未执行 |
| Schema 原子升级且数据库拒绝非法写入 | DDL/版本分裂、旧提示或旧事件伪造历史、只靠 Python 校验 | schema unit + 隔离 PostgreSQL migration（含 v11/v12 旧数据与 v13→v14 历史不一致失败回滚 oracle）+ 开发库 v14 只读回读 | 旧提示/旧事件显式失败、悬空末事件与事件计数不一致时版本和 DDL 同步回滚、指标矛盾、旧事件重用、决定篡改、非法状态、不可变来源更新 | 通过 |

执行证据：

- `cd backend && uv run ruff check ...`：P2 相关后端文件通过。
- `cd backend && uv run --group test pytest -q test/unit/storage/test_counseling_schema.py test/unit/services/test_counseling_risk_hint_evaluation.py`：27 passed。
- `docker compose exec -T api pytest -q test/integration/storage/test_counseling_schema_postgres.py`：3 passed。
- `docker compose exec -T api pytest -q test/integration/api/test_counseling_minimal_workflow_api.py test/integration/api/test_counseling_p1b_api.py test/integration/api/test_counseling_p2_api.py`：3 passed。
- `cd web && node --test --test-concurrency=1 test/unit/studentConversations.test.js`：19 passed；本地 ESLint 与 `vite build` 通过。
- 完整 Web unit 运行至 59 项通过后停在既有 Vite dependency optimizer，未取得全套终态；浏览器辅助进程两次因 `helper_unknown_error` 无法启动。
- 共享开发 PostgreSQL 已通过历史一致性验证并原子升级至 counseling v14；危机事件保留 `applied_case_version`，提示表保留三项冻结来源列。
- 未运行授权的独立真实标注集或真实模型输出评测；因此不把代码 fixture 的 95%/5% 结果表述为产品质量通过。
