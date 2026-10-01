"""P1B 量表与内部预约的真实 HTTP 和 PostgreSQL 验证。"""

import os
import asyncio
import uuid

import asyncpg
import pytest
from counseling.identity.auth import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_assessment_and_appointment_are_scored_isolated_and_versioned(test_client) -> None:
    """量表由服务端计分，预约按版本与状态机在负责人档案内收敛。"""
    suffix = uuid.uuid4().hex[:10]
    connection = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    department_id = None
    user_ids: list[int] = []

    async def actor(roles: str):
        uid = f"p1b_{suffix}_{len(user_ids)}"
        user_id = await connection.fetchval(
            """
            INSERT INTO users (username, uid, password_hash, role, business_roles,
                               department_id, login_failed_count, is_deleted, created_at)
            VALUES ($1, $1, 'test', 'user', $2::jsonb, $3, 0, 0, NOW()) RETURNING id
            """,
            uid,
            roles,
            department_id,
        )
        await connection.execute(
            "INSERT INTO counseling_data_use_acknowledgments (user_id, notice_version) "
            "VALUES ($1, '2026-10-01')",
            user_id,
        )
        user_ids.append(user_id)
        return {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(user_id)})}"}

    try:
        department_id = await connection.fetchval(
            "INSERT INTO departments (name, description) VALUES ($1, 'test') RETURNING id",
            f"p1b_dept_{suffix}",
        )
        owner = await actor('["counselor"]')
        other = await actor('["counselor"]')
        created = await test_client.post(
            "/api/counseling/students",
            headers=owner,
            json={"student_code": "P1B-001", "display_name": "虚构学生"},
        )
        assert created.status_code == 201, created.text
        student_id = created.json()["id"]

        catalog = await test_client.get("/api/counseling/students/scales", headers=owner)
        assert catalog.status_code == 200
        assert [(item["code"], item["version"], len(item["items"])) for item in catalog.json()] == [
            ("phq9", 1, 9)
        ]

        invalid = await test_client.post(
            f"/api/counseling/students/{student_id}/assessments",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "scale_code": "phq9",
                "scale_version": 1,
                "answers": [0] * 8,
                "administered_at": "2026-10-01T01:00:00Z",
            },
        )
        for invalid_answer in (True, "1"):
            strict_invalid = await test_client.post(
                f"/api/counseling/students/{student_id}/assessments",
                headers=owner,
                json={
                    "request_id": uuid.uuid4().hex,
                    "scale_code": "phq9",
                    "scale_version": 1,
                    "answers": [invalid_answer] + [0] * 8,
                    "administered_at": "2026-10-01T01:00:00Z",
                },
            )
            assert strict_invalid.status_code == 422

        assert invalid.status_code == 422

        assessment_request = uuid.uuid4().hex
        assessment_payload = {
            "request_id": assessment_request,
            "scale_code": "phq9",
            "scale_version": 1,
            "answers": [1, 1, 1, 1, 1, 1, 1, 1, 2],
            "administered_at": "2026-10-01T01:00:00Z",
        }
        assessment_responses = await asyncio.gather(
            *(
                test_client.post(
                    f"/api/counseling/students/{student_id}/assessments",
                    headers=owner,
                    json=assessment_payload,
                )
                for _ in range(2)
            )
        )
        assert {response.status_code for response in assessment_responses} == {201}
        assert len({response.json()["id"] for response in assessment_responses}) == 1
        assessment = assessment_responses[0]
        listed_assessments = await test_client.get(
            f"/api/counseling/students/{student_id}/assessments", headers=owner
        )
        assert listed_assessments.status_code == 200
        assert assessment.status_code == 201, assessment.text
        assert (assessment.json()["total_score"], assessment.json()["severity"]) == (10, "moderate")
        repeated = await test_client.post(
            f"/api/counseling/students/{student_id}/assessments",
            headers=owner,
            json=assessment_payload,
        )
        assert repeated.status_code == 201 and repeated.json()["id"] == assessment.json()["id"]
        denied = await test_client.get(
            f"/api/counseling/students/{student_id}/assessments", headers=other
        )
        assert denied.status_code == 404
        detail = await test_client.get(f"/api/counseling/students/{student_id}", headers=owner)
        assert detail.json()["current_risk_level"] == "unassessed"

        invalid_time = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "scheduled_start": "2026-10-02T02:00:00Z",
                "scheduled_end": "2026-10-02T01:00:00Z",
                "appointment_type": "面谈",
            },
        )
        assert invalid_time.status_code == 422

        appointment_payload = {
            "request_id": uuid.uuid4().hex,
            "scheduled_start": "2026-10-02T01:00:00Z",
            "scheduled_end": "2026-10-02T02:00:00Z",
            "appointment_type": "面谈",
            "location": "虚构地点",
        }
        appointment_responses = await asyncio.gather(
            *(
                test_client.post(
                    f"/api/counseling/students/{student_id}/appointments",
                    headers=owner,
                    json=appointment_payload,
                )
                for _ in range(2)
            )
        )
        assert {response.status_code for response in appointment_responses} == {201}
        assert len({response.json()["id"] for response in appointment_responses}) == 1
        appointment = appointment_responses[0]
        assert appointment.status_code == 201, appointment.text
        appointment_id = appointment.json()["id"]
        stale = await test_client.put(
            f"/api/counseling/students/{student_id}/appointments/{appointment_id}",
            headers=owner,
            json={
                "expected_version": 99,
                "scheduled_start": "2026-10-03T01:00:00Z",
                "scheduled_end": "2026-10-03T02:00:00Z",
                "appointment_type": "面谈",
            },
        )
        assert stale.status_code == 409
        updated = await test_client.put(
            f"/api/counseling/students/{student_id}/appointments/{appointment_id}",
            headers=owner,
            json={
                "expected_version": 1,
                "scheduled_start": "2026-10-03T01:00:00Z",
                "scheduled_end": "2026-10-03T02:00:00Z",
                "appointment_type": "线上",
                "note": "虚构备注",
            },
        )
        assert updated.status_code == 200 and updated.json()["version"] == 2
        arrived = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments/{appointment_id}/status",
            headers=owner,
            json={"expected_version": 2, "status": "arrived"},
        )
        assert arrived.status_code == 200 and arrived.json()["version"] == 3
        completed = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments/{appointment_id}/status",
            headers=owner,
            json={"expected_version": 3, "status": "completed"},
        )
        assert completed.status_code == 200 and completed.json()["status"] == "completed"
        terminal = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments/{appointment_id}/status",
            headers=owner,
            json={"expected_version": 4, "status": "canceled"},
        )
        assert terminal.status_code == 409
        cancel_payload = {
            "request_id": uuid.uuid4().hex,
            "scheduled_start": "2026-10-04T01:00:00Z",
            "scheduled_end": "2026-10-04T02:00:00Z",
            "appointment_type": "面谈",
            "location": "原始地点",
        }
        cancel_created = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments",
            headers=owner,
            json=cancel_payload,
        )
        assert cancel_created.status_code == 201
        cancel_id = cancel_created.json()["id"]
        cancel_updated = await test_client.put(
            f"/api/counseling/students/{student_id}/appointments/{cancel_id}",
            headers=owner,
            json={
                "expected_version": 1,
                "scheduled_start": "2026-10-05T01:00:00Z",
                "scheduled_end": "2026-10-05T02:00:00Z",
                "appointment_type": "线上",
                "location": "改期地点",
            },
        )
        assert cancel_updated.status_code == 200
        replayed_create = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments",
            headers=owner,
            json=cancel_payload,
        )
        assert replayed_create.status_code == 201
        assert replayed_create.json()["id"] == cancel_id
        canceled = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments/{cancel_id}/status",
            headers=owner,
            json={"expected_version": 2, "status": "canceled"},
        )
        assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
        cannot_restore = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments/{cancel_id}/status",
            headers=owner,
            json={"expected_version": 3, "status": "arrived"},
        )
        assert cannot_restore.status_code == 409
        listed_appointments = await test_client.get(
            f"/api/counseling/students/{student_id}/appointments", headers=owner
        )
        assert listed_appointments.status_code == 200
        denied = await test_client.get(
            f"/api/counseling/students/{student_id}/appointments", headers=other
        )
        assert denied.status_code == 404

        timeline = await test_client.get(
            f"/api/counseling/students/{student_id}/timeline", headers=owner
        )
        assert {"assessment", "appointment"} <= {item["type"] for item in timeline.json()}
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM counseling_assessment_results WHERE student_id = $1", student_id
        ) == 1
        assert await connection.fetchval(
            "SELECT status FROM counseling_appointments WHERE id = $1", appointment_id
        ) == "completed"
        assert await connection.fetchval(
            "SELECT status FROM counseling_appointments WHERE id = $1", cancel_id
        ) == "canceled"
        audit_actions = await connection.fetch(
            "SELECT action FROM counseling_audit_events "
            "WHERE student_id = $1 AND action IN ('assessment.list', 'appointment.list')",
            student_id,
        )
        assert {row["action"] for row in audit_actions} == {"assessment.list", "appointment.list"}
        closed = await test_client.post(
            f"/api/counseling/students/{student_id}/close",
            headers=owner,
            json={"expected_version": detail.json()["version"], "closure_note": "P1B 测试结案"},
        )
        assert closed.status_code == 200
        assessment_after_close = await test_client.post(
            f"/api/counseling/students/{student_id}/assessments",
            headers=owner,
            json=assessment_payload,
        )
        assert assessment_after_close.status_code == 201
        assert assessment_after_close.json()["id"] == assessment.json()["id"]
        appointment_after_close = await test_client.post(
            f"/api/counseling/students/{student_id}/appointments",
            headers=owner,
            json=appointment_payload,
        )
        assert appointment_after_close.status_code == 201
        assert appointment_after_close.json()["id"] == appointment_id
        new_after_close = await test_client.post(
            f"/api/counseling/students/{student_id}/assessments",
            headers=owner,
            json={**assessment_payload, "request_id": uuid.uuid4().hex},
        )
        assert new_after_close.status_code == 422


        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="counseling_assessment_results are immutable"):
                await connection.execute(
                    "UPDATE counseling_assessment_results SET total_score = 0 WHERE id = $1",
                    assessment.json()["id"],
                )
        finally:
            await transaction.rollback()
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(
                asyncpg.RaiseError,
                match="counseling appointment creation intent is immutable",
            ):
                await connection.execute(
                    "UPDATE counseling_appointments SET created_note = '篡改' WHERE id = $1",
                    appointment_id,
                )
        finally:
            await transaction.rollback()
    finally:
        if department_id is not None:
            transaction = connection.transaction()
            await transaction.start()
            try:
                await connection.execute(
                    "ALTER TABLE counseling_assessment_results DISABLE TRIGGER "
                    "trg_counseling_assessments_immutable"
                )
                await connection.execute(
                    "DELETE FROM counseling_audit_events WHERE department_id = $1", department_id
                )
                await connection.execute(
                    "DELETE FROM counseling_appointments WHERE department_id = $1", department_id
                )
                await connection.execute(
                    "DELETE FROM counseling_assessment_results WHERE department_id = $1", department_id
                )
                await connection.execute(
                    "ALTER TABLE counseling_assessment_results ENABLE TRIGGER "
                    "trg_counseling_assessments_immutable"
                )
                await connection.execute(
                    "DELETE FROM counseling_students WHERE department_id = $1", department_id
                )
                if user_ids:
                    await connection.execute(
                        "ALTER TABLE counseling_data_use_acknowledgments DISABLE TRIGGER "
                        "trg_counseling_notice_immutable"
                    )
                    await connection.execute(
                        "DELETE FROM counseling_data_use_acknowledgments "
                        "WHERE user_id = ANY($1::integer[])",
                        user_ids,
                    )
                    await connection.execute(
                        "ALTER TABLE counseling_data_use_acknowledgments ENABLE TRIGGER "
                        "trg_counseling_notice_immutable"
                    )
                    await connection.execute(
                        "DELETE FROM users WHERE id = ANY($1::integer[])", user_ids
                    )
                await connection.execute("DELETE FROM departments WHERE id = $1", department_id)
                await transaction.commit()
            except Exception:
                await transaction.rollback()
                raise
        await connection.close()
