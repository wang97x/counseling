from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from yuxi.agents.buildin.chatbot.graph import CounselingToolScopeMiddleware
from yuxi.services import chat_service as svc


def test_apply_model_override_sets_model_from_meta():
    input_context = {"model": "agent-default"}
    svc._apply_model_override(input_context, {"model_spec": "user-pick"})
    assert input_context["model"] == "user-pick"


def test_apply_model_override_noop_without_model_spec():
    input_context = {"model": "agent-default"}
    svc._apply_model_override(input_context, {"request_id": "r1"})
    svc._apply_model_override(input_context, None)
    assert input_context["model"] == "agent-default"


def test_apply_counseling_resource_scope_noop_for_ordinary_run():
    input_context = {"tools": ["search"], "skills": ["image-gen"]}
    svc._apply_counseling_resource_scope(input_context, {"request_id": "r1"})
    assert input_context == {"tools": ["search"], "skills": ["image-gen"]}


def test_apply_counseling_resource_scope_closes_implicit_resources():
    input_context = {
        "tools": ["search"],
        "knowledges": ["k"],
        "mcps": ["m"],
        "skills": ["s"],
        "preload_skills": ["s"],
        "subagents": ["a"],
    }
    svc._apply_counseling_resource_scope(
        input_context,
        {"counseling_context_thread_id": "thread-1"},
        {"system_prompt": "controlled"},
    )
    assert input_context["tools"] == ["read_file", "write_file", "edit_file", "present_artifacts"]
    assert input_context["knowledges"] == []
    assert input_context["mcps"] == []
    assert input_context["skills"] == []
    assert input_context["preload_skills"] == []
    assert input_context["system_prompt"] == "controlled"
    assert input_context["subagents"] == []

@pytest.mark.asyncio
async def test_counseling_tool_scope_filters_final_model_request():
    middleware = CounselingToolScopeMiddleware()
    context = SimpleNamespace(counseling_context_thread_id="thread-1")
    tools = [
        SimpleNamespace(name=name)
        for name in (
            "read_file",
            "write_file",
            "edit_file",
            "present_artifacts",
            "execute",
            "task",
            "write_todos",
        )
    ]

    class Request:
        runtime = SimpleNamespace(context=context)

        def __init__(self, selected):
            self.tools = selected

        def override(self, *, tools):
            return Request(tools)

    handler = AsyncMock(return_value="ok")
    result = await middleware.awrap_model_call(Request(tools), handler)

    assert result == "ok"
    request = handler.await_args.args[0]
    assert [tool.name for tool in request.tools] == [
        "read_file",
        "write_file",
        "edit_file",
        "present_artifacts",
    ]
