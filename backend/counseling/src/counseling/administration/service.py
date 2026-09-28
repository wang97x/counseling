"""业务管理员最小聚合统计。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import CounselingRecord, CounselingRecordDraft, CounselingRiskEvent, StudentRecord
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.identity.models import User


async def get_department_summary(db: AsyncSession, actor: User) -> dict:
    """只返回本部门计数，不读取或返回个案正文。"""
    if BusinessCapability.VIEW_DEPARTMENT_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要业务管理权限")
    if actor.department_id is None:
        raise ValueError("当前用户未绑定部门")

    status_rows = await db.execute(
        select(StudentRecord.status, func.count(StudentRecord.id))
        .where(StudentRecord.department_id == actor.department_id)
        .group_by(StudentRecord.status)
    )
    risk_rows = await db.execute(
        select(StudentRecord.current_risk_level, func.count(StudentRecord.id))
        .where(StudentRecord.department_id == actor.department_id)
        .group_by(StudentRecord.current_risk_level)
    )
    consultation_count = await db.scalar(
        select(func.count(CounselingRecord.id))
        .join(CounselingRecordDraft, CounselingRecordDraft.id == CounselingRecord.draft_id)
        .where(CounselingRecordDraft.department_id == actor.department_id)
    )
    latest_risk = (
        select(
            CounselingRiskEvent.student_id,
            CounselingRiskEvent.status,
            func.row_number()
            .over(
                partition_by=CounselingRiskEvent.student_id,
                order_by=(CounselingRiskEvent.created_at.desc(), CounselingRiskEvent.id.desc()),
            )
            .label("position"),
        )
        .where(CounselingRiskEvent.department_id == actor.department_id)
        .subquery()
    )
    open_risk_count = await db.scalar(
        select(func.count()).select_from(latest_risk).where(
            latest_risk.c.position == 1,
            latest_risk.c.status != "closed",
        )
    )
    status_counts = {str(status): int(count) for status, count in status_rows}
    risk_counts = {str(level): int(count) for level, count in risk_rows}
    return {
        "student_count": sum(status_counts.values()),
        "student_status_counts": status_counts,
        "risk_level_counts": risk_counts,
        "confirmed_record_count": int(consultation_count or 0),
        "open_risk_event_count": int(open_risk_count or 0),
    }
