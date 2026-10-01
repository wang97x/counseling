"""心理辅导领域 Schema 的真实 PostgreSQL 迁移验证。"""

import json
import os
import uuid

import asyncpg
import pytest
from counseling.storage import schema as counseling_schema
from counseling.storage.schema import (
    COUNSELING_SCHEMA_V1_STATEMENTS,
    COUNSELING_SCHEMA_V2_STATEMENTS,
    COUNSELING_SCHEMA_V3_STATEMENTS,
    COUNSELING_SCHEMA_V4_STATEMENTS,
    COUNSELING_SCHEMA_V5_STATEMENTS,
    COUNSELING_SCHEMA_V6_STATEMENTS,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from yuxi.storage.postgres.manager import PostgresManager

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _scoped_manager(engine) -> PostgresManager:
    """创建只访问隔离 PostgreSQL Schema 的迁移 manager。"""

    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager._initialized = True
    return manager


async def test_counseling_v1_rows_upgrade_to_v8_without_overwriting_model_context() -> None:
    """带旧会话行的 v1 可重复升级到 v4，且不覆盖已有通用模型上下文。"""
    schema_name = f"test_counseling_migration_{uuid.uuid4().hex}"
    connection = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    try:
        await connection.execute(f'CREATE SCHEMA "{schema_name}"')
        await connection.execute(f'SET search_path TO "{schema_name}"')
        await connection.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY)")
        await connection.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, role VARCHAR NOT NULL, business_roles JSONB NOT NULL)"
        )
        await connection.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, extra_metadata JSON)")
        await connection.execute("INSERT INTO departments (id) VALUES (1)")
        await connection.execute(
            "INSERT INTO users (id, role, business_roles) VALUES (1, 'superadmin', '[\"technical_admin\"]')"
        )
        await connection.execute(
            "INSERT INTO conversations (id, extra_metadata) VALUES (1, $1::json), (2, $2::json)",
            '{"counseling":{"student_id":11,"background_snapshot":"旧快照"}}',
            '{"counseling":{"student_id":12},"model_context":{"label":"保留原值","payload":{"fixed":true}}}',
        )

        for statement in COUNSELING_SCHEMA_V1_STATEMENTS:
            await connection.execute(statement)

        migrated = json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 1"))
        preserved = json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 2"))
        assert migrated["model_context"]["payload"]["background_snapshot"] == "旧快照"
        assert preserved["model_context"] == {"label": "保留原值", "payload": {"fixed": True}}

        for statement in COUNSELING_SCHEMA_V1_STATEMENTS:
            await connection.execute(statement)
        assert (
            json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 1")) == migrated
        )
        assert (
            json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 2")) == preserved
        )

        for _ in range(2):
            for statement in COUNSELING_SCHEMA_V2_STATEMENTS:
                await connection.execute(statement)

        for statement in COUNSELING_SCHEMA_V3_STATEMENTS:
            await connection.execute(statement)

        for _ in range(2):
            for statement in COUNSELING_SCHEMA_V4_STATEMENTS:
                await connection.execute(statement)

        for statement in COUNSELING_SCHEMA_V5_STATEMENTS:
            await connection.execute(statement)

        for _ in range(2):
            for statement in COUNSELING_SCHEMA_V6_STATEMENTS:
                await connection.execute(statement)

        assert (
            json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 1")) == migrated
        )
        assert (
            json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 2")) == preserved
        )

        columns = {
            row["column_name"]
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = $1 AND table_name = 'counseling_students'",
                schema_name,
            )
        }
        assert {"display_name", "class_name", "current_risk_level", "version", "closed_at"} <= columns
        assert await connection.fetchval("SELECT to_regclass('counseling_record_corrections') IS NOT NULL")
        assert await connection.fetchval("SELECT to_regclass('counseling_risk_events') IS NOT NULL")
        assert await connection.fetchval("SELECT to_regclass('counseling_ai_work_items') IS NOT NULL")
        assert await connection.fetchval("SELECT to_regclass('counseling_materials') IS NOT NULL")
        assert await connection.fetchval("SELECT business_roles FROM users WHERE id = 1") == '["super_admin"]'
        assert await connection.fetchval("SELECT to_regclass('counseling_assessment_results') IS NOT NULL")
        assert await connection.fetchval("SELECT to_regclass('counseling_appointments') IS NOT NULL")
    finally:
        await connection.execute("SET search_path TO public")
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await connection.close()


async def test_counseling_v2_migrator_publishes_v8_after_converting_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实迁移入口转换旧角色并创建 P1B 表后再发布 v8。"""

    schema_name = f"test_counseling_v2_migration_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema_name}},
    )
    manager = _scoped_manager(scoped_engine)
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        await manager.create_schema_version_table()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("CREATE TABLE departments (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE counseling_students (id INTEGER PRIMARY KEY)"))
            await connection.execute(
                text(
                    "CREATE TABLE users ("
                    "id INTEGER PRIMARY KEY, business_roles JSONB NOT NULL, "
                    "CONSTRAINT ck_users_business_roles CHECK ("
                    "jsonb_typeof(business_roles) = 'array' AND "
                    'business_roles <@ \'["counselor", "business_admin", "technical_admin"]\'::jsonb))'
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO users (id, business_roles) VALUES "
                    "(1, '[\"technical_admin\"]'::jsonb), "
                    '(2, \'["counselor", "business_admin"]\'::jsonb)'
                )
            )
        await manager.record_schema_version("counseling", 2)
        monkeypatch.setattr(counseling_schema, "pg_manager", manager)

        await counseling_schema.migrate_schema()

        async with scoped_engine.connect() as connection:
            published_version = await connection.scalar(
                text("SELECT version FROM yuxi_schema_migrations WHERE domain = 'counseling'")
            )
            rows = (await connection.execute(text("SELECT id, business_roles FROM users ORDER BY id"))).all()
            ai_work_exists = await connection.scalar(text("SELECT to_regclass('counseling_ai_work_items') IS NOT NULL"))
            materials_exist = await connection.scalar(text("SELECT to_regclass('counseling_materials') IS NOT NULL"))
            notice_exists = await connection.scalar(
                text("SELECT to_regclass('counseling_data_use_acknowledgments') IS NOT NULL")
            )
            assessments_exist = await connection.scalar(
                text("SELECT to_regclass('counseling_assessment_results') IS NOT NULL")
            )
            appointments_exist = await connection.scalar(
                text("SELECT to_regclass('counseling_appointments') IS NOT NULL")
            )
        assert published_version == 8
        assert notice_exists
        assert ai_work_exists and materials_exist
        assert assessments_exist and appointments_exist
        assert {row.id: row.business_roles for row in rows} == {
            1: ["super_admin"],
            2: ["counselor", "business_admin"],
        }
        with pytest.raises(IntegrityError, match="ck_users_business_roles"):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text("UPDATE users SET business_roles = '[\"technical_admin\"]'::jsonb WHERE id = 1")
                )
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await admin_engine.dispose()

async def test_counseling_v6_rows_upgrade_to_v8_with_frozen_creation_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v6 预约升级后以迁移时快照作为不可变创建意图。"""
    schema_name = f"test_counseling_v6_migration_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema_name}},
    )
    manager = _scoped_manager(scoped_engine)
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        await manager.create_schema_version_table()
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE counseling_appointments ("
                    "id VARCHAR(64) PRIMARY KEY, "
                    "scheduled_start TIMESTAMP WITHOUT TIME ZONE NOT NULL, "
                    "scheduled_end TIMESTAMP WITHOUT TIME ZONE NOT NULL, "
                    "appointment_type VARCHAR(32) NOT NULL, "
                    "location TEXT NOT NULL, note TEXT NOT NULL)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO counseling_appointments "
                    "(id, scheduled_start, scheduled_end, appointment_type, location, note) "
                    "VALUES ('a1', '2026-10-01 01:00:00', '2026-10-01 02:00:00', "
                    "'面谈', '原地点', '原备注')"
                )
            )
        await manager.record_schema_version("counseling", 6)
        monkeypatch.setattr(counseling_schema, "pg_manager", manager)

        await counseling_schema.migrate_schema()

        async with scoped_engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT version FROM yuxi_schema_migrations WHERE domain = 'counseling'")
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT scheduled_start, scheduled_end, appointment_type, location, note, "
                        "created_scheduled_start, created_scheduled_end, "
                        "created_appointment_type, created_location, created_note "
                        "FROM counseling_appointments WHERE id = 'a1'"
                    )
                )
            ).one()
        assert version == 8
        assert row[5:] == row[:5]
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await admin_engine.dispose()
