"""内部预约创建、改期与状态用例。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.appointments.repository import AppointmentRepository
from counseling.identity.models import User
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.storage.models import CounselingAppointment, CounselingAuditEvent
from counseling.students.repository import StudentRepository
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

ALLOWED_TRANSITIONS = {
    "scheduled": {"arrived", "no_show", "canceled"},
    "arrived": {"completed"},
}


class AppointmentConflictError(Exception):
    """表示预约版本、幂等意图或状态迁移冲突。"""


def _key(value: str) -> str:
    value = value.strip()
    if not 8 <= len(value) <= 64 or not all(char.isalnum() or char in "_-" for char in value):
        raise ValueError("request_id格式无效")
    return value


def _utc_naive(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field}必须包含时区")
    return value.astimezone(UTC).replace(tzinfo=None)


def _schedule(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    normalized_start = _utc_naive(start, "预约开始时间")
    normalized_end = _utc_naive(end, "预约结束时间")
    if normalized_end <= normalized_start:
        raise ValueError("预约结束时间必须晚于开始时间")
    return normalized_start, normalized_end


def _payload(item: CounselingAppointment) -> dict:
    return {
        "id": item.id,
        "student_id": item.student_id,
        "scheduled_start": format_utc_datetime(item.scheduled_start),
        "scheduled_end": format_utc_datetime(item.scheduled_end),
        "appointment_type": item.appointment_type,
        "location": item.location,
        "note": item.note,
        "status": item.status,
        "version": item.version,
        "created_at": format_utc_datetime(item.created_at),
        "updated_at": format_utc_datetime(item.updated_at),
    }


def _same_intent(
    item: CounselingAppointment,
    student_id: int,
    start: datetime,
    end: datetime,
    appointment_type: str,
    location: str,
    note: str,
) -> bool:
    """判断既有预约是否对应同一次创建意图。"""
    return (
        item.student_id == student_id
        and item.created_scheduled_start == start
        and item.created_scheduled_end == end
        and item.created_appointment_type == appointment_type
        and item.created_location == location
        and item.created_note == note
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


async def create_appointment(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    scheduled_start: datetime,
    scheduled_end: datetime,
    appointment_type: str,
    location: str,
    note: str,
) -> dict:
    """为进行中档案创建内部预约。"""
    request_id = _key(request_id)
    start, end = _schedule(scheduled_start, scheduled_end)
    appointment_type = appointment_type.strip()
    location = location.strip()
    note = note.strip()
    if not appointment_type:
        raise ValueError("预约方式不能为空")
    student = await _student(db, actor, student_id, for_update=True)
    repository = AppointmentRepository(db)
    existing = await repository.get_by_request(actor.id, request_id)
    if existing is not None:
        if not _same_intent(
            existing, student_id, start, end, appointment_type, location, note
        ):
            raise AppointmentConflictError("request_id 已用于其他预约")
        return _payload(existing)
    if student.status != "active":
        raise ValueError("已结束档案不能创建预约")
    appointment = CounselingAppointment(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        request_id=request_id,
        scheduled_start=start,
        scheduled_end=end,
        appointment_type=appointment_type,
        location=location,
        note=note,
        created_scheduled_start=start,
        created_scheduled_end=end,
        created_appointment_type=appointment_type,
        created_location=location,
        created_note=note,
    )
    repository.add(appointment)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="appointment.create",
            outcome="success",
            event_metadata={},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await AppointmentRepository(db).get_by_request(actor.id, request_id)
        if existing is not None and _same_intent(
            existing, student_id, start, end, appointment_type, location, note
        ):
            return _payload(existing)
        raise AppointmentConflictError("预约创建发生并发冲突") from exc
    await db.refresh(appointment)
    return _payload(appointment)


async def list_appointments(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出负责人档案的内部预约。"""
    await _student(db, actor, student_id)
    items = await AppointmentRepository(db).list_for_owner(
        student_id, actor.department_id, actor.id
    )
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="appointment.list",
            outcome="success",
            event_metadata={"count": len(items)},
        )
    )
    await db.commit()
    return [_payload(item) for item in items]


async def update_appointment(
    db: AsyncSession,
    actor: User,
    student_id: int,
    appointment_id: str,
    *,
    expected_version: int,
    scheduled_start: datetime,
    scheduled_end: datetime,
    appointment_type: str,
    location: str,
    note: str,
) -> dict:
    """按乐观版本修改尚未到访的预约。"""
    await _student(db, actor, student_id)
    start, end = _schedule(scheduled_start, scheduled_end)
    appointment_type = appointment_type.strip()
    if not appointment_type:
        raise ValueError("预约方式不能为空")
    item = await AppointmentRepository(db).get_for_owner(
        appointment_id, student_id, actor.department_id, actor.id, for_update=True
    )
    if item is None:
        raise LookupError("预约不存在")
    if item.version != expected_version or item.status != "scheduled":
        raise AppointmentConflictError("预约版本已变化或当前状态不可修改")
    item.scheduled_start = start
    item.scheduled_end = end
    item.appointment_type = appointment_type
    item.location = location.strip()
    item.note = note.strip()
    item.version += 1
    item.updated_at = utc_now_naive()
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="appointment.update",
            outcome="success",
            event_metadata={"appointment_id": item.id},
        )
    )
    await db.commit()
    return _payload(item)


async def change_appointment_status(
    db: AsyncSession,
    actor: User,
    student_id: int,
    appointment_id: str,
    *,
    expected_version: int,
    status: str,
) -> dict:
    """按允许的线性迁移记录取消或到访结果。"""
    await _student(db, actor, student_id)
    item = await AppointmentRepository(db).get_for_owner(
        appointment_id, student_id, actor.department_id, actor.id, for_update=True
    )
    if item is None:
        raise LookupError("预约不存在")
    if item.version != expected_version:
        raise AppointmentConflictError("预约版本已变化")
    if status not in ALLOWED_TRANSITIONS.get(item.status, set()):
        raise AppointmentConflictError("预约状态迁移无效")
    item.status = status
    item.version += 1
    item.updated_at = utc_now_naive()
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="appointment.status",
            outcome="success",
            event_metadata={"appointment_id": item.id, "status": status},
        )
    )
    await db.commit()
    return _payload(item)
