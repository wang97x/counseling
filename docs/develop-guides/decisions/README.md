# 工程决策记录

决策记录保存非平凡变更的当前判断、真实替代方案、接受的代价和验证。它补充代码与当前文档，不替代二者。查找当前事实先按下表进入当前记录；changelog 只回答发布历史，不参与当前事实检索。

## 主题索引

未列出的 implemented 记录以标题表达唯一局部主题；同一长期主题只在下表保留一个入口。

| 主题 | Owner | 当前记录 | 被取代记录 |
|---|---|---|---|
| 工程闭环与文档治理 | `docs/develop-guides/spec-loop.md` | [Yuxi Spec Loop](implemented/2026-08-16-yuxi-spec-loop.md) | 文档信息架构、面向读者的文档维护 |
| 依赖供应链 | `.github/workflows/dependency-audit.yml` | [依赖供应链审计门禁](implemented/2026-08-18-dependency-supply-chain-gates.md) | 依赖更新降噪、工具链刷新、漏洞修复阶段记录 |
| Skill 运行时 | `yuxi.agents.skills.runtime` | [Skill 运行时边界](implemented/2026-08-20-skill-runtime-module-boundary.md) | Skill 预加载、DeepAgents 迁移 |
| Schema 迁移 | `yuxi.storage_migration` | [版本化迁移 Owner](implemented/2026-08-24-versioned-schema-migration-owner.md) | v0.7.1 一次性迁移边界 |
| Run 审计事实 | AgentRun audit repository/service | [AgentRun 审计基础](implemented/2026-08-28-agent-run-audit-foundation.md) | Model、Tool、Message 分阶段审计记录 |
| Project 生命周期 | `yuxi.services.project_service` | [Project 持久化与选择](implemented/2026-08-22-project-persistence-and-selection.md) | 测试清理阶段记录；运行旁路另见生命周期闭合记录 |
| 知识目录 | `yuxi.knowledge.base` | [文件夹移动与重命名](implemented/2026-08-24-knowledge-folder-move-and-rename.md) | 历史虚拟目录迁移 |
| 文档解析 | parser registry 与依赖声明 | [Docling Slim Office 解析](implemented/2026-09-03-docling-slim-office-parser.md) | QA、书籍抽样、能力去重、LibreOffice 下线等局部记录 |
| Agent 并发容量 | Compose、运行指标与性能工具 | [并发容量与流式协议](implemented/2026-09-04-agent-concurrency-capacity.md) | 模型前时延优化与阶段性评测 |
| 运行时冗余表面 | shipping composition | [删除无消费者入口](implemented/2026-09-04-remove-redundant-surfaces.md) | 二次冗余清理、内容审查残留 |
| Decision 治理 | `docs/develop-guides/decisions/README.md` | [收敛 implemented Decision 集合](implemented/2026-09-24-consolidate-implemented-decisions.md) | 本轮被吸收的阶段性、重复记录 |
| 测试边界 | `backend/test/run_tests.sh` | [测试套件边界](implemented/2026-09-07-test-suite-simplification.md) | 测试审计 follow-up |
| Web 性能与展示 | Web 组件、Vite 与 unit/build | [性能与构建优化](implemented/2026-09-08-performance-and-bundle-optimization.md) | 局部展示、流式、Dashboard、PDF 和图标迁移记录 |
| 发布验证 | `.github/workflows` | [候选发布验证](implemented/2026-09-09-release-validation.md) | Beta 版本升级阶段记录 |
| 心理辅导后端 | `backend/counseling` | [最小心理辅导业务后端](implemented/2026-09-23-minimal-counseling-backend.md) | 学生档案、知识入口、会话和页面切片记录 |
| 业务身份与组织 | `counseling.identity` | [业务模块拥有用户认证与组织](implemented/2026-09-28-business-owned-identity.md) | 无 |
| 心理辅导工作台 | counseling Web domain | [手工优先工作台](implemented/2026-09-24-manual-first-counseling-workspace.md) | 前端演示原型与早期最小发布方案 |
| 心理辅导交付阶段 | `docs/develop-guides/roadmap.md` | [按依赖拆分交付切片](implemented/2026-10-01-counseling-roadmap-delivery-slices.md) | 无 |
| 心理辅导 P0 发布收口 | `backend/counseling/src/counseling/storage/schema.py` | [P0 与 P0.5 发布收口](implemented/2026-10-01-counseling-p0-release-closure.md) | 无 |
| 心理辅导 P1B 量表与预约 | `counseling.assessments`、`counseling.appointments` | [固定量表与内部预约闭环](implemented/2026-10-01-counseling-p1b-assessments-appointments.md) | 无 |
| 档案驱动 AI 协作 | `counseling.ai_work` | [AI 协作与材料回填](implemented/2026-09-29-counseling-ai-work-items.md) | 手工优先工作台中的“无 AI 主入口”绝对结论 |

## 生命周期

- `proposed/`：尚未实现的提案；必须写问题、候选方案、验收标准和风险。
- `implemented/`：已经生效的当前决定；使用现在时，只保留问题、决策、替代方案、后果和验证。
- `rejected/`：明确拒绝且值得保留原因的提案；不构成当前实现要求。
- `archived/`：冻结历史，不能修改或作为当前权威。当前机制必须链接到新的 owning record。

提案实现后，把记录移动到 `implemented/` 并改写为当前事实；不要保留迁移 checklist、进度日志或”应当”式 spec。决定被部分取代时，在新旧记录中交叉链接；完全失去当前价值时，将旧记录移到 `archived/`，或在理由已经被新记录完整吸收后删除。任何记录移入 `archived/` 前先改写为问题、决策、替代方案、后果、验证结构，不保留提案、进度或迁移章节。

非平凡工作必须在实现前创建 `proposed`。小而完整、在同一变更中已经生效且没有待裁决替代或风险的修复可直接写 `implemented`，但 PR 必须解释为何不需要 proposal；不得用 diff 大小或文件数量自动判定 trivial。完整流程见 [Yuxi Spec Loop](../spec-loop.md)。

## 何时需要

满足任一条件即为非平凡：

- 改变重要工程主张的语义 Owner、commit/publication 边界、oracle、负向案例或实际 gate。
- 改变持久状态、事务发布点、权限、worker 生命周期、模型可见输入或兼容承诺。
- 引入新的抽象、依赖、配置、fallback、状态机或长期维护表面。
- 接受一个并不显然、未来可能重开的工程取舍。

局部文案、机械重命名和不改变行为的等价清理可以免除，但 PR 要明确说明原因。

## 格式

文件名使用 `YYYY-MM-DD-topic.md`。所有记录包含：

```markdown
# 决策标题

状态：implemented
类型：feature
Owner：path/to/owner
取代：无

## 问题
## 决策
## 替代方案
## 后果
## 验证
```

`类型` 只使用 `feature`、`bug-fix`、`simplification`、`architecture`、`process`、`testing`。`Owner` 指向拥有当前行为的首要代码、契约或文档；一项决定跨越多个事实 Owner 时，在正文明确分工，不能让 decision record 反向成为运行时事实源。`取代` 使用文件名列出被当前记录完整吸收并删除的记录，没有时写 `无`。

`proposed` 使用 `## 问题`、`## 提案`、`## 替代方案`、`## 验收标准`、`## 风险`，并在验收标准中包含以下证据矩阵：

```markdown
| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
```

`simplification` 提案和 implemented 记录还必须分别在 `## 验收标准` 或 `## 验证` 中包含 `旧能力不存在：` 与 `重新引入条件：`，避免只增加替代物而不删除旧表面。`rejected` 说明拒绝原因。不要保存 chain-of-thought、逐步实现叙事、Review 对话、人员评价或敏感数据。
