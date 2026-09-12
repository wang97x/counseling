# 学生会话与确认背景

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/conversation_service.py

## 问题

辅导人员需要从负责的学生档案新建、重开正确会话，避免切换学生后串用背景。背景必须保留人工确认时的内容，并随请求持久化。

## 决策

复用 Conversation 和原对话页。创建事务校验学生负责人，将学生 ID、编号和人工确认背景存入服务端保留的 counseling metadata。创建接口拒绝伪造该字段，更新接口不接受学生或背景绑定字段；同一创建请求 ID 不能改用于其他学生或快照。每名学生可有多个会话，档案列表只返回本人创建且未删除的关联会话。

档案确认弹窗可以编辑本次快照，确认不会修改档案。档案编辑不改变已有会话快照。普通请求接入在生产队列 service 中将快照写入 Request、Run 的 input_payload，并固化到 Message 的 raw_message；模型读取用户级参考资料，普通历史正文保持用户原文。资料不具有系统指令优先级。

前端以请求代次丢弃切换学生后的旧详情和保存结果，创建完成也只在仍处于该学生时跳转。无模型可管理会话；模型选择为空时提示配置、阻止发送并保留草稿。无效模型仍由后端模型解析明确拒绝。

## 替代方案

独立表和页面会重复已有线程生命周期。采用现有 JSON 持久化与限制更新字段的 API，避免新增迁移。背景刷新、跟进和知识来源选择由后续批次处理。学生关联的可写边界由会话 service 与 HTTP 契约拥有，档案列表查询由 counseling repository 拥有。

## 后果

旧通用会话继续有效，不自动关联学生。重新打开会话从持久化 metadata 恢复学生与快照。当前档案没有负责人转移接口；未来引入转移时，需要明确历史会话与附件权限如何随归属变化。当前快照在每次普通输入中携带，增加模型输入长度。

## 验证

- docker compose exec api uv run --group test pytest test/integration/api/test_counseling_student_api.py test/unit/services/test_counseling_input.py -q：3 passed，覆盖真实 HTTP 新建、重开、越权、幂等冲突、禁止修改绑定、档案变化及无效模型。真实 PostgreSQL 接入测试仅隔离模型目录解析，提交后用独立 session 回读 Request 和 Message，确认背景固定且忽略客户端伪造数据；测试不向 worker 发布运行。
- docker exec counseling-dev-api-1 uv run --group test pytest test/unit -m 'not slow' -q -p no:cacheprovider：1958 passed、53 skipped。跳过项不计为通过。
- docker compose exec web node --test test/unit/studentConversations.test.js：4 passed，验证旧详情、旧保存与创建结果晚到、错误保留和成功跳转。相关请求队列、线程状态和创建契约另有 75 项后端测试通过。
- 本次前端文件的 ESLint 与 pnpm run build 通过。全量 pnpm run lint:check 被既有 pdfPreviewAssets.test.js 的两处 Buffer 未声明错误阻断；全量 pnpm run test:unit 在既有 Dashboard API 测试触发 Vite 依赖预构建期间耗尽环境内存，未完成。
- 真实 Playwright 页面验证通过：确认新建、刷新重开、档案重开、学生切换隔离；浅色与深色窄屏截图已检查。空模型场景在浏览器响应层模拟空配置，验证提示、阻止发送及草稿保留；不修改系统模型配置。
- 工程契约及其 62 项单测通过。cd docs && pnpm run build 因本机缺少 pnpm 未运行成功；锁定版本依赖下载无响应，已停止。真实 worker/provider 生成链路尚未验证，无模型验证不代表生成质量通过。
