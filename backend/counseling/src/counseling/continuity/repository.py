"""连续服务状态的档案隔离查询。"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from counseling.storage.models import (
    CounselingAssessmentResult,
    CounselingCrisisCase,
    CounselingCrisisCaseEvent,
    CounselingCrisisProtocol,
    CounselingPlanVersion,
    CounselingRecord,
    CounselingReferral,
    CounselingRiskEvent,
)


class ContinuityRepository:
    """在负责人或部门边界内维护 P2 持久状态。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, value: object) -> None:
        """把新状态加入当前用例事务。"""
        self.db.add(value)

    async def get_plan_by_request(self, counselor_id: int, request_id: str):
        result = await self.db.execute(
            select(CounselingPlanVersion).where(
                CounselingPlanVersion.counselor_id == counselor_id,
                CounselingPlanVersion.request_id == request_id,
            )
        )
        return result.scalar_one_or_none()

    async def next_plan_version(self, student_id: int) -> int:
        value = await self.db.scalar(
            select(func.max(CounselingPlanVersion.version_no)).where(CounselingPlanVersion.student_id == student_id)
        )
        return int(value or 0) + 1

    async def list_plans(self, student_id: int, department_id: int, counselor_id: int):
        result = await self.db.execute(
            select(CounselingPlanVersion)
            .where(
                CounselingPlanVersion.student_id == student_id,
                CounselingPlanVersion.department_id == department_id,
                CounselingPlanVersion.counselor_id == counselor_id,
            )
            .order_by(CounselingPlanVersion.version_no.desc())
        )
        return list(result.scalars().all())

    async def evidence_belongs_to_student(
        self,
        student_id: int,
        department_id: int,
        counselor_id: int,
        *,
        record_id: str | None,
        assessment_id: str | None,
    ) -> bool:
        if record_id:
            record = await self.db.scalar(
                select(CounselingRecord.id).where(
                    CounselingRecord.id == record_id,
                    CounselingRecord.student_id == student_id,
                    CounselingRecord.confirmed_by == counselor_id,
                )
            )
            if record is None:
                return False
        if assessment_id:
            assessment = await self.db.scalar(
                select(CounselingAssessmentResult.id).where(
                    CounselingAssessmentResult.id == assessment_id,
                    CounselingAssessmentResult.student_id == student_id,
                    CounselingAssessmentResult.department_id == department_id,
                    CounselingAssessmentResult.counselor_id == counselor_id,
                )
            )
            if assessment is None:
                return False
        return True

    async def get_protocol_by_request(self, department_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingCrisisProtocol).where(
                CounselingCrisisProtocol.department_id == department_id,
                CounselingCrisisProtocol.request_id == request_id,
            )
        )

    async def next_protocol_version(self, department_id: int) -> int:
        value = await self.db.scalar(
            select(func.max(CounselingCrisisProtocol.version_no)).where(
                CounselingCrisisProtocol.department_id == department_id
            )
        )
        return int(value or 0) + 1

    async def get_active_protocol(self, department_id: int, at: datetime):
        return await self.db.scalar(
            select(CounselingCrisisProtocol)
            .where(
                CounselingCrisisProtocol.department_id == department_id,
                CounselingCrisisProtocol.effective_from <= at,
                or_(CounselingCrisisProtocol.expires_at.is_(None), CounselingCrisisProtocol.expires_at > at),
            )
            .order_by(CounselingCrisisProtocol.version_no.desc())
            .limit(1)
        )

    async def list_protocols(self, department_id: int):
        result = await self.db.execute(
            select(CounselingCrisisProtocol)
            .where(CounselingCrisisProtocol.department_id == department_id)
            .order_by(CounselingCrisisProtocol.version_no.desc())
        )
        return list(result.scalars().all())

    async def get_risk_for_owner(self, risk_id: str, student_id: int, department_id: int, counselor_id: int):
        return await self.db.scalar(
            select(CounselingRiskEvent).where(
                CounselingRiskEvent.id == risk_id,
                CounselingRiskEvent.student_id == student_id,
                CounselingRiskEvent.department_id == department_id,
                CounselingRiskEvent.counselor_id == counselor_id,
            )
        )

    async def get_case_by_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingCrisisCase).where(
                CounselingCrisisCase.counselor_id == counselor_id,
                CounselingCrisisCase.request_id == request_id,
            )
        )

    async def get_case_for_owner(
        self, case_id: str, student_id: int, department_id: int, counselor_id: int, *, for_update: bool = False
    ):
        query = select(CounselingCrisisCase).where(
            CounselingCrisisCase.id == case_id,
            CounselingCrisisCase.student_id == student_id,
            CounselingCrisisCase.department_id == department_id,
            CounselingCrisisCase.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_cases(self, student_id: int, department_id: int, counselor_id: int):
        result = await self.db.execute(
            select(CounselingCrisisCase)
            .where(
                CounselingCrisisCase.student_id == student_id,
                CounselingCrisisCase.department_id == department_id,
                CounselingCrisisCase.counselor_id == counselor_id,
            )
            .order_by(CounselingCrisisCase.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_case_events(self, case_id: str):
        result = await self.db.execute(
            select(CounselingCrisisCaseEvent)
            .where(CounselingCrisisCaseEvent.case_id == case_id)
            .order_by(CounselingCrisisCaseEvent.created_at, CounselingCrisisCaseEvent.id)
        )
        return list(result.scalars().all())

    async def get_case_event_by_request(self, actor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingCrisisCaseEvent).where(
                CounselingCrisisCaseEvent.actor_id == actor_id,
                CounselingCrisisCaseEvent.request_id == request_id,
            )
        )

    async def get_referral_by_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingReferral).where(
                CounselingReferral.counselor_id == counselor_id,
                CounselingReferral.request_id == request_id,
            )
        )

    async def get_referral_for_owner(
        self, referral_id: str, student_id: int, department_id: int, counselor_id: int, *, for_update: bool = False
    ):
        query = select(CounselingReferral).where(
            CounselingReferral.id == referral_id,
            CounselingReferral.student_id == student_id,
            CounselingReferral.department_id == department_id,
            CounselingReferral.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def get_referral_for_manager(self, referral_id: str, department_id: int, *, for_update: bool = False):
        query = select(CounselingReferral).where(
            CounselingReferral.id == referral_id,
            CounselingReferral.department_id == department_id,
        )
        query = query.options(
            load_only(
                CounselingReferral.id,
                CounselingReferral.student_id,
                CounselingReferral.counselor_id,
                CounselingReferral.authorization_status,
                CounselingReferral.status,
                CounselingReferral.decision_note,
                CounselingReferral.follow_up_at,
                CounselingReferral.version,
                CounselingReferral.created_at,
            )
        )
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_referrals_for_owner(self, student_id: int, department_id: int, counselor_id: int):
        result = await self.db.execute(
            select(CounselingReferral)
            .where(
                CounselingReferral.student_id == student_id,
                CounselingReferral.department_id == department_id,
                CounselingReferral.counselor_id == counselor_id,
            )
            .order_by(CounselingReferral.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_referrals_for_manager(self, department_id: int):
        result = await self.db.execute(
            select(CounselingReferral)
            .options(
                load_only(
                    CounselingReferral.id,
                    CounselingReferral.student_id,
                    CounselingReferral.counselor_id,
                    CounselingReferral.authorization_status,
                    CounselingReferral.status,
                    CounselingReferral.decision_note,
                    CounselingReferral.follow_up_at,
                    CounselingReferral.version,
                    CounselingReferral.created_at,
                )
            )
            .where(CounselingReferral.department_id == department_id)
            .order_by(CounselingReferral.created_at.desc())
        )
        return list(result.scalars().all())
