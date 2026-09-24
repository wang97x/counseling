"""学生档案的归属查询与持久化边界。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import StudentRecord
from yuxi.storage.postgres.models_business import Conversation
from yuxi.utils.datetime_utils import utc_now_naive


class StudentRepository:
    """在查询条件中落实部门与负责人隔离。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_conversations(self, student_id: int, uid: str) -> list[Conversation]:
        """只列出本人创建且仍有效的学生会话。"""
        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.uid == str(uid),
                Conversation.status != "deleted",
                Conversation.extra_metadata["counseling"]["student_id"].as_integer() == student_id,
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        department_id: int,
        student_code: str,
        counselor_id: int,
        display_name: str,
        class_name: str,
    ) -> StudentRecord:
        """创建空背景的档案并等待调用方提交。"""
        record = StudentRecord(
            department_id=department_id,
            student_code=student_code,
            counselor_id=counselor_id,
            display_name=display_name,
            class_name=class_name,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def list_for_owner(self, department_id: int, counselor_id: int) -> list[StudentRecord]:
        """只读取当前负责人名下的档案。"""
        result = await self.db.execute(
            select(StudentRecord)
            .where(StudentRecord.department_id == department_id, StudentRecord.counselor_id == counselor_id)
            .order_by(StudentRecord.id)
        )
        return list(result.scalars().all())

    async def list_for_manager(self, department_id: int) -> list[StudentRecord]:
        """读取业务管理员可见的部门档案元数据。"""
        result = await self.db.execute(
            select(
                StudentRecord.id,
                StudentRecord.student_code,
                StudentRecord.counselor_id,
                StudentRecord.status,
                StudentRecord.current_risk_level,
                StudentRecord.version,
            )
            .where(StudentRecord.department_id == department_id)
            .order_by(StudentRecord.id)
        )
        return list(result.all())

    async def get_for_owner(
        self,
        student_id: int,
        department_id: int,
        counselor_id: int,
        *,
        for_update: bool = False,
    ) -> StudentRecord | None:
        """只返回负责人能读取和修改的档案。"""
        query = select(StudentRecord).where(
            StudentRecord.id == student_id,
            StudentRecord.department_id == department_id,
            StudentRecord.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_for_owner(
        self,
        student_id: int,
        department_id: int,
        counselor_id: int,
        *,
        background_summary: str | None,
        status: str | None,
        display_name: str | None,
        class_name: str | None,
        expected_version: int | None,
    ) -> StudentRecord | None:
        """持锁更新负责人名下的背景和状态。"""
        result = await self.db.execute(
            select(StudentRecord)
            .where(
                StudentRecord.id == student_id,
                StudentRecord.department_id == department_id,
                StudentRecord.counselor_id == counselor_id,
            )
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        if expected_version is not None and record.version != expected_version:
            raise RuntimeError("学生档案版本已变化")
        if record.status == "closed" and status == "active":
            raise RuntimeError("已结束档案不能通过普通编辑重新开启")
        if background_summary is not None:
            record.background_summary = background_summary
        if status is not None:
            record.status = status
        if display_name is not None:
            record.display_name = display_name
        if class_name is not None:
            record.class_name = class_name
        record.version += 1
        record.updated_at = utc_now_naive()
        await self.db.flush()
        return record

    async def close_for_owner(
        self,
        student_id: int,
        department_id: int,
        counselor_id: int,
        *,
        closure_note: str,
        expected_version: int,
    ) -> StudentRecord | None:
        """持锁结束负责人档案并保留结束说明。"""
        result = await self.db.execute(
            select(StudentRecord)
            .where(
                StudentRecord.id == student_id,
                StudentRecord.department_id == department_id,
                StudentRecord.counselor_id == counselor_id,
            )
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        if record.version != expected_version or record.status == "closed":
            raise RuntimeError("学生档案版本已变化或已经结束")
        record.status = "closed"
        record.closure_note = closure_note
        record.closed_at = utc_now_naive()
        record.version += 1
        record.updated_at = utc_now_naive()
        await self.db.flush()
        return record
