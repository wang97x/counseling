"""量表施测结果的档案隔离查询。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import CounselingAssessmentResult


class AssessmentRepository:
    """只在负责人档案范围内保存和读取量表结果。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, result: CounselingAssessmentResult) -> None:
        """加入当前用例事务。"""
        self.db.add(result)

    async def get_by_request(self, counselor_id: int, request_id: str) -> CounselingAssessmentResult | None:
        """按负责人幂等键读取结果。"""
        query = select(CounselingAssessmentResult).where(
            CounselingAssessmentResult.counselor_id == counselor_id,
            CounselingAssessmentResult.request_id == request_id,
        )
        return (await self.db.execute(query)).scalar_one_or_none()

    async def list_for_owner(
        self, student_id: int, department_id: int, counselor_id: int
    ) -> list[CounselingAssessmentResult]:
        """列出本人负责档案的量表历史。"""
        query = (
            select(CounselingAssessmentResult)
            .where(
                CounselingAssessmentResult.student_id == student_id,
                CounselingAssessmentResult.department_id == department_id,
                CounselingAssessmentResult.counselor_id == counselor_id,
            )
            .order_by(
                CounselingAssessmentResult.administered_at.desc(),
                CounselingAssessmentResult.id.desc(),
            )
        )
        return list((await self.db.execute(query)).scalars().all())
