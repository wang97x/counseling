# 心理辅导与 Yuxi 端口边界收敛

状态：implemented
类型：architecture
Owner：backend/server/composition.py
取代：2026-09-28-business-owned-identity.md 中的读取边界与兼容出口条款

## 问题

Yuxi 的 Agent、知识、Skill、Dashboard 和 Run 代码直接导入 `counseling.identity.User`
与 `UserRepository`，而心理辅导文书服务直接调用 Yuxi OCR 和 MinIO 实现。两个包因此形成运行时
环依赖，业务权限、平台能力和基础设施的替换边界只能靠导入约定维持。Yuxi 还保留身份模型
兼容 re-export 与心理辅导历史 DDL，导致身份和业务 Schema 的当前 Owner 不唯一。

## 决策

- Yuxi 定义不可变身份快照和只读 `IdentityReader` 端口，只表达 AI 平台当前消费者需要的字段与查询。
  `server` composition root 注册由 `counseling.identity` 实现的适配器；未注册时显式失败，不提供
  隐式业务实现 fallback。
- Yuxi 的运行时代码只依赖身份快照与读取端口，不导入 counseling 包。身份写入、密码、部门管理、
  业务角色解释和审计继续只由 `counseling.identity` 拥有。
- counseling 文书用例定义 OCR 与对象存储端口；Yuxi 适配器负责调用现有 parser 和 MinIO。
  业务服务继续拥有文件校验、对象命名、补偿、草稿版本、模型输入和正式归档事务。
- 删除 `yuxi.storage.postgres.models_business` 的身份模型 re-export，以及 Yuxi 当前迁移中的 counseling
  DDL/历史运行残留。历史 business v7/v8 counseling DDL 移交 counseling Schema Owner，并由
  `server.storage_migration` 以显式回调交给 Yuxi 编排器在记录 business v9 前执行；随后迁移当前
  counseling Schema。未知版本或缺失历史回调继续 fail-closed。
- 建立统一架构契约：Yuxi 不导入 counseling；counseling 仅能通过明确适配器或共享低层原语消费
  Yuxi；业务能力到平台能力的映射由独立参数化测试验证，缺失能力默认拒绝。

## 替代方案

- 只把 `User` 改名为 Protocol，继续直接实例化 `UserRepository`：没有切断运行时依赖，拒绝。
- 在 Yuxi 端口中暴露业务 ORM Model 供 SQLAlchemy join：把具体模型藏在接口后但仍由平台解释业务
  Schema，拒绝。
- 把身份模型迁回 Yuxi：恢复双 Owner，违反当前业务身份决策，拒绝。
- 一次拆分独立身份或 counseling 微服务：需要分布式事务、认证和部署协议，当前没有消费者收益，
  不在本次范围。
- 保留旧 re-export 与历史 DDL 作为无限期兼容：维护两个入口且无法证明 Owner 已收敛，拒绝；重新
  引入条件是出现已确认的仓库外 consumer 或受支持升级基线，并另建兼容决策与回归测试。

## 后果

- Yuxi 不再拥有或直接导入 counseling 身份模型，只能读取组合根装配的脱敏身份快照。
- counseling 文书用例保留业务事务和补偿 Owner，OCR 与对象存储实现可通过端口替换。
- 业务角色到平台知识权限的解释只有 counseling mapper 一个 Owner，缺失映射默认拒绝。
- 历史 business v7/v8 counseling DDL 仍受支持，但实现和验证归 counseling Schema Owner。
- 身份 re-export 删除属于明确接受的公开兼容收窄；若确认仓库外受支持消费者，需另建兼容决策。

## 验证

以下矩阵记录直接证据以及受当前本地环境限制而尚未执行的范围。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| Yuxi 只通过身份读取端口获得用户事实 | 仍导入业务模型、repository 或从平台角色推导业务权限 | `yuxi.identity`、server composition | 架构 AST 测试与相关 unit | 恢复任一 `counseling` import 时测试失败；未注册端口明确失败 | 架构测试手动执行通过；pytest 未运行 |
| counseling 文件流程只依赖 OCR/对象存储端口 | service 直接创建 Yuxi parser/MinIO client | documents service、Yuxi adapter | service unit 与真实文件 integration | parser、上传或补偿失败不形成正式记录或孤立成功状态 | 架构检查通过；真实文件 integration 未运行 |
| 身份 re-export 与 Yuxi counseling DDL 不再存在 | 旧 import 或第二 Schema Owner 仍可被使用 | models_business、Yuxi migrator、counseling schema | 负向搜索、migration unit、真实 PostgreSQL upgrade | 恢复 re-export/DDL 时架构测试失败；未知 Schema 拒绝 | 负向搜索与架构测试通过；真实 PostgreSQL 升级未运行 |
| 业务能力到平台能力映射完整且默认拒绝 | 前端或 Yuxi 自行猜测角色，超级管理入口与 API 不一致 | counseling capability policy、平台访问策略 | 参数化契约 unit 与 HTTP integration | 空角色、单角色和复合角色逐项验证，无隐式继承 | 契约测试已新增；pytest 与 HTTP integration 未运行 |
| 旧能力不存在 | 仓库继续依赖兼容出口或历史迁移常量 | 架构契约与工程信任检查 | `git grep`、工程契约检查 | 重新加入旧符号或导入路径时测试失败 | 负向搜索与工程契约检查通过 |

## 风险

- Dashboard 在 PostgreSQL 使用单个数组 bind 保持活动身份过滤，避免展开无界 IN 参数；定时任务统一
  先锁 User、再锁 ScheduledAgentJob 或 ScheduledAgentRun。真实 PostgreSQL 规模与并发回归仍需补跑。
- API、worker、迁移器和测试都必须装配同一身份适配器；漏注册必须在启动或首次使用时显式失败。
- 删除已发布 Python import 属于兼容收窄；仓库内无 consumer，仓库外 consumer 尚未证明；若后续确认
  存在受支持消费者，需另建期限明确的兼容决策与回归测试。
- OCR 与 MinIO 有外部副作用；端口化不得改变对象 key、补偿删除、大小限制或事务提交顺序。
- 历史数据库升级必须从正式支持基线验证，不能以新库建表成功代替升级证据。
