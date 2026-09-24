# 收敛 implemented Decision 集合

状态：implemented
类型：simplification
Owner：docs/develop-guides/decisions/README.md
取代：无

## 问题

`implemented/` 曾同时保存长期架构取舍、阶段性迁移、局部缺陷修复和已经被后续记录吸收的演进步骤。100 份记录都表现为当前有效，导致同一主题存在多个候选 Owner，增加开发者和 AI 重建当前事实的成本。

## 决策

implemented Decision 保持为 50 份当前记录。同一长期主题只保留一份入口：保留记录在顶部用 `取代` 列出已完整吸收并删除的旧记录，主题索引列出主题、Owner、当前记录和被取代记录。局部修复由源码和回归测试拥有，阶段性演进留在 Git 历史；changelog 只回答发布历史，不参与当前事实检索。

权限、持久化、事务、Run/worker、文件隔离、模型输入、公开兼容和心理辅导产品边界继续保留独立记录。Proposed 只保留仍有未实现范围和明确验收标准的提案；已经失效或被当前决定吸收的提案删除。辅助配置文件不因文档数量收敛而改动。

## 替代方案

- 全部移动到 archived：文件数量和搜索噪声不变，不能解决当前事实候选过多的问题。
- 只新增索引：改善导航但继续维护重复事实。
- 按日期批量删除：会丢失仍约束权限、状态和兼容性的非显然取舍。
- 收敛为当前集合并显式记录取代关系：保留高风险边界，同时减少重复 Owner。

## 后果

仓库内旧 Decision 深链接必须迁移到当前记录或真实语义 Owner；仓库外历史链接可能失效，但内容仍可从 Git 历史恢复。新增 Decision 前需要先判断是否应更新既有主题记录，避免集合再次按实现步骤增长。

## 验证

旧能力不存在：implemented 目录不再把局部修复、阶段性迁移和已被后续决定完整吸收的记录暴露为并列当前 Owner。

重新引入条件：只有新的非显然取舍无法由现有主题 Decision、源码契约和测试表达时，才新增 implemented Decision。

- `find docs/develop-guides/decisions/implemented -maxdepth 1 -name '*.md' | wc -l` 返回 50。
- 所有 50 份 implemented 记录都包含顶部 `取代：` 元数据；仍有效的 proposed 记录为 2 份。
- 仓库 Markdown 链接检查不再指向本轮删除的 Decision。
- `python3 scripts/verify_engineering_contracts.py` 与 `python3 -m unittest scripts.test_verify_engineering_contracts` 通过。
- `git diff --check` 通过；Decision 收敛阶段没有修改 backend、web、workflow、schema 或辅助配置文件。
