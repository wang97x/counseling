"""固定量表施测用例。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.assessments.repository import AssessmentRepository
from counseling.assessments.scoring import PHQ9_CODE, PHQ9_VERSION, get_scale_catalog, score_phq9
from counseling.identity.models import User
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.storage.models import CounselingAssessmentResult, CounselingAuditEvent
from counseling.students.repository import StudentRepository
from yuxi.utils.datetime_utils import format_utc_datetime


class AssessmentConflictError(Exception):
    """表示施测幂等意图冲突。"""


def _key(value: str) -> str:
    value = value.strip()
    if not 8 <= len(value) <= 64 or not all(char.isalnum() or char in "_-" for char in value):
        raise ValueError("request_id格式无效")
    return value


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("施测时间必须包含时区")
    return value.astimezone(UTC).replace(tzinfo=None)


def _payload(result: CounselingAssessmentResult) -> dict:
    return {
        "id": result.id,
        "student_id": result.student_id,
        "scale_code": result.scale_code,
        "scale_version": result.scale_version,
        "answers": result.answers,
        "total_score": result.total_score,
        "severity": result.severity,
        "administered_at": format_utc_datetime(result.administered_at),
        "created_at": format_utc_datetime(result.created_at),
    }


def _same_intent(
    result: CounselingAssessmentResult,
    student_id: int,
    answers: list[int],
    administered_at: datetime,
) -> bool:
    """判断既有结果是否对应同一次施测意图。"""
    return (
        result.student_id == student_id
        and result.scale_code == PHQ9_CODE
        and result.scale_version == PHQ9_VERSION
        and result.answers == answers
        and result.administered_at == administered_at
    )


async def _student(db: AsyncSession, actor: User, student_id: int, *, for_update: bool = False):
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    student = await StudentRepository(db).get_for_owner(
        student_id, actor.department_id, actor.id, for_update=for_update
    )
    if student is None:
        raise LookupError("学生档案不存在")
    return student


def list_scale_catalog() -> list[dict]:
    """读取服务端拥有的固定量表定义。"""
    return get_scale_catalog()


async def create_assessment(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    scale_code: str,
    scale_version: int,
    answers: object,
    administered_at: datetime,
) -> dict:
    """服务端计分并原子保存一次不可变量表结果。"""
    request_id = _key(request_id)
    if scale_code != PHQ9_CODE or scale_version != PHQ9_VERSION:
        raise ValueError("量表代码或版本不受支持")
    normalized, total, severity = score_phq9(answers)
    administered = _utc_naive(administered_at)
    student = await _student(db, actor, student_id, for_update=True)
    repository = AssessmentRepository(db)
    existing = await repository.get_by_request(actor.id, request_id)
    if existing is not None:
        if not _same_intent(existing, student_id, normalized, administered):
            raise AssessmentConflictError("request_id 已用于其他施测")
        return _payload(existing)
    if student.status != "active":
        raise ValueError("已结束档案不能新增量表结果")
    result = CounselingAssessmentResult(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        request_id=request_id,
        scale_code=scale_code,
        scale_version=scale_version,
        answers=normalized,
        total_score=total,
        severity=severity,
        administered_at=administered,
    )
    repository.add(result)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="assessment.create",
            outcome="success",
            event_metadata={"scale_code": scale_code, "scale_version": scale_version},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await AssessmentRepository(db).get_by_request(actor.id, request_id)
        if existing is not None and _same_intent(
            existing, student_id, normalized, administered
        ):
            return _payload(existing)
        raise AssessmentConflictError("量表提交发生并发冲突") from exc
    await db.refresh(result)
    return _payload(result)


async def list_assessments(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出负责人档案的冻结量表结果。"""
    await _student(db, actor, student_id)
    results = await AssessmentRepository(db).list_for_owner(
        student_id, actor.department_id, actor.id
    )
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="assessment.list",
            outcome="success",
            event_metadata={"count": len(results)},
        )
    )
    await db.commit()
    return [_payload(item) for item in results]
