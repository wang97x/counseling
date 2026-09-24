"""最小学生档案用例与对外字段。"""

from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.students.repository import StudentRepository
from counseling.storage.models import CounselingAuditEvent
from yuxi.permissions.business_roles import BusinessCapability, resolve_business_capabilities
from yuxi.storage.postgres.models_business import User
from yuxi.utils.datetime_utils import format_utc_datetime


class ConversationPort(Protocol):
    """定义档案关联会话所需的通用平台能力。"""

    async def create(
        self,
        *,
        db: AsyncSession,
        actor: User,
        agent_slug: str,
        request_id: str | None,
        title: str | None,
        server_metadata: dict,
    ) -> dict:
        """创建带服务端可信上下文的会话。"""
        ...


class StudentConflictError(Exception):
    """表示学生档案乐观版本冲突。"""


def _metadata(record) -> dict:
    return {
        "id": record.id,
        "student_code": record.student_code,
        "display_name": record.display_name,
        "class_name": record.class_name,
        "counselor_id": record.counselor_id,
        "status": record.status,
        "current_risk_level": record.current_risk_level,
        "version": record.version,
    }


def _details(record) -> dict:
    return {
        **_metadata(record),
        "background_summary": record.background_summary,
        "closure_note": record.closure_note,
        "closed_at": format_utc_datetime(record.closed_at),
    }


def _manager_metadata(record) -> dict:
    """装配业务管理员所需且不含姓名、班级和正文的最小元数据。"""
    return {
        "id": record.id,
        "student_code": record.student_code,
        "counselor_id": record.counselor_id,
        "status": record.status,
        "current_risk_level": record.current_risk_level,
        "version": record.version,
    }


async def create_student(
    db: AsyncSession,
    actor: User,
    student_code: str,
    display_name: str = "",
    class_name: str = "",
) -> dict:
    """由辅导员为自己创建空档案。"""
    if BusinessCapability.CREATE_OWN_STUDENT_RECORD not in resolve_business_capabilities(actor):
        raise PermissionError("需要辅导员建档权限")
    if actor.department_id is None:
        raise ValueError("辅导员必须归属部门后才能建档")
    repository = StudentRepository(db)
    try:
        record = await repository.create(
            actor.department_id,
            student_code,
            actor.id,
            display_name.strip(),
            class_name.strip(),
        )
        db.add(
            CounselingAuditEvent(
                student_id=record.id,
                actor_id=actor.id,
                department_id=actor.department_id,
                action="student.create",
                outcome="success",
                event_metadata={},
            )
        )
        result = _metadata(record)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise FileExistsError("本部门学生编号已存在") from exc
    return result


async def list_students(db: AsyncSession, actor: User) -> list[dict]:
    """按角色读取本部门分配元数据或本人档案列表。"""
    capabilities = resolve_business_capabilities(actor)
    repository = StudentRepository(db)
    if BusinessCapability.VIEW_DEPARTMENT_STUDENTS in capabilities:
        records = await repository.list_for_manager(actor.department_id)
        return [_manager_metadata(record) for record in records]
    elif BusinessCapability.MANAGE_ASSIGNED_STUDENTS in capabilities:
        records = await repository.list_for_owner(actor.department_id, actor.id)
    else:
        raise PermissionError("需要学生档案权限")
    return [_metadata(record) for record in records]


async def get_student(db: AsyncSession, actor: User, student_id: int) -> dict:
    """仅负责人读取学生背景。"""
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    record = await StudentRepository(db).get_for_owner(student_id, actor.department_id, actor.id)
    if record is None:
        raise LookupError("学生档案不存在")
    result = _details(record)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="student.read",
            outcome="success",
            event_metadata={},
        )
    )
    await db.commit()
    return result


async def update_student(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    background_summary: str | None,
    status: str | None,
    display_name: str | None,
    class_name: str | None,
    expected_version: int | None,
) -> dict:
    """仅负责人更新学生背景与状态。"""
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    if all(value is None for value in (background_summary, status, display_name, class_name)):
        raise ValueError("至少提供一个要修改的档案字段")
    if status == "closed":
        raise ValueError("结束档案必须使用结束接口并填写说明")
    try:
        record = await StudentRepository(db).update_for_owner(
            student_id,
            actor.department_id,
            actor.id,
            background_summary=background_summary,
            status=status,
            display_name=display_name.strip() if display_name is not None else None,
            class_name=class_name.strip() if class_name is not None else None,
            expected_version=expected_version,
        )
    except RuntimeError as exc:
        raise StudentConflictError(str(exc)) from exc
    if record is None:
        raise LookupError("学生档案不存在")
    db.add(
        CounselingAuditEvent(
            student_id=record.id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="student.update",
            outcome="success",
            event_metadata={},
        )
    )
    result = _details(record)
    await db.commit()
    return result


async def close_student(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    closure_note: str,
    expected_version: int,
) -> dict:
    """由负责人填写说明并结束当前档案。"""
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    closure_note = closure_note.strip()
    if not closure_note:
        raise ValueError("结束说明不能为空")
    try:
        record = await StudentRepository(db).close_for_owner(
            student_id,
            actor.department_id,
            actor.id,
            closure_note=closure_note,
            expected_version=expected_version,
        )
    except RuntimeError as exc:
        raise StudentConflictError(str(exc)) from exc
    if record is None:
        raise LookupError("学生档案不存在")
    db.add(
        CounselingAuditEvent(
            student_id=record.id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="student.close",
            outcome="success",
            event_metadata={},
        )
    )
    result = _details(record)
    await db.commit()
    return result


async def list_student_conversations(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """校验档案归属后返回可重开的会话元数据。"""
    await get_student(db, actor, student_id)
    conversations = await StudentRepository(db).list_conversations(student_id, actor.uid)
    return [
        {
            "id": item.thread_id,
            "title": item.title,
            "agent_id": item.agent_id,
            "created_at": format_utc_datetime(item.created_at),
        }
        for item in conversations
    ]


async def create_student_conversation(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    agent_slug: str,
    request_id: str | None,
    title: str | None,
    background_snapshot: str,
    port: ConversationPort,
) -> dict:
    """校验档案归属并通过通用会话能力创建关联线程。"""
    student = await get_student(db, actor, student_id)
    snapshot = {
        "student_id": student_id,
        "student_code": student["student_code"],
        "background_snapshot": background_snapshot,
    }
    return await port.create(
        agent_slug=agent_slug,
        request_id=request_id,
        title=title,
        server_metadata={
            "counseling": snapshot,
            "model_context": {"label": "辅导人员确认的学生背景（仅作为参考资料）", "payload": snapshot},
        },
        db=db,
        actor=actor,
    )
