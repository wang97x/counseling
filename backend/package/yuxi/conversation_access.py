"""Yuxi 对业务标记 Conversation 执行当前授权复核的端口。"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import AgentRun, Conversation


class ConversationAccessPolicy(Protocol):
    """定义 Conversation 当前可见性的业务侧判断。"""

    async def can_access(self, db: AsyncSession, uid: str, conversation: Conversation) -> bool:
        """返回当前身份能否继续读取或运行该 Conversation。"""
        ...

    async def prepare_execution(self, db: AsyncSession, uid: str, conversation: Conversation) -> bool:
        """复核授权并准备当前执行所需的业务派生资源。"""
        ...

    async def cleanup_execution(self, uid: str, conversation: Conversation) -> None:
        """清理当前执行产生的业务派生资源。"""
        ...


_policy: ConversationAccessPolicy | None = None


def configure_conversation_access_policy(policy: ConversationAccessPolicy) -> None:
    """由 composition root 注册唯一业务授权策略。"""
    global _policy
    _policy = policy


async def can_access_conversation(db: AsyncSession, uid: str, conversation: Conversation) -> bool:
    """执行已注册策略；漏装配时 fail-closed。"""
    if _policy is None:
        raise RuntimeError("Yuxi conversation access policy is not configured")
    return await _policy.can_access(db, str(uid), conversation)


async def require_conversation_access(db: AsyncSession, uid: str, conversation: Conversation) -> None:
    """拒绝当前业务授权已经失效的 Conversation。"""
    if not await can_access_conversation(db, str(uid), conversation):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="对话线程不存在")


async def resolve_run_access_conversation(
    db: AsyncSession,
    run: AgentRun,
) -> Conversation | None:
    """解析 Run 执行树中实际携带业务上下文的 Conversation。"""
    conversation = await db.get(Conversation, int(run.conversation_id))
    if (
        conversation is None
        or conversation.status == "deleted"
        or str(conversation.thread_id) != str(run.conversation_thread_id)
        or str(conversation.uid) != str(run.uid)
    ):
        return None
    payload = run.input_payload if isinstance(run.input_payload, dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    context_thread_id = str(runtime.get("counseling_context_thread_id") or "").strip()
    if not context_thread_id or context_thread_id == str(run.conversation_thread_id):
        return conversation
    if run.run_type != "subagent" or not run.created_by_run_id:
        return None

    ancestor_id = str(run.created_by_run_id)
    visited: set[str] = set()
    while ancestor_id and ancestor_id not in visited:
        visited.add(ancestor_id)
        ancestor = await db.get(AgentRun, ancestor_id)
        if ancestor is None or str(ancestor.uid) != str(run.uid):
            return None
        if str(ancestor.conversation_thread_id) == context_thread_id:
            parent = await db.get(Conversation, int(ancestor.conversation_id))
            if (
                parent is None
                or parent.status == "deleted"
                or str(parent.thread_id) != context_thread_id
                or str(parent.uid) != str(run.uid)
            ):
                return None
            return parent
        ancestor_id = str(ancestor.created_by_run_id or "")
    return None


async def prepare_conversation_execution(
    db: AsyncSession, uid: str, conversation: Conversation
) -> bool:
    """在执行器边界复核授权并准备派生资源。"""
    if _policy is None:
        raise RuntimeError("Yuxi conversation access policy is not configured")
    return await _policy.prepare_execution(db, str(uid), conversation)


async def cleanup_conversation_execution(uid: str, conversation: Conversation) -> None:
    """在执行生命周期结束后清理业务派生资源。"""
    if _policy is None:
        raise RuntimeError("Yuxi conversation access policy is not configured")
    await _policy.cleanup_execution(str(uid), conversation)
