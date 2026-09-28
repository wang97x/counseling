"""心理辅导 Schema 由独立领域迁移拥有。"""

from unittest.mock import AsyncMock

import pytest

from counseling.storage import schema
from server import storage_migration


async def test_counseling_schema_validation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺失或超前的业务 Schema 版本都不能启动 API。"""
    monkeypatch.setattr(schema.pg_manager, "get_schema_versions", AsyncMock(return_value={}))
    with pytest.raises(RuntimeError, match="counseling=missing"):
        await schema.require_current_schema()

    monkeypatch.setattr(
        schema.pg_manager,
        "get_schema_versions",
        AsyncMock(return_value={"counseling": schema.COUNSELING_SCHEMA_VERSION + 1}),
    )
    with pytest.raises(RuntimeError, match=f"counseling={schema.COUNSELING_SCHEMA_VERSION + 1}"):
        await schema.require_current_schema()


async def test_composed_migrator_orders_platform_before_counseling(monkeypatch: pytest.MonkeyPatch) -> None:
    """业务外键依赖的平台表必须先于业务表迁移。"""
    calls: list[str] = []

    async def migrate_platform() -> None:
        calls.append("platform")

    async def migrate_counseling() -> None:
        calls.append("counseling")

    monkeypatch.setattr(storage_migration, "migrate_yuxi_schema", migrate_platform)
    monkeypatch.setattr(storage_migration, "migrate_counseling_schema", migrate_counseling)

    await storage_migration.main()

    assert calls == ["platform", "counseling"]


def test_counseling_schema_backfills_generic_model_context() -> None:
    """旧档案会话升级后继续把原确认快照提供给模型。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_STATEMENTS)

    assert "UPDATE conversations" in migration_sql
    assert "(extra_metadata::jsonb)->'counseling'" in migration_sql
    assert "extra_metadata::jsonb ? 'counseling'" in migration_sql
    assert "'{model_context}'" in migration_sql


def test_counseling_schema_v2_adds_minimal_workflow_guards() -> None:
    """v2 同时拥有风险历史、追加更正和数据库不可变保护。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V2_STATEMENTS)

    assert schema.COUNSELING_SCHEMA_VERSION == 3
    assert "current_risk_level" in migration_sql
    assert "counseling_risk_events" in migration_sql
    assert "counseling_record_corrections" in migration_sql
    assert "trg_counseling_corrections_immutable" in migration_sql
    assert "ALTER COLUMN summary DROP NOT NULL" in migration_sql


def test_counseling_schema_v3_owns_business_role_migration() -> None:
    """v3 将旧技术角色转换为业务模块拥有的超级管理角色。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V3_STATEMENTS)

    assert "technical_admin" in migration_sql
    assert "super_admin" in migration_sql
    assert "ck_users_business_roles" in migration_sql
