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
from sqlalchemy.exc import DBAPIError, IntegrityError
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


async def test_counseling_v1_rows_upgrade_to_v9_without_overwriting_model_context() -> None:
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


async def test_counseling_v2_migrator_publishes_v9_after_converting_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实迁移入口转换旧角色并创建 P1B 表后再发布 v9。"""

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
            await connection.execute(text("CREATE TABLE counseling_records (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE counseling_risk_events (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE agent_runs (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE messages (id INTEGER PRIMARY KEY)"))
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
            risk_hint_evaluations_exist = await connection.scalar(
                text("SELECT to_regclass('counseling_risk_hint_evaluations') IS NOT NULL")
            )
            risk_hints_exist = await connection.scalar(
                text("SELECT to_regclass('counseling_risk_hints') IS NOT NULL")
            )
        assert published_version == 14
        assert notice_exists
        assert ai_work_exists and materials_exist
        assert assessments_exist and appointments_exist
        assert risk_hint_evaluations_exist and risk_hints_exist
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


async def test_counseling_v6_rows_upgrade_to_v9_with_frozen_creation_intent(
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
            await connection.execute(text("CREATE TABLE departments (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE counseling_students (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE counseling_records (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE counseling_assessment_results (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE counseling_risk_events (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE counseling_ai_work_items (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE agent_runs (id VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE messages (id INTEGER PRIMARY KEY)"))
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
        assert version == 14
        assert row[5:] == row[:5]

        async with scoped_engine.begin() as connection:
            await connection.execute(text("INSERT INTO departments (id) VALUES (1)"))
            await connection.execute(text("INSERT INTO users (id) VALUES (1)"))
            await connection.execute(text("INSERT INTO counseling_students (id) VALUES (1)"))
            await connection.execute(text("INSERT INTO counseling_risk_events (id) VALUES ('risk-1')"))
            await connection.execute(
                text(
                    "INSERT INTO counseling_crisis_protocols "
                    "(id, department_id, title, content, effective_from, expires_at, "
                    "version_no, published_by, request_id) "
                    "VALUES ('protocol-1', 1, '协议', '内容', NOW() - INTERVAL '1 day', "
                    "NOW() + INTERVAL '1 day', 1, 1, 'protocol-request')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO counseling_crisis_cases "
                    "(id, student_id, department_id, counselor_id, risk_event_id, protocol_id, owner_id, "
                    "deadline_at, last_event_id, request_id) VALUES "
                    "('v14-case', 1, 1, 1, 'risk-1', 'protocol-1', 1, NOW() + INTERVAL '1 day', "
                    "NULL, 'v14-case-request')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO counseling_crisis_case_events "
                    "(id, case_id, event_type, note, actor_id, request_id, applied_case_version) VALUES "
                    "('v14-event', 'v14-case', 'measure', '事件', 1, 'v14-event-request', 1)"
                )
            )
            await connection.execute(
                text("UPDATE yuxi_schema_migrations SET version = 13 WHERE domain = 'counseling'")
            )
        manager = _scoped_manager(scoped_engine)
        monkeypatch.setattr(counseling_schema, "pg_manager", manager)
        with pytest.raises(DBAPIError, match="crisis event version history is inconsistent"):
            await counseling_schema.migrate_schema()
        async with scoped_engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT version FROM yuxi_schema_migrations WHERE domain = 'counseling'")
            )
        assert version == 13

        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE counseling_crisis_cases DISABLE TRIGGER USER"))
            await connection.execute(
                text(
                    "UPDATE counseling_crisis_cases SET last_event_id = 'v14-event', version = 2 "
                    "WHERE id = 'v14-case'"
                )
            )
            await connection.execute(text("ALTER TABLE counseling_crisis_cases ENABLE TRIGGER USER"))
        manager = _scoped_manager(scoped_engine)
        monkeypatch.setattr(counseling_schema, "pg_manager", manager)
        with pytest.raises(DBAPIError, match="crisis event version history is inconsistent"):
            await counseling_schema.migrate_schema()
        async with scoped_engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT version FROM yuxi_schema_migrations WHERE domain = 'counseling'")
            )
        assert version == 13

        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE counseling_crisis_case_events DISABLE TRIGGER USER"))
            await connection.execute(
                text("DELETE FROM counseling_crisis_case_events WHERE case_id = 'v14-case'")
            )
            await connection.execute(text("ALTER TABLE counseling_crisis_case_events ENABLE TRIGGER USER"))
            await connection.execute(text("DELETE FROM counseling_crisis_cases WHERE id = 'v14-case'"))
            for column_name in (
                "source_work_item_id",
                "source_run_id",
                "source_message_id",
            ):
                await connection.execute(
                    text(f"ALTER TABLE counseling_risk_hints DROP COLUMN {column_name} CASCADE")
                )
            await connection.execute(
                text("UPDATE yuxi_schema_migrations SET version = 11 WHERE domain = 'counseling'")
            )
            await connection.execute(
                text(
                    "INSERT INTO counseling_risk_hint_evaluations "
                    "(id, department_id, dataset_reference, dataset_fingerprint, model_reference, threshold, "
                    "true_positive, false_negative, false_positive, true_negative, recall, false_positive_rate, "
                    "passed, created_by, request_id) VALUES "
                    "('evaluation-1', 1, 'fixture', repeat('a', 64), 'model-1', 0.5, "
                    "19, 1, 1, 19, 0.95, 0.05, TRUE, 1, 'evaluation-request')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO counseling_risk_hints "
                    "(id, student_id, department_id, counselor_id, evaluation_id, protocol_id, "
                    "score, evidence_summary, request_id) VALUES "
                    "('hint-1', 1, 1, 1, 'evaluation-1', 'protocol-1', 0.9, '旧提示', 'hint-request')"
                )
            )
        manager = _scoped_manager(scoped_engine)
        monkeypatch.setattr(counseling_schema, "pg_manager", manager)
        with pytest.raises(DBAPIError, match="cannot bind legacy risk hints"):
            await counseling_schema.migrate_schema()
        async with scoped_engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT version FROM yuxi_schema_migrations WHERE domain = 'counseling'")
            )
            source_column_exists = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'counseling_risk_hints' "
                    "AND column_name = 'source_work_item_id')"
                )
            )
        assert version == 11
        assert source_column_exists is False

        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE counseling_risk_hints DISABLE TRIGGER USER"))
            await connection.execute(text("DELETE FROM counseling_risk_hints"))
            await connection.execute(text("ALTER TABLE counseling_risk_hints ENABLE TRIGGER USER"))
            await connection.execute(text("ALTER TABLE counseling_crisis_case_events DROP COLUMN applied_case_version"))
            await connection.execute(
                text("UPDATE yuxi_schema_migrations SET version = 12 WHERE domain = 'counseling'")
            )
            await connection.execute(
                text(
                    "INSERT INTO counseling_crisis_cases "
                    "(id, student_id, department_id, counselor_id, risk_event_id, protocol_id, owner_id, "
                    "deadline_at, last_event_id, request_id) VALUES "
                    "('case-1', 1, 1, 1, 'risk-1', 'protocol-1', 1, NOW() + INTERVAL '1 day', "
                    "'event-1', 'case-request')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO counseling_crisis_case_events "
                    "(id, case_id, event_type, note, actor_id, request_id) VALUES "
                    "('event-1', 'case-1', 'measure', '旧事件', 1, 'event-request')"
                )
            )
        manager = _scoped_manager(scoped_engine)
        monkeypatch.setattr(counseling_schema, "pg_manager", manager)
        with pytest.raises(DBAPIError, match="cannot reconstruct legacy crisis event application order"):
            await counseling_schema.migrate_schema()
        async with scoped_engine.connect() as connection:
            version = await connection.scalar(
                text("SELECT version FROM yuxi_schema_migrations WHERE domain = 'counseling'")
            )
            event_version_column_exists = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'counseling_crisis_case_events' "
                    "AND column_name = 'applied_case_version')"
                )
            )
        assert version == 12
        assert event_version_column_exists is False
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await admin_engine.dispose()
