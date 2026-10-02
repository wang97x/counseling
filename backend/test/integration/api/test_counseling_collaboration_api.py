"""P3 授权协作真实 HTTP 与 PostgreSQL 回读测试。"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _acknowledge_notice(test_client, headers):
    notice = await test_client.get("/api/counseling/data-use-notice", headers=headers)
    assert notice.status_code == 200, notice.text
    response = await test_client.post(
        "/api/counseling/data-use-notice/acknowledgments",
        headers=headers,
        json={"version": notice.json()["version"]},
    )
    assert response.status_code in {200, 201}, response.text


async def test_supervision_authorization_is_role_and_scope_isolated(test_client, p3_users):
    """负责人可申请、管理员可批准、督导只能读取获准授权。"""
    counselor = p3_users["counselor"]
    supervisor = p3_users["supervisor"]
    manager = p3_users["business_admin"]
    for item in (counselor, supervisor, manager):
        await _acknowledge_notice(test_client, item["headers"])

    suffix = uuid.uuid4().hex[:10]
    student = await test_client.post(
        "/api/counseling/students",
        headers=counselor["headers"],
        json={"student_code": f"P3-{suffix}"},
    )
    assert student.status_code == 201, student.text
    student_id = student.json()["id"]
    authorization_id = None
    conn = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    try:
        now = datetime.now(UTC)
        created = await test_client.post(
            f"/api/counseling/collaboration/students/{student_id}/supervision-authorizations",
            headers=counselor["headers"],
            json={
                "request_id": f"p3_{suffix}_auth",
                "supervisor_id": supervisor["user"]["id"],
                "scopes": ["case_overview"],
                "purpose": "真实 HTTP 集成测试",
                "effective_from": now.isoformat(),
                "expires_at": (now + timedelta(days=1)).isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        authorization_id = created.json()["id"]
        assert created.json()["status"] == "pending"

        denied = await test_client.get(
            "/api/counseling/collaboration/supervision-authorizations",
            headers=supervisor["headers"],
        )
        assert denied.status_code == 200, denied.text
        assert authorization_id not in {item["id"] for item in denied.json()}

        decision = await test_client.post(
            f"/api/counseling/collaboration/supervision-authorizations/{authorization_id}/decision",
            headers=manager["headers"],
            json={"expected_version": 1, "decision": "approved", "note": "测试批准"},
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["status"] == "active"

        visible = await test_client.get(
            "/api/counseling/collaboration/supervision-authorizations",
            headers=supervisor["headers"],
        )
        assert visible.status_code == 200, visible.text
        assert authorization_id in {item["id"] for item in visible.json()}

        revoked = await test_client.post(
            f"/api/counseling/collaboration/supervision-authorizations/{authorization_id}/revoke",
            headers=counselor["headers"],
            json={"expected_version": 2, "note": "测试撤回"},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"

        blocked = await test_client.get(
            f"/api/counseling/collaboration/supervision-authorizations/{authorization_id}/materials",
            headers=supervisor["headers"],
        )
        assert blocked.status_code == 403, blocked.text
    finally:
        if authorization_id:
            for table in (
                "counseling_supervision_feedback",
                "counseling_supervision_materials",
                "counseling_supervision_summaries",
            ):
                await conn.execute(f"DELETE FROM {table} WHERE authorization_id = $1", authorization_id)
            await conn.execute(
                "DELETE FROM counseling_supervision_authorizations WHERE id = $1",
                authorization_id,
            )
        await conn.execute("DELETE FROM counseling_audit_events WHERE student_id = $1", student_id)
        await conn.execute("DELETE FROM counseling_students WHERE id = $1", student_id)
        await conn.close()
