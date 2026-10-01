"""用途告知与业务审计的持久化查询。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import (
    CounselingAuditEvent,
    CounselingDataUseAcknowledgment,
    StudentRecord,
)


class CounselingGovernanceRepository:
    """只在调用方业务可见范围内读写治理事实。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_acknowledgment(
        self, user_id: int, notice_version: str
    ) -> CounselingDataUseAcknowledgment | None:
        """读取用户对指定版本告知的确认。"""
        return await self.db.get(
            CounselingDataUseAcknowledgment,
            {"user_id": user_id, "notice_version": notice_version},
        )

    def add_acknowledgment(self, acknowledgment: CounselingDataUseAcknowledgment) -> None:
        """把不可变确认加入当前事务。"""
        self.db.add(acknowledgment)

    async def list_audit_events(
        self,
        *,
        actor_id: int,
        department_id: int,
        can_view_department: bool,
        student_id: int | None,
        limit: int,
    ) -> list[CounselingAuditEvent]:
        """按负责人或部门管理员范围读取审计事件。"""
        query = (
            select(CounselingAuditEvent)
            .join(StudentRecord, StudentRecord.id == CounselingAuditEvent.student_id)
            .where(CounselingAuditEvent.department_id == department_id)
        )
        if can_view_department:
            visibility = StudentRecord.department_id == department_id
        else:
            visibility = (
                (StudentRecord.department_id == department_id)
                & (StudentRecord.counselor_id == actor_id)
            )
        query = query.where(visibility)
        if student_id is not None:
            query = query.where(CounselingAuditEvent.student_id == student_id)
        result = await self.db.execute(
            query.order_by(
                CounselingAuditEvent.created_at.desc(),
                CounselingAuditEvent.id.desc(),
            ).limit(limit)
        )
        return list(result.scalars().all())
