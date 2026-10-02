# 授权协作、质量统计与受控外发

状态：implemented
类型：feature
Owner：backend/counseling/src/counseling/collaboration/service.py
取代：无

## 问题

现有档案只允许负责人读取正文，业务管理员只读取最小元数据。系统尚不能在不扩大管理员权限的前提下，为督导建立限时、限范围的个案访问，也不能提供固定口径且不会泄露小样本正文的质量统计，或证明一次对外资源/转介材料究竟处于准备、发送、失败、重试还是撤回状态。

## 决策

- 新增独立 supervisor 业务角色，不继承辅导员、业务管理员或超级管理员能力。负责人提出同部门个案授权，业务管理员批准后才生效；授权冻结范围、起止时间和双方操作，负责人或业务管理员可随时撤回。
- counseling.collaboration 拥有授权、结构化去标识材料、督导意见和督导摘要草稿。督导查询每次以数据库当前授权、范围和有效期过滤；撤回或到期后立即拒绝读取与生成。材料只接受固定枚举和计数，不接受姓名、学号、班级、日期、地址或自由正文。
- counseling.administration 拥有 P3 质量看板。指标名称、分子、分母、时间窗和部门范围由服务端固定；小于五个个案的分组只返回抑制标记，不返回可反推正文的值。
- counseling.external_delivery 拥有接收方、限时授权、最小材料清单和交付状态。业务管理员核验同部门接收方并批准外发授权；负责人创建交付后由显式渠道执行器发送，只有执行器返回成功才写入 sent，失败保留错误并允许带幂等键重试；发送前撤回进入 withdrawn，发送后只能记录撤回请求，不能伪装为已追回。
- counseling schema 以 v15/v16 原子迁移发布上述状态、关系一致性和数据库约束；HTTP 路由只校验 wire 并调用 owning service；Web 只接入当前角色的最小操作入口。

## 替代方案

- 把督导映射为 business_admin：会同时获得部门元数据、团队知识维护等无关权限，拒绝。
- 向督导返回替换姓名后的档案正文：无法验证间接标识符，拒绝。
- 允许任意 SQL 指标或返回小样本明细：统计口径不可审计且可反推个案，拒绝。
- 用“已生成下载文件”表示已经外发：无法区分准备与外部副作用，拒绝。
- 本阶段同时实现语音：语音有独立授权、供应商、保留和质量边界，且路线图明确不阻塞 P3A 至 P3C，拒绝纳入。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 督导是独立角色且只读当前有效授权范围 | 角色继承管理员权限、撤回后仍可缓存读取 | identity permissions、collaboration service/repository | identity unit + test/integration/api/test_counseling_collaboration_api.py：1 passed | 跨部门、未批准、过期、撤回、缺 scope | Passed（角色隔离链路） |
| 去标识材料不包含直接或间接标识正文 | 替换姓名后仍泄露学号、班级、日期、地址或自由正文 | collaboration service 与 schema | service unit + HTTP wire 回读 | 额外字段、自由文本、数字标识、越权读取 | Inspected |
| 督导意见和摘要绑定同一授权且撤权后不可生成 | 从相邻授权猜测内容或撤权后继续追加 | collaboration service/repository | 真实 HTTP/PostgreSQL 回读 | 错误授权、旧版本、撤回后写入 | Inspected |
| 质量看板口径、时间窗和可见范围固定 | 任意查询口径或小样本反推正文 | administration service | 真实 PostgreSQL 聚合回读 | 非管理员、跨部门、非法窗口、少于五例 | Inspected |
| 外发只在授权接收方与最小范围内执行并保留真实终态 | 准备即成功、失败/重试/撤回伪装成功 | external delivery service/repository/channel | 真实 HTTP/PostgreSQL + 确定性渠道测试 | 无授权、接收方失效、超范围、失败、重复重试、发送前后撤回 | Inspected |
| Schema 原子升级且拒绝非法状态 | 只靠 Python 校验或版本与 DDL 分裂 | counseling storage schema | uv run pytest test/unit/services/test_counseling_p3_contract.py test/unit/storage/test_counseling_schema.py test/integration/storage/test_counseling_schema_postgres.py -q：21 passed；v16 关系一致性 trigger 已装配 | v6→v16 迁移回读；非法 scope/status 的专门 DB 负向测试未运行 | Passed（迁移回读与关系 guard 装配） |
| 页面按角色展示并刷新回读服务端事实 | 前端隐藏冒充授权或失败回退演示数据 | counseling Web domain | node --test test/unit/p3Boundary.test.js、pnpm run lint:check、pnpm run build；OpenAPI 回读 19 条 P3 路由 | 用户手工确认登录、Dashboard 与协作入口正常；computer-use 自动控制仍不可用 | Passed（定向 Web gate） |

## Review 结论

完整 Review 复核了身份权限、事务持久化、v15/v16 Schema、关系一致性触发器、协作/外发 service 与 router、Web 角色入口。Review 发现的跨授权串接风险已由 v16 关系 trigger 收口；v6 历史 users 缺少 business_roles 的迁移兼容问题已修复并由真实 PostgreSQL 测试覆盖；外发领取成功/失败均写入审计事件。

## 未验证范围

P3 真实 HTTP/PostgreSQL 业务链路已使用本地随机 super_admin 引导账号、临时辅导师/督导/业务管理员账号完成 1 项通过的角色隔离测试；浏览器登录、Dashboard 与协作入口由用户手工确认正常。生产第三方邮件、短信或转介渠道不属于本切片。

## 风险

- 督导访问与对外发送同时改变权限、持久状态和外部副作用，必须执行完整 Review；任何只靠前端可见性或路由角色判断的实现都不构成授权。
- 去标识化不能由模型自由改写证明。本切片故意收窄为服务端固定结构；如果未来需要正文摘要，必须新增独立的间接标识评测与人工确认门禁。
- 当前渠道只实现仓库内可确定验证的执行器；生产邮件、短信或第三方系统接入需要单独配置、密钥、供应商保留和重放语义决策。
