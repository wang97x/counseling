"""人工风险事件的归属查询。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import CounselingRiskEvent


class CounselingRiskRepository:
    """只在负责人档案范围内持久化风险事件。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, event: CounselingRiskEvent) -> None:
        """把风险事件加入当前用例事务。"""
        self.db.add(event)

    async def get_by_request(self, counselor_id: int, request_id: str) -> CounselingRiskEvent | None:
        """按负责人幂等键读取已创建风险事件。"""
        result = await self.db.execute(
            select(CounselingRiskEvent).where(
                CounselingRiskEvent.counselor_id == counselor_id,
                CounselingRiskEvent.request_id == request_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_owner(
        self, student_id: int, department_id: int, counselor_id: int
    ) -> list[CounselingRiskEvent]:
        """列出负责人档案的人工风险历史。"""
        result = await self.db.execute(
            select(CounselingRiskEvent)
            .where(
                CounselingRiskEvent.student_id == student_id,
                CounselingRiskEvent.department_id == department_id,
                CounselingRiskEvent.counselor_id == counselor_id,
            )
            .order_by(CounselingRiskEvent.created_at.desc(), CounselingRiskEvent.id.desc())
        )
        return list(result.scalars().all())
