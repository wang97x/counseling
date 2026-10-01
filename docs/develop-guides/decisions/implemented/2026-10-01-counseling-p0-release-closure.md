# 心理辅导 P0 与 P0.5 发布收口

状态：implemented
类型：feature
Owner：backend/counseling/src/counseling/storage/schema.py
取代：无

## 问题

P0 已有建档、手工咨询草稿、人工确认、追加更正、人工风险、统一时间线和阶段结束的代码及 HTTP/PostgreSQL 证据，但发布边界仍不完整：真实浏览器没有验证刷新回读、失败反馈、重复动作和直接 URL 越权；业务审计虽随部分事务写入，却没有受限的持久回读入口；心理辅导数据用途告知没有版本化确认事实；保留边界和 PostgreSQL/MinIO 备份恢复没有可执行 Owner。当前档案驱动 AI 协作也缺少真实 worker、Run、Artifact、对象导入及晚到/撤权负控的 assembled-path 证据。

这些缺口会让页面演示、HTTP 200 或静态装配被误当成发布完成，也无法证明权限撤回、重复或并发请求、对象失败和恢复后的业务终态仍然正确。

## 决策

- P0 手工业务状态继续由现有 counseling service/repository 和 PostgreSQL 表拥有，不新建平行记录模型，不把 AI 设为手工闭环前置条件。
- 数据用途告知使用服务端固定版本与正文摘要；每个业务用户按版本保存确认时间。心理辅导数据接口在当前版本未确认时 fail-closed，只开放告知读取和确认入口。确认表示已阅读系统用途与边界，不推导来访者授权、临床同意或法律依据。
- counseling 审计事件继续不复制个案正文，并在拥有业务事务中写入。新增受限回读：辅导员只能读取本人负责档案的审计，业务管理员只能读取本部门事件的最小动作元数据；超级管理员不因平台身份获得业务审计正文或档案访问。
- Web 在进入心理辅导业务路径时读取服务端告知状态，未确认时展示不可绕过的确认界面；确认后才加载学生数据。API 失败保持错误态，不回退演示数据。
- 浏览器验收覆盖辅导员完整手工闭环、刷新回读、重复动作、接口失败，以及业务管理员最小列表/统计与直接详情 URL 越权。DOM 结果和服务端持久事实共同作为 oracle。
- 当前 AI 协作沿 shipping API、PostgreSQL、worker、Run、Artifact、Project Workdir 和 MinIO 材料导入路径验证；权限撤回、切换档案晚到结果、重复/并发提交和对象失败必须保持原档案绑定且不产生部分确认结果。
- 保留策略明确当前可执行边界：正式档案、审计和确认事实不自动删除；运行日志使用既有 30 天轮转；临时对象和 AI 中间产物仅由其已有生命周期 Owner 清理。未配置机构批准的删除期限时不得声称自动清除或零保留，也不新增无消费者的通用删除状态机。
- 备份恢复脚本同时覆盖 PostgreSQL 与 MinIO，生成带校验清单的备份，并只向隔离目标执行恢复演练；不得覆盖当前开发或生产数据。演练回读关键表、不可变约束和对象校验值。

## 替代方案

- 只补浏览器截图或操作记录：不能证明持久审计、用途告知、恢复和负向边界，因此拒绝。
- 复用通用 `operation_logs`：它面向身份管理操作，缺少学生范围和 counseling 事务绑定，会混淆 Owner，因此保留 `counseling_audit_events`。
- 只在 localStorage 保存用途告知：清缓存或换设备后丢失，也不能被服务端强制执行，因此拒绝。
- 立即建设完整数据生命周期引擎：当前没有机构批准的期限、删除例外和合法保留规则，预建状态机会制造错误承诺，因此只落实可执行保留边界和恢复能力。
- 在现有数据库或对象桶上直接做恢复演练：可能覆盖用户数据，因此只允许隔离目标。

## 后果

- counseling Schema、API 和 Web 入口新增一个发布前必需的用途告知门禁及受限审计读取能力；现有业务账号首次进入时需确认当前版本。
- 业务管理员获得审计动作的最小可见性，但仍不能读取学生背景、咨询正文、附件、文书正文或个人知识。
- 备份文件属于敏感运维产物，默认写入忽略目录，不能提交仓库；演练结束清理隔离数据库、桶和临时凭据。
- 若后续改变告知内容、保留期限、模型供应商数据范围、Schema、worker 或对象拓扑，必须提升版本并重跑相应门禁。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 无模型时可从建档完成手工记录、风险、确认、更正、时间线和阶段结束并刷新回读 | 前端状态冒充 PostgreSQL 终态，重复提交产生重复正式记录 | counseling service/repository、`StudentWorkspaceView.vue` | 真实浏览器 + HTTP/PostgreSQL integration | 旧版本、重复确认、并发确认、接口失败不产生部分终态 | Passed：HTTP/PostgreSQL + Chromium |
| 正文只对负责人可见，业务管理员仅见部门最小元数据和审计动作 | 前端隐藏但直接 URL/API 可读取正文 | repository 可见性查询、FastAPI 依赖 | 两辅导员、两部门、业务管理员真实 HTTP 与浏览器 | 替换 student/draft/record ID、直接详情 URL、权限撤回均拒绝 | Passed：HTTP + Chromium 直接 URL |
| 当前用途告知未确认时服务端拒绝 counseling 数据访问，确认后可持久回读 | 只存在前端弹窗或 localStorage 标记 | notice model/service/router | HTTP/PostgreSQL integration + 浏览器刷新 | 旧版本确认、跨用户确认、绕过 UI 直调业务 API 均不能通过 | Passed：HTTP/PostgreSQL + Chromium 刷新 |
| counseling 访问审计可按业务范围回读且不复制正文 | 只有写入无读取证据，或管理员借审计读取正文 | `counseling_audit_events` repository/service | HTTP/PostgreSQL integration | 跨负责人、跨部门、超级管理员和正文关键词均不可见 | Passed |
| AI 协作结果绑定原 student/request/run，Artifact 导入和人工确认可回读 | 邻近 Run 或晚到结果串到当前学生，MinIO 失败留下半状态 | `counseling.ai_work`、Yuxi Run/Artifact/MinIO 装配 | deterministic E2E + PostgreSQL/MinIO 回读 | 权限撤回、切换学生、晚到结果、重复/并发导入、对象失败 | Passed |
| 当前保留边界与实际装配一致且不宣称未实现的自动删除 | 文档承诺零保留或自动删除但日志、对象、备份仍保留 | retention decision、logging/object lifecycle composition | 配置与运行装配检查 | 未配置机构期限时不启动通用删除或声称已删除 | Inspected |
| PostgreSQL 与 MinIO 备份可恢复到隔离目标并保持关键约束与对象校验值 | 只生成备份未恢复，或恢复覆盖当前数据 | backup/restore script、Compose storage | 实际演练命令、SHA-256/大小/source/schema manifest 和恢复后回读 | 错误目标、损坏清单、旧 schema 版本、缺失对象或约束时 fail-closed | Passed |

2026-10-01 使用 Playwright Chromium 在真实 Compose 页面完成 13 项浏览器场景，覆盖用途告知、手工闭环、刷新、重复建档、确定性接口失败恢复、业务管理员和非负责人直接 URL 越权；DOM 与截图结果通过。
同轮 PostgreSQL 回读确认学生终态为 `closed/watch`，正式记录、更正和风险事件各一条，三类账号用途告知确认各一条。真实大文件/OCR/模型、移动端专项视觉回归和外部渗透测试不属于本决定的发布收口主张。
