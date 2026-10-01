# 档案驱动的 AI 协作与材料回填

状态：implemented
类型：feature
Owner：backend/counseling/src/counseling/ai_work/service.py
取代：无

## 问题

心理辅导工作台已经形成不依赖模型的手工闭环，但辅导员需要生成文件时只能离开档案语境进入通用对话，生成结果也只能下载或保存到个人工作区。系统不能证明一次对话使用了哪个学生的已确认事实，也不能把指定 Run 展示的交付物以受控、可审计的方式回填到原档案。

## 决策

- 辅导员从本人学生档案创建一项 AI 协作任务；每项任务创建独立 Conversation，冻结创建时的学生信息、正式咨询记录、追加更正和人工风险事实。
- 完整快照保存在 counseling 业务表，并写入 Sandbox Workspace 挂载之外的服务端私有投影；Agent 文件后端把它映射为该 Conversation 的只读虚拟上下文文件。模型只接收任务说明、虚拟文件位置和不得自动改变业务状态的约束。
- 只有指定已完成 Run 通过成功 `present_artifacts` 调用展示的 TXT、Markdown、DOCX 或 PDF 普通文件可以回填，且回填时重新执行路径、类型、大小和内容校验。
- 回填文件复制到 counseling 专属对象存储并成为待整理材料；人工确认后进入档案材料列表，不进入正式咨询记录、时间线或风险投影。
- 业务 service 拥有 WorkItem、Conversation 创建和回填事务编排；Yuxi 通过端口提供默认 Agent、Conversation、Workdir 和 Run/Artifact 读取能力，不解释业务角色或正式档案语义。
- Yuxi 的通用 Conversation、Run、历史和 Workdir 边界通过依赖注入策略复核 counseling 当前授权；角色、部门或学生负责人变化后，即使 Conversation 仍属于原 UID，也不能再读取快照或发起运行。

## 替代方案

- 下载后手工上传：实现简单，但丢失 WorkItem、Conversation 和 Run 来源链，且容易串档，因此拒绝。
- 一名学生长期复用一个 Conversation：连续性更强，但无法稳定冻结任务材料和回填意图，因此一任务一会话。
- 直接把 Agent 输出写成正式记录：步骤更少，但绕过人工终审和正式记录不可变边界，因此只回填待整理材料。
- 第一版同时支持多种业务目标位置：会提前引入尚无稳定消费者的关联状态，因此只提供学生级待整理区和材料列表。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 每项任务绑定唯一档案、冻结已确认事实并创建独立 Conversation | 使用当前可变档案、复用其他学生会话或带入草稿 | AI work service、PostgreSQL、Conversation metadata | AI work、Schema、端口和架构单测 | 重复请求、跨档案 ID、创建后修改档案均不改变原快照 | Passed：相关后端 30 tests |
| 模型只看到任务约束和受控快照文件 | 浏览器伪造正文或自动带入历史会话、原始附件 | model context、Workdir 投影 | 快照、资源关闭与端口 unit | 草稿、原始文件、历史会话、知识库、MCP、Skill、SubAgent 和个人笔记不进入档案 Run | Passed：快照排除项、稳定指纹和档案 Run 默认资源关闭单测 |
| 只有当前任务已完成 Run 成功展示的安全文件可以回填 | 任意路径、相邻 Run、目录或伪文件进入业务存储 | artifact port、材料 service、MinIO | 字节边界 unit；真实服务 E2E | 越权、未完成 Run、未登记路径、软链接、超限和伪签名均失败 | Passed：确定性 PostgreSQL/MinIO/worker assembled-path E2E；真实模型供应商未运行 |
| 回填与确认幂等且不改变正式业务状态 | 重复文件、部分对象、时间线或风险被模型结果修改 | counseling materials、PostgreSQL、MinIO | Schema/服务 unit；数据库与对象回读 | 重复、并发、上传或提交失败不产生部分成功 | Passed：assembled-path E2E 覆盖并发同来源导入及对象/数据库回读，失败补偿由负向单测覆盖 |
| 业务页面提供按需 AI 入口、待整理和材料列表 | 通用技术入口泄露、失败后冒充保存成功 | counseling Web domain | Web unit、lint、build、真实浏览器 | 业务管理员、切换学生、刷新和接口失败均安全收敛 | Passed：Web unit、lint、build 和 P0 业务路径浏览器验收；AI 协作浏览器链路未运行 |

## 后果

- PostgreSQL 与 MinIO 不具备分布式事务；材料导入在上传前持久化 `importing` Owner，上传或最终提交中断时由同一来源重试继续完成，避免产生数据库不可发现的对象。
- Artifact 来源表示指定 Run 成功展示了该路径；业务侧另外记录导入时实际字节散列，不宣称 Workdir 文件在展示后不可变。
- 完整已确认事实可能较大，因此通过文件按需读取而不是每轮重复注入模型；部署方仍需核实模型供应商、观测和保留策略。
- rejected 材料第一版保留对象和审计，不宣称自动清理或零保留；物理删除与保留期限需要独立决策。
- [手工优先工作台](2026-09-24-manual-first-counseling-workspace.md)仍拥有基础业务闭环；本决定只部分取代其“无 AI 主入口”结论，不把 AI 变成归档、风险或时间线的自动 Owner。
