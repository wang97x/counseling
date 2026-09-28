"""辅导员人工风险记录用例。"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.documents.repository import CounselingRecordRepository
from counseling.risks.repository import CounselingRiskRepository
from counseling.storage.models import CounselingAuditEvent, CounselingRiskEvent
from counseling.students.repository import StudentRepository
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.identity.models import User
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

RISK_LEVELS = {"normal", "watch", "urgent"}
RISK_STATUSES = {"open", "monitoring", "closed"}


class RiskConflictError(Exception):
    """表示风险事件幂等意图冲突。"""


def _validate_request_id(value: str) -> str:
    """校验风险写入的稳定幂等键。"""
    value = value.strip()
    if not 8 <= len(value) <= 64 or not all(character.isalnum() or character in "_-" for character in value):
        raise ValueError("request_id格式无效")
    return value


def _payload(event: CounselingRiskEvent) -> dict:
    """装配不包含其他档案信息的风险事件。"""
    return {
        "id": event.id,
        "student_id": event.student_id,
        "level": event.level,
        "basis": event.basis,
        "action_taken": event.action_taken,
        "status": event.status,
        "source_record_id": event.source_record_id,
        "created_at": format_utc_datetime(event.created_at),
    }


async def _owned_student(db: AsyncSession, actor: User, student_id: int, *, for_update: bool = False):
    """校验负责人权限并按需持锁读取学生。"""
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    student = await StudentRepository(db).get_for_owner(
        student_id, actor.department_id, actor.id, for_update=for_update
    )
    if student is None:
        raise LookupError("学生档案不存在")
    return student


async def create_risk_event(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    level: str,
    basis: str,
    action_taken: str,
    status: str,
    source_record_id: str | None,
) -> dict:
    """原子追加人工风险事件并更新档案当前风险投影。"""
    request_id = _validate_request_id(request_id)
    if level not in RISK_LEVELS:
        raise ValueError("风险等级无效")
    if status not in RISK_STATUSES:
        raise ValueError("风险处置状态无效")
    basis = basis.strip()
    if not basis:
        raise ValueError("风险判断依据不能为空")
    await _owned_student(db, actor, student_id)
    repository = CounselingRiskRepository(db)
    existing = await repository.get_by_request(actor.id, request_id)
    if existing is not None:
        if existing.student_id != student_id:
            raise RiskConflictError("request_id 已用于其他学生风险事件")
        return _payload(existing)
    student = await _owned_student(db, actor, student_id, for_update=True)
    existing = await repository.get_by_request(actor.id, request_id)
    if existing is not None:
        if existing.student_id != student_id:
            raise RiskConflictError("request_id 已用于其他学生风险事件")
        return _payload(existing)
    if source_record_id:
        source = await CounselingRecordRepository(db).get_formal(
            source_record_id, student_id, actor.department_id, actor.id
        )
        if source is None:
            raise LookupError("风险来源记录不存在")
    event = CounselingRiskEvent(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        level=level,
        basis=basis,
        action_taken=action_taken.strip(),
        status=status,
        source_record_id=source_record_id,
        created_by=actor.id,
        request_id=request_id,
    )
    repository.add(event)
    student.current_risk_level = level
    student.version += 1
    student.updated_at = utc_now_naive()
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            record_id=source_record_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="risk_event.create",
            outcome="success",
            event_metadata={"level": level, "status": status},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise RiskConflictError("风险事件请求发生并发冲突") from exc
    await db.refresh(event)
    return _payload(event)


async def list_risk_events(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """返回负责人可见的人工风险历史。"""
    await _owned_student(db, actor, student_id)
    events = await CounselingRiskRepository(db).list_for_owner(student_id, actor.department_id, actor.id)
    result = [_payload(event) for event in events]
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="risk_event.list",
            outcome="success",
            event_metadata={},
        )
    )
    await db.commit()
    return result
