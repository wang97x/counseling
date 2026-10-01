"""档案 Conversation 在通用 Yuxi 边界必须复核当前业务授权。"""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import HTTPException
from yuxi.services import (
    agent_request_queue_service as queue_service,
)
from yuxi.services import (
    agent_run_service as run_service,
)
from yuxi.services import (
    attachment_service,
    chat_service,
    context_compression_service,
    conversation_service,
)


def _denied() -> HTTPException:
    return HTTPException(status_code=404, detail="对话线程不存在")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_thread_lookup_rechecks_current_business_access(monkeypatch):
    conversation = SimpleNamespace(uid="user-1", status="active", agent_id="assistant")

    class Repository:
        def __init__(self, _db):
            pass

        async def get_conversation_by_thread_id(self, _thread_id):
            return conversation

    access = AsyncMock(side_effect=_denied())
    monkeypatch.setattr(queue_service, "ConversationRepository", Repository)
    monkeypatch.setattr(queue_service, "require_conversation_access", access)

    with pytest.raises(HTTPException) as exc_info:
        await queue_service._get_thread_conversation(
            db=object(), uid="user-1", agent_slug="assistant", thread_id="thread-1"
        )

    assert exc_info.value.status_code == 404
    access.assert_awaited_once_with(ANY, "user-1", conversation)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_lookup_rechecks_current_business_access(monkeypatch):
    request = SimpleNamespace(
        uid="user-1",
        agent_slug="assistant",
        conversation_thread_id="thread-1",
    )

    class Repository:
        def __init__(self, _db):
            pass

        async def get_by_request_id(self, _request_id):
            return request

    lookup = AsyncMock(side_effect=_denied())
    monkeypatch.setattr(queue_service, "AgentRunRequestRepository", Repository)
    monkeypatch.setattr(queue_service, "_get_thread_conversation", lookup)

    with pytest.raises(HTTPException) as exc_info:
        await queue_service.get_request(db=object(), request_id="request-1", uid="user-1")

    assert exc_info.value.status_code == 404
    lookup.assert_awaited_once_with(
        db=ANY,
        uid="user-1",
        agent_slug="assistant",
        thread_id="thread-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_read_rechecks_current_business_access(monkeypatch):
    conversation = SimpleNamespace(uid="user-1", status="active")
    run = SimpleNamespace(
        uid="user-1",
        conversation_thread_id="child-thread",
        input_payload={"runtime": {"counseling_context_thread_id": "parent-thread"}},
    )
    resolve = AsyncMock(return_value=conversation)
    access = AsyncMock(side_effect=_denied())
    monkeypatch.setattr(run_service, "resolve_run_access_conversation", resolve)
    monkeypatch.setattr(run_service, "require_conversation_access", access)

    with pytest.raises(HTTPException) as exc_info:
        await run_service._require_run_conversation_access(object(), run, "user-1")

    assert exc_info.value.status_code == 404
    resolve.assert_awaited_once_with(ANY, run)
    access.assert_awaited_once_with(ANY, "user-1", conversation)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_read_rechecks_current_business_access(monkeypatch):
    conversation = SimpleNamespace(uid="user-1", status="active")

    class ConversationRepository:
        def __init__(self, _db):
            pass

        async def get_conversation_by_thread_id(self, _thread_id):
            return conversation

    class EmptyRepository:
        def __init__(self, _db):
            pass

    monkeypatch.setattr(chat_service, "ConversationRepository", ConversationRepository)
    monkeypatch.setattr(chat_service, "AgentRepository", EmptyRepository)
    monkeypatch.setattr(chat_service, "AgentRunRepository", EmptyRepository)
    monkeypatch.setattr(chat_service, "require_conversation_access", AsyncMock(side_effect=_denied()))

    with pytest.raises(HTTPException) as exc_info:
        await chat_service.get_agent_state_view(
            thread_id="thread-1", current_user=SimpleNamespace(uid="user-1"), db=object()
        )

    assert exc_info.value.status_code == 404


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attachment_list_rechecks_current_business_access(monkeypatch):
    conversation = SimpleNamespace(uid="user-1", status="active")
    repository = SimpleNamespace(
        db=object(), get_conversation_by_thread_id=AsyncMock(return_value=conversation)
    )
    monkeypatch.setattr(
        attachment_service, "require_conversation_access", AsyncMock(side_effect=_denied())
    )

    with pytest.raises(HTTPException) as exc_info:
        await attachment_service._require_user_conversation(repository, "thread-1", "user-1")

    assert exc_info.value.status_code == 404


@pytest.mark.unit
@pytest.mark.asyncio
async def test_context_compression_rechecks_current_business_access(monkeypatch):
    conversation = SimpleNamespace(uid="user-1", status="active", agent_id="assistant")

    class Repository:
        def __init__(self, _db):
            pass

        async def lock_conversation_by_thread_id(self, _thread_id):
            return conversation

    monkeypatch.setattr(context_compression_service, "ConversationRepository", Repository)
    monkeypatch.setattr(
        context_compression_service,
        "require_conversation_access",
        AsyncMock(side_effect=_denied()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await context_compression_service.compress_thread_context(
            thread_id="thread-1",
            current_user=SimpleNamespace(uid="user-1"),
            db=object(),
        )

    assert exc_info.value.status_code == 404


def _listed_conversation(thread_id: str, *, allowed: bool):
    return SimpleNamespace(
        id=thread_id,
        thread_id=thread_id,
        uid="user-1",
        agent_id="assistant",
        title=thread_id,
        is_pinned=False,
        created_at=None,
        updated_at=None,
        extra_metadata={"allowed": allowed},
        last_viewed_run_id=None,
        project=SimpleNamespace(workdir_path=f"projects/{thread_id}"),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_threads_applies_offset_after_access_filter(monkeypatch):
    denied = _listed_conversation("denied", allowed=False)
    first = _listed_conversation("first", allowed=True)
    second = _listed_conversation("second", allowed=True)

    class ConversationRepository:
        def __init__(self, _db):
            pass

        async def list_conversations(self, **kwargs):
            assert kwargs["limit"] is None
            assert kwargs["offset"] == 0
            return [denied, first, second]

    class RunRepository:
        def __init__(self, _db):
            pass

        async def get_latest_top_level_runs_for_threads(self, _uid, _thread_ids):
            return {}

    async def can_access(_db, _uid, conversation):
        return conversation.extra_metadata["allowed"]

    async def serialize(conversation, **_kwargs):
        return {"id": conversation.thread_id}

    monkeypatch.setattr(conversation_service, "ConversationRepository", ConversationRepository)
    monkeypatch.setattr(conversation_service, "AgentRunRepository", RunRepository)
    monkeypatch.setattr(conversation_service, "can_access_conversation", can_access)
    monkeypatch.setattr(conversation_service, "_serialize_thread", serialize)

    result = await conversation_service.list_threads_view(
        agent_slug=None, db=object(), current_uid="user-1", limit=1, offset=1
    )

    assert result == [{"id": "second"}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_threads_fills_page_after_access_filter(monkeypatch):
    denied = _listed_conversation("denied", allowed=False)
    first = _listed_conversation("first", allowed=True)
    second = _listed_conversation("second", allowed=True)

    class ConversationRepository:
        def __init__(self, _db):
            pass

        async def search_conversations_by_message_content(self, **kwargs):
            if kwargs["offset"] == 0:
                return [
                    {"conversation": denied, "snippets": []},
                    {"conversation": first, "snippets": []},
                ], True
            assert kwargs["offset"] == 2
            return [{"conversation": second, "snippets": []}], False

    async def can_access(_db, _uid, conversation):
        return conversation.extra_metadata["allowed"]

    monkeypatch.setattr(conversation_service, "ConversationRepository", ConversationRepository)
    monkeypatch.setattr(conversation_service, "can_access_conversation", can_access)

    result = await conversation_service.search_threads_view(
        query="report", agent_id=None, db=object(), current_uid="user-1", limit=1, offset=0
    )

    assert [item["thread_id"] for item in result["items"]] == ["first"]
    assert result["has_more"] is True
