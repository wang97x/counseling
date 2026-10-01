from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRetryMiddleware, TodoListMiddleware

from yuxi.agents import BaseAgent
from yuxi.agents.backends import (
    create_agent_composite_backend,
    create_agent_filesystem_middleware,
    sync_agent_context_skills,
)
from yuxi.agents.backends.paths import runtime_workdir_path
from yuxi.agents.context import (
    DEFAULT_TOOL_RESULT_EVICTION_K_TOKENS,
    COUNSELING_RUNTIME_TOOLS,
    prepare_agent_runtime_context,
)
from yuxi.agents.middlewares import (
    ImageInputCompatibilityMiddleware,
    SteerMiddleware,
    TokenUsageMiddleware,
    create_memory_middleware,
    create_summary_middleware_from_context,
)
from yuxi.agents.middlewares.skills import SkillsMiddleware
from yuxi.agents.middlewares.subagent_task import create_subagent_task_middleware
from yuxi.agents.tool_approval import create_tool_approval_middleware, normalize_tool_approval_mode
from yuxi.agents.toolkits.service import resolve_configured_runtime_tools
from yuxi.models.chat import load_chat_model, resolve_chat_model_spec

from .context import ChatBotContext
from .prompt import TODO_MID_PROMPT, build_prompt_with_context
from .state import ChatBotState


class CounselingToolScopeMiddleware(AgentMiddleware):
    """在最终模型请求边界强制档案 Run 工具白名单。"""

    async def awrap_model_call(self, request, handler):
        context = request.runtime.context
        if not str(getattr(context, "counseling_context_thread_id", "") or "").strip():
            return await handler(request)
        allowed = set(COUNSELING_RUNTIME_TOOLS)
        scoped_tools = [tool for tool in request.tools or [] if tool.name in allowed]
        return await handler(request.override(tools=scoped_tools))


async def _build_middlewares(context, backend):
    """构建中间件列表。"""
    is_counseling = bool(
        str(getattr(context, "counseling_context_thread_id", "") or "").strip()
    )
    middlewares = [
        SteerMiddleware(),
        create_agent_filesystem_middleware(
            getattr(context, "tool_token_limit", DEFAULT_TOOL_RESULT_EVICTION_K_TOKENS) * 1024,
            backend=backend,
        ),
        SkillsMiddleware(),
    ]
    if not is_counseling:
        memory_middleware = await create_memory_middleware(context)
        if memory_middleware:
            middlewares.append(memory_middleware)
        subagent_middleware = await create_subagent_task_middleware(context)
        if subagent_middleware:
            middlewares.append(subagent_middleware)
    middlewares.append(create_summary_middleware_from_context(context, backend=backend))
    if not is_counseling:
        middlewares.append(TodoListMiddleware(system_prompt=TODO_MID_PROMPT))
    middlewares.extend(
        [
            PatchToolCallsMiddleware(),
            ModelRetryMiddleware(max_retries=getattr(context, "model_retry_times", 2)),
            ImageInputCompatibilityMiddleware(),
            TokenUsageMiddleware(),
        ]
    )
    approval_middleware = create_tool_approval_middleware(
        normalize_tool_approval_mode(getattr(context, "tool_approval_mode", "default")),
        current_project_path=runtime_workdir_path(context.workdir_relative_path),
    )
    if approval_middleware:
        middlewares.append(approval_middleware)
    middlewares.append(CounselingToolScopeMiddleware())
    return middlewares


class ChatbotAgent(BaseAgent):
    name = "智能助手"
    description = "基础的对话机器人，可以回答问题，可在配置中启用需要的工具。"
    capabilities = ["file_upload", "files", "context_compression"]
    context_schema = ChatBotContext

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def get_graph(self, context=None, **kwargs):
        context = await prepare_agent_runtime_context(
            context or self.context_schema(),
            context_schema=self.context_schema,
        )
        await sync_agent_context_skills(context)

        # DeepAgents 0.7 移除 backend factory：每次 graph 构造创建本 Run 独享的
        # CompositeBackend，filesystem 与 summary middleware 共用同一实例。
        backend = create_agent_composite_backend(context)
        model_spec = resolve_chat_model_spec(context.model)
        graph = create_agent(
            model=load_chat_model(fully_specified_name=model_spec, session_id=context.thread_id),
            tools=await resolve_configured_runtime_tools(context),
            system_prompt=build_prompt_with_context(context),
            middleware=await _build_middlewares(context, backend),
            state_schema=ChatBotState,
            checkpointer=await self._get_checkpointer(),
        )
        return graph


def main():
    pass


if __name__ == "__main__":
    main()
    # asyncio.run(main())
