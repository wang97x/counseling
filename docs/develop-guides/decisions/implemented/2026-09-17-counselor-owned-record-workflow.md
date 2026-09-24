# 辅导员自助建档与档案内助手会话

状态：implemented
类型：feature
Owner：backend/counseling/src/counseling/students/service.py

## 问题

当前学生档案由业务管理员选择负责人后创建，辅导员反而不能建档；通用侧栏又向超级管理员保留“新建对话”和“个人空间”。档案详情同时存在“新建会话”、独立助手抽屉和下一步助手，导致同一个业务动作有多条入口；关联会话虽来自档案流程，但时间轴节点没有明确表达其助手对话身份和继续入口。

## 决策

- 仅具有 `counselor` 业务角色的用户为自己创建学生档案，服务端从当前用户确定负责人，不接受客户端提交负责人 ID。
- 业务管理员继续查看本部门档案元数据，但不能创建、打开或修改辅导员负责的档案；超级管理员不因平台角色获得个案能力。
- 业务管理员和超级管理员均不显示、也不能直接进入通用新建对话与个人空间；技术控制台权限保持独立。
- 关联 Conversation 作为助手对话节点合并到现有辅导时间轴，并从对应节点继续对话，不另设“对话历史”分区。
- 删除档案详情的独立“新建会话”和模拟助手抽屉入口；“下一步助手”和“助手”统一打开关联会话创建流程，成功后进入 `/agent/:thread_id`。

## 替代方案

- 仍由业务管理员建档，只在前端给辅导员按钮：服务端权限没有改变，辅导员请求仍失败，因此拒绝。
- 同时保留新建会话、助手抽屉和下一步助手：三个入口表达同一动作，且模拟助手与真实 Conversation 历史分裂，因此拒绝。
- 把对话历史另设一级分区：会割裂一次辅导步骤与该步生成材料的对话，因此拒绝；会话直接进入对应时间轴节点。

## 后果

- 旧客户端继续提交 `counselor_id` 会因请求模型 `extra="forbid"` 收到 422；这是收紧后的明确契约，不做静默兼容。
- 原负责人候选接口不再注册；建档流程没有选择或转派负责人的入口。未来若引入转派，必须重新定义权限、审计和既有会话归属。
- Conversation 页面仍复用通用 Agent UI，但必须携带并校验档案关联；前端分组不能替代后端档案归属校验。
- 本次不新增辅导路线、归档或材料生成的持久化模型，只纠正权限、入口和现有会话的归属展示。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 辅导员创建的档案自动归本人 | 客户端伪造负责人或仍依赖管理员分配 | `yuxi.services.counseling.create_student` | `docker compose exec -T api uv run --no-sync --no-dev pytest test/integration/api/test_counseling_student_api.py -q` | 业务管理员、超级管理员、无角色用户创建均为 403 | Passed：2 tests |
| 业务管理员与超级管理员无通用对话、个人空间入口 | 只隐藏菜单但可直接输入 URL | `web/src/utils/frontendAccess.js`、Router | `cd web && node --test test/unit/frontendAccess.test.js test/unit/studentConversations.test.js` | 两类角色访问 `/agent`、`/workspace` 被重定向 | Passed：2 files |
| 助手对话进入对应时间轴节点 | Conversation 被放到独立历史区或无法继续 | `StudentWorkspaceView.vue`、`apiAdapter.js` | 同上 Web unit；真实浏览器检查 | 普通手动/上传节点不出现继续对话入口 | Unit passed；真实浏览器未执行 |
| 下一步助手是唯一的新对话业务入口 | 独立新建会话或模拟助手仍可触发 | `StudentWorkspaceView.vue` | 同上 Web unit；真实浏览器检查 | 源码与 DOM 不再出现独立“新建会话”操作 | Unit passed；真实浏览器未执行 |

提交前还执行 `docker compose exec -T api uv run --no-sync --no-dev pytest test/unit -m 'not slow' -q`，结果为 1971 passed、53 skipped；`python3 scripts/verify_engineering_contracts.py`、其 64 项单元测试与 `git diff --check` 通过。Web build 在同一工作树通过。未执行真实浏览器视觉检查。
