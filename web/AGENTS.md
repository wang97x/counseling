# Web 约定

本目录是 Vue 3 / Vite 前端。默认只读本文件、受影响组件/API 和相关测试；只有 UI、样式或交互改动才读取[设计规范](../docs/develop-guides/design.md)的相关章节，跨前后端链路或陌生模块才读取根[架构文档](../ARCHITECTURE.md)。

- API 调用统一放在 `src/apis`；组件不直接拼接普通 HTTP 请求。
- 前端权限与路由守卫只提供体验约束，后端执行最终授权。
- 复用 `base.css` 变量和 `@lucide/vue`，不为一次需求引入依赖或样式体系。
- 保持 loading、empty、error、断线恢复和终态投影一致；不用乐观 UI 覆盖 PostgreSQL 最终事实。
- 修改心理辅导页面时按需读取[产品约束](../docs/develop-guides/counseling-product-contract.md)：档案隔离草稿和晚到结果，生成、保存与确认归档分别反馈，真实 API 失败不回退演示数据。
- 逻辑修改运行相关 unit 和 `pnpm run lint:check`；构建边界或关键交互再运行 build。UI 改动在真实页面验证，按适用范围覆盖浅色、深色、响应式和异常状态。
