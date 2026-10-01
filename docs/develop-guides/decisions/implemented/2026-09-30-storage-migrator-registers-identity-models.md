# 迁移装配入口注册业务身份模型

状态：implemented
类型：bug-fix
Owner：backend/server/storage_migration.py
取代：无

## 问题

`storage-migrator` 在干净进程中先查询 Yuxi 平台 ORM，但没有注册已经迁入
`counseling.identity` 的 `users` 表模型。SQLAlchemy 配置 `projects.uid` 外键时因此抛出
`NoReferencedTableError`，Compose 按门禁阻止 API、worker 和 Web 启动。

## 决策

由迁移 composition root 在调用平台迁移前显式注册业务身份 ORM。Yuxi 保持只消费身份端口，
不重新拥有或 re-export 业务身份模型；Schema、迁移版本与数据不改变。

## 替代方案

- 在 Yuxi 恢复 `User` 模型或 re-export：重新形成两个身份 Owner，拒绝。
- 绕过 `storage-migrator` 启动运行服务：破坏 fail-closed Schema 门禁，拒绝。
- 在各个 repository 隐式导入身份模型：装配责任分散且不能保证迁移入口先执行，拒绝。

## 后果

迁移器在任何平台 ORM 查询前注册业务身份表；依赖 `users` 的 Yuxi 外键可以配置 mapper，
但身份模型仍由 counseling 拥有。迁移门禁、Schema 版本、DDL 和数据保持不变。

## 验证

- 独立进程回归测试在修复前恢复 `users` 缺失失败，修复后与 counseling Schema 单测合计 7 项通过。
- `docker compose -p counseling-dev up -d` 成功；`storage-migrator` 退出码为 0，API、worker、
  sandbox-provisioner 与全部基础服务健康，Web 正常运行。
