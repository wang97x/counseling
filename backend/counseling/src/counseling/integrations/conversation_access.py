"""心理辅导 Conversation 的当前归属授权策略。"""

from __future__ import annotations

import asyncio
import json

from yuxi.workspace.filesystem import PrivateProjectionStore
from yuxi.storage.postgres.models_business import Conversation

from counseling.ai_work.repository import CounselingAIWorkRepository
from counseling.governance.repository import CounselingGovernanceRepository
from counseling.governance.service import CURRENT_DATA_USE_NOTICE_VERSION
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.identity.repositories.user import UserRepository
from counseling.students.repository import StudentRepository


class CounselingConversationAccessPolicy:
    """普通 Conversation 沿用 UID，档案 Conversation 额外复核业务归属。"""

    async def _resolve_access_root(self, db, uid: str, conversation):
        """沿受校验的子会话父链解析实际业务授权根会话。"""
        current = conversation
        visited: set[int] = set()
        while current is not None:
            metadata = getattr(current, "extra_metadata", None) or {}
            if not isinstance(metadata, dict):
                return None
            if "counseling" in metadata:
                return current
            is_subagent = (
                metadata.get("source") == "subagent"
                or getattr(current, "status", None) == "subagent"
            )
            if not is_subagent:
                return current
            raw_parent_id = metadata.get("parent_conversation_id")
            parent_thread_id = str(metadata.get("parent_thread_id") or "").strip()
            try:
                parent_id = int(raw_parent_id)
            except (TypeError, ValueError):
                return None
            if parent_id in visited or not parent_thread_id:
                return None
            visited.add(parent_id)
            parent = await db.get(Conversation, parent_id)
            if (
                parent is None
                or getattr(parent, "status", None) == "deleted"
                or str(getattr(parent, "uid", "")) != str(uid)
                or str(getattr(current, "uid", "")) != str(uid)
                or str(getattr(parent, "thread_id", "")) != parent_thread_id
            ):
                return None
            current = parent
        return None

    async def can_access(self, db, uid: str, conversation) -> bool:
        """仅允许当前仍负责该学生的辅导员访问档案协作会话。"""
        conversation = await self._resolve_access_root(db, uid, conversation)
        if conversation is None:
            return False
        root_metadata = getattr(conversation, "extra_metadata", None) or {}
        if "counseling" not in root_metadata:
            return True
        metadata = root_metadata.get("counseling") or {}
        raw_student_id = metadata.get("student_id")
        if raw_student_id in (None, ""):
            return False
        work_item_id = str(metadata.get("work_item_id") or "").strip()
        try:
            student_id = int(raw_student_id)
        except (TypeError, ValueError):
            return False
        user = await UserRepository(db).get_active_by_uid(str(uid))
        if (
            user is None
            or user.department_id is None
            or BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(user)
        ):
            return False
        acknowledgment = await CounselingGovernanceRepository(db).get_acknowledgment(
            int(user.id), CURRENT_DATA_USE_NOTICE_VERSION
        )
        if acknowledgment is None:
            return False
        student = await StudentRepository(db).get_for_owner(
            student_id,
            int(user.department_id),
            int(user.id),
        )
        if student is None:
            return False
        if not work_item_id:
            return True
        work_item = await CounselingAIWorkRepository(db).get_work_item(
            work_item_id,
            student_id,
            int(user.department_id),
            int(user.id),
        )
        return bool(
            work_item is not None
            and work_item.status == "ready"
            and work_item.conversation_thread_id == conversation.thread_id
        )

    async def prepare_execution(self, db, uid: str, conversation) -> bool:
        """按 PostgreSQL 快照重建当前 Run 的只读私有投影。"""
        if not await self.can_access(db, uid, conversation):
            return False
        metadata = (getattr(conversation, "extra_metadata", None) or {}).get("counseling") or {}
        work_item_id = str(metadata.get("work_item_id") or "").strip()
        if not work_item_id:
            return True
        student_id = int(metadata["student_id"])
        user = await UserRepository(db).get_active_by_uid(str(uid))
        if user is None or user.department_id is None:
            return False
        work_item = await CounselingAIWorkRepository(db).get_work_item(
            work_item_id,
            student_id,
            int(user.department_id),
            int(user.id),
        )
        if work_item is None:
            return False
        content = json.dumps(
            work_item.context_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        store = PrivateProjectionStore(str(uid), "counseling-ai-context")
        await asyncio.to_thread(
            store.replace_file,
            str(conversation.thread_id),
            "confirmed-context.json",
            content,
        )
        return True

    async def cleanup_execution(self, uid: str, conversation) -> None:
        """Run 生命周期结束后删除可由 PostgreSQL 重建的私有投影。"""
        metadata = (getattr(conversation, "extra_metadata", None) or {}).get("counseling") or {}
        if not str(metadata.get("work_item_id") or "").strip():
            return
        store = PrivateProjectionStore(str(uid), "counseling-ai-context")
        await asyncio.to_thread(store.remove_scope, str(conversation.thread_id))
