"""内部预约的档案隔离查询。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import CounselingAppointment


class AppointmentRepository:
    """只在负责人档案范围内维护预约。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, appointment: CounselingAppointment) -> None:
        """加入当前用例事务。"""
        self.db.add(appointment)

    async def get_by_request(self, counselor_id: int, request_id: str) -> CounselingAppointment | None:
        query = select(CounselingAppointment).where(
            CounselingAppointment.counselor_id == counselor_id,
            CounselingAppointment.request_id == request_id,
        )
        return (await self.db.execute(query)).scalar_one_or_none()

    async def get_for_owner(
        self,
        appointment_id: str,
        student_id: int,
        department_id: int,
        counselor_id: int,
        *,
        for_update: bool = False,
    ) -> CounselingAppointment | None:
        query = select(CounselingAppointment).where(
            CounselingAppointment.id == appointment_id,
            CounselingAppointment.student_id == student_id,
            CounselingAppointment.department_id == department_id,
            CounselingAppointment.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update()
        return (await self.db.execute(query)).scalar_one_or_none()

    async def list_for_owner(
        self, student_id: int, department_id: int, counselor_id: int
    ) -> list[CounselingAppointment]:
        query = (
            select(CounselingAppointment)
            .where(
                CounselingAppointment.student_id == student_id,
                CounselingAppointment.department_id == department_id,
                CounselingAppointment.counselor_id == counselor_id,
            )
            .order_by(CounselingAppointment.scheduled_start.desc(), CounselingAppointment.id.desc())
        )
        return list((await self.db.execute(query)).scalars().all())
