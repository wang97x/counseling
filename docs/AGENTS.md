# 文档约定

本目录包含用户文档、开发规范、决策和版本材料。默认只读本文件、正在修改的 owning page 及其事实 Owner；不要因进入 `docs/` 全文加载架构、产品、测试和写作指南。

## 路由与 Owner

- 教程位于 `intro/`，配置和运维参考位于 `advanced/`，Agent 扩展位于 `agents/`，运行机制位于 `mechanisms/`，工程流程位于 `develop-guides/`。
- 系统边界属于根 [ARCHITECTURE.md](../ARCHITECTURE.md)，测试方法属于[测试规范](develop-guides/testing-guidelines.md)，心理辅导需求属于[产品约束](develop-guides/counseling-product-contract.md)。只在本次页面涉及对应事实时读取相关章节。
- 非显然取舍属于 `decisions/`，达到门槛的事故属于 `postmortems/`，已发布事实属于 changelog，未完成方向属于 roadmap。
- 新增页面、移动页面或实质改变信息架构时，读取[文档规范](develop-guides/documentation-guidelines.md)的相关章节并更新导航和入站链接。

## 写作与验证

- 每个事实只有一个完整 Owner；其他页面保留完成读者任务所需的最小上下文和相对链接。先核对源码、Schema、Compose、配置或测试，再写当前行为。
- 使用直接、可验证的现在时，写明执行者、条件、结果和失败。不要保存推理流水账、Review 对话或把目标能力写成已实现。
- 示例只用占位凭据和虚构数据，不写 secret、账号、用户数据、本地绝对路径或内部地址。
- 文档变更运行最小相关检查、文档构建和 `git diff --check`。纯文案或链接修复按根规则可免 Reviewer Agent；涉及权限、状态、公开契约或长期治理时按风险升级 Review。
