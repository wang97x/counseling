"""用途告知门禁与业务审计回读的真实 HTTP/PostgreSQL 验证。"""

import os
import uuid

import asyncpg
import pytest
from counseling.governance.service import CURRENT_DATA_USE_NOTICE_VERSION
from counseling.identity.auth import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_notice_gate_and_audit_visibility_are_persisted(test_client) -> None:
    """用途告知由服务端强制，审计只在负责人或部门范围内回读。"""
    suffix = uuid.uuid4().hex[:10]
    connection = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    departments = [
        await connection.fetchval(
            "INSERT INTO departments (name, description) VALUES ($1, 'test') RETURNING id",
            f"governance_dept_{suffix}_{number}",
        )
        for number in (1, 2)
    ]
    users: list[int] = []

    async def actor(department_id: int, role: str, business_roles: str):
        uid = f"governance_{suffix}_{len(users)}"
        user_id = await connection.fetchval(
            """
            INSERT INTO users (username, uid, password_hash, role, business_roles,
                               department_id, login_failed_count, is_deleted, created_at)
            VALUES ($1, $1, 'test', $2, $3::jsonb, $4, 0, 0, NOW()) RETURNING id
            """,
            uid, role, business_roles, department_id,
        )
        users.append(user_id)
        return user_id, {
            "Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(user_id)})}"
        }

    async def acknowledge(headers: dict[str, str]) -> dict:
        notice = await test_client.get("/api/counseling/data-use-notice", headers=headers)
        assert notice.status_code == 200 and notice.json()["acknowledged"] is False
        response = await test_client.post(
            "/api/counseling/data-use-notice/acknowledgments",
            headers=headers,
            json={"version": notice.json()["version"]},
        )
        assert response.status_code == 200, response.text
        return response.json()

    owner_id, owner = await actor(departments[0], "user", '["counselor"]')
    _, other = await actor(departments[0], "user", '["counselor"]')
    _, manager = await actor(departments[0], "admin", '["business_admin"]')
    _, foreign_manager = await actor(departments[1], "admin", '["business_admin"]')
    _, super_admin = await actor(departments[0], "superadmin", '["super_admin"]')
    student_id = None
    try:
        blocked = await test_client.get("/api/counseling/students", headers=owner)
        assert blocked.status_code == 428, blocked.text
        stale = await test_client.post(
            "/api/counseling/data-use-notice/acknowledgments",
            headers=owner,
            json={"version": "obsolete"},
        )
        assert stale.status_code == 409

        accepted = await acknowledge(owner)
        assert accepted["version"] == CURRENT_DATA_USE_NOTICE_VERSION
        repeated = await test_client.post(
            "/api/counseling/data-use-notice/acknowledgments",
            headers=owner,
            json={"version": CURRENT_DATA_USE_NOTICE_VERSION},
        )
        assert repeated.json()["acknowledged_at"] == accepted["acknowledged_at"]
        persisted = await test_client.get("/api/counseling/data-use-notice", headers=owner)
        assert persisted.json()["acknowledged"] is True

        created = await test_client.post(
            "/api/counseling/students",
            headers=owner,
            json={
                "student_code": f"G-{suffix}",
                "display_name": "不得出现在审计响应的姓名",
                "class_name": "不得出现在审计响应的班级",
            },
        )
        assert created.status_code == 201, created.text
        student_id = created.json()["id"]
        detail = await test_client.get(
            f"/api/counseling/students/{student_id}", headers=owner
        )
        assert detail.status_code == 200

        await acknowledge(other)
        other_audit = await test_client.get("/api/counseling/audit-events", headers=other)
        assert other_audit.status_code == 200
        assert other_audit.json()["items"] == []

        await acknowledge(manager)
        manager_audit = await test_client.get(
            f"/api/counseling/audit-events?student_id={student_id}", headers=manager
        )
        assert manager_audit.status_code == 200, manager_audit.text
        assert {item["action"] for item in manager_audit.json()["items"]} >= {
            "student.create", "student.read"
        }
        assert all(item["actor_id"] == owner_id for item in manager_audit.json()["items"])
        assert "不得出现在审计响应" not in manager_audit.text

        await acknowledge(foreign_manager)
        foreign_audit = await test_client.get(
            "/api/counseling/audit-events", headers=foreign_manager
        )
        assert foreign_audit.status_code == 200
        assert foreign_audit.json()["items"] == []

        forbidden_notice = await test_client.get(
            "/api/counseling/data-use-notice", headers=super_admin
        )
        assert forbidden_notice.status_code == 403
        forbidden_audit = await test_client.get(
            "/api/counseling/audit-events", headers=super_admin
        )
        assert forbidden_audit.status_code == 403

        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(
                asyncpg.RaiseError,
                match="counseling_data_use_acknowledgments are immutable",
            ):
                await connection.execute(
                    "UPDATE counseling_data_use_acknowledgments "
                    "SET acknowledged_at = NOW() WHERE user_id = $1",
                    owner_id,
                )
        finally:
            await transaction.rollback()
    finally:
        if student_id is not None:
            await connection.execute(
                "DELETE FROM counseling_audit_events WHERE student_id = $1", student_id
            )
            await connection.execute(
                "DELETE FROM counseling_students WHERE id = $1", student_id
            )
        await connection.execute(
            "ALTER TABLE counseling_data_use_acknowledgments "
            "DISABLE TRIGGER trg_counseling_notice_immutable"
        )
        await connection.execute(
            "DELETE FROM counseling_data_use_acknowledgments "
            "WHERE user_id = ANY($1::integer[])",
            users,
        )
        await connection.execute(
            "ALTER TABLE counseling_data_use_acknowledgments "
            "ENABLE TRIGGER trg_counseling_notice_immutable"
        )
        await connection.execute(
            "DELETE FROM users WHERE id = ANY($1::integer[])", users
        )
        await connection.execute(
            "DELETE FROM departments WHERE id = ANY($1::integer[])", departments
        )
        await connection.close()
