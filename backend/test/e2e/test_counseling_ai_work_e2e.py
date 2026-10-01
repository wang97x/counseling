"""心理辅导 AI 工作项的真实 assembled-path E2E。"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import httpx
import pytest
from counseling.identity.auth import AuthUtils
from e2e_helpers import cancel_run, postgres_dsn, wait_for_run
from yuxi.repositories.agent_repository import DEFAULT_AGENT_SLUG
from yuxi.storage.minio.client import get_minio_client

from test.live_api_cleanup import cleanup_test_chat_resources, make_test_conversation_title

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow]

PROVIDER_ID = "ci-counseling-replay"
MODEL_SPEC = f"{PROVIDER_ID}:deterministic-chat"
EXPECTED_OUTPUT = "DETERMINISTIC_AGENT_E2E_OK"


def _headers(user_id: int) -> dict[str, str]:
    """为已落库的合成用户生成短期测试令牌。"""
    token = AuthUtils.create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def _json_mapping(value) -> dict:
    """把 asyncpg JSON 字段规范为字典。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _execution_evidence(conn, thread_id: str) -> list[dict]:
    """回读会话级消息和工具调用，供失败断言展示真实持久化事实。"""
    rows = await conn.fetch(
        """
        SELECT m.run_id, m.message_type, m.operation_id, m.execution_status,
               m.content, m.extra_metadata,
               tc.tool_name, tc.tool_input, tc.tool_output, tc.status, tc.error_message
        FROM conversations AS c
        JOIN messages AS m ON m.conversation_id = c.id
        LEFT JOIN tool_calls AS tc ON tc.message_id = m.id
        WHERE c.thread_id = $1
        ORDER BY m.sequence NULLS LAST, m.id
        """,
        thread_id,
    )
    return [dict(item) for item in rows]


async def _create_provider(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/system/model-providers",
        json={
            "provider_id": PROVIDER_ID,
            "display_name": "Counseling deterministic replay",
            "provider_type": "openai",
            "base_url": "http://api:8765/v1",
            "api_key": "ci-replay-key",
            "capabilities": ["chat"],
            "enabled_models": [
                {
                    "id": "deterministic-chat",
                    "display_name": "Deterministic chat",
                    "type": "chat",
                    "source": "manual",
                }
            ],
            "is_enabled": True,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def _delete_provider(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    response = await client.delete(f"/api/system/model-providers/{PROVIDER_ID}", headers=headers)
    assert response.status_code in {200, 404}, response.text


async def test_ai_work_artifact_import_and_confirmation_assembled_path() -> None:
    """真实 worker Run 展示文件后，经 MinIO 回填并由辅导员确认。"""
    suffix = uuid.uuid4().hex[:10]
    conn = await asyncpg.connect(postgres_dsn())
    base_url = os.getenv("TEST_BASE_URL", os.getenv("API_BASE_URL", "http://localhost:5050")).rstrip("/")
    timeout = httpx.Timeout(300.0, connect=10.0)
    department_id = None
    owner_id = other_id = admin_id = None
    owner_uid = None
    student_ids: list[int] = []
    thread_id = None
    workdir_path = None
    run_id = None
    original_agent_config = None
    bucket = object_name = None
    provider_created = False

    try:
        department_id = await conn.fetchval(
            "INSERT INTO departments (name, description) VALUES ($1, 'e2e') RETURNING id",
            f"counseling_ai_e2e_{suffix}",
        )

        async def add_user(role: str, business_roles: str) -> int:
            uid = f"counseling_ai_{suffix}_{role}_{uuid.uuid4().hex[:4]}"
            user_id = await conn.fetchval(
                """
                INSERT INTO users (
                    username, uid, password_hash, role, business_roles, department_id,
                    login_failed_count, is_deleted, created_at
                )
                VALUES ($1, $1, 'e2e', $2, $3::jsonb, $4, 0, 0, NOW())
                RETURNING id
                """,
                uid,
                role,
                business_roles,
                department_id,
            )
            if business_roles != "[]":
                await conn.execute(
                    """
                    INSERT INTO counseling_data_use_acknowledgments (user_id, notice_version)
                    VALUES ($1, '2026-10-01')
                    """,
                    user_id,
                )
            return int(user_id)

        owner_id = await add_user("user", '["counselor"]')
        owner_uid = await conn.fetchval("SELECT uid FROM users WHERE id = $1", owner_id)
        other_id = await add_user("user", '["counselor"]')
        admin_id = await add_user("superadmin", '["super_admin"]')
        owner_headers = _headers(owner_id)
        other_headers = _headers(other_id)
        admin_headers = _headers(admin_id)

        async with httpx.AsyncClient(base_url=base_url, timeout=timeout, follow_redirects=True) as client:
            default_agent = await client.get("/api/agent/default", headers=owner_headers)
            assert default_agent.status_code == 200, default_agent.text
            original_agent_config = default_agent.json()["agent"]["config_json"]
            deterministic_config = {
                "context": {
                    "model": MODEL_SPEC,
                    "system_prompt": f"Only output {EXPECTED_OUTPUT}.",
                    "tools": ["present_artifacts"],
                    "knowledges": [],
                    "mcps": [],
                    "skills": ["image-gen"],
                    "preload_skills": ["image-gen"],
                    "subagents": [],
                }
            }
            await _create_provider(client, admin_headers)
            provider_created = True
            updated_agent = await client.put(
                f"/api/agent/{DEFAULT_AGENT_SLUG}",
                headers=admin_headers,
                json={"config_json": deterministic_config},
            )
            assert updated_agent.status_code == 200, updated_agent.text

            async def create_student(code: str) -> int:
                response = await client.post(
                    "/api/counseling/students",
                    headers=owner_headers,
                    json={
                        "student_code": code,
                        "display_name": "E2E student",
                        "class_name": "E2E class",
                    },
                )
                assert response.status_code == 201, response.text
                student_id = int(response.json()["id"])
                student_ids.append(student_id)
                return student_id

            student_id = await create_student(f"AI-{suffix}-A")
            other_student_id = await create_student(f"AI-{suffix}-B")
            work_response = await client.post(
                f"/api/counseling/students/{student_id}/ai-work-items",
                headers=owner_headers,
                json={
                    "request_id": f"work_{suffix}",
                    "instruction": "Create a synthetic follow-up note for human review.",
                },
            )
            assert work_response.status_code == 201, work_response.text
            work = work_response.json()
            thread_id = str(work["thread_id"])
            await conn.execute(
                """
                UPDATE conversations
                SET title = $1,
                    extra_metadata = (COALESCE(extra_metadata, '{}'::json)::jsonb || $2::jsonb)::json
                WHERE thread_id = $3
                """,
                make_test_conversation_title("counseling-ai"),
                json.dumps({"_yuxi_test": True}),
                thread_id,
            )

            await conn.execute(
                "ALTER TABLE counseling_data_use_acknowledgments "
                "DISABLE TRIGGER trg_counseling_notice_immutable"
            )
            await conn.execute(
                "DELETE FROM counseling_data_use_acknowledgments WHERE user_id = $1",
                owner_id,
            )
            await conn.execute(
                "ALTER TABLE counseling_data_use_acknowledgments "
                "ENABLE TRIGGER trg_counseling_notice_immutable"
            )
            hidden_threads = await client.get("/api/chat/threads", headers=owner_headers)
            assert hidden_threads.status_code == 200, hidden_threads.text
            assert all(str(item["id"]) != thread_id for item in hidden_threads.json())
            await conn.execute(
                """
                INSERT INTO counseling_data_use_acknowledgments (user_id, notice_version)
                VALUES ($1, '2026-10-01')
                """,
                owner_id,
            )

            threads = await client.get("/api/chat/threads", headers=owner_headers)
            assert threads.status_code == 200, threads.text
            thread = next(item for item in threads.json() if str(item["id"]) == thread_id)
            workdir_path = str(thread["workdir_path"])
            file_name = f"followup-{suffix}.md"
            artifact_bytes = f"# Synthetic counseling artifact {suffix}\n\nRequires human review.\n".encode()
            upload_response = await client.post(
                "/api/chat/attachments/tmp",
                files={"file": (file_name, artifact_bytes, "text/markdown")},
                headers=owner_headers,
            )
            assert upload_response.status_code == 200, upload_response.text
            uploaded = upload_response.json()
            confirm_attachment = await client.post(
                f"/api/chat/thread/{thread_id}/attachments/confirm",
                json={
                    "attachments": [
                        {
                            "file_type": uploaded.get("file_type"),
                            "object_name": uploaded["object_name"],
                        }
                    ]
                },
                headers=owner_headers,
            )
            assert confirm_attachment.status_code == 200, confirm_attachment.text
            artifact_path = str(confirm_attachment.json()["attachments"][0]["original_path"])
            assert artifact_path.startswith(f"/home/gem/user-data/{workdir_path}/uploads/")

            request_id = f"counseling-ai-run-{uuid.uuid4()}"
            run_response = await client.post(
                "/api/agent/runs",
                headers=owner_headers,
                json={
                    "query": (
                        f"Only output {EXPECTED_OUTPUT}. "
                        "DETERMINISTIC_STRICT_RESOURCE_SCOPE "
                        f"DETERMINISTIC_TOOL_CALL_ID:counseling-present-{suffix} "
                        f"DETERMINISTIC_ARTIFACT_PATH:{artifact_path}"
                    ),
                    "agent_slug": DEFAULT_AGENT_SLUG,
                    "thread_id": thread_id,
                    "meta": {"request_id": request_id},
                },
            )
            assert run_response.status_code == 200, run_response.text
            run_id = str(run_response.json()["run_id"])
            run = await wait_for_run(client, owner_headers, run_id)
            assert run["status"] == "completed", await _execution_evidence(conn, thread_id)
            tool_calls = await conn.fetch(
                """
                SELECT tc.tool_name, tc.tool_input, tc.tool_output, tc.status, tc.error_message
                FROM tool_calls AS tc
                JOIN messages AS m ON m.id = tc.message_id
                WHERE m.run_id = $1
                """,
                run_id,
            )
            presented = next(
                (item for item in tool_calls if item["tool_name"] == "present_artifacts"), None
            )
            assert presented is not None, [dict(item) for item in tool_calls]
            assert presented["status"] == "success", dict(presented)
            tool_input = _json_mapping(presented["tool_input"])
            assert artifact_path in list(tool_input.get("filepaths") or []), {
                "artifact_path": artifact_path, "tool_input": tool_input
            }

            preflight_url = (
                f"/api/counseling/students/{student_id}/ai-work-items/"
                f"{work['work_item_id']}/materials/preflight"
            )
            source = {"run_id": run_id, "path": artifact_path}
            preflight = await client.post(preflight_url, headers=owner_headers, json=source)
            assert preflight.status_code == 200, preflight.text
            assert preflight.json() == {
                "file_name": artifact_path.rsplit("/", 1)[-1],
                "content_type": "text/markdown",
                "size": len(artifact_bytes),
            }

            switched = await client.post(
                preflight_url.replace(f"/students/{student_id}/", f"/students/{other_student_id}/"),
                headers=owner_headers,
                json=source,
            )
            assert switched.status_code == 404, switched.text

            await conn.execute(
                "UPDATE counseling_students SET counselor_id = $1 WHERE id = $2",
                other_id,
                student_id,
            )
            revoked = await client.post(preflight_url, headers=owner_headers, json=source)
            assert revoked.status_code == 404, revoked.text
            await conn.execute(
                "UPDATE counseling_students SET counselor_id = $1 WHERE id = $2",
                owner_id,
                student_id,
            )

            import_url = preflight_url.removesuffix("/preflight") + "/import"
            import_payload = {
                **source,
                "request_id": f"import_{suffix}",
            }
            imports = await asyncio.gather(
                client.post(import_url, headers=owner_headers, json=import_payload),
                client.post(import_url, headers=owner_headers, json=import_payload),
            )
            assert [item.status_code for item in imports] == [201, 201], [item.text for item in imports]
            assert len({item.json()["id"] for item in imports}) == 1
            material = imports[0].json()
            assert material["status"] == "pending_review"

            denied = await client.get(
                f"/api/counseling/students/{student_id}/materials/{material['id']}/content",
                headers=other_headers,
            )
            assert denied.status_code == 404, denied.text
            content = await client.get(
                f"/api/counseling/students/{student_id}/materials/{material['id']}/content",
                headers=owner_headers,
            )
            assert content.status_code == 200 and content.content == artifact_bytes
            materials_response = await client.get(
                f"/api/counseling/students/{student_id}/materials",
                headers=owner_headers,
            )
            assert materials_response.status_code == 200, materials_response.text
            assert any(item["id"] == material["id"] for item in materials_response.json())
            read_audits = await conn.fetch(
                """
                SELECT action, event_metadata
                FROM counseling_audit_events
                WHERE student_id = $1
                  AND actor_id = $2
                  AND action IN ('material.list', 'material.content.read')
                ORDER BY id
                """,
                student_id,
                owner_id,
            )
            assert [row["action"] for row in read_audits[-2:]] == [
                "material.content.read",
                "material.list",
            ]
            assert _json_mapping(read_audits[-2]["event_metadata"]) == {
                "material_id": material["id"]
            }
            assert _json_mapping(read_audits[-1]["event_metadata"]) == {"count": 1}

            persisted = await conn.fetchrow(
                """
                SELECT status, bucket, object_name, sha256
                FROM counseling_materials
                WHERE id = $1
                """,
                material["id"],
            )
            assert persisted and persisted["status"] == "pending_review"
            bucket, object_name = persisted["bucket"], persisted["object_name"]

            await conn.execute(
                "UPDATE counseling_students SET counselor_id = $1 WHERE id = $2",
                other_id,
                student_id,
            )
            revoked_content = await client.get(
                f"/api/counseling/students/{student_id}/materials/{material['id']}/content",
                headers=owner_headers,
            )
            revoked_import = await client.post(
                import_url,
                headers=owner_headers,
                json=import_payload,
            )
            revoked_confirm = await client.post(
                f"/api/counseling/students/{student_id}/materials/{material['id']}/confirm",
                headers=owner_headers,
                json={"confirmation_key": f"revoked_confirm_{suffix}"},
            )
            revoked_reject = await client.post(
                f"/api/counseling/students/{student_id}/materials/{material['id']}/reject",
                headers=owner_headers,
                json={"request_id": f"revoked_reject_{suffix}"},
            )
            assert [
                revoked_content.status_code,
                revoked_import.status_code,
                revoked_confirm.status_code,
                revoked_reject.status_code,
            ] == [404, 404, 404, 404]
            assert await conn.fetchval(
                "SELECT status FROM counseling_materials WHERE id = $1",
                material["id"],
            ) == "pending_review"
            await conn.execute(
                "UPDATE counseling_students SET counselor_id = $1 WHERE id = $2",
                owner_id,
                student_id,
            )

            await get_minio_client().adelete_file(bucket, object_name)
            missing_object_confirm = await client.post(
                f"/api/counseling/students/{student_id}/materials/{material['id']}/confirm",
                headers=owner_headers,
                json={"confirmation_key": f"missing_{suffix}"},
            )
            assert missing_object_confirm.status_code == 409, missing_object_confirm.text
            assert await conn.fetchval(
                "SELECT status FROM counseling_materials WHERE id = $1",
                material["id"],
            ) == "pending_review"
            await get_minio_client().aupload_file(
                bucket,
                object_name,
                artifact_bytes,
                "text/markdown",
            )

            confirmation_key = f"confirm_{suffix}"
            confirm_url = f"/api/counseling/students/{student_id}/materials/{material['id']}/confirm"
            first_confirm = await client.post(
                confirm_url,
                headers=owner_headers,
                json={"confirmation_key": confirmation_key},
            )
            second_confirm = await client.post(
                confirm_url,
                headers=owner_headers,
                json={"confirmation_key": confirmation_key},
            )
            assert first_confirm.status_code == 200, first_confirm.text
            assert second_confirm.status_code == 200, second_confirm.text
            assert first_confirm.json()["status"] == second_confirm.json()["status"] == "active"

            await conn.execute(
                "UPDATE counseling_students SET counselor_id = $1 WHERE id = $2",
                other_id,
                student_id,
            )
            revoked_idempotent_confirm = await client.post(
                confirm_url,
                headers=owner_headers,
                json={"confirmation_key": confirmation_key},
            )
            assert revoked_idempotent_confirm.status_code == 404, revoked_idempotent_confirm.text
            await conn.execute(
                "UPDATE counseling_students SET counselor_id = $1 WHERE id = $2",
                owner_id,
                student_id,
            )

            persisted = await conn.fetchrow(
                """
                SELECT status, bucket, object_name, sha256
                FROM counseling_materials
                WHERE id = $1
                """,
                material["id"],
            )
            assert persisted and persisted["status"] == "active"
            stored = await get_minio_client().adownload_file(bucket, object_name)
            assert stored == artifact_bytes
    finally:
        if bucket and object_name:
            await get_minio_client().adelete_file(bucket, object_name)
        if run_id and owner_id:
            async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as cleanup_client:
                await cancel_run(cleanup_client, _headers(owner_id), run_id)
                await wait_for_run(cleanup_client, _headers(owner_id), run_id)
        if admin_id:
            async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as cleanup_client:
                if original_agent_config is not None:
                    restored_agent = await cleanup_client.put(
                        f"/api/agent/{DEFAULT_AGENT_SLUG}",
                        headers=_headers(admin_id),
                        json={"config_json": original_agent_config},
                    )
                    assert restored_agent.status_code == 200, restored_agent.text
                if provider_created:
                    await _delete_provider(cleanup_client, _headers(admin_id))
        if student_ids:
            await conn.execute(
                "ALTER TABLE counseling_data_use_acknowledgments DISABLE TRIGGER trg_counseling_notice_immutable"
            )
            await conn.execute("DELETE FROM counseling_audit_events WHERE student_id = ANY($1::bigint[])", student_ids)
            await conn.execute("DELETE FROM counseling_materials WHERE student_id = ANY($1::bigint[])", student_ids)
            await conn.execute("DELETE FROM counseling_ai_work_items WHERE student_id = ANY($1::bigint[])", student_ids)
            await conn.execute("DELETE FROM counseling_students WHERE id = ANY($1::bigint[])", student_ids)
            await conn.execute(
                "ALTER TABLE counseling_data_use_acknowledgments ENABLE TRIGGER trg_counseling_notice_immutable"
            )
        if owner_id and owner_uid:
            await conn.execute(
                """
                UPDATE conversations
                SET title = $1,
                    extra_metadata = (COALESCE(extra_metadata, '{}'::json)::jsonb || $2::jsonb)::json
                WHERE uid = $3
                  AND COALESCE(extra_metadata, '{}'::json)::jsonb -> 'counseling' ->> 'work_item_id'
                      IS NOT NULL
                """,
                make_test_conversation_title("counseling-ai"),
                json.dumps({"_yuxi_test": True}),
                owner_uid,
            )
            async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as cleanup_client:
                await cleanup_test_chat_resources(
                    cleanup_client,
                    _headers(owner_id),
                    owner_uid=str(owner_uid),
                )
        user_ids = [item for item in (owner_id, other_id, admin_id) if item]
        if user_ids:
            await conn.execute(
                "ALTER TABLE counseling_data_use_acknowledgments DISABLE TRIGGER trg_counseling_notice_immutable"
            )
            await conn.execute(
                "DELETE FROM counseling_data_use_acknowledgments WHERE user_id = ANY($1::bigint[])",
                user_ids,
            )
            await conn.execute(
                "ALTER TABLE counseling_data_use_acknowledgments ENABLE TRIGGER trg_counseling_notice_immutable"
            )
            await conn.execute("DELETE FROM users WHERE id = ANY($1::bigint[])", user_ids)
        if department_id:
            await conn.execute("DELETE FROM departments WHERE id = $1", department_id)
        await conn.close()
