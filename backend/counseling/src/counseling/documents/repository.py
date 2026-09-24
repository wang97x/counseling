"""辅导记录草稿、修订与正式归档的持久化边界。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import (
    CounselingAuditEvent,
    CounselingRecord,
    CounselingRecordCorrection,
    CounselingRecordDraft,
    CounselingRecordRevision,
)


class CounselingRecordRepository:
    """在所有内容查询中同时限定部门、负责人和学生。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, item) -> None:
        """把新记录加入当前用例事务。"""
        self.db.add(item)

    async def get_draft_by_request(
        self, counselor_id: int, upload_request_id: str
    ) -> CounselingRecordDraft | None:
        """按负责人和上传幂等键读取草稿。"""
        result = await self.db.execute(
            select(CounselingRecordDraft).where(
                CounselingRecordDraft.counselor_id == counselor_id,
                CounselingRecordDraft.upload_request_id == upload_request_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_drafts(
        self, student_id: int, department_id: int, counselor_id: int
    ) -> list[CounselingRecordDraft]:
        """列出负责人当前学生的全部草稿。"""
        result = await self.db.execute(
            select(CounselingRecordDraft)
            .where(
                CounselingRecordDraft.student_id == student_id,
                CounselingRecordDraft.department_id == department_id,
                CounselingRecordDraft.counselor_id == counselor_id,
            )
            .order_by(CounselingRecordDraft.created_at.desc(), CounselingRecordDraft.id.desc())
        )
        return list(result.scalars().all())

    async def get_draft(
        self,
        draft_id: str,
        student_id: int,
        department_id: int,
        counselor_id: int,
        *,
        for_update: bool = False,
    ) -> CounselingRecordDraft | None:
        """读取或持锁读取负责人名下的指定草稿。"""
        query = select(CounselingRecordDraft).where(
            CounselingRecordDraft.id == draft_id,
            CounselingRecordDraft.student_id == student_id,
            CounselingRecordDraft.department_id == department_id,
            CounselingRecordDraft.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def latest_revision(self, draft: CounselingRecordDraft) -> CounselingRecordRevision:
        """读取草稿声明的当前修订，缺失时显式失败。"""
        result = await self.db.execute(
            select(CounselingRecordRevision).where(
                CounselingRecordRevision.draft_id == draft.id,
                CounselingRecordRevision.revision_no == draft.current_revision,
            )
        )
        revision = result.scalar_one_or_none()
        if revision is None:
            raise RuntimeError("辅导记录草稿缺少当前修订")
        return revision

    async def formal_for_draft(self, draft_id: str) -> CounselingRecord | None:
        """按来源草稿读取唯一正式记录。"""
        result = await self.db.execute(select(CounselingRecord).where(CounselingRecord.draft_id == draft_id))
        return result.scalar_one_or_none()

    async def list_formal(
        self, student_id: int, department_id: int, counselor_id: int
    ) -> list[CounselingRecord]:
        """仅列出负责人当前学生的正式记录。"""
        result = await self.db.execute(
            select(CounselingRecord)
            .join(CounselingRecordDraft, CounselingRecordDraft.id == CounselingRecord.draft_id)
            .where(
                CounselingRecord.student_id == student_id,
                CounselingRecordDraft.department_id == department_id,
                CounselingRecordDraft.counselor_id == counselor_id,
            )
            .order_by(CounselingRecord.confirmed_at.desc(), CounselingRecord.id.desc())
        )
        return list(result.scalars().all())

    async def get_formal(
        self, record_id: str, student_id: int, department_id: int, counselor_id: int
    ) -> CounselingRecord | None:
        """按档案归属读取正式记录。"""
        result = await self.db.execute(
            select(CounselingRecord)
            .join(CounselingRecordDraft, CounselingRecordDraft.id == CounselingRecord.draft_id)
            .where(
                CounselingRecord.id == record_id,
                CounselingRecord.student_id == student_id,
                CounselingRecordDraft.department_id == department_id,
                CounselingRecordDraft.counselor_id == counselor_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_corrections(
        self, student_id: int, department_id: int, counselor_id: int
    ) -> list[CounselingRecordCorrection]:
        """列出负责人档案的追加更正。"""
        result = await self.db.execute(
            select(CounselingRecordCorrection)
            .join(CounselingRecord, CounselingRecord.id == CounselingRecordCorrection.record_id)
            .join(CounselingRecordDraft, CounselingRecordDraft.id == CounselingRecord.draft_id)
            .where(
                CounselingRecordCorrection.student_id == student_id,
                CounselingRecordDraft.department_id == department_id,
                CounselingRecordDraft.counselor_id == counselor_id,
            )
            .order_by(CounselingRecordCorrection.created_at.desc(), CounselingRecordCorrection.id.desc())
        )
        return list(result.scalars().all())

    async def get_correction_by_request(
        self, created_by: int, request_id: str
    ) -> CounselingRecordCorrection | None:
        """按操作者幂等键读取已追加更正。"""
        result = await self.db.execute(
            select(CounselingRecordCorrection).where(
                CounselingRecordCorrection.created_by == created_by,
                CounselingRecordCorrection.request_id == request_id,
            )
        )
        return result.scalar_one_or_none()

    def audit(
        self,
        *,
        student_id: int,
        draft_id: str | None,
        record_id: str | None,
        actor_id: int,
        department_id: int,
        action: str,
        outcome: str = "success",
        metadata: dict | None = None,
    ) -> None:
        """在同一事务中追加不含正文的审计事件。"""
        self.db.add(
            CounselingAuditEvent(
                student_id=student_id,
                draft_id=draft_id,
                record_id=record_id,
                actor_id=actor_id,
                department_id=department_id,
                action=action,
                outcome=outcome,
                event_metadata=metadata or {},
            )
        )
