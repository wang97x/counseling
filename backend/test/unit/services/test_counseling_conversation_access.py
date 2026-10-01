"""档案 Conversation 必须随当前业务归属撤销访问。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from counseling.integrations.conversation_access import CounselingConversationAccessPolicy
from yuxi.conversation_access import resolve_run_access_conversation


def _conversation():
    return SimpleNamespace(
        thread_id="thread-1",
        extra_metadata={"counseling": {"student_id": 7, "work_item_id": "work-1"}},
    )


@pytest.mark.asyncio
async def test_counseling_conversation_requires_current_role_student_and_work_item(monkeypatch):
    """角色、学生归属和 WorkItem/thread 任一失配都立即撤销通用会话访问。"""
    user = SimpleNamespace(id=11, department_id=3, business_roles=["counselor"])
    get_user = AsyncMock(return_value=user)
    get_student = AsyncMock(return_value=SimpleNamespace(id=7))
    get_acknowledgment = AsyncMock(return_value=SimpleNamespace())
    get_work_item = AsyncMock(
        return_value=SimpleNamespace(status="ready", conversation_thread_id="thread-1")
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.UserRepository.get_active_by_uid", get_user
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.CounselingGovernanceRepository.get_acknowledgment",
        get_acknowledgment,
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.StudentRepository.get_for_owner", get_student
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.CounselingAIWorkRepository.get_work_item",
        get_work_item,
    )
    policy = CounselingConversationAccessPolicy()

    assert await policy.can_access(object(), "uid-1", _conversation()) is True

    legacy_conversation = SimpleNamespace(
        thread_id="legacy-thread",
        extra_metadata={"counseling": {"student_id": 7}},
    )
    get_work_item.reset_mock()
    assert await policy.can_access(object(), "uid-1", legacy_conversation) is True
    get_work_item.assert_not_awaited()

    user.business_roles = ["business_admin"]
    assert await policy.can_access(object(), "uid-1", _conversation()) is False
    user.business_roles = ["counselor"]
    get_student.return_value = None
    assert await policy.can_access(object(), "uid-1", _conversation()) is False
    get_acknowledgment.return_value = None
    assert await policy.can_access(object(), "uid-1", _conversation()) is False
    get_acknowledgment.return_value = SimpleNamespace()
    get_student.return_value = SimpleNamespace(id=7)
    get_work_item.return_value = SimpleNamespace(status="ready", conversation_thread_id="other-thread")
    assert await policy.can_access(object(), "uid-1", _conversation()) is False


@pytest.mark.asyncio
async def test_ordinary_conversation_does_not_require_counseling_assignment():
    """没有 counseling 标记的普通会话保持原 UID 授权语义。"""
    conversation = SimpleNamespace(thread_id="thread-1", extra_metadata={})

    assert await CounselingConversationAccessPolicy().can_access(object(), "uid-1", conversation) is True


@pytest.mark.asyncio
async def test_subagent_conversation_inherits_parent_counseling_access(monkeypatch):
    """子会话必须沿父链复核当前档案归属，撤权或伪造父链时 fail-closed。"""
    parent = _conversation()
    parent.id = 1
    parent.uid = "uid-1"
    parent.status = "active"
    child = SimpleNamespace(
        id=2,
        uid="uid-1",
        thread_id="child-thread",
        status="subagent",
        extra_metadata={
            "source": "subagent",
            "parent_conversation_id": 1,
            "parent_thread_id": "thread-1",
        },
    )

    class FakeDB:
        async def get(self, _model, key):
            return parent if key == 1 else None

    get_student = AsyncMock(return_value=SimpleNamespace(id=7))
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.UserRepository.get_active_by_uid",
        AsyncMock(return_value=SimpleNamespace(id=11, department_id=3, business_roles=["counselor"])),
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.CounselingGovernanceRepository.get_acknowledgment",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.StudentRepository.get_for_owner",
        get_student,
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.CounselingAIWorkRepository.get_work_item",
        AsyncMock(return_value=SimpleNamespace(status="ready", conversation_thread_id="thread-1")),
    )

    policy = CounselingConversationAccessPolicy()
    assert await policy.can_access(FakeDB(), "uid-1", child) is True

    get_student.return_value = None
    assert await policy.can_access(FakeDB(), "uid-1", child) is False

    child.extra_metadata = {"source": "subagent", "parent_conversation_id": 1}
    assert await policy.can_access(FakeDB(), "uid-1", child) is False


@pytest.mark.asyncio
async def test_prepare_execution_rebuilds_projection_from_current_database_snapshot(monkeypatch):
    """每次执行都从当前 PostgreSQL 快照重建投影，而不复用残留文件。"""
    policy = CounselingConversationAccessPolicy()
    policy.can_access = AsyncMock(return_value=True)
    user = SimpleNamespace(id=11, department_id=3)
    work_item = SimpleNamespace(context_snapshot={"student": {"id": 7}, "version": 2})
    projection = SimpleNamespace(replace_file=Mock(), remove_scope=Mock())
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.UserRepository.get_active_by_uid",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.CounselingAIWorkRepository.get_work_item",
        AsyncMock(return_value=work_item),
    )
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.PrivateProjectionStore",
        lambda *_args: projection,
    )

    assert await policy.prepare_execution(object(), "uid-1", _conversation()) is True

    projection.replace_file.assert_called_once()
    scope_id, filename, content = projection.replace_file.call_args.args
    assert (scope_id, filename) == ("thread-1", "confirmed-context.json")
    assert b'"version": 2' in content


@pytest.mark.asyncio
async def test_cleanup_execution_removes_only_current_conversation_projection(monkeypatch):
    """Run 结束时清理当前 Conversation 的可重建投影。"""
    projection = SimpleNamespace(remove_scope=Mock())
    monkeypatch.setattr(
        "counseling.integrations.conversation_access.PrivateProjectionStore",
        lambda *_args: projection,
    )

    await CounselingConversationAccessPolicy().cleanup_execution("uid-1", _conversation())

    projection.remove_scope.assert_called_once_with("thread-1")

@pytest.mark.asyncio
async def test_subagent_run_resolves_parent_counseling_conversation():
    """子 Run 通过 created_by 执行树复用父档案会话，而非误查子会话。"""
    parent_conversation = SimpleNamespace(
        id=1,
        thread_id="parent-thread",
        uid="uid-1",
        status="active",
    )
    child_conversation = SimpleNamespace(
        id=2,
        thread_id="child-thread",
        uid="uid-1",
        status="active",
    )
    parent_run = SimpleNamespace(
        id="run-parent",
        conversation_id=1,
        conversation_thread_id="parent-thread",
        uid="uid-1",
        created_by_run_id=None,
    )
    child_run = SimpleNamespace(
        id="run-child",
        conversation_id=2,
        conversation_thread_id="child-thread",
        uid="uid-1",
        run_type="subagent",
        created_by_run_id="run-parent",
        input_payload={"runtime": {"counseling_context_thread_id": "parent-thread"}},
    )

    class FakeDB:
        async def get(self, model, key):
            if model.__name__ == "Conversation":
                return {1: parent_conversation, 2: child_conversation}.get(key)
            return {"run-parent": parent_run}.get(key)

    assert await resolve_run_access_conversation(FakeDB(), child_run) is parent_conversation
