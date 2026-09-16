# Web 约定

本目录是 Vue 3 / Vite 前端。先阅读根 [AGENTS.md](../AGENTS.md)、[设计规范](../docs/develop-guides/design.md) 和 [ARCHITECTURE.md](../ARCHITECTURE.md)。

- API 调用统一放在 `src/apis`；组件不直接拼接普通 HTTP 请求。
- 前端权限与路由守卫只提供体验约束，后端始终执行最终授权。
- 复用 `src/assets/css/base.css` 变量和 `@lucide/vue`；不为一次性视觉需求引入新依赖。
- 保持 loading、empty、error、断线恢复和终态投影语义一致；不要用乐观 UI 覆盖 PostgreSQL 返回的最终事实。
- `pnpm run lint:check` 是只读 gate；`pnpm run lint` 才允许本地自动修复。

心理辅导交互遵循[产品约束](../docs/develop-guides/counseling-product-contract.md)：档案为主，对话辅助；五标签内容按实际能力呈现。切换档案隔离草稿和晚到结果，确认归档前展示影响，成功后读取正式结果。草稿保存、生成完成和归档成功分别反馈；演示仅用虚构数据，API 失败不能回退演示。危机提示包含文字、依据和人工处置入口，风险与结案状态分别表达。

提交前运行：

```bash
docker compose exec web pnpm run lint:check
docker compose exec web pnpm run test:unit
docker compose exec web pnpm run build
```

UI 改动必须在真实页面验证，并提供最终截图或录屏；适用时覆盖浅/深色、响应式、loading、empty 和 error 状态。
