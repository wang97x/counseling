"""P2 方案、人工危机工单、内部转介与回访的真实 HTTP 验证。"""

import asyncio
import os
import json
import uuid

import asyncpg
import pytest
from counseling.identity.auth import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_p2_continuity_and_human_safety_are_versioned_and_isolated(test_client) -> None:
    """P2 状态按档案和部门隔离，并在协议与人工状态机边界失败关闭。"""
    suffix = uuid.uuid4().hex[:10]
    connection = await asyncpg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", ""))
    department_id = None
    user_ids: list[int] = []
    source_run_ids: list[str] = []
    source_thread_id = None

    async def actor(roles: str):
        uid = f"p2_{suffix}_{len(user_ids)}"
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
            "INSERT INTO counseling_data_use_acknowledgments (user_id, notice_version) VALUES ($1, '2026-10-01')",
            user_id,
        )
        user_ids.append(user_id)
        return {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(user_id)})}"}

    try:
        department_id = await connection.fetchval(
            "INSERT INTO departments (name, description) VALUES ($1, 'test') RETURNING id",
            f"p2_dept_{suffix}",
        )
        owner = await actor('["counselor"]')
        other = await actor('["counselor"]')
        manager = await actor('["business_admin"]')
        created = await test_client.post(
            "/api/counseling/students",
            headers=owner,
            json={"student_code": "P2-001", "display_name": "虚构学生"},
        )
        assert created.status_code == 201, created.text
        student_id = created.json()["id"]
        work_item = await test_client.post(
            f"/api/counseling/students/{student_id}/ai-work-items",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "instruction": "输出严格 JSON 风险提示候选，不执行任何干预",
            },
        )
        assert work_item.status_code == 201, work_item.text
        work_item_id = work_item.json()["work_item_id"]
        source_thread_id = work_item.json()["thread_id"]
        conversation = await connection.fetchrow(
            "SELECT id, agent_id, uid FROM conversations WHERE thread_id = $1", source_thread_id
        )

        async def model_output(score: float, evidence: str, model_reference: str = "deterministic-test-model-v1"):
            run_id = uuid.uuid4().hex
            source_run_ids.append(run_id)
            await connection.execute(
                """
                INSERT INTO agent_runs
                    (id, conversation_thread_id, runtime_scope_id, agent_slug, uid, status,
                     request_id, source, channel, conversation_id, run_type, input_payload,
                     token_usage, origin_metadata, created_at, started_at, finished_at)
                VALUES ($1, $2, $2, $3, $4, 'completed', $5, 'chat', 'web', $6, 'chat',
                        $7::jsonb, '{}'::jsonb, '{}'::jsonb, NOW(), NOW(), NOW())
                """,
                run_id,
                source_thread_id,
                conversation["agent_id"],
                conversation["uid"],
                uuid.uuid4().hex,
                conversation["id"],
                json.dumps({"model_spec": model_reference}),
            )
            message_id = await connection.fetchval(
                """
                INSERT INTO messages (conversation_id, role, content, run_id, delivery_status)
                VALUES ($1, 'assistant', $2, $3, 'complete') RETURNING id
                """,
                conversation["id"],
                json.dumps({"schema_version": 1, "score": score, "evidence_summary": evidence}),
                run_id,
            )
            await connection.execute("UPDATE agent_runs SET output_message_id = $1 WHERE id = $2", message_id, run_id)
            return run_id

        first_plan = await test_client.post(
            f"/api/counseling/students/{student_id}/plans",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "stage_goals": ["稳定到访"],
                "action_plan": ["每周回顾"],
                "review_basis": "首次共同制定",
            },
        )
        assert first_plan.status_code == 201, first_plan.text
        second_plan = await test_client.post(
            f"/api/counseling/students/{student_id}/plans",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "stage_goals": ["巩固支持网络"],
                "action_plan": ["记录可用资源"],
                "review_basis": "阶段复盘后调整",
            },
        )
        assert second_plan.status_code == 201
        plans = await test_client.get(f"/api/counseling/students/{student_id}/plans", headers=owner)
        assert [item["version_no"] for item in plans.json()] == [2, 1]
        assert (await test_client.get(f"/api/counseling/students/{student_id}/plans", headers=other)).status_code == 404

        risk = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-events",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "level": "urgent",
                "basis": "虚构的人工核实依据",
                "action_taken": "已进行当面核实",
                "status": "open",
            },
        )
        assert risk.status_code == 201, risk.text
        case_payload = {
            "request_id": uuid.uuid4().hex,
            "risk_event_id": risk.json()["id"],
            "deadline_at": "2026-12-31T08:00:00Z",
            "initial_measure": "按机构流程持续人工跟进",
        }
        missing_protocol = await test_client.post(
            f"/api/counseling/students/{student_id}/crisis-cases",
            headers=owner,
            json=case_payload,
        )
        assert missing_protocol.status_code == 422
        protocol = await test_client.post(
            "/api/counseling/admin/crisis-protocols",
            headers=manager,
            json={
                "request_id": uuid.uuid4().hex,
                "title": "测试协议",
                "content": "仅用于自动化测试的虚构机构流程",
                "effective_from": "2026-01-01T00:00:00Z",
                "expires_at": "2027-01-01T00:00:00Z",
            },
        )
        assert protocol.status_code == 201, protocol.text
        protocols = await test_client.get("/api/counseling/admin/crisis-protocols", headers=manager)
        assert protocols.status_code == 200
        assert protocol.json()["id"] in {item["id"] for item in protocols.json()}

        passing_labels = [True] * 20 + [False] * 20
        denied_evaluation = await test_client.post(
            "/api/counseling/admin/risk-hint-evaluations",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "dataset_reference": "authorized-fixture-v1",
                "model_reference": "deterministic-test-model-v1",
                "threshold": 0.5,
                "labels": passing_labels,
                "scores": [0.9] * 19 + [0.1] + [0.9] + [0.1] * 19,
            },
        )
        assert denied_evaluation.status_code == 403
        invalid_labels = await test_client.post(
            "/api/counseling/admin/risk-hint-evaluations",
            headers=manager,
            json={
                "request_id": uuid.uuid4().hex,
                "dataset_reference": "invalid-fixture",
                "model_reference": "deterministic-test-model-v1",
                "threshold": 0.5,
                "labels": [1, False],
                "scores": [0.9, 0.1],
            },
        )
        assert invalid_labels.status_code == 422
        failed_evaluation = await test_client.post(
            "/api/counseling/admin/risk-hint-evaluations",
            headers=manager,
            json={
                "request_id": uuid.uuid4().hex,
                "dataset_reference": "authorized-fixture-failing-v1",
                "model_reference": "deterministic-test-model-v1",
                "threshold": 0.5,
                "labels": passing_labels,
                "scores": [0.9] * 20 + [0.9, 0.9] + [0.1] * 18,
            },
        )
        assert failed_evaluation.status_code == 201 and failed_evaluation.json()["passed"] is False
        passing_evaluation = await test_client.post(
            "/api/counseling/admin/risk-hint-evaluations",
            headers=manager,
            json={
                "request_id": uuid.uuid4().hex,
                "dataset_reference": "authorized-fixture-passing-v1",
                "model_reference": "deterministic-test-model-v1",
                "threshold": 0.5,
                "labels": passing_labels,
                "scores": [0.9] * 19 + [0.1] + [0.9] + [0.1] * 19,
            },
        )
        assert passing_evaluation.status_code == 201, passing_evaluation.text
        assert passing_evaluation.json()["passed"] is True
        evaluations = await test_client.get(
            "/api/counseling/admin/risk-hint-evaluations", headers=manager
        )
        assert evaluations.status_code == 200
        assert passing_evaluation.json()["id"] in {item["id"] for item in evaluations.json()}
        failed_run_id = await model_output(0.9, "虚构的未通过门禁来源")
        rejected_by_gate = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-hints",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "evaluation_id": failed_evaluation.json()["id"],
                "source_work_item_id": work_item_id,
                "source_run_id": failed_run_id,
            },
        )
        assert rejected_by_gate.status_code == 422
        below_run_id = await model_output(0.49, "虚构的低分依据")
        below_threshold = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-hints",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "evaluation_id": passing_evaluation.json()["id"],
                "source_work_item_id": work_item_id,
                "source_run_id": below_run_id,
            },
        )
        assert below_threshold.status_code == 422
        mismatched_run_id = await model_output(0.9, "错误模型来源", "other-model-v1")
        mismatched_model = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-hints",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "evaluation_id": passing_evaluation.json()["id"],
                "source_work_item_id": work_item_id,
                "source_run_id": mismatched_run_id,
            },
        )
        assert mismatched_model.status_code == 422
        accepted_run_id = await model_output(0.9, "虚构的模型触发依据，等待人工核实")
        hint = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-hints",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "evaluation_id": passing_evaluation.json()["id"],
                "source_work_item_id": work_item_id,
                "source_run_id": accepted_run_id,
            },
        )
        assert hint.status_code == 201, hint.text
        assert hint.json()["status"] == "pending_review"
        assert hint.json()["protocol_id"] == protocol.json()["id"]
        owner_hints = await test_client.get(
            f"/api/counseling/students/{student_id}/risk-hints", headers=owner
        )
        assert owner_hints.status_code == 200 and owner_hints.json()[0]["id"] == hint.json()["id"]
        hidden_hints = await test_client.get(
            f"/api/counseling/students/{student_id}/risk-hints", headers=other
        )
        assert hidden_hints.status_code == 404
        review_request_id = uuid.uuid4().hex
        review_payload = {
            "request_id": review_request_id,
            "expected_version": 1,
            "decision": "accepted",
            "note": "人工核实后采纳；仍需另行创建人工风险事件",
        }
        accepted_hint, replayed_hint = await asyncio.gather(
            *(
                test_client.post(
                    f"/api/counseling/students/{student_id}/risk-hints/{hint.json()['id']}/review",
                    headers=owner,
                    json=review_payload,
                )
                for _ in range(2)
            )
        )
        assert accepted_hint.status_code == 200, accepted_hint.text
        assert replayed_hint.status_code == 200, replayed_hint.text
        assert accepted_hint.json()["requires_manual_risk_event"] is True
        assert {accepted_hint.json()["version"], replayed_hint.json()["version"]} == {2}
        changed_replay = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-hints/{hint.json()['id']}/review",
            headers=owner,
            json={**review_payload, "note": "改变后的核实意图"},
        )
        assert changed_replay.status_code == 409
        rejected_run_id = await model_output(0.8, "第二条虚构提示，验证人工拒绝终态")
        second_hint = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-hints",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "evaluation_id": passing_evaluation.json()["id"],
                "source_work_item_id": work_item_id,
                "source_run_id": rejected_run_id,
            },
        )
        assert second_hint.status_code == 201, second_hint.text
        rejected_hint = await test_client.post(
            f"/api/counseling/students/{student_id}/risk-hints/{second_hint.json()['id']}/review",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "expected_version": 1,
                "decision": "rejected",
                "note": "人工核实后拒绝该提示",
            },
        )
        assert rejected_hint.status_code == 200
        assert rejected_hint.json()["status"] == "rejected"
        assert rejected_hint.json()["requires_manual_risk_event"] is False
        timeline = await test_client.get(
            f"/api/counseling/students/{student_id}/timeline", headers=owner
        )
        assert timeline.status_code == 200, timeline.text
        hint_nodes = [item for item in timeline.json() if item["type"] == "risk_hint"]
        assert {item["hint_status"] for item in hint_nodes} == {"accepted", "rejected"}
        hint_node = next(item for item in hint_nodes if item["id"] == hint.json()["id"])
        assert hint_node["hint_status"] == "accepted"
        assert hint_node["decision_note"] == review_payload["note"]
        crisis_case = await test_client.post(
            f"/api/counseling/students/{student_id}/crisis-cases",
            headers=owner,
            json=case_payload,
        )
        assert crisis_case.status_code == 201, crisis_case.text
        case_id = crisis_case.json()["id"]
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="requires one new event"):
                await connection.execute(
                    "UPDATE counseling_crisis_cases SET status = 'closed', version = version + 1 WHERE id = $1",
                    case_id,
                )
        finally:
            await transaction.rollback()
        premature_close = await test_client.post(
            f"/api/counseling/students/{student_id}/crisis-cases/{case_id}/events",
            headers=owner,
            json={"request_id": uuid.uuid4().hex, "expected_version": 1, "event_type": "close", "note": "不能跳过复核"},
        )
        assert premature_close.status_code == 409
        review_event_payload = {
            "request_id": uuid.uuid4().hex,
            "expected_version": 1,
            "event_type": "review",
            "note": "已由人工复核",
        }
        reviewed, replayed_review = await asyncio.gather(
            *(
                test_client.post(
                    f"/api/counseling/students/{student_id}/crisis-cases/{case_id}/events",
                    headers=owner,
                    json=review_event_payload,
                )
                for _ in range(2)
            )
        )
        assert reviewed.status_code == 200, reviewed.text
        assert replayed_review.status_code == 200, replayed_review.text
        assert reviewed.json()["status"] == replayed_review.json()["status"] == "reviewed"
        assert {reviewed.json()["version"], replayed_review.json()["version"]} == {2}
        initial_event_id = await connection.fetchval(
            "SELECT id FROM counseling_crisis_case_events "
            "WHERE case_id = $1 AND applied_case_version = 1",
            case_id,
        )
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="transition is invalid"):
                await connection.execute(
                    "UPDATE counseling_crisis_cases SET last_event_id = $1, "
                    "version = version + 1 WHERE id = $2",
                    initial_event_id,
                    case_id,
                )
        finally:
            await transaction.rollback()
        closed = await test_client.post(
            f"/api/counseling/students/{student_id}/crisis-cases/{case_id}/events",
            headers=owner,
            json={"request_id": uuid.uuid4().hex, "expected_version": 2, "event_type": "close", "note": "人工确认关闭"},
        )
        assert closed.status_code == 200 and closed.json()["status"] == "closed"
        assert closed.json()["protocol_id"] == protocol.json()["id"]

        denied_referral = await test_client.post(
            f"/api/counseling/students/{student_id}/referrals",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "reason": "测试",
                "authorization_status": "denied",
                "material_scope": ["student_metadata"],
            },
        )
        assert denied_referral.status_code == 422
        referral = await test_client.post(
            f"/api/counseling/students/{student_id}/referrals",
            headers=owner,
            json={
                "request_id": uuid.uuid4().hex,
                "reason": "需要机构内部协作",
                "authorization_status": "granted",
                "material_scope": ["student_metadata", "risk_level"],
                "follow_up_at": "2026-11-01T08:00:00Z",
            },
        )
        assert referral.status_code == 201, referral.text
        referral_id = referral.json()["id"]
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="transition is invalid"):
                await connection.execute(
                    "UPDATE counseling_referrals SET status = 'completed', version = version + 1 WHERE id = $1",
                    referral_id,
                )
        finally:
            await transaction.rollback()
        manager_queue = await test_client.get("/api/counseling/admin/referrals", headers=manager)
        assert manager_queue.status_code == 200
        manager_item = next(item for item in manager_queue.json() if item["id"] == referral_id)
        assert "reason" not in manager_item and "material_scope" not in manager_item
        accepted = await test_client.post(
            f"/api/counseling/admin/referrals/{referral_id}/decision",
            headers=manager,
            json={"expected_version": 1, "decision": "accepted", "note": "由内部人员接收"},
        )
        assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="decision metadata is immutable"):
                await connection.execute(
                    "UPDATE counseling_referrals SET status = 'completed', version = version + 1, "
                    "decision_note = '篡改', follow_up_result = '伪造回访', completed_at = NOW() "
                    "WHERE id = $1",
                    referral_id,
                )
        finally:
            await transaction.rollback()
        followed = await test_client.post(
            f"/api/counseling/students/{student_id}/referrals/{referral_id}/follow-up",
            headers=owner,
            json={"expected_version": 2, "result": "已完成虚构回访"},
        )
        assert followed.status_code == 200 and followed.json()["status"] == "completed"

        assert (
            await connection.fetchval("SELECT COUNT(*) FROM counseling_plan_versions WHERE student_id = $1", student_id)
            == 2
        )
        assert (
            await connection.fetchval("SELECT status FROM counseling_crisis_cases WHERE id = $1", case_id) == "closed"
        )
        assert (
            await connection.fetchval("SELECT status FROM counseling_referrals WHERE id = $1", referral_id)
            == "completed"
        )
        assert await connection.fetchval(
            "SELECT status FROM counseling_risk_hints WHERE id = $1", hint.json()["id"]
        ) == "accepted"
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM counseling_risk_events WHERE student_id = $1", student_id
        ) == 1
        manager_operations = {
            row["operation"]
            for row in await connection.fetch(
                "SELECT operation FROM operation_logs WHERE user_id = $1", user_ids[2]
            )
        }
        assert {
            "counseling.crisis_protocol.publish",
            "counseling.crisis_protocol.list",
            "counseling.referral.list",
            "counseling.risk_hint_evaluation.publish",
            "counseling.risk_hint_evaluation.list",
        } <= manager_operations
        owner_audits = {
            row["action"]
            for row in await connection.fetch(
                "SELECT action FROM counseling_audit_events WHERE actor_id = $1 AND student_id = $2",
                user_ids[0],
                student_id,
            )
        }
        assert {
            "risk_hint.create",
            "risk_hint.list",
            "risk_hint.accepted",
            "risk_hint.rejected",
            "timeline.read",
        } <= owner_audits
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.CheckViolationError):
                await connection.execute(
                    """
                    INSERT INTO counseling_risk_hint_evaluations
                        (id, department_id, dataset_reference, dataset_fingerprint, model_reference,
                         threshold, true_positive, false_negative, false_positive, true_negative,
                         recall, false_positive_rate, passed, created_by, request_id)
                    VALUES ($1, $2, 'invalid', $3, 'invalid', 0.5, 1, 99, 99, 1,
                            0.95, 0.05, TRUE, $4, $5)
                    """,
                    uuid.uuid4().hex,
                    department_id,
                    uuid.uuid4().hex + uuid.uuid4().hex,
                    user_ids[2],
                    uuid.uuid4().hex,
                )
        finally:
            await transaction.rollback()

        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="counseling P2 history is immutable"):
                await connection.execute(
                    "UPDATE counseling_plan_versions SET review_basis = '篡改' WHERE id = $1",
                    first_plan.json()["id"],
                )
        finally:
            await transaction.rollback()
        transaction = connection.transaction()
        await transaction.start()
        try:
            with pytest.raises(asyncpg.RaiseError, match="counseling risk hint origin is immutable"):
                await connection.execute(
                    "UPDATE counseling_risk_hints SET evidence_summary = '篡改' WHERE id = $1",
                    hint.json()["id"],
                )
        finally:
            await transaction.rollback()
    finally:
        if department_id is not None:
            transaction = connection.transaction()
            await transaction.start()
            try:
                for table in (
                    "counseling_plan_versions",
                    "counseling_crisis_protocols",
                    "counseling_crisis_case_events",
                    "counseling_risk_hint_evaluations",
                    "counseling_risk_hints",
                ):
                    await connection.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
                await connection.execute("DELETE FROM counseling_risk_hints WHERE department_id = $1", department_id)
                await connection.execute(
                    "DELETE FROM counseling_risk_hint_evaluations WHERE department_id = $1", department_id
                )
                await connection.execute(
                    "DELETE FROM counseling_crisis_case_events WHERE case_id IN "
                    "(SELECT id FROM counseling_crisis_cases WHERE department_id = $1)",
                    department_id,
                )
                await connection.execute("DELETE FROM counseling_crisis_cases WHERE department_id = $1", department_id)
                await connection.execute("DELETE FROM counseling_referrals WHERE department_id = $1", department_id)
                await connection.execute("DELETE FROM counseling_plan_versions WHERE department_id = $1", department_id)
                await connection.execute(
                    "DELETE FROM counseling_crisis_protocols WHERE department_id = $1", department_id
                )
                await connection.execute("DELETE FROM counseling_audit_events WHERE department_id = $1", department_id)
                await connection.execute("DELETE FROM counseling_risk_events WHERE department_id = $1", department_id)
                if source_run_ids:
                    await connection.execute(
                        "DELETE FROM messages WHERE run_id = ANY($1::varchar[])", source_run_ids
                    )
                    await connection.execute(
                        "DELETE FROM agent_runs WHERE id = ANY($1::varchar[])", source_run_ids
                    )
                await connection.execute(
                    "DELETE FROM counseling_ai_work_items WHERE department_id = $1", department_id
                )
                if source_thread_id:
                    await connection.execute(
                        "DELETE FROM conversation_stats WHERE conversation_id = "
                        "(SELECT id FROM conversations WHERE thread_id = $1)", source_thread_id
                    )
                    await connection.execute("DELETE FROM conversations WHERE thread_id = $1", source_thread_id)
                await connection.execute("DELETE FROM counseling_students WHERE department_id = $1", department_id)
                await connection.execute("ALTER TABLE counseling_data_use_acknowledgments DISABLE TRIGGER USER")
                await connection.execute(
                    "DELETE FROM counseling_data_use_acknowledgments WHERE user_id = ANY($1::integer[])", user_ids
                )
                await connection.execute("DELETE FROM operation_logs WHERE user_id = ANY($1::integer[])", user_ids)
                await connection.execute("DELETE FROM users WHERE id = ANY($1::integer[])", user_ids)
                await connection.execute("DELETE FROM departments WHERE id = $1", department_id)
                await connection.execute("ALTER TABLE counseling_data_use_acknowledgments ENABLE TRIGGER USER")
                for table in (
                    "counseling_plan_versions",
                    "counseling_crisis_protocols",
                    "counseling_crisis_case_events",
                    "counseling_risk_hint_evaluations",
                    "counseling_risk_hints",
                ):
                    await connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
                await transaction.commit()
            except Exception:
                await transaction.rollback()
                raise
        await connection.close()
