# 手工优先的心理辅导工作台

状态：implemented
类型：feature
Owner：web/src/domains/counseling/views/StudentWorkspaceView.vue
取代：2026-09-16-counseling-workspace-frontend-prototype.md、proposed/2026-09-12-counseling-minimal-release.md

## 问题

最小业务后端支持手工咨询草稿、人工确认、追加更正、人工风险事件、统一时间线、阶段结束和业务管理员聚合统计，但原生产工作台以文件上传、AI 摘要和关联 Agent 会话作为主要动作。辅导员无法仅通过业务页面完成从建档到阶段结束的 P0 闭环，五个标签还把未接入能力表现为当前工作区的一部分。

## 决策

- 学生详情由学生信息、待确认草稿和统一时间线组成，不再以目标、量表和危机等未接入标签切分档案。
- 当前主操作是新增手工咨询记录、记录人工风险和阶段结束。文件上传、AI 摘要和关联 Agent 会话不在生产工作台主路径；后端增强能力继续保留，待后续独立验收后再提供按需入口。
- 手工咨询记录先保存为可恢复草稿，辅导员可继续修订，再以独立动作确认归档。正式记录不提供编辑动作，纠错通过时间线节点追加更正。
- 风险只由辅导员手工记录。页面展示服务端当前风险投影和历史事件，不根据咨询正文自动推断风险；档案阶段结束不自动解除风险，也不阻止后续补充风险记录或正式记录更正。
- 阶段结束使用专用接口、乐观版本和必填结束说明，不通过普通档案编辑提交 `closed`。
- 业务管理员在档案列表页读取最小聚合统计，不获得正文入口。
- 2026-09-29 起，档案页增加受控的按需“AI 协助”入口。它创建独立任务和冻结快照，结果只能先回填待整理区再人工确认；这部分取代了“无 AI 主入口”的绝对结论，但不改变手工业务闭环的主路径。

## 替代方案

- 保留文件上传和 Agent 会话为首要按钮，同时新增手工记录：会继续让增强能力与基本业务闭环争夺主路径，因此拒绝。
- 在一个表单中直接创建正式记录：交互更短，但会消除草稿与人工确认边界，因此拒绝。
- 为手工记录、风险和阶段结束继续保留独立标签：入口清楚，但与统一时间线的产品主线冲突，因此使用上下文动作和时间线节点。

## 后果

先前的前端演示工作台只保留在 changelog 与 Git 历史；当前页面不再以 localStorage 或固定生成结果冒充业务成功。手工记录、档案时间线和后续增强入口由当前领域组件、业务 API 与本记录共同拥有。

- 辅导员不依赖模型、worker 或知识库即可完成建档、记录、确认、风险跟进、回看、更正和阶段结束。
- 现有文件草稿、上传与生成 API 没有删除；当前工作台不为它们提供主入口。后续恢复时需要独立任务列表、真实对象存储/模型验证和人工确认体验。
- 本决定不新增自动风险判断、量表、预约、目标、转介或危机工单，也不改变后端权限与持久化结构。

## 验证

| 验收主张 | 证据 | 结果 |
|---|---|---|
| 工作台接入手工草稿、确认、更正、风险和阶段结束；AI 仅作为受控的按需入口 | `docker compose exec -T web node --test --test-concurrency=1 test/unit/studentConversations.test.js test/unit/counselingBoundary.test.js test/unit/frontendAccess.test.js` | 原结论已由 2026-09-29 的 AI 协作决定部分取代 |
| 业务前端目录通过静态检查 | `docker compose exec -T web pnpm exec eslint src/domains/counseling --max-warnings=0` | Passed |
| 生产前端可构建 | `docker compose exec -T web pnpm run build` | Passed；仅有既有 chunk size 警告 |
| 后端 P0 契约与 PostgreSQL 终态保持有效 | `docker compose exec -T api python -m pytest test/integration/api/test_counseling_minimal_workflow_api.py -q` | Passed：1 test |
| 完整前端单元测试 | `docker compose exec -T web pnpm run test:unit` | Not passed：运行至通用 Project/Workspace API 测试时 Vite SSR 加载超时，进程以 137 退出；此前本次业务相关测试已独立通过 |
| 真实浏览器交互 | Chromium 覆盖用途告知、手工闭环、刷新、重复操作、接口失败恢复和直接 URL 越权 | Passed：13 项场景；PostgreSQL 回读正式记录、更正、风险和三类账号确认事实 |
