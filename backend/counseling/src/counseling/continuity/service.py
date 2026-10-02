"""方案、人工危机工单、内部转介与回访用例。"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.continuity.repository import ContinuityRepository
from counseling.identity.models import User
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.identity.services.audit import log_operation
from counseling.storage.models import (
    CounselingAuditEvent,
    CounselingCrisisCase,
    CounselingCrisisCaseEvent,
    CounselingCrisisProtocol,
    CounselingPlanVersion,
    CounselingReferral,
)
from counseling.students.repository import StudentRepository
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive


class ContinuityConflictError(Exception):
    """表示幂等意图、版本或状态迁移冲突。"""


def _key(value: str) -> str:
    value = value.strip()
    if not 8 <= len(value) <= 64 or not all(char.isalnum() or char in "_-" for char in value):
        raise ValueError("request_id格式无效")
    return value


def _text(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field}不能为空")
    return value


def _utc_naive(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field}必须包含时区")
    return value.astimezone(UTC).replace(tzinfo=None)


def _require_manager(actor: User) -> int:
    if BusinessCapability.VIEW_DEPARTMENT_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要业务管理权限")
    if actor.department_id is None:
        raise ValueError("当前用户未绑定部门")
    return actor.department_id


async def _owned_student(db: AsyncSession, actor: User, student_id: int, *, for_update: bool = False):
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    student = await StudentRepository(db).get_for_owner(
        student_id, actor.department_id, actor.id, for_update=for_update
    )
    if student is None:
        raise LookupError("学生档案不存在")
    return student


def _plan_payload(item: CounselingPlanVersion) -> dict:
    return {
        "id": item.id,
        "student_id": item.student_id,
        "version_no": item.version_no,
        "stage_goals": item.stage_goals,
        "action_plan": item.action_plan,
        "review_basis": item.review_basis,
        "source_record_id": item.source_record_id,
        "source_assessment_id": item.source_assessment_id,
        "created_by": item.created_by,
        "created_at": format_utc_datetime(item.created_at),
    }


async def create_plan_version(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    stage_goals: list[str],
    action_plan: list[str],
    review_basis: str,
    source_record_id: str | None,
    source_assessment_id: str | None,
) -> dict:
    """为进行中档案追加一个可追溯方案版本。"""
    request_id = _key(request_id)
    goals = [_text(value, "阶段目标") for value in stage_goals]
    actions = [_text(value, "行动计划") for value in action_plan]
    if not goals or not actions:
        raise ValueError("阶段目标和行动计划不能为空")
    review_basis = _text(review_basis, "调整依据")
    await _owned_student(db, actor, student_id)
    repository = ContinuityRepository(db)
    existing = await repository.get_plan_by_request(actor.id, request_id)
    if existing is not None:
        if not (
            existing.student_id == student_id
            and existing.stage_goals == goals
            and existing.action_plan == actions
            and existing.review_basis == review_basis
            and existing.source_record_id == source_record_id
            and existing.source_assessment_id == source_assessment_id
        ):
            raise ContinuityConflictError("request_id 已用于不同方案意图")
        return _plan_payload(existing)
    student = await _owned_student(db, actor, student_id, for_update=True)
    if student.status != "active":
        raise ValueError("已结束档案不能新增方案")
    if not await repository.evidence_belongs_to_student(
        student_id,
        actor.department_id,
        actor.id,
        record_id=source_record_id,
        assessment_id=source_assessment_id,
    ):
        raise LookupError("方案依据不存在")
    item = CounselingPlanVersion(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        version_no=await repository.next_plan_version(student_id),
        stage_goals=goals,
        action_plan=actions,
        review_basis=review_basis,
        source_record_id=source_record_id,
        source_assessment_id=source_assessment_id,
        created_by=actor.id,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="plan.create",
            outcome="success",
            event_metadata={"version": item.version_no},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await repository.get_plan_by_request(actor.id, request_id)
        if existing is not None and (
            existing.student_id == student_id
            and existing.stage_goals == goals
            and existing.action_plan == actions
            and existing.review_basis == review_basis
            and existing.source_record_id == source_record_id
            and existing.source_assessment_id == source_assessment_id
        ):
            return _plan_payload(existing)
        raise ContinuityConflictError("方案创建发生并发冲突") from exc
    await db.refresh(item)
    return _plan_payload(item)


async def list_plan_versions(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出负责人档案的全部方案版本。"""
    await _owned_student(db, actor, student_id)
    items = await ContinuityRepository(db).list_plans(student_id, actor.department_id, actor.id)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="plan.list",
            outcome="success",
            event_metadata={"count": len(items)},
        )
    )
    await db.commit()
    return [_plan_payload(item) for item in items]


def _protocol_payload(item: CounselingCrisisProtocol) -> dict:
    return {
        "id": item.id,
        "version_no": item.version_no,
        "title": item.title,
        "content": item.content,
        "effective_from": format_utc_datetime(item.effective_from),
        "expires_at": format_utc_datetime(item.expires_at),
        "created_at": format_utc_datetime(item.created_at),
    }


async def publish_crisis_protocol(
    db: AsyncSession,
    actor: User,
    *,
    request_id: str,
    title: str,
    content: str,
    effective_from: datetime,
    expires_at: datetime | None,
) -> dict:
    """由业务管理员发布不可覆盖的部门危机协议版本。"""
    department_id = _require_manager(actor)
    request_id = _key(request_id)
    title, content = _text(title, "协议标题"), _text(content, "协议内容")
    effective = _utc_naive(effective_from, "生效时间")
    expires = _utc_naive(expires_at, "失效时间") if expires_at else None
    if expires is not None and expires <= effective:
        raise ValueError("失效时间必须晚于生效时间")
    repository = ContinuityRepository(db)
    existing = await repository.get_protocol_by_request(department_id, request_id)
    if existing is not None:
        if not (
            existing.title == title
            and existing.content == content
            and existing.effective_from == effective
            and existing.expires_at == expires
        ):
            raise ContinuityConflictError("request_id 已用于不同协议意图")
        return _protocol_payload(existing)
    item = CounselingCrisisProtocol(
        id=uuid.uuid4().hex,
        department_id=department_id,
        version_no=await repository.next_protocol_version(department_id),
        title=title,
        content=content,
        effective_from=effective,
        expires_at=expires,
        published_by=actor.id,
        request_id=request_id,
    )
    repository.add(item)
    await log_operation(
        db,
        actor.id,
        "counseling.crisis_protocol.publish",
        details=json.dumps(
            {"protocol_id": item.id, "department_id": department_id, "version": item.version_no},
            separators=(",", ":"),
        ),
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await repository.get_protocol_by_request(department_id, request_id)
        if existing is not None and (
            existing.title == title
            and existing.content == content
            and existing.effective_from == effective
            and existing.expires_at == expires
        ):
            return _protocol_payload(existing)
        raise ContinuityConflictError("协议发布发生并发冲突") from exc
    await db.refresh(item)
    return _protocol_payload(item)


async def list_crisis_protocols(db: AsyncSession, actor: User) -> list[dict]:
    """列出业务管理员本部门的协议历史。"""
    department_id = _require_manager(actor)
    items = await ContinuityRepository(db).list_protocols(department_id)
    await log_operation(
        db,
        actor.id,
        "counseling.crisis_protocol.list",
        details=json.dumps({"department_id": department_id, "count": len(items)}, separators=(",", ":")),
    )
    await db.commit()
    return [_protocol_payload(item) for item in items]


def _case_payload(item: CounselingCrisisCase, events: list[CounselingCrisisCaseEvent] | None = None) -> dict:
    result = {
        "id": item.id,
        "student_id": item.student_id,
        "risk_event_id": item.risk_event_id,
        "protocol_id": item.protocol_id,
        "owner_id": item.owner_id,
        "deadline_at": format_utc_datetime(item.deadline_at),
        "status": item.status,
        "version": item.version,
        "created_at": format_utc_datetime(item.created_at),
        "updated_at": format_utc_datetime(item.updated_at),
    }
    if events is not None:
        result["events"] = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "note": event.note,
                "actor_id": event.actor_id,
                "created_at": format_utc_datetime(event.created_at),
            }
            for event in events
        ]
    return result


async def create_crisis_case(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    risk_event_id: str,
    deadline_at: datetime,
    initial_measure: str,
) -> dict:
    """从人工风险事件创建绑定当前有效协议的工单。"""
    request_id, initial_measure = _key(request_id), _text(initial_measure, "初始措施")
    deadline = _utc_naive(deadline_at, "处置时限")
    await _owned_student(db, actor, student_id)
    repository = ContinuityRepository(db)
    existing = await repository.get_case_by_request(actor.id, request_id)
    if existing is not None:
        events = await repository.list_case_events(existing.id)
        if not (
            existing.student_id == student_id
            and existing.risk_event_id == risk_event_id
            and existing.deadline_at == deadline
            and events
            and events[0].event_type == "measure"
            and events[0].note == initial_measure
        ):
            raise ContinuityConflictError("request_id 已用于不同工单意图")
        return _case_payload(existing, events)
    if deadline <= utc_now_naive():
        raise ValueError("处置时限必须晚于当前时间")
    await _owned_student(db, actor, student_id, for_update=True)
    risk = await repository.get_risk_for_owner(risk_event_id, student_id, actor.department_id, actor.id)
    if risk is None or risk.status == "closed" or risk.level == "normal":
        raise ValueError("工单必须来源于未关闭的人工风险事件")
    protocol = await repository.get_active_protocol(actor.department_id, utc_now_naive())
    if protocol is None:
        raise ValueError("当前部门缺少生效中的危机协议")
    item = CounselingCrisisCase(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        risk_event_id=risk_event_id,
        protocol_id=protocol.id,
        owner_id=actor.id,
        deadline_at=deadline,
        request_id=request_id,
    )
    event = CounselingCrisisCaseEvent(
        id=uuid.uuid4().hex,
        case_id=item.id,
        event_type="measure",
        note=initial_measure,
        actor_id=actor.id,
        request_id=request_id,
        applied_case_version=1,
    )
    item.last_event_id = event.id
    repository.add(item)
    repository.add(event)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="crisis_case.create",
            outcome="success",
            event_metadata={"protocol_id": protocol.id},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await repository.get_case_by_request(actor.id, request_id)
        if existing is not None:
            events = await repository.list_case_events(existing.id)
            if (
                existing.student_id == student_id
                and existing.risk_event_id == risk_event_id
                and existing.deadline_at == deadline
                and events
                and events[0].event_type == "measure"
                and events[0].note == initial_measure
            ):
                return _case_payload(existing, events)
        raise ContinuityConflictError("危机工单创建发生并发冲突") from exc
    await db.refresh(item)
    await db.refresh(event)
    return _case_payload(item, [event])


async def append_crisis_case_event(
    db: AsyncSession,
    actor: User,
    student_id: int,
    case_id: str,
    *,
    request_id: str,
    expected_version: int,
    event_type: str,
    note: str,
) -> dict:
    """按乐观版本追加措施、复核或人工关闭记录。"""
    request_id, note = _key(request_id), _text(note, "处置记录")
    if event_type not in {"measure", "review", "close"}:
        raise ValueError("工单事件类型无效")
    await _owned_student(db, actor, student_id)
    repository = ContinuityRepository(db)
    replay = await repository.get_case_event_by_request(actor.id, request_id)
    if replay is not None:
        if replay.case_id != case_id or replay.event_type != event_type or replay.note != note:
            raise ContinuityConflictError("request_id 已用于不同工单事件")
        item = await repository.get_case_for_owner(
            case_id, student_id, actor.department_id, actor.id
        )
        if item is None:
            raise LookupError("危机工单不存在")
        return _case_payload(item, await repository.list_case_events(case_id))
    item = await repository.get_case_for_owner(case_id, student_id, actor.department_id, actor.id, for_update=True)
    if item is None:
        raise LookupError("危机工单不存在")
    replay = await repository.get_case_event_by_request(actor.id, request_id)
    if replay is not None:
        if replay.case_id != case_id or replay.event_type != event_type or replay.note != note:
            raise ContinuityConflictError("request_id 已用于不同工单事件")
        return _case_payload(item, await repository.list_case_events(case_id))
    if item.version != expected_version:
        raise ContinuityConflictError("危机工单版本已变化")
    if (
        item.status == "closed"
        or event_type == "review"
        and item.status != "open"
        or event_type == "close"
        and item.status != "reviewed"
    ):
        raise ContinuityConflictError("危机工单状态迁移无效")
    event = CounselingCrisisCaseEvent(
        id=uuid.uuid4().hex,
        case_id=case_id,
        event_type=event_type,
        note=note,
        actor_id=actor.id,
        request_id=request_id,
        applied_case_version=expected_version + 1,
    )
    repository.add(event)
    await db.flush()
    item.last_event_id = event.id
    if event_type == "review":
        item.status = "reviewed"
    if event_type == "close":
        item.status = "closed"
    item.version += 1
    item.updated_at = utc_now_naive()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        replay = await repository.get_case_event_by_request(actor.id, request_id)
        if replay is not None and replay.case_id == case_id and replay.event_type == event_type and replay.note == note:
            item = await repository.get_case_for_owner(case_id, student_id, actor.department_id, actor.id)
            if item is not None:
                return _case_payload(item, await repository.list_case_events(case_id))
        raise ContinuityConflictError("危机工单事件发生并发冲突") from exc
    return _case_payload(item, await repository.list_case_events(case_id))


async def list_crisis_cases(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出负责人档案的工单及追加事件。"""
    await _owned_student(db, actor, student_id)
    repository = ContinuityRepository(db)
    items = await repository.list_cases(student_id, actor.department_id, actor.id)
    result = [_case_payload(item, await repository.list_case_events(item.id)) for item in items]
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="crisis_case.list",
            outcome="success",
            event_metadata={"count": len(items)},
        )
    )
    await db.commit()
    return result


def _referral_payload(item: CounselingReferral, *, include_content: bool = True) -> dict:
    result = {
        "id": item.id,
        "student_id": item.student_id,
        "counselor_id": item.counselor_id,
        "authorization_status": item.authorization_status,
        "status": item.status,
        "decision_note": item.decision_note,
        "follow_up_at": format_utc_datetime(item.follow_up_at),
        "follow_up_result": item.follow_up_result if include_content else None,
        "version": item.version,
        "created_at": format_utc_datetime(item.created_at),
    }
    if include_content:
        result.update(reason=item.reason, material_scope=item.material_scope)
    return result


async def create_referral(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    reason: str,
    authorization_status: str,
    material_scope: list[str],
    follow_up_at: datetime | None,
) -> dict:
    """创建只在机构内部流转的最小转介请求。"""
    request_id, reason = _key(request_id), _text(reason, "转介原因")
    if authorization_status != "granted":
        raise ValueError("未取得授权时不能创建转介")
    scope = list(dict.fromkeys(value.strip() for value in material_scope if value.strip()))
    allowed = {"student_metadata", "risk_level", "plan_summary"}
    if not scope or not set(scope) <= allowed:
        raise ValueError("转介材料范围无效")
    follow_up = _utc_naive(follow_up_at, "回访时间") if follow_up_at else None
    await _owned_student(db, actor, student_id)
    repository = ContinuityRepository(db)
    existing = await repository.get_referral_by_request(actor.id, request_id)
    if existing is not None:
        if not (
            existing.student_id == student_id
            and existing.reason == reason
            and existing.authorization_status == authorization_status
            and existing.material_scope == scope
            and existing.follow_up_at == follow_up
        ):
            raise ContinuityConflictError("request_id 已用于不同转介意图")
        return _referral_payload(existing)
    student = await _owned_student(db, actor, student_id, for_update=True)
    if student.status != "active":
        raise ValueError("已结束档案不能新增转介")
    item = CounselingReferral(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        reason=reason,
        authorization_status=authorization_status,
        material_scope=scope,
        follow_up_at=follow_up,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="referral.create",
            outcome="success",
            event_metadata={"material_scope": scope},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await repository.get_referral_by_request(actor.id, request_id)
        if existing is not None and (
            existing.student_id == student_id
            and existing.reason == reason
            and existing.authorization_status == authorization_status
            and existing.material_scope == scope
            and existing.follow_up_at == follow_up
        ):
            return _referral_payload(existing)
        raise ContinuityConflictError("转介创建发生并发冲突") from exc
    await db.refresh(item)
    return _referral_payload(item)


async def list_referrals(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出负责人档案内的转介与回访。"""
    await _owned_student(db, actor, student_id)
    items = await ContinuityRepository(db).list_referrals_for_owner(student_id, actor.department_id, actor.id)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="referral.list",
            outcome="success",
            event_metadata={"count": len(items)},
        )
    )
    await db.commit()
    return [_referral_payload(item) for item in items]


async def list_department_referrals(db: AsyncSession, actor: User) -> list[dict]:
    """向业务管理员返回不含原因和材料正文的转介队列。"""
    department_id = _require_manager(actor)
    items = [
        _referral_payload(item, include_content=False)
        for item in await ContinuityRepository(db).list_referrals_for_manager(department_id)
    ]
    await log_operation(
        db,
        actor.id,
        "counseling.referral.list",
        details=json.dumps({"department_id": department_id, "count": len(items)}, separators=(",", ":")),
    )
    await db.commit()
    return items


async def decide_referral(
    db: AsyncSession, actor: User, referral_id: str, *, expected_version: int, decision: str, note: str
) -> dict:
    """由同部门业务管理员接收或拒绝内部转介。"""
    department_id = _require_manager(actor)
    if decision not in {"accepted", "rejected"}:
        raise ValueError("转介决定无效")
    note = _text(note, "决定说明")
    item = await ContinuityRepository(db).get_referral_for_manager(referral_id, department_id, for_update=True)
    if item is None:
        raise LookupError("转介不存在")
    if item.version != expected_version or item.status != "pending":
        raise ContinuityConflictError("转介版本已变化或状态不可处理")
    item.status = decision
    item.decision_note = note
    item.decided_by = actor.id
    item.decided_at = utc_now_naive()
    item.version += 1
    item.updated_at = utc_now_naive()
    await db.commit()
    return _referral_payload(item, include_content=False)


async def complete_referral_follow_up(
    db: AsyncSession, actor: User, student_id: int, referral_id: str, *, expected_version: int, result: str
) -> dict:
    """由原负责人记录已接收转介的回访结果。"""
    result = _text(result, "回访结果")
    await _owned_student(db, actor, student_id)
    item = await ContinuityRepository(db).get_referral_for_owner(
        referral_id, student_id, actor.department_id, actor.id, for_update=True
    )
    if item is None:
        raise LookupError("转介不存在")
    if item.version != expected_version or item.status != "accepted":
        raise ContinuityConflictError("转介版本已变化或尚未接收")
    item.follow_up_result = result
    item.completed_at = utc_now_naive()
    item.status = "completed"
    item.version += 1
    item.updated_at = utc_now_naive()
    await db.commit()
    return _referral_payload(item)
