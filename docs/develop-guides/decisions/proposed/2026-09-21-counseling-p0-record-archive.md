# 心理辅导 P0 记录生成与确认归档

状态：proposed
类型：feature
Owner：backend/counseling/src/counseling/documents/service.py

该文件生成链路已按[最小心理辅导业务后端](../implemented/2026-09-23-minimal-counseling-backend.md)后移为 P1 增强；其安全验收仍有效，但不再阻塞 P0 手工咨询记录闭环。

## 问题

当前真实工作台只能把附件加入一条 Conversation，不能回读并核对解析文本；摘要、草稿、归档预览和确认归档仍返回 `not_supported`。前端演示数据可以模拟完整流程，但 PostgreSQL 没有草稿版本、正式记录、幂等确认或审计事实，因此不能形成 P0 业务闭环。

## 提案

- 档案直属记录草稿保存原文件元数据、MinIO 稳定对象、状态、乐观版本和生成请求状态；每次解析文本或结构化摘要修改都追加不可覆盖的 revision。
- 结构化摘要只包含中性的会谈概述、关键内容、辅导员观察、已讨论行动和后续计划，不自动产生诊断、量表、目标状态或危机结论。
- `CounselingGenerationPort` 只向当前默认聊天模型发送已确认的档案背景快照与解析文本，不装配 Conversation 历史、Skills、工具或知识库。生成请求先提交幂等键和输入版本，事务外调用模型，回写时重新锁定并拒绝晚到结果。
- 确认归档在一个 PostgreSQL 事务中锁定草稿和版本，写入不可变正式记录并把草稿置为已确认；相同确认键重复提交返回同一记录，旧版本或不同确认意图返回冲突。
- 时间线合并正式记录与档案关联 Conversation。正式记录正文只向档案负责人返回；业务管理员仍只读取学生列表最小元数据。
- 原文件使用独立的 `counseling/<uid>/<student>/<draft>/` 对象前缀，不依赖临时附件或 Conversation Workdir。审计事件只保存主体、对象、动作、结果和时间，不复制正文。
- Web 真实模式使用上传、原文核对、生成、草稿编辑、预览和确认 API；确认后重新读取 PostgreSQL 时间线。生产入口移除本地 demo 伪归档、最近 Conversation 附件绑定和 P1/P2 五标签占位。

## 替代方案

- 继续复用最近 Conversation 的附件：来源文件会绑定执行线程而不是档案，统一时间线加入正式记录后还会把记录 ID 当成 thread ID，因此拒绝。
- 复用普通 Agent Run：现有 Agent 自动装配会话历史、Skills、工具和知识，无法证明材料范围；P0 使用隔离生成端口。
- 用同步模型响应直接拼出前端草稿：没有持久幂等键、输入版本和晚到结果保护，因此拒绝。模型调用可以同步等待，但生成状态必须先持久化，并在事务外执行。
- 把目标、量表、风险和待办一起写入：这些属于 P1/P2 或需要独立规则与评测，P0 只追加一条正式时间线记录。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| TXT、DOCX、PDF 来源文件绑定当前档案并返回可修订解析文本 | 只保存文件名、绑错 Conversation 或用占位预览 | counseling service、MinIO 对象和 draft revision | 真实 HTTP、MinIO、PostgreSQL integration | 空文件、超限、伪扩展、损坏、无文本、跨档案 ID 均失败 | Not run |
| 摘要只使用已确认的当前档案材料 | 普通 Agent 带入历史、工具或其他学生内容 | `CounselingGenerationPort` 与 generation state | 模型输入捕获 unit、deterministic provider integration | 缺少模型、非法 JSON、旧文本版本和晚到结果不产生摘要 revision | Not run |
| 草稿可恢复并拒绝并发覆盖 | 前端状态成为唯一副本或旧页面覆盖新版本 | draft/revision repository | HTTP 与 PostgreSQL 回读 | 旧 `expected_version` 返回 409且原 revision 不变 | Not run |
| 人工确认只产生一条不可变正式记录 | 重复点击、失败事务或后续更新覆盖历史 | confirm service、数据库约束 | 并发 integration 与数据库回读 | 未确认时间线为空；重复/并发确认只有一条；正式记录 UPDATE/DELETE 被数据库拒绝 | Not run |
| 权限和审计覆盖来源、草稿、预览、归档与时间线 | 只隐藏前端或审计复制正文 | owner-scoped repository、audit events | 两辅导员、业务管理、技术管理真实 HTTP | 替换 student/draft/record/object ID 均拒绝，审计 metadata 无正文 | Not run |
| Web 只展示真实 P0 状态 | demo/localStorage 或五标签占位冒充业务能力 | counseling adapter、上传流程、学生工作台 | Web unit、build、真实浏览器 | API 失败不回退 demo；确认后必须回读服务端时间线 | Not run |

## 风险

- MinIO 与 PostgreSQL 不支持分布式事务；上传数据库失败时补偿删除，稳定前缀的孤儿对象由显式清理入口处理，不能把孤儿当正式记录。
- 模型调用可能在进程中断后留下 `generating`；新请求只在超时后持锁接管，旧结果因请求键或版本不匹配被拒绝。外部调用按 at-least-once 成本语义处理，档案写入保持幂等。
- 默认模型供应商、观测和保留策略必须在处理真实个案前由部署方确认；本实现不宣称零保留或端到端加密。
- 正式记录通过数据库触发器拒绝 UPDATE/DELETE。未来数据保留或依法删除需要独立受审计清理流程，不能开放普通业务更新接口。
