"""授权督导、固定口径看板与一次性交付用例。"""

import hashlib
import json
import secrets
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.collaboration.repository import CollaborationRepository
from counseling.identity.models import User
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.identity.services.audit import log_operation
from counseling.storage.models import (
    CounselingAssessmentResult,
    CounselingAuditEvent,
    CounselingRecord,
    CounselingRiskEvent,
)
from counseling.storage.p3_models import (
    CounselingExternalAuthorization,
    CounselingExternalDelivery,
    CounselingExternalRecipient,
    CounselingSupervisionAuthorization,
    CounselingSupervisionFeedback,
    CounselingSupervisionMaterial,
    CounselingSupervisionSummary,
)
from counseling.students.repository import StudentRepository
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

SUPERVISION_SCOPES = frozenset({"case_overview", "supervision_feedback", "supervision_summary"})
EXTERNAL_SCOPES = frozenset({"resource_catalog", "referral_status"})
CONCERN_TAGS = frozenset({"adjustment", "anxiety", "mood", "relationships", "study", "sleep", "risk", "other"})
STAGES = frozenset({"engagement", "assessment", "intervention", "review", "closure"})
FOCUS_AREAS = frozenset({"case_conceptualization", "process", "ethics", "risk", "referral"})
WINDOW_DAYS = {"month": 30, "quarter": 90, "year": 365}
SMALL_COHORT_LIMIT = 5


class CollaborationConflictError(Exception):
    """表示 P3 幂等意图、版本或状态迁移冲突。"""


def _key(value: str) -> str:
    value = value.strip()
    if not 8 <= len(value) <= 64 or not all(char.isalnum() or char in "_-" for char in value):
        raise ValueError("request_id格式无效")
    return value


def _text(value: str, field: str, *, maximum: int) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field}不能为空")
    if len(value) > maximum:
        raise ValueError(f"{field}过长")
    return value


def _utc_naive(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field}必须包含时区")
    return value.astimezone(UTC).replace(tzinfo=None)


def _normalize_scopes(values: list[str], allowed: frozenset[str]) -> list[str]:
    scopes = sorted(set(values))
    if not scopes or any(value not in allowed for value in scopes):
        raise ValueError("授权范围无效")
    return scopes


def _require_manager(actor: User) -> int:
    if BusinessCapability.VIEW_DEPARTMENT_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要业务管理权限")
    if actor.department_id is None:
        raise ValueError("当前用户未绑定部门")
    return actor.department_id


def _require_supervisor(actor: User) -> int:
    if BusinessCapability.VIEW_AUTHORIZED_SUPERVISION not in resolve_business_capabilities(actor):
        raise PermissionError("需要督导权限")
    if actor.department_id is None:
        raise ValueError("当前用户未绑定部门")
    return actor.department_id


async def _owned_student(db: AsyncSession, actor: User, student_id: int):
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    student = await StudentRepository(db).get_for_owner(student_id, actor.department_id, actor.id)
    if student is None:
        raise LookupError("学生档案不存在")
    return student


def _active(authorization, scope: str, *, at: datetime | None = None) -> None:
    now = at or utc_now_naive()
    if authorization.status != "active":
        raise PermissionError("授权当前未生效")
    if not authorization.effective_from <= now < authorization.expires_at:
        raise PermissionError("授权不在有效期")
    if scope not in authorization.scopes:
        raise PermissionError("授权范围不包含当前操作")


def _authorization_payload(item, *, expose_student: bool = True) -> dict:
    payload = {
        "id": item.id,
        "scopes": list(item.scopes),
        "status": item.status,
        "effective_from": format_utc_datetime(item.effective_from),
        "expires_at": format_utc_datetime(item.expires_at),
        "version": item.version,
        "decision_note": item.decision_note,
        "created_at": format_utc_datetime(item.created_at),
    }
    if isinstance(item, CounselingSupervisionAuthorization):
        payload.update({"supervisor_id": item.supervisor_id, "purpose": item.purpose})
    else:
        payload["recipient_id"] = item.recipient_id
    if expose_student:
        payload["student_id"] = item.student_id
        payload["counselor_id"] = item.counselor_id
    return payload


async def create_supervision_authorization(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    supervisor_id: int,
    scopes: list[str],
    purpose: str,
    effective_from: datetime,
    expires_at: datetime,
) -> dict:
    """由负责人提出同部门、限时且限范围的督导授权。"""
    student = await _owned_student(db, actor, student_id)
    if student.status != "active":
        raise ValueError("已结束档案不能新增督导授权")
    request_id = _key(request_id)
    scopes = _normalize_scopes(scopes, SUPERVISION_SCOPES)
    purpose = _text(purpose, "授权目的", maximum=500)
    effective = _utc_naive(effective_from, "生效时间")
    expires = _utc_naive(expires_at, "失效时间")
    if expires <= effective:
        raise ValueError("失效时间必须晚于生效时间")
    repository = CollaborationRepository(db)
    supervisor = await repository.get_supervisor(supervisor_id, actor.department_id)
    if supervisor is None:
        raise LookupError("同部门督导不存在")
    existing = await repository.get_supervision_auth_by_request(actor.id, request_id)
    intent = (student_id, supervisor_id, scopes, purpose, effective, expires)
    if existing is not None:
        current = (
            existing.student_id,
            existing.supervisor_id,
            list(existing.scopes),
            existing.purpose,
            existing.effective_from,
            existing.expires_at,
        )
        if current != intent:
            raise CollaborationConflictError("request_id 已用于不同督导授权")
        return _authorization_payload(existing)
    item = CounselingSupervisionAuthorization(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        supervisor_id=supervisor_id,
        scopes=scopes,
        purpose=purpose,
        effective_from=effective,
        expires_at=expires,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="supervision.authorization.request",
            outcome="success",
            event_metadata={"authorization_id": item.id, "scopes": scopes},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _authorization_payload(item)


async def decide_supervision_authorization(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
    *,
    expected_version: int,
    decision: str,
    note: str,
) -> dict:
    """由同部门业务管理员批准或拒绝督导授权。"""
    department_id = _require_manager(actor)
    if decision not in {"approved", "rejected"}:
        raise ValueError("授权决定无效")
    note = _text(note, "决定说明", maximum=1000)
    repository = CollaborationRepository(db)
    item = await repository.get_supervision_auth(authorization_id, for_update=True)
    if item is None or item.department_id != department_id:
        raise LookupError("督导授权不存在")
    if item.status != "pending" or item.version != expected_version:
        raise CollaborationConflictError("督导授权状态或版本已变化")
    if await repository.get_supervisor(item.supervisor_id, department_id) is None:
        raise CollaborationConflictError("督导账号已失效")
    now = utc_now_naive()
    item.status = "active" if decision == "approved" else "rejected"
    item.version += 1
    item.decision_note = note
    if decision == "approved":
        item.approved_by, item.approved_at = actor.id, now
    else:
        item.rejected_by, item.rejected_at = actor.id, now
    await log_operation(
        db,
        actor.id,
        f"counseling.supervision.authorization.{decision}",
        details=json.dumps({"authorization_id": item.id}, separators=(",", ":")),
    )
    await db.commit()
    await db.refresh(item)
    return _authorization_payload(item)


async def revoke_supervision_authorization(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
    *,
    expected_version: int,
    note: str,
) -> dict:
    """由负责人或同部门业务管理员立即撤回督导授权。"""
    note = _text(note, "撤回说明", maximum=1000)
    repository = CollaborationRepository(db)
    item = await repository.get_supervision_auth(authorization_id, for_update=True)
    if item is None:
        raise LookupError("督导授权不存在")
    manager = BusinessCapability.VIEW_DEPARTMENT_STUDENTS in resolve_business_capabilities(actor)
    if not ((actor.id == item.counselor_id) or (manager and actor.department_id == item.department_id)):
        raise PermissionError("无权撤回该督导授权")
    if item.status != "active" or item.version != expected_version:
        raise CollaborationConflictError("督导授权状态或版本已变化")
    item.status = "revoked"
    item.version += 1
    item.revoked_by = actor.id
    item.revoked_at = utc_now_naive()
    item.decision_note = note
    db.add(
        CounselingAuditEvent(
            student_id=item.student_id,
            actor_id=actor.id,
            department_id=item.department_id,
            action="supervision.authorization.revoke",
            outcome="success",
            event_metadata={"authorization_id": item.id},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _authorization_payload(item)


async def list_supervision_authorizations(
    db: AsyncSession,
    actor: User,
    *,
    student_id: int | None = None,
) -> list[dict]:
    """按负责人、管理员或督导的真实可见范围列出授权。"""
    repository = CollaborationRepository(db)
    capabilities = resolve_business_capabilities(actor)
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS in capabilities:
        if student_id is None:
            raise ValueError("负责人查询必须指定学生档案")
        await _owned_student(db, actor, student_id)
        rows = await repository.list_supervision_for_owner(student_id, actor.department_id, actor.id)
        return [_authorization_payload(item) for item in rows]
    if BusinessCapability.VIEW_DEPARTMENT_STUDENTS in capabilities:
        rows = await repository.list_supervision_for_manager(_require_manager(actor))
        return [_authorization_payload(item) for item in rows]
    department_id = _require_supervisor(actor)
    rows = await repository.list_supervision_for_supervisor(actor.id, department_id)
    now = utc_now_naive()
    return [
        _authorization_payload(item, expose_student=False)
        for item in rows
        if item.status == "active" and item.effective_from <= now < item.expires_at
    ]


def _material_payload(item: CounselingSupervisionMaterial) -> dict:
    return {
        "id": item.id,
        "authorization_id": item.authorization_id,
        "version_no": item.version_no,
        "case_alias": item.case_alias,
        "stage": item.stage,
        "concern_tags": list(item.concern_tags),
        "session_count": item.session_count,
        "assessment_count": item.assessment_count,
        "risk_event_count": item.risk_event_count,
        "created_at": format_utc_datetime(item.created_at),
    }


async def publish_supervision_material(
    db: AsyncSession,
    actor: User,
    student_id: int,
    authorization_id: str,
    *,
    request_id: str,
    stage: str,
    concern_tags: list[str],
) -> dict:
    """由负责人发布仅含受控枚举和计数的去标识材料。"""
    await _owned_student(db, actor, student_id)
    request_id = _key(request_id)
    if stage not in STAGES:
        raise ValueError("辅导阶段无效")
    tags = sorted(set(concern_tags))
    if any(tag not in CONCERN_TAGS for tag in tags):
        raise ValueError("主题标签无效")
    repository = CollaborationRepository(db)
    authorization = await repository.get_supervision_auth(authorization_id, for_update=True)
    if authorization is None or authorization.student_id != student_id or authorization.counselor_id != actor.id:
        raise LookupError("督导授权不存在")
    _active(authorization, "case_overview")
    existing = await repository.get_material_by_request(actor.id, request_id)
    if existing is not None:
        if (
            existing.authorization_id != authorization_id
            or existing.stage != stage
            or list(existing.concern_tags) != tags
        ):
            raise CollaborationConflictError("request_id 已用于不同去标识材料")
        return _material_payload(existing)
    session_count = int(
        await db.scalar(select(func.count(CounselingRecord.id)).where(CounselingRecord.student_id == student_id)) or 0
    )
    assessment_count = int(
        await db.scalar(
            select(func.count(CounselingAssessmentResult.id)).where(CounselingAssessmentResult.student_id == student_id)
        )
        or 0
    )
    risk_event_count = int(
        await db.scalar(select(func.count(CounselingRiskEvent.id)).where(CounselingRiskEvent.student_id == student_id))
        or 0
    )
    item = CounselingSupervisionMaterial(
        id=uuid.uuid4().hex,
        authorization_id=authorization_id,
        student_id=student_id,
        version_no=await repository.next_material_version(authorization_id),
        case_alias=f"CASE-{authorization.id[:8].upper()}",
        stage=stage,
        concern_tags=tags,
        session_count=session_count,
        assessment_count=assessment_count,
        risk_event_count=risk_event_count,
        created_by=actor.id,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="supervision.material.publish",
            outcome="success",
            event_metadata={"authorization_id": authorization_id, "material_id": item.id},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _material_payload(item)


async def list_supervision_materials(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
) -> list[dict]:
    """按当前有效授权列出去标识材料。"""
    repository = CollaborationRepository(db)
    authorization = await repository.get_supervision_auth(authorization_id)
    if authorization is None:
        raise LookupError("督导授权不存在")
    if actor.id == authorization.counselor_id:
        await _owned_student(db, actor, authorization.student_id)
    else:
        _require_supervisor(actor)
        if actor.id != authorization.supervisor_id or actor.department_id != authorization.department_id:
            raise PermissionError("无权读取该督导材料")
        _active(authorization, "case_overview")
    return [_material_payload(item) for item in await repository.list_materials(authorization_id)]


def _feedback_payload(item: CounselingSupervisionFeedback) -> dict:
    return {
        "id": item.id,
        "authorization_id": item.authorization_id,
        "material_id": item.material_id,
        "focus_area": item.focus_area,
        "comment": item.comment,
        "created_at": format_utc_datetime(item.created_at),
    }


async def create_supervision_feedback(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
    *,
    request_id: str,
    material_id: str,
    focus_area: str,
    comment: str,
) -> dict:
    """由督导在当前有效授权内追加意见。"""
    _require_supervisor(actor)
    request_id = _key(request_id)
    if focus_area not in FOCUS_AREAS:
        raise ValueError("督导关注面无效")
    comment = _text(comment, "督导意见", maximum=10000)
    repository = CollaborationRepository(db)
    authorization = await repository.get_supervision_auth(authorization_id)
    if (
        authorization is None
        or authorization.supervisor_id != actor.id
        or authorization.department_id != actor.department_id
    ):
        raise LookupError("督导授权不存在")
    _active(authorization, "supervision_feedback")
    if await repository.get_material(material_id, authorization_id) is None:
        raise LookupError("去标识材料不存在")
    existing = await repository.get_feedback_by_request(actor.id, request_id)
    if existing is not None:
        if (
            existing.authorization_id != authorization_id
            or existing.material_id != material_id
            or existing.focus_area != focus_area
            or existing.comment != comment
        ):
            raise CollaborationConflictError("request_id 已用于不同督导意见")
        return _feedback_payload(existing)
    item = CounselingSupervisionFeedback(
        id=uuid.uuid4().hex,
        authorization_id=authorization_id,
        material_id=material_id,
        supervisor_id=actor.id,
        focus_area=focus_area,
        comment=comment,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=authorization.student_id,
            actor_id=actor.id,
            department_id=authorization.department_id,
            action="supervision.feedback.create",
            outcome="success",
            event_metadata={"authorization_id": authorization_id, "material_id": material_id},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _feedback_payload(item)


async def list_supervision_feedback(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
) -> list[dict]:
    """让负责人或当前获授权督导读取督导意见。"""
    repository = CollaborationRepository(db)
    authorization = await repository.get_supervision_auth(authorization_id)
    if authorization is None:
        raise LookupError("督导授权不存在")
    if actor.id == authorization.counselor_id:
        await _owned_student(db, actor, authorization.student_id)
    else:
        _require_supervisor(actor)
        if actor.id != authorization.supervisor_id:
            raise PermissionError("无权读取该督导意见")
        _active(authorization, "supervision_feedback")
    rows = await repository.list_feedback(authorization_id)
    return [_feedback_payload(item) for item in rows]


async def create_supervision_summary(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
    *,
    request_id: str,
    material_id: str,
) -> dict:
    """由负责人从同一授权的意见生成结构化摘要。"""
    request_id = _key(request_id)
    repository = CollaborationRepository(db)
    authorization = await repository.get_supervision_auth(authorization_id)
    if authorization is None or authorization.counselor_id != actor.id:
        raise LookupError("督导授权不存在")
    await _owned_student(db, actor, authorization.student_id)
    _active(authorization, "supervision_summary")
    if await repository.get_material(material_id, authorization_id) is None:
        raise LookupError("去标识材料不存在")
    feedback = await repository.list_feedback(authorization_id, material_id)
    if not feedback:
        raise ValueError("当前材料没有督导意见")
    focus_areas = dict(sorted(Counter(item.focus_area for item in feedback).items()))
    existing = await repository.get_summary_by_request(actor.id, request_id)
    if existing is not None:
        if (
            existing.authorization_id != authorization_id
            or existing.material_id != material_id
            or existing.feedback_count != len(feedback)
            or dict(existing.focus_areas) != focus_areas
        ):
            raise CollaborationConflictError("request_id 已用于不同督导摘要")
        item = existing
    else:
        item = CounselingSupervisionSummary(
            id=uuid.uuid4().hex,
            authorization_id=authorization_id,
            material_id=material_id,
            feedback_count=len(feedback),
            focus_areas=focus_areas,
            counselor_id=actor.id,
            request_id=request_id,
        )
        repository.add(item)
        await db.commit()
        await db.refresh(item)
    return {
        "id": item.id,
        "authorization_id": item.authorization_id,
        "material_id": item.material_id,
        "feedback_count": item.feedback_count,
        "focus_areas": dict(item.focus_areas),
        "created_at": format_utc_datetime(item.created_at),
    }


async def get_quality_dashboard(db: AsyncSession, actor: User, *, window: str) -> dict:
    """返回固定口径、固定窗口且抑制小样本的部门质量指标。"""
    department_id = _require_manager(actor)
    if window not in WINDOW_DAYS:
        raise ValueError("统计窗口无效")
    end = utc_now_naive()
    start = end - timedelta(days=WINDOW_DAYS[window])
    values = await CollaborationRepository(db).count_case_metrics(department_id, start, end)
    cohort = values.pop("cohort")
    definitions = {
        "records": "窗口内至少确认一份正式记录的个案数",
        "assessments": "窗口内至少完成一次固定量表的个案数",
        "appointments_completed": "窗口内至少完成一次内部预约的个案数",
        "risk_events": "窗口内至少记录一次人工风险事件的个案数",
        "crisis_closed": "窗口内至少人工关闭一个危机工单的个案数",
        "referrals_completed": "窗口内至少完成一次内部转介回访的个案数",
    }
    suppressed = cohort < SMALL_COHORT_LIMIT
    metrics = []
    for code, definition in definitions.items():
        numerator = values[code]
        metrics.append(
            {
                "code": code,
                "definition": definition,
                "numerator": None if suppressed else numerator,
                "denominator": None if suppressed else cohort,
                "ratio": None if suppressed or cohort == 0 else round(numerator / cohort, 4),
                "suppressed": suppressed,
            }
        )
    await log_operation(
        db,
        actor.id,
        "counseling.quality_dashboard.read",
        details=json.dumps({"window": window, "suppressed": suppressed}, separators=(",", ":")),
    )
    await db.commit()
    return {
        "window": window,
        "start": format_utc_datetime(start),
        "end": format_utc_datetime(end),
        "scope": "current_department",
        "minimum_cohort": SMALL_COHORT_LIMIT,
        "metrics": metrics,
    }


def _recipient_payload(item: CounselingExternalRecipient) -> dict:
    return {
        "id": item.id,
        "recipient_code": item.recipient_code,
        "display_name": item.display_name,
        "purpose": item.purpose,
        "active": bool(item.active),
        "created_at": format_utc_datetime(item.created_at),
    }


async def register_external_recipient(
    db: AsyncSession,
    actor: User,
    *,
    request_id: str,
    recipient_code: str,
    display_name: str,
    purpose: str,
) -> dict:
    """由业务管理员核验当前部门的外部接收方。"""
    department_id = _require_manager(actor)
    request_id = _key(request_id)
    recipient_code = _text(recipient_code, "接收方编号", maximum=64)
    if not all(char.isalnum() or char in "_-" for char in recipient_code):
        raise ValueError("接收方编号格式无效")
    display_name = _text(display_name, "接收方名称", maximum=200)
    purpose = _text(purpose, "接收用途", maximum=500)
    repository = CollaborationRepository(db)
    existing = await repository.get_recipient_by_request(department_id, request_id)
    if existing is not None:
        if (existing.recipient_code, existing.display_name, existing.purpose) != (
            recipient_code,
            display_name,
            purpose,
        ):
            raise CollaborationConflictError("request_id 已用于不同接收方")
        return _recipient_payload(existing)
    item = CounselingExternalRecipient(
        id=uuid.uuid4().hex,
        department_id=department_id,
        recipient_code=recipient_code,
        display_name=display_name,
        purpose=purpose,
        verified_by=actor.id,
        request_id=request_id,
    )
    repository.add(item)
    await log_operation(
        db,
        actor.id,
        "counseling.external_recipient.register",
        details=json.dumps({"recipient_id": item.id}, separators=(",", ":")),
    )
    await db.commit()
    await db.refresh(item)
    return _recipient_payload(item)


async def list_external_recipients(db: AsyncSession, actor: User) -> list[dict]:
    """向管理员或同部门负责人列出已核验接收方。"""
    capabilities = resolve_business_capabilities(actor)
    if not (
        BusinessCapability.VIEW_DEPARTMENT_STUDENTS in capabilities
        or BusinessCapability.MANAGE_ASSIGNED_STUDENTS in capabilities
    ):
        raise PermissionError("需要业务管理或辅导员权限")
    if actor.department_id is None:
        raise ValueError("当前用户未绑定部门")
    rows = await CollaborationRepository(db).list_recipients(actor.department_id)
    return [_recipient_payload(item) for item in rows if item.active]


async def create_external_authorization(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    recipient_id: str,
    scopes: list[str],
    effective_from: datetime,
    expires_at: datetime,
) -> dict:
    """由负责人提出面向已核验接收方的最小外发授权。"""
    student = await _owned_student(db, actor, student_id)
    if student.status != "active":
        raise ValueError("已结束档案不能新增外发授权")
    request_id = _key(request_id)
    scopes = _normalize_scopes(scopes, EXTERNAL_SCOPES)
    effective = _utc_naive(effective_from, "生效时间")
    expires = _utc_naive(expires_at, "失效时间")
    if expires <= effective:
        raise ValueError("失效时间必须晚于生效时间")
    repository = CollaborationRepository(db)
    recipient = await repository.get_recipient(recipient_id, actor.department_id)
    if recipient is None or not recipient.active:
        raise LookupError("有效接收方不存在")
    existing = await repository.get_external_auth_by_request(actor.id, request_id)
    intent = (student_id, recipient_id, scopes, effective, expires)
    if existing is not None:
        current = (
            existing.student_id,
            existing.recipient_id,
            list(existing.scopes),
            existing.effective_from,
            existing.expires_at,
        )
        if current != intent:
            raise CollaborationConflictError("request_id 已用于不同外发授权")
        return _authorization_payload(existing)
    item = CounselingExternalAuthorization(
        id=uuid.uuid4().hex,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        recipient_id=recipient_id,
        scopes=scopes,
        effective_from=effective,
        expires_at=expires,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="external.authorization.request",
            outcome="success",
            event_metadata={"authorization_id": item.id, "recipient_id": recipient_id, "scopes": scopes},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _authorization_payload(item)


async def decide_external_authorization(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
    *,
    expected_version: int,
    decision: str,
    note: str,
) -> dict:
    """由同部门业务管理员批准或拒绝外发授权。"""
    department_id = _require_manager(actor)
    if decision not in {"approved", "rejected"}:
        raise ValueError("授权决定无效")
    note = _text(note, "决定说明", maximum=1000)
    repository = CollaborationRepository(db)
    item = await repository.get_external_auth(authorization_id, for_update=True)
    if item is None or item.department_id != department_id:
        raise LookupError("外发授权不存在")
    if item.status != "pending" or item.version != expected_version:
        raise CollaborationConflictError("外发授权状态或版本已变化")
    recipient = await repository.get_recipient(item.recipient_id, department_id)
    if recipient is None or not recipient.active:
        raise CollaborationConflictError("接收方已失效")
    now = utc_now_naive()
    item.status = "active" if decision == "approved" else "rejected"
    item.version += 1
    item.decision_note = note
    if decision == "approved":
        item.approved_by, item.approved_at = actor.id, now
    else:
        item.rejected_by, item.rejected_at = actor.id, now
    await log_operation(
        db,
        actor.id,
        f"counseling.external.authorization.{decision}",
        details=json.dumps({"authorization_id": item.id}, separators=(",", ":")),
    )
    await db.commit()
    await db.refresh(item)
    return _authorization_payload(item)


async def revoke_external_authorization(
    db: AsyncSession,
    actor: User,
    authorization_id: str,
    *,
    expected_version: int,
    note: str,
) -> dict:
    """撤回外发授权并在同一事务中关闭尚未领取的交付。"""
    note = _text(note, "撤回说明", maximum=1000)
    repository = CollaborationRepository(db)
    item = await repository.get_external_auth(authorization_id, for_update=True)
    if item is None:
        raise LookupError("外发授权不存在")
    manager = BusinessCapability.VIEW_DEPARTMENT_STUDENTS in resolve_business_capabilities(actor)
    if not ((actor.id == item.counselor_id) or (manager and actor.department_id == item.department_id)):
        raise PermissionError("无权撤回该外发授权")
    if item.status != "active" or item.version != expected_version:
        raise CollaborationConflictError("外发授权状态或版本已变化")
    now = utc_now_naive()
    item.status = "revoked"
    item.version += 1
    item.revoked_by, item.revoked_at, item.decision_note = actor.id, now, note
    for delivery in await repository.list_open_deliveries(item.id):
        delivery.status = "withdrawn"
        delivery.version += 1
        delivery.withdrawn_at = now
    db.add(
        CounselingAuditEvent(
            student_id=item.student_id,
            actor_id=actor.id,
            department_id=item.department_id,
            action="external.authorization.revoke",
            outcome="success",
            event_metadata={"authorization_id": item.id},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _authorization_payload(item)


async def list_external_authorizations(
    db: AsyncSession,
    actor: User,
    *,
    student_id: int | None = None,
) -> list[dict]:
    """按负责人或管理员范围列出外发授权。"""
    repository = CollaborationRepository(db)
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS in resolve_business_capabilities(actor):
        if student_id is None:
            raise ValueError("负责人查询必须指定学生档案")
        await _owned_student(db, actor, student_id)
        rows = await repository.list_external_auth_for_owner(student_id, actor.department_id, actor.id)
    else:
        rows = await repository.list_external_auth_for_manager(_require_manager(actor))
    return [_authorization_payload(item) for item in rows]


def _delivery_payload(item: CounselingExternalDelivery, *, token: str | None = None) -> dict:
    payload = {
        "id": item.id,
        "authorization_id": item.authorization_id,
        "scopes": list(item.scopes),
        "resource_codes": list(item.resource_codes),
        "referral_id": item.referral_id,
        "status": item.status,
        "version": item.version,
        "failed_attempts": item.failed_attempts,
        "last_error": item.last_error,
        "token_expires_at": format_utc_datetime(item.token_expires_at),
        "delivered_at": format_utc_datetime(item.delivered_at),
        "withdrawal_requested_at": format_utc_datetime(item.withdrawn_at),
        "created_at": format_utc_datetime(item.created_at),
    }
    if token is not None:
        payload["claim_token"] = token
    return payload


async def create_external_delivery(
    db: AsyncSession,
    actor: User,
    student_id: int,
    authorization_id: str,
    *,
    request_id: str,
    scopes: list[str],
    resource_codes: list[str],
    referral_id: str | None,
    token_expires_at: datetime,
) -> dict:
    """创建仅在外部领取后才成为 delivered 的一次性交付。"""
    await _owned_student(db, actor, student_id)
    request_id = _key(request_id)
    scopes = _normalize_scopes(scopes, EXTERNAL_SCOPES)
    codes = sorted(set(_text(code, "资源编号", maximum=64) for code in resource_codes))
    if len(codes) > 20 or any(not all(char.isalnum() or char in "_-" for char in code) for code in codes):
        raise ValueError("资源编号无效")
    expires = _utc_naive(token_expires_at, "领取失效时间")
    now = utc_now_naive()
    if not now < expires <= now + timedelta(days=7):
        raise ValueError("领取有效期必须在未来七天内")
    repository = CollaborationRepository(db)
    authorization = await repository.get_external_auth(authorization_id)
    if authorization is None or authorization.student_id != student_id or authorization.counselor_id != actor.id:
        raise LookupError("外发授权不存在")
    for scope in scopes:
        _active(authorization, scope, at=now)
    if not set(scopes) <= set(authorization.scopes):
        raise PermissionError("交付范围超出授权")
    if "resource_catalog" in scopes and not codes:
        raise ValueError("资源交付必须包含资源编号")
    if "resource_catalog" not in scopes and codes:
        raise ValueError("未授权资源目录范围")
    if "referral_status" in scopes:
        if referral_id is None or await repository.get_referral_for_delivery(referral_id, student_id, actor.id) is None:
            raise LookupError("可外发的转介状态不存在")
    elif referral_id is not None:
        raise ValueError("未授权转介状态范围")
    existing = await repository.get_delivery_by_request(actor.id, request_id)
    if existing is not None:
        if (
            existing.authorization_id != authorization_id
            or list(existing.scopes) != scopes
            or list(existing.resource_codes) != codes
            or existing.referral_id != referral_id
            or existing.token_expires_at != expires
        ):
            raise CollaborationConflictError("request_id 已用于不同交付")
        return _delivery_payload(existing)
    token = secrets.token_urlsafe(32)
    item = CounselingExternalDelivery(
        id=uuid.uuid4().hex,
        authorization_id=authorization_id,
        student_id=student_id,
        counselor_id=actor.id,
        recipient_id=authorization.recipient_id,
        scopes=scopes,
        resource_codes=codes,
        referral_id=referral_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_expires_at=expires,
        request_id=request_id,
    )
    repository.add(item)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="external.delivery.prepare",
            outcome="success",
            event_metadata={"delivery_id": item.id, "scopes": scopes},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _delivery_payload(item, token=token)


async def list_external_deliveries(
    db: AsyncSession,
    actor: User,
    student_id: int,
) -> list[dict]:
    """列出负责人档案的交付事实，不返回领取令牌。"""
    await _owned_student(db, actor, student_id)
    rows = await CollaborationRepository(db).list_deliveries_for_owner(student_id, actor.id)
    return [_delivery_payload(item) for item in rows]


async def redeem_external_delivery(db: AsyncSession, token: str) -> dict:
    """用一次性令牌领取最小材料，并在成功后原子记录 delivered。"""
    token = _text(token, "领取令牌", maximum=256)
    repository = CollaborationRepository(db)
    item = await repository.get_delivery_by_token(
        hashlib.sha256(token.encode()).hexdigest(),
        for_update=True,
    )
    if item is None:
        raise LookupError("交付不存在")
    if item.status != "ready":
        raise CollaborationConflictError("交付当前不可领取")
    now = utc_now_naive()
    authorization = await repository.get_external_auth(item.authorization_id)
    recipient = await repository.get_recipient(item.recipient_id, authorization.department_id)
    if (
        authorization.status != "active"
        or not authorization.effective_from <= now < authorization.expires_at
        or recipient is None
        or not recipient.active
        or item.token_expires_at <= now
    ):
        item.status = "failed"
        item.version += 1
        item.failed_attempts += 1
        item.last_error = "authorization_or_token_expired"
        db.add(
            CounselingAuditEvent(
                student_id=item.student_id,
                actor_id=item.counselor_id,
                department_id=authorization.department_id,
                action="external.delivery.claim",
                outcome="failed",
                event_metadata={"delivery_id": item.id, "reason": item.last_error},
            )
        )
        await db.commit()
        raise CollaborationConflictError("授权、接收方或领取令牌已失效")
    item.status = "delivered"
    item.version += 1
    item.delivered_at = now
    item.last_error = None
    db.add(
        CounselingAuditEvent(
            student_id=item.student_id,
            actor_id=item.counselor_id,
            department_id=authorization.department_id,
            action="external.delivery.claim",
            outcome="success",
            event_metadata={"delivery_id": item.id, "recipient_id": item.recipient_id},
        )
    )
    await db.commit()
    return {
        "delivery_id": item.id,
        "recipient": recipient.display_name,
        "scopes": list(item.scopes),
        "resource_codes": list(item.resource_codes),
        "referral_status": "authorized_referral_available" if item.referral_id else None,
        "delivered_at": format_utc_datetime(item.delivered_at),
    }


async def retry_external_delivery(
    db: AsyncSession,
    actor: User,
    delivery_id: str,
    *,
    expected_version: int,
    token_expires_at: datetime,
) -> dict:
    """由负责人为失败交付轮换一次性令牌。"""
    expires = _utc_naive(token_expires_at, "领取失效时间")
    now = utc_now_naive()
    if not now < expires <= now + timedelta(days=7):
        raise ValueError("领取有效期必须在未来七天内")
    repository = CollaborationRepository(db)
    item = await repository.get_delivery(delivery_id, for_update=True)
    if item is None or item.counselor_id != actor.id:
        raise LookupError("交付不存在")
    await _owned_student(db, actor, item.student_id)
    if item.status != "failed" or item.version != expected_version:
        raise CollaborationConflictError("交付状态或版本已变化")
    authorization = await repository.get_external_auth(item.authorization_id)
    for scope in item.scopes:
        _active(authorization, scope, at=now)
    token = secrets.token_urlsafe(32)
    item.status = "ready"
    item.version += 1
    item.token_hash = hashlib.sha256(token.encode()).hexdigest()
    item.token_expires_at = expires
    item.last_error = None
    await db.commit()
    await db.refresh(item)
    return _delivery_payload(item, token=token)


async def withdraw_external_delivery(
    db: AsyncSession,
    actor: User,
    delivery_id: str,
    *,
    expected_version: int,
) -> dict:
    """撤回未领取交付；已领取时只记录撤回请求而不伪装追回。"""
    repository = CollaborationRepository(db)
    item = await repository.get_delivery(delivery_id, for_update=True)
    if item is None:
        raise LookupError("交付不存在")
    authorization = await repository.get_external_auth(item.authorization_id)
    manager = BusinessCapability.VIEW_DEPARTMENT_STUDENTS in resolve_business_capabilities(actor)
    if not ((item.counselor_id == actor.id) or (manager and authorization.department_id == actor.department_id)):
        raise PermissionError("无权撤回该交付")
    if item.version != expected_version or item.status not in {"ready", "failed", "delivered"}:
        raise CollaborationConflictError("交付状态或版本已变化")
    item.version += 1
    item.withdrawn_at = utc_now_naive()
    if item.status in {"ready", "failed"}:
        item.status = "withdrawn"
    db.add(
        CounselingAuditEvent(
            student_id=item.student_id,
            actor_id=actor.id,
            department_id=authorization.department_id,
            action="external.delivery.withdraw",
            outcome="requested" if item.status == "delivered" else "success",
            event_metadata={"delivery_id": item.id},
        )
    )
    await db.commit()
    await db.refresh(item)
    return _delivery_payload(item)
