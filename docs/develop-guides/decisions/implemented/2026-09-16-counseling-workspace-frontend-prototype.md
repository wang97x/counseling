# 心理辅导档案工作台前端原型

状态：implemented
类型：feature
Owner：web/src/services/counselingWorkspaceService.js

## 问题

现有学生档案页面只覆盖编号、负责人、背景摘要、状态和关联通用会话，无法在后端业务模型尚未齐备时验证档案工作台的信息架构、文本记录上传、摘要审阅和归档交互。前端原型必须能独立完成设计评审，同时不能把模拟结果伪装成真实业务成功或形成第二套生产事实。

## 决策

学生列表与详情拆成独立页面，详情以概览、时间轴、目标与作业、量表、危机五个标签组织。新增前端 `CounselingWorkspaceService` 作为页面唯一数据入口，分别提供显式演示适配器和真实 API 适配器。演示模式由 `VITE_COUNSELING_DEMO=true` 开启，使用版本化 localStorage 保存纯虚构结构化状态，页面持续展示“演示数据”并提供重置入口；真实模式继续复用现有学生、会话和附件接口，未接入能力显式返回 `not_supported`，不回退模拟结果。

文本记录上传只接受 TXT、DOCX、PDF。演示模式不保存文件二进制，以文件元数据和固定解析结果演示“上传、解析、生成摘要、人工编辑、归档预览、确认归档”流程。高风险摘要必须经人工确认后才能归档，但前端不执行或宣称完成危机干预。档案内“下一步助手”创建绑定当前档案与背景快照的会话，并复用通用 Agent 页面，不复制其调试、工具轨迹和线程管理能力。

## 替代方案

- 等后端完成再做页面：会推迟信息架构和关键交互验证，拒绝。
- 在现有组件中散落 mock 分支：真实与模拟状态容易混淆，拒绝。
- 直接嵌入完整 `AgentChatComponent`：其线程、工具和调试状态超出档案页面需要，且难以脱离后端演示，因此从档案创建关联会话后进入既有 Agent 页面。
- 新增 mock 框架或状态依赖：当前原型可由浏览器存储和普通模块完成，不新增依赖。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 演示流程明确且不会伪装生产成功 | API 缺失时静默回退模拟数据 | counseling workspace service 与页面演示标识 | 前端 unit、真实页面检查 | API 模式调用未接入能力返回 `not_supported` | `studentConversations` unit 通过；当前页面检查未运行 |
| 五标签共享同一档案状态 | 归档后只更新局部组件 | demo adapter 的归档提交 | 前端 unit、页面主流程 | 高风险未确认不能归档 | `studentConversations` unit 通过；当前页面检查未运行 |
| 文件原文不进入 localStorage | DOCX/PDF 二进制持久化到浏览器 | demo adapter 文件边界 | localStorage 结构断言 | 刷新后只恢复元数据和结构化草稿 | `studentConversations` unit 通过 |
| 页面遵循现有设计与响应式约束 | 硬编码浅色或窄屏丢失操作 | counseling views/components | lint、build、浅深色与响应式页面检查 | 加载、空、错误和高风险状态均可恢复 | build 通过；lint 与当前页面检查未通过或未运行 |
| 下一步助手绑定当前档案上下文 | 会话未绑定档案或使用可变背景 | counseling service、会话 metadata 与工作台入口 | 前端 unit、HTTP integration 与数据库回读 | 演示模式不显示不可用入口；未选择档案或非负责人不能创建关联会话 | 前端 unit 通过；HTTP integration 与数据库回读本轮未运行 |

### 执行结果

- `node --test test/unit/studentConversations.test.js`：通过。
- `node --test --test-concurrency=1 "test/**/*.test.js" "test/**/*.spec.js"`：72/73 个文件通过；唯一失败为 `pdfPreviewAssets` 在受限环境监听端口时报 `EPERM`。
- `node node_modules/vite/bin/vite.js build`：通过。
- `node node_modules/eslint/bin/eslint.js . --max-warnings=0`：未通过；当前依赖环境对全部 Vue 文件统一报告 `Invalid Version: main`。
- `python3 scripts/verify_engineering_contracts.py` 与 `python3 -m unittest scripts.test_verify_engineering_contracts`：通过，工程契约单测 64 项。
- `node node_modules/vitepress/bin/vitepress.js build`：通过。
- 当前最终页面截图与浏览器交互未运行，历史抽屉截图不作为关联会话入口的证据。

## 后果

原型字段先于后端契约固化，接口因此只使用用户可见领域语义，后端接入时仍需独立决定持久化、权限和事务 Owner。localStorage 只服务演示，不适合敏感数据或多人协作。真实附件解析可复用现有接口，但模型生成、档案归档与危机处置不会因原型完成而视为后端已实现。
