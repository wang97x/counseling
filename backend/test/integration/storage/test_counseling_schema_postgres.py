"""心理辅导领域 Schema 的真实 PostgreSQL 迁移验证。"""

import json
import os
import uuid

import asyncpg
import pytest

from counseling.storage.schema import COUNSELING_SCHEMA_V1_STATEMENTS, COUNSELING_SCHEMA_V2_STATEMENTS

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_counseling_v1_rows_upgrade_to_v2_without_overwriting_model_context() -> None:
    """带旧会话行的 v1 可重复升级到 v2，且不覆盖已有通用模型上下文。"""
    schema_name = f"test_counseling_migration_{uuid.uuid4().hex}"
    connection = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    try:
        await connection.execute(f'CREATE SCHEMA "{schema_name}"')
        await connection.execute(f'SET search_path TO "{schema_name}"')
        await connection.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY)")
        await connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        await connection.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, extra_metadata JSON)")
        await connection.execute("INSERT INTO departments (id) VALUES (1)")
        await connection.execute("INSERT INTO users (id) VALUES (1)")
        await connection.execute(
            "INSERT INTO conversations (id, extra_metadata) VALUES "
            "(1, $1::json), (2, $2::json)",
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
        assert json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 1")) == migrated
        assert json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 2")) == preserved

        for _ in range(2):
            for statement in COUNSELING_SCHEMA_V2_STATEMENTS:
                await connection.execute(statement)

        assert json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 1")) == migrated
        assert json.loads(await connection.fetchval("SELECT extra_metadata FROM conversations WHERE id = 2")) == preserved

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
    finally:
        await connection.execute("SET search_path TO public")
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await connection.close()
