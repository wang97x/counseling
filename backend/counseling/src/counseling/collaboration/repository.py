"""P3 授权协作与外发的档案隔离查询。"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.identity.models import User
from counseling.storage.p3_models import (
    CounselingExternalAuthorization,
    CounselingExternalDelivery,
    CounselingExternalRecipient,
    CounselingSupervisionAuthorization,
    CounselingSupervisionFeedback,
    CounselingSupervisionMaterial,
    CounselingSupervisionSummary,
)
from counseling.storage.models import (
    CounselingAppointment,
    CounselingAssessmentResult,
    CounselingCrisisCase,
    CounselingRecord,
    CounselingReferral,
    CounselingRiskEvent,
    StudentRecord,
)


class CollaborationRepository:
    """在当前事务内执行 P3 可见性查询与持久化。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, value: object) -> None:
        """把新状态加入当前用例事务。"""
        self.db.add(value)

    async def get_supervisor(self, user_id: int, department_id: int):
        return await self.db.scalar(
            select(User).where(
                User.id == user_id,
                User.department_id == department_id,
                User.is_deleted == 0,
                func.jsonb_exists(User.business_roles, "supervisor"),
            )
        )

    async def get_supervision_auth_by_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingSupervisionAuthorization).where(
                CounselingSupervisionAuthorization.counselor_id == counselor_id,
                CounselingSupervisionAuthorization.request_id == request_id,
            )
        )

    async def get_supervision_auth(self, authorization_id: str, *, for_update: bool = False):
        query = select(CounselingSupervisionAuthorization).where(
            CounselingSupervisionAuthorization.id == authorization_id
        )
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_supervision_for_owner(self, student_id: int, department_id: int, counselor_id: int):
        rows = await self.db.execute(
            select(CounselingSupervisionAuthorization)
            .where(
                CounselingSupervisionAuthorization.student_id == student_id,
                CounselingSupervisionAuthorization.department_id == department_id,
                CounselingSupervisionAuthorization.counselor_id == counselor_id,
            )
            .order_by(CounselingSupervisionAuthorization.created_at.desc())
        )
        return list(rows.scalars().all())

    async def list_supervision_for_manager(self, department_id: int):
        rows = await self.db.execute(
            select(CounselingSupervisionAuthorization)
            .where(CounselingSupervisionAuthorization.department_id == department_id)
            .order_by(CounselingSupervisionAuthorization.created_at.desc())
        )
        return list(rows.scalars().all())

    async def list_supervision_for_supervisor(self, supervisor_id: int, department_id: int):
        rows = await self.db.execute(
            select(CounselingSupervisionAuthorization)
            .where(
                CounselingSupervisionAuthorization.supervisor_id == supervisor_id,
                CounselingSupervisionAuthorization.department_id == department_id,
            )
            .order_by(CounselingSupervisionAuthorization.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_material_by_request(self, created_by: int, request_id: str):
        return await self.db.scalar(
            select(CounselingSupervisionMaterial).where(
                CounselingSupervisionMaterial.created_by == created_by,
                CounselingSupervisionMaterial.request_id == request_id,
            )
        )

    async def next_material_version(self, authorization_id: str) -> int:
        value = await self.db.scalar(
            select(func.max(CounselingSupervisionMaterial.version_no)).where(
                CounselingSupervisionMaterial.authorization_id == authorization_id
            )
        )
        return int(value or 0) + 1

    async def get_material(self, material_id: str, authorization_id: str):
        return await self.db.scalar(
            select(CounselingSupervisionMaterial).where(
                CounselingSupervisionMaterial.id == material_id,
                CounselingSupervisionMaterial.authorization_id == authorization_id,
            )
        )

    async def list_materials(self, authorization_id: str):
        rows = await self.db.execute(
            select(CounselingSupervisionMaterial)
            .where(CounselingSupervisionMaterial.authorization_id == authorization_id)
            .order_by(CounselingSupervisionMaterial.version_no.desc())
        )
        return list(rows.scalars().all())

    async def get_feedback_by_request(self, supervisor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingSupervisionFeedback).where(
                CounselingSupervisionFeedback.supervisor_id == supervisor_id,
                CounselingSupervisionFeedback.request_id == request_id,
            )
        )

    async def list_feedback(self, authorization_id: str, material_id: str | None = None):
        query = select(CounselingSupervisionFeedback).where(
            CounselingSupervisionFeedback.authorization_id == authorization_id
        )
        if material_id is not None:
            query = query.where(CounselingSupervisionFeedback.material_id == material_id)
        rows = await self.db.execute(query.order_by(CounselingSupervisionFeedback.created_at))
        return list(rows.scalars().all())

    async def get_summary_by_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingSupervisionSummary).where(
                CounselingSupervisionSummary.counselor_id == counselor_id,
                CounselingSupervisionSummary.request_id == request_id,
            )
        )

    async def get_recipient_by_request(self, department_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingExternalRecipient).where(
                CounselingExternalRecipient.department_id == department_id,
                CounselingExternalRecipient.request_id == request_id,
            )
        )

    async def get_recipient(self, recipient_id: str, department_id: int):
        return await self.db.scalar(
            select(CounselingExternalRecipient).where(
                CounselingExternalRecipient.id == recipient_id,
                CounselingExternalRecipient.department_id == department_id,
            )
        )

    async def list_recipients(self, department_id: int):
        rows = await self.db.execute(
            select(CounselingExternalRecipient)
            .where(CounselingExternalRecipient.department_id == department_id)
            .order_by(CounselingExternalRecipient.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_external_auth_by_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingExternalAuthorization).where(
                CounselingExternalAuthorization.counselor_id == counselor_id,
                CounselingExternalAuthorization.request_id == request_id,
            )
        )

    async def get_external_auth(self, authorization_id: str, *, for_update: bool = False):
        query = select(CounselingExternalAuthorization).where(CounselingExternalAuthorization.id == authorization_id)
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_external_auth_for_owner(self, student_id: int, department_id: int, counselor_id: int):
        rows = await self.db.execute(
            select(CounselingExternalAuthorization)
            .where(
                CounselingExternalAuthorization.student_id == student_id,
                CounselingExternalAuthorization.department_id == department_id,
                CounselingExternalAuthorization.counselor_id == counselor_id,
            )
            .order_by(CounselingExternalAuthorization.created_at.desc())
        )
        return list(rows.scalars().all())

    async def list_external_auth_for_manager(self, department_id: int):
        rows = await self.db.execute(
            select(CounselingExternalAuthorization)
            .where(CounselingExternalAuthorization.department_id == department_id)
            .order_by(CounselingExternalAuthorization.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_delivery_by_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingExternalDelivery).where(
                CounselingExternalDelivery.counselor_id == counselor_id,
                CounselingExternalDelivery.request_id == request_id,
            )
        )

    async def get_delivery(self, delivery_id: str, *, for_update: bool = False):
        query = select(CounselingExternalDelivery).where(CounselingExternalDelivery.id == delivery_id)
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def get_delivery_by_token(self, token_hash: str, *, for_update: bool = False):
        query = select(CounselingExternalDelivery).where(CounselingExternalDelivery.token_hash == token_hash)
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_deliveries_for_owner(self, student_id: int, counselor_id: int):
        rows = await self.db.execute(
            select(CounselingExternalDelivery)
            .where(
                CounselingExternalDelivery.student_id == student_id,
                CounselingExternalDelivery.counselor_id == counselor_id,
            )
            .order_by(CounselingExternalDelivery.created_at.desc())
        )
        return list(rows.scalars().all())

    async def list_open_deliveries(self, authorization_id: str):
        rows = await self.db.execute(
            select(CounselingExternalDelivery)
            .where(
                CounselingExternalDelivery.authorization_id == authorization_id,
                CounselingExternalDelivery.status.in_(("ready", "failed")),
            )
            .with_for_update()
        )
        return list(rows.scalars().all())

    async def get_referral_for_delivery(self, referral_id: str, student_id: int, counselor_id: int):
        return await self.db.scalar(
            select(CounselingReferral).where(
                CounselingReferral.id == referral_id,
                CounselingReferral.student_id == student_id,
                CounselingReferral.counselor_id == counselor_id,
                CounselingReferral.status.in_(("accepted", "completed")),
            )
        )

    async def count_case_metrics(self, department_id: int, start: datetime, end: datetime) -> dict[str, int]:
        """按固定部门与时间窗返回去重个案计数。"""

        async def count(model, timestamp, *filters) -> int:
            value = await self.db.scalar(
                select(func.count(func.distinct(model.student_id))).where(
                    model.department_id == department_id,
                    timestamp >= start,
                    timestamp < end,
                    *filters,
                )
            )
            return int(value or 0)

        record_count = int(
            await self.db.scalar(
                select(func.count(func.distinct(CounselingRecord.student_id)))
                .join(StudentRecord, StudentRecord.id == CounselingRecord.student_id)
                .where(
                    StudentRecord.department_id == department_id,
                    CounselingRecord.confirmed_at >= start,
                    CounselingRecord.confirmed_at < end,
                )
            )
            or 0
        )
        cohort = int(
            await self.db.scalar(
                select(func.count(StudentRecord.id)).where(
                    StudentRecord.department_id == department_id,
                    StudentRecord.created_at < end,
                )
            )
            or 0
        )
        return {
            "cohort": cohort,
            "records": record_count,
            "assessments": await count(CounselingAssessmentResult, CounselingAssessmentResult.administered_at),
            "appointments_completed": await count(
                CounselingAppointment,
                CounselingAppointment.updated_at,
                CounselingAppointment.status == "completed",
            ),
            "risk_events": await count(CounselingRiskEvent, CounselingRiskEvent.created_at),
            "crisis_closed": await count(
                CounselingCrisisCase,
                CounselingCrisisCase.updated_at,
                CounselingCrisisCase.status == "closed",
            ),
            "referrals_completed": await count(
                CounselingReferral,
                CounselingReferral.updated_at,
                CounselingReferral.status == "completed",
            ),
        }
