"""心理辅导用途告知门禁与审计回读用例。"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.utils.datetime_utils import format_utc_datetime

from counseling.governance.repository import CounselingGovernanceRepository
from counseling.identity.models import User
from counseling.identity.permissions import (
    BusinessCapability,
    resolve_business_capabilities,
)
from counseling.storage.models import CounselingDataUseAcknowledgment

CURRENT_DATA_USE_NOTICE_VERSION = "2026-10-01"
DATA_USE_NOTICE_ITEMS = (
    "仅为获准的心理辅导建档、记录、跟进和人工确认使用档案数据。",
    "业务管理员只读取部门最小元数据与聚合信息，不读取咨询正文。",
    "AI 协作必须由辅导员从具体档案主动发起，结果经人工确认后才能进入档案。",
    "系统不独立诊断、开处方或自主执行危机干预。",
    "访问动作保留不复制正文的审计事实；正式记录与更正不允许覆盖。",
)


class DataUseNoticeRequiredError(PermissionError):
    """表示当前用户尚未确认最新用途告知。"""


def _require_business_user(actor: User) -> frozenset[BusinessCapability]:
    """要求调用者持有心理辅导业务能力。"""
    capabilities = resolve_business_capabilities(actor)
    if not capabilities.intersection(
        {
            BusinessCapability.MANAGE_ASSIGNED_STUDENTS,
            BusinessCapability.VIEW_DEPARTMENT_STUDENTS,
        }
    ):
        raise PermissionError("需要心理辅导业务权限")
    if actor.department_id is None:
        raise PermissionError("业务用户必须归属部门")
    return capabilities


def _notice_payload(acknowledgment: CounselingDataUseAcknowledgment | None) -> dict:
    """装配不含用户或个案数据的告知状态。"""
    return {
        "version": CURRENT_DATA_USE_NOTICE_VERSION,
        "title": "心理辅导数据用途告知",
        "items": list(DATA_USE_NOTICE_ITEMS),
        "acknowledged": acknowledgment is not None,
        "acknowledged_at": (
            format_utc_datetime(acknowledgment.acknowledged_at)
            if acknowledgment is not None
            else None
        ),
    }


async def get_data_use_notice(db: AsyncSession, actor: User) -> dict:
    """返回当前版本告知及用户的持久确认状态。"""
    _require_business_user(actor)
    acknowledgment = await CounselingGovernanceRepository(db).get_acknowledgment(
        actor.id, CURRENT_DATA_USE_NOTICE_VERSION
    )
    return _notice_payload(acknowledgment)


async def acknowledge_data_use_notice(
    db: AsyncSession, actor: User, notice_version: str
) -> dict:
    """幂等保存用户对当前版本用途告知的确认。"""
    _require_business_user(actor)
    if notice_version != CURRENT_DATA_USE_NOTICE_VERSION:
        raise ValueError("用途告知版本已更新，请重新读取")
    repository = CounselingGovernanceRepository(db)
    existing = await repository.get_acknowledgment(actor.id, notice_version)
    if existing is not None:
        return _notice_payload(existing)
    acknowledgment = CounselingDataUseAcknowledgment(
        user_id=actor.id,
        notice_version=notice_version,
    )
    repository.add_acknowledgment(acknowledgment)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await CounselingGovernanceRepository(db).get_acknowledgment(
            actor.id, notice_version
        )
        if existing is None:
            raise
        return _notice_payload(existing)
    await db.refresh(acknowledgment)
    return _notice_payload(acknowledgment)


async def require_current_data_use_notice(db: AsyncSession, actor: User) -> None:
    """未确认当前用途告知时拒绝业务数据访问。"""
    _require_business_user(actor)
    acknowledgment = await CounselingGovernanceRepository(db).get_acknowledgment(
        actor.id, CURRENT_DATA_USE_NOTICE_VERSION
    )
    if acknowledgment is None:
        raise DataUseNoticeRequiredError("请先确认当前心理辅导数据用途告知")


async def list_audit_events(
    db: AsyncSession,
    actor: User,
    *,
    student_id: int | None,
    limit: int,
) -> list[dict]:
    """按负责人或业务管理员范围回读不含正文的审计事实。"""
    capabilities = _require_business_user(actor)
    events = await CounselingGovernanceRepository(db).list_audit_events(
        actor_id=actor.id,
        department_id=actor.department_id,
        can_view_department=(
            BusinessCapability.VIEW_DEPARTMENT_STUDENTS in capabilities
        ),
        student_id=student_id,
        limit=limit,
    )
    return [
        {
            "id": event.id,
            "student_id": event.student_id,
            "actor_id": event.actor_id,
            "action": event.action,
            "outcome": event.outcome,
            "created_at": format_utc_datetime(event.created_at),
        }
        for event in events
    ]
