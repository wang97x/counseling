"""最小业务闭环的真实 HTTP 与 PostgreSQL 验证。"""

import asyncio
import json
import os
import uuid

import asyncpg
import pytest

from yuxi.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _content(overview: str) -> dict:
    """构造不含真实个案信息的咨询记录。"""
    return {
        "overview": overview,
        "observation": "虚构观察",
        "action_taken": "虚构行动",
        "next_plan": "虚构计划",
        "risk_notes": "由辅导员另行人工判断",
    }


async def test_manual_consultation_risk_correction_and_admin_summary(test_client) -> None:
    """手工记录、风险、更正和最小统计形成隔离的持久化闭环。"""
    suffix = uuid.uuid4().hex[:10]
    connection = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    department_id = None
    user_ids: list[int] = []

    async def actor(role: str, business_roles: str):
        uid = f"minimal_{suffix}_{len(user_ids)}"
        user_id = await connection.fetchval(
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
        user_ids.append(user_id)
        return {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(user_id)})}"}

    try:
        department_id = await connection.fetchval(
            "INSERT INTO departments (name, description) VALUES ($1, 'test') RETURNING id",
            f"minimal_dept_{suffix}",
        )
        owner = await actor("user", '["counselor"]')
        other = await actor("user", '["counselor"]')
        manager = await actor("admin", '["business_admin"]')

        created = await test_client.post(
            "/api/counseling/students",
            headers=owner,
            json={"student_code": "M-001", "display_name": "测试学生", "class_name": "测试班级"},
        )
        assert created.status_code == 201, created.text
        student_id = created.json()["id"]
        assert created.json()["current_risk_level"] == "unassessed"

        request_id = uuid.uuid4().hex
        draft_response = await test_client.post(
            f"/api/counseling/students/{student_id}/consultation-drafts",
            headers=owner,
            json={
                "request_id": request_id,
                "consulted_at": "2026-09-23T02:00:00Z",
                "consultation_type": "面谈",
                "content": _content("第一次虚构咨询"),
            },
        )
        assert draft_response.status_code == 201, draft_response.text
        draft = draft_response.json()
        assert draft["record_kind"] == "manual" and draft["version"] == 1
        assert draft["source"] is None

        repeated = await test_client.post(
            f"/api/counseling/students/{student_id}/consultation-drafts",
            headers=owner,
            json={
                "request_id": request_id,
                "consulted_at": "2026-09-23T02:00:00Z",
                "consultation_type": "面谈",
                "content": _content("重复请求不覆盖原草稿"),
            },
        )
        assert repeated.status_code == 201 and repeated.json()["id"] == draft["id"]
        assert repeated.json()["content"]["overview"] == "第一次虚构咨询"
        listed_drafts = await test_client.get(
            f"/api/counseling/students/{student_id}/record-drafts", headers=owner
        )
        assert listed_drafts.status_code == 200, listed_drafts.text
        draft_detail = await test_client.get(
            f"/api/counseling/students/{student_id}/record-drafts/{draft['id']}", headers=owner
        )
        assert draft_detail.status_code == 200, draft_detail.text

        concurrent_request_id = uuid.uuid4().hex
        concurrent_payload = {
            "request_id": concurrent_request_id,
            "consulted_at": "2026-09-23T02:10:00Z",
            "consultation_type": "面谈",
            "content": _content("并发幂等咨询记录"),
        }
        concurrent_responses = await asyncio.gather(
            *(
                test_client.post(
                    f"/api/counseling/students/{student_id}/consultation-drafts",
                    headers=owner,
                    json=concurrent_payload,
                )
                for _ in range(2)
            )
        )
        assert [response.status_code for response in concurrent_responses] == [201, 201]
        assert len({response.json()["id"] for response in concurrent_responses}) == 1

        before_confirm = await test_client.get(
            f"/api/counseling/students/{student_id}/timeline", headers=owner
        )
        assert before_confirm.status_code == 200 and before_confirm.json() == []

        for headers in (other, manager):
            denied = await test_client.get(
                f"/api/counseling/students/{student_id}/record-drafts/{draft['id']}", headers=headers
            )
            assert denied.status_code in {403, 404}, denied.text

        stale_update = await test_client.put(
            f"/api/counseling/students/{student_id}/consultation-drafts/{draft['id']}",
            headers=owner,
            json={
                "expected_version": 99,
                "consulted_at": "2026-09-23T02:30:00Z",
                "consultation_type": "面谈",
                "content": _content("不得写入的旧版本"),
            },
        )
        assert stale_update.status_code == 409, stale_update.text

        updated = await test_client.put(
            f"/api/counseling/students/{student_id}/consultation-drafts/{draft['id']}",
            headers=owner,
            json={
                "expected_version": 1,
                "consulted_at": "2026-09-23T02:30:00Z",
                "consultation_type": "面谈",
                "content": _content("人工修订后的咨询记录"),
            },
        )
        assert updated.status_code == 200 and updated.json()["version"] == 2, updated.text

        confirmation_key = uuid.uuid4().hex
        confirmed = await test_client.post(
            f"/api/counseling/students/{student_id}/consultation-drafts/{draft['id']}/confirm",
            headers=owner,
            json={"expected_version": 2, "confirmation_key": confirmation_key},
        )
        assert confirmed.status_code == 200, confirmed.text
        record = confirmed.json()
        assert record["content"]["overview"] == "人工修订后的咨询记录"
        repeated_confirm = await test_client.post(
            f"/api/counseling/students/{student_id}/consultation-drafts/{draft['id']}/confirm",
            headers=owner,
            json={"expected_version": 2, "confirmation_key": confirmation_key},
        )
        assert repeated_confirm.status_code == 200 and repeated_confirm.json()["id"] == record["id"]

        correction = await test_client.post(
            f"/api/counseling/students/{student_id}/records/{record['id']}/corrections",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "reason": "补充人工核对内容",
                "corrected_content": _content("追加更正后的内容"),
            },
        )
        assert correction.status_code == 201, correction.text

        risk = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-events",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "level": "watch",
                "basis": "辅导员人工判断的虚构依据",
                "action_taken": "继续观察",
                "status": "monitoring",
                "source_record_id": record["id"],
            },
        )
        assert risk.status_code == 201, risk.text
        risk_history = await test_client.get(
            f"/api/counseling/students/{student_id}/risk-events", headers=owner
        )
        assert risk_history.status_code == 200 and len(risk_history.json()) == 1, risk_history.text
        detail = await test_client.get(f"/api/counseling/students/{student_id}", headers=owner)
        assert detail.json()["current_risk_level"] == "watch"

        timeline = await test_client.get(f"/api/counseling/students/{student_id}/timeline", headers=owner)
        assert timeline.status_code == 200, timeline.text
        assert {item["type"] for item in timeline.json()} == {
            "consultation_record",
            "record_correction",
            "risk_event",
        }

        summary = await test_client.get("/api/counseling/admin/summary", headers=manager)
        assert summary.status_code == 200, summary.text
        assert summary.json()["student_count"] == 1
        assert summary.json()["confirmed_record_count"] == 1
        assert summary.json()["open_risk_event_count"] == 1
        assert "人工修订后的咨询记录" not in summary.text
        manager_students = await test_client.get("/api/counseling/students", headers=manager)
        assert manager_students.status_code == 200
        assert "测试学生" not in manager_students.text and "测试班级" not in manager_students.text
        denied_summary = await test_client.get("/api/counseling/admin/summary", headers=owner)
        assert denied_summary.status_code == 403

        closed = await test_client.post(
            f"/api/counseling/students/{student_id}/close",
            headers=owner,
            json={"expected_version": detail.json()["version"], "closure_note": "阶段工作结束"},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"
        assert closed.json()["closure_note"] == "阶段工作结束"

        persisted = await connection.fetchrow(
            "SELECT record_kind, content FROM counseling_records WHERE id = $1", record["id"]
        )
        assert persisted["record_kind"] == "manual"
        persisted_content = (
            json.loads(persisted["content"])
            if isinstance(persisted["content"], str)
            else persisted["content"]
        )
        assert persisted_content["overview"] == "人工修订后的咨询记录"
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM counseling_record_revisions WHERE draft_id = $1", draft["id"]
        ) == 2
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM counseling_risk_events WHERE student_id = $1", student_id
        ) == 1
        audited_reads = await connection.fetch(
            "SELECT action FROM counseling_audit_events "
            "WHERE student_id = $1 AND action = ANY($2::varchar[])",
            student_id,
            ["student.read", "record_draft.list", "record_draft.read", "timeline.read", "risk_event.list"],
        )
        assert {row["action"] for row in audited_reads} >= {
            "student.read",
            "record_draft.list",
            "record_draft.read",
            "timeline.read",
            "risk_event.list",
        }

        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="counseling_records are immutable"):
                await connection.execute(
                    "UPDATE counseling_records SET parsed_text = 'forbidden' WHERE id = $1", record["id"]
                )
        finally:
            await transaction.rollback()

        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="counseling_record_corrections are immutable"):
                await connection.execute(
                    "UPDATE counseling_record_corrections SET reason = 'forbidden' WHERE id = $1",
                    correction.json()["id"],
                )
        finally:
            await transaction.rollback()
    finally:
        if department_id is not None:
            cleanup = connection.transaction()
            await cleanup.start()
            try:
                await connection.execute(
                    "LOCK TABLE counseling_record_corrections, counseling_records IN ACCESS EXCLUSIVE MODE"
                )
                await connection.execute(
                    "ALTER TABLE counseling_record_corrections DISABLE TRIGGER trg_counseling_corrections_immutable"
                )
                await connection.execute(
                    "ALTER TABLE counseling_records DISABLE TRIGGER trg_counseling_records_immutable"
                )
                await connection.execute(
                    "DELETE FROM counseling_audit_events WHERE department_id = $1", department_id
                )
                await connection.execute(
                    "DELETE FROM counseling_risk_events WHERE department_id = $1", department_id
                )
                await connection.execute(
                    "DELETE FROM counseling_record_corrections WHERE student_id IN "
                    "(SELECT id FROM counseling_students WHERE department_id = $1)",
                    department_id,
                )
                await connection.execute(
                    "DELETE FROM counseling_records WHERE student_id IN "
                    "(SELECT id FROM counseling_students WHERE department_id = $1)",
                    department_id,
                )
                await connection.execute(
                    "ALTER TABLE counseling_records ENABLE TRIGGER trg_counseling_records_immutable"
                )
                await connection.execute(
                    "ALTER TABLE counseling_record_corrections ENABLE TRIGGER "
                    "trg_counseling_corrections_immutable"
                )
                await connection.execute(
                    "DELETE FROM counseling_record_revisions WHERE draft_id IN "
                    "(SELECT id FROM counseling_record_drafts WHERE department_id = $1)",
                    department_id,
                )
                await connection.execute(
                    "DELETE FROM counseling_record_drafts WHERE department_id = $1", department_id
                )
                await connection.execute(
                    "DELETE FROM counseling_students WHERE department_id = $1", department_id
                )
                if user_ids:
                    await connection.execute("DELETE FROM users WHERE id = ANY($1::integer[])", user_ids)
                await connection.execute("DELETE FROM departments WHERE id = $1", department_id)
                await cleanup.commit()
            except Exception:
                await cleanup.rollback()
                raise
        await connection.close()
