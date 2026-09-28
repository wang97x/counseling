"""真实 HTTP、PostgreSQL 学生档案归属和迁移测试。"""

import os
import shutil
import json
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from yuxi.services import agent_request_queue_service as queue_service
from yuxi.services.input_message_service import build_chat_input_message
from yuxi.storage.postgres.models_business import AgentRun, AgentRunRequest, Message
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace.paths import global_user_data_dir

import asyncpg
import pytest
from counseling.storage.schema import migrate_legacy_business_schema

from yuxi.storage.postgres.manager import pg_manager
from counseling.identity.auth import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_student_owner_and_manager_access_are_isolated(test_client):
    """不同负责人、部门及技术管理员不能读取或覆盖背景。"""
    suffix = uuid.uuid4().hex[:10]
    conn = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    departments = []
    users = []

    async def actor(department_id, role, business_roles):
        uid = f"student_{suffix}_{len(users)}"
        user_id = await conn.fetchval(
            """
            INSERT INTO users (username, uid, password_hash, role, business_roles,
                               department_id, login_failed_count, is_deleted, created_at)
            VALUES ($1, $1, 'test', $2, $3::jsonb, $4, 0, 0, NOW()) RETURNING id
            """,
            uid,
            role,
            business_roles,
            department_id,
        )
        users.append(user_id)
        return user_id, {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(user_id)})}"}

    try:
        for number in (1, 2):
            departments.append(
                await conn.fetchval(
                    "INSERT INTO departments (name, description) VALUES ($1, 'test') RETURNING id",
                    f"student_dept_{suffix}_{number}",
                )
            )
        _, manager = await actor(departments[0], "admin", '["business_admin"]')
        owner_id, owner = await actor(departments[0], "user", '["counselor"]')
        other_id, other = await actor(departments[0], "user", '["counselor"]')
        _, tech = await actor(departments[0], "superadmin", '["super_admin"]')
        _, foreign_manager = await actor(departments[1], "admin", '["business_admin"]')
        _, no_role = await actor(departments[0], "user", "[]")
        _, no_department_counselor = await actor(None, "user", '["counselor"]')

        for headers in (manager, foreign_manager, tech, no_role):
            denied = await test_client.post(
                "/api/counseling/students",
                headers=headers,
                json={"student_code": "S-001"},
            )
            assert denied.status_code == 403, denied.text
        denied = await test_client.post(
            "/api/counseling/students",
            headers=no_department_counselor,
            json={"student_code": "S-001"},
        )
        assert denied.status_code == 400, denied.text
        assert denied.json()["detail"] == "当前用户未绑定部门"

        created = await test_client.post(
            "/api/counseling/students",
            headers=owner,
            json={"student_code": "S-001"},
        )
        assert created.status_code == 201, created.text
        student_id = created.json()["id"]
        assert "background_summary" not in created.json()
        assert created.json()["current_risk_level"] == "unassessed"
        duplicate = await test_client.post(
            "/api/counseling/students",
            headers=owner,
            json={"student_code": "S-001"},
        )
        assert duplicate.status_code == 409, duplicate.text
        forged_owner = await test_client.post(
            "/api/counseling/students",
            headers=owner,
            json={"student_code": "S-002", "counselor_id": other_id},
        )
        assert forged_owner.status_code == 422, forged_owner.text

        updated = await test_client.put(
            f"/api/counseling/students/{student_id}",
            headers=owner,
            json={"background_summary": "虚构背景，仅测试隔离", "status": "active", "expected_version": 1},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["background_summary"] == "虚构背景，仅测试隔离"
        persisted = await conn.fetchrow(
            "SELECT department_id, student_code, counselor_id, background_summary, status "
            "FROM counseling_students WHERE id = $1",
            student_id,
        )
        assert tuple(persisted.values()) == (departments[0], "S-001", owner_id, "虚构背景，仅测试隔离", "active")

        for headers in (manager, other, tech, foreign_manager, no_role):
            detail = await test_client.get(f"/api/counseling/students/{student_id}", headers=headers)
            assert detail.status_code in {403, 404}, detail.text
            assert "虚构背景" not in detail.text
            write = await test_client.put(
                f"/api/counseling/students/{student_id}",
                headers=headers,
                json={"background_summary": "越权覆盖", "status": "active"},
            )
            assert write.status_code in {403, 404}, write.text

        owner_list = await test_client.get("/api/counseling/students", headers=owner)
        assert owner_list.status_code == 200, owner_list.text
        assert owner_list.json() == [
            {
                "id": student_id,
                "student_code": "S-001",
                "display_name": "",
                "class_name": "",
                "counselor_id": owner_id,
                "status": "active",
                "current_risk_level": "unassessed",
                "version": 2,
            }
        ]
        manager_list = await test_client.get("/api/counseling/students", headers=manager)
        assert manager_list.status_code == 200, manager_list.text
        assert manager_list.json() == [
            {
                "id": student_id,
                "student_code": "S-001",
                "counselor_id": owner_id,
                "status": "active",
                "current_risk_level": "unassessed",
                "version": 2,
            }
        ]
        assert "background_summary" not in owner_list.text
        assert "background_summary" not in manager_list.text
        for headers in (other, foreign_manager):
            listed = await test_client.get("/api/counseling/students", headers=headers)
            assert listed.status_code == 200 and listed.json() == [], listed.text
        for headers in (tech, no_role):
            listed = await test_client.get("/api/counseling/students", headers=headers)
            assert listed.status_code == 403, listed.text
        assert (
            await conn.fetchval("SELECT background_summary FROM counseling_students WHERE id = $1", student_id)
        ) == "虚构背景，仅测试隔离"

        agent_slug = f"student-agent-{suffix}"
        agent = await test_client.post(
            "/api/agent", headers=owner, json={"name": "虚构辅导测试", "slug": agent_slug, "backend_id": "ChatbotAgent"}
        )
        assert agent.status_code == 200, agent.text
        second = await test_client.post(
            "/api/counseling/students", headers=owner, json={"student_code": "S-002"}
        )
        assert second.status_code == 201, second.text
        second_id = second.json()["id"]
        payload = {
            "agent_id": agent_slug,
            "request_id": uuid.uuid4().hex,
            "background_snapshot": "人工确认的虚构背景",
        }
        conversation_url = f"/api/counseling/students/{student_id}/conversations"
        created_thread = await test_client.post(conversation_url, headers=owner, json=payload)
        assert created_thread.status_code == 201, created_thread.text
        thread = created_thread.json()
        snapshot = {"student_id": student_id, "student_code": "S-001", "background_snapshot": "人工确认的虚构背景"}
        assert thread["metadata"]["counseling"] == snapshot
        repeated = await test_client.post(conversation_url, headers=owner, json=payload)
        assert repeated.status_code == 201 and repeated.json()["id"] == thread["id"]
        for url, changes in (
            (f"/api/counseling/students/{second_id}/conversations", {}),
            (conversation_url, {"background_snapshot": "另一份背景"}),
        ):
            conflict = await test_client.post(url, headers=owner, json={**payload, **changes})
            assert conflict.status_code == 409, conflict.text
        for changes in ({"student_id": second_id}, {"metadata": {"counseling": snapshot}}):
            denied = await test_client.put(f"/api/chat/thread/{thread['id']}", headers=owner, json=changes)
            assert denied.status_code == 422, denied.text
        forged = await test_client.post(
            "/api/chat/thread", headers=owner, json={"agent_id": agent_slug, "metadata": {"counseling": snapshot}}
        )
        assert forged.status_code == 400, forged.text
        missing_confirmation = await test_client.post(conversation_url, headers=owner, json={"agent_id": agent_slug})
        assert missing_confirmation.status_code == 422
        for headers in (other, manager, tech, foreign_manager, no_role):
            denied = await test_client.post(conversation_url, headers=headers, json=payload)
            assert denied.status_code in {403, 404}, denied.text
            denied = await test_client.get(f"/api/chat/thread/{thread['id']}/history", headers=headers)
            assert denied.status_code == 404, denied.text
            denied = await test_client.get(f"/api/counseling/students/{student_id}/conversations", headers=headers)
            assert denied.status_code in {403, 404}, denied.text
        await test_client.put(
            f"/api/counseling/students/{student_id}",
            headers=owner,
            json={"background_summary": "档案后续变化", "status": "active"},
        )
        history = await test_client.get(f"/api/chat/thread/{thread['id']}/history", headers=owner)
        assert history.status_code == 200, history.text
        assert history.json()["thread"]["metadata"]["counseling"] == snapshot
        listed = await test_client.get(f"/api/counseling/students/{student_id}/conversations", headers=owner)
        assert [item["id"] for item in listed.json()] == [thread["id"]]
        listed = await test_client.get(f"/api/counseling/students/{second_id}/conversations", headers=owner)
        assert listed.json() == []
        failed_run = await test_client.post(
            "/api/agent/runs",
            headers=owner,
            json={
                "agent_slug": agent_slug,
                "thread_id": thread["id"],
                "query": "无模型测试",
                "model_spec": "missing-counseling-provider/model",
            },
        )
        assert failed_run.status_code == 422, failed_run.text
        assert "模型" in failed_run.text
        persisted_metadata = await conn.fetchval(
            "SELECT extra_metadata FROM conversations WHERE thread_id = $1", thread["id"]
        )
        assert json.loads(persisted_metadata)["counseling"] == snapshot
        assert (
            await conn.fetchval("SELECT COUNT(*) FROM agent_runs WHERE conversation_thread_id = $1", thread["id"]) == 0
        )
        engine = create_async_engine(os.environ["POSTGRES_URL"])
        request_id = uuid.uuid4().hex
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                # 只隔离模型目录解析；接入、消息、请求和 Run 使用真实 PostgreSQL。
                with patch.object(
                    queue_service, "resolve_agent_run_config", AsyncMock(return_value=("test:model", "auto"))
                ):
                    result = await queue_service.intake_request(
                        db=db,
                        request_id=request_id,
                        uid=thread["uid"],
                        agent_slug=agent_slug,
                        thread_id=thread["id"],
                        input_message=build_chat_input_message("当前问题"),
                        agent_item=None,
                        agent_backend=None,
                        meta={"counseling": {"student_id": second_id, "background_snapshot": "伪造"}},
                    )
                run = await db.get(AgentRun, result.run_id)
                assert run is not None
                assert run.input_payload["model_context"]["payload"] == snapshot
                # 本测试不向 worker 发布任务，同事务结束测试运行，避免留下待执行任务。
                run.status = "cancelled"
                run.finished_at = utc_now_naive()
                await db.commit()
            async with async_sessionmaker(engine)() as db:
                request = await db.scalar(select(AgentRunRequest).where(AgentRunRequest.request_id == request_id))
                persisted_input = await db.get(Message, request.input_message_id)
                assert request.input_payload["model_context"]["payload"] == snapshot
                assert persisted_input.content == "当前问题"
                model_input = persisted_input.extra_metadata["raw_message"]["content"]
                assert "人工确认的虚构背景" in model_input[0]["text"]
                assert "档案后续变化" not in model_input[0]["text"]
                assert "伪造" not in model_input[0]["text"]
        finally:
            await engine.dispose()
        await test_client.delete(f"/api/chat/thread/{thread['id']}", headers=owner)
        listed = await test_client.get(f"/api/counseling/students/{student_id}/conversations", headers=owner)
        assert listed.json() == []
    finally:
        await conn.execute(
            "UPDATE messages SET run_id = NULL WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE uid IN (SELECT uid FROM users WHERE id = ANY($1::integer[])))",
            users,
        )
        for table in ("agent_run_requests", "agent_runs"):
            await conn.execute(
                f"DELETE FROM {table} WHERE uid IN (SELECT uid FROM users WHERE id = ANY($1::integer[]))", users
            )
        await conn.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE uid IN (SELECT uid FROM users WHERE id = ANY($1::integer[])))",
            users,
        )
        await conn.execute(
            "DELETE FROM conversation_stats WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE uid IN (SELECT uid FROM users WHERE id = ANY($1::integer[])))",
            users,
        )
        await conn.execute(
            "DELETE FROM conversations WHERE uid IN (SELECT uid FROM users WHERE id = ANY($1::integer[]))", users
        )
        await conn.execute(
            "DELETE FROM projects WHERE uid IN (SELECT uid FROM users WHERE id = ANY($1::integer[]))", users
        )
        await conn.execute("DELETE FROM agents WHERE slug = $1", f"student-agent-{suffix}")
        await conn.execute("DELETE FROM counseling_audit_events WHERE department_id = ANY($1::integer[])", departments)
        await conn.execute("DELETE FROM counseling_students WHERE department_id = ANY($1::integer[])", departments)
        await conn.execute("DELETE FROM users WHERE id = ANY($1::integer[])", users)
        await conn.execute("DELETE FROM departments WHERE id = ANY($1::integer[])", departments)
        await conn.close()
        owner_uid = f"student_{suffix}_1"
        test_directory = global_user_data_dir(owner_uid)
        assert test_directory.name == owner_uid and test_directory.parent.name == "shared"
        if test_directory.exists():
            shutil.rmtree(test_directory)


async def test_student_migration_is_idempotent_and_checks_status():
    """迁移可重复执行，数据库拒绝非法状态。"""
    pg_manager.initialize()
    await migrate_legacy_business_schema(8)
    await migrate_legacy_business_schema(8)
    conn = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    try:
        columns = {
            row["column_name"]
            for row in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'counseling_students'"
            )
        }
        assert {
            "department_id",
            "student_code",
            "display_name",
            "class_name",
            "counselor_id",
            "background_summary",
            "status",
            "current_risk_level",
            "version",
        } <= columns
        constraints = {
            row["conname"]
            for row in await conn.fetch(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'counseling_students'::regclass"
            )
        }
        assert {"uq_counseling_students_department_code", "ck_counseling_students_status"} <= constraints
        transaction = conn.transaction()
        await transaction.start()
        try:
            dept = await conn.fetchval(
                "INSERT INTO departments (name, description) VALUES ($1, 'test') RETURNING id",
                f"migration_student_{uuid.uuid4().hex}",
            )
            user = await conn.fetchval(
                """INSERT INTO users (username, uid, password_hash, role, department_id,
                                      login_failed_count, is_deleted, created_at)
                   VALUES ($1, $1, 'test', 'user', $2, 0, 0, NOW()) RETURNING id""",
                f"migration_student_{uuid.uuid4().hex}",
                dept,
            )
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """INSERT INTO counseling_students (department_id, student_code, counselor_id, status)
                       VALUES ($1, $2, $3, 'invalid')""",
                    dept,
                    "invalid-state",
                    user,
                )
        finally:
            await transaction.rollback()
    finally:
        await conn.close()
