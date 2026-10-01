"""AI 协作任务和材料的归属查询。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.storage.postgres.models_business import AgentRun, Conversation, Message, ToolCall

from counseling.storage.models import CounselingAIWorkItem, CounselingMaterial, StudentRecord


class CounselingAIWorkRepository:
    """在查询条件中强制限定学生、部门和负责人。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, item) -> None:
        """加入当前用例事务。"""
        self.db.add(item)

    async def get_by_request(
        self,
        department_id: int,
        counselor_id: int,
        request_id: str,
        *,
        for_update: bool = False,
    ) -> CounselingAIWorkItem | None:
        """按当前学生归属和创建幂等键读取任务。"""
        query = (
            select(CounselingAIWorkItem)
            .join(StudentRecord, StudentRecord.id == CounselingAIWorkItem.student_id)
            .where(
                CounselingAIWorkItem.department_id == department_id,
                CounselingAIWorkItem.counselor_id == counselor_id,
                CounselingAIWorkItem.request_id == request_id,
                StudentRecord.department_id == department_id,
                StudentRecord.counselor_id == counselor_id,
            )
        )
        if for_update:
            query = query.with_for_update(of=CounselingAIWorkItem)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_work_item(
        self, work_item_id: str, student_id: int, department_id: int, counselor_id: int, *, for_update: bool = False
    ) -> CounselingAIWorkItem | None:
        """读取负责人当前学生的协作任务。"""
        query = select(CounselingAIWorkItem).join(
            StudentRecord, StudentRecord.id == CounselingAIWorkItem.student_id
        ).where(
            CounselingAIWorkItem.id == work_item_id,
            CounselingAIWorkItem.student_id == student_id,
            CounselingAIWorkItem.department_id == department_id,
            CounselingAIWorkItem.counselor_id == counselor_id,
            StudentRecord.department_id == department_id,
            StudentRecord.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update(of=CounselingAIWorkItem)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_material_by_request(
        self, department_id: int, counselor_id: int, request_id: str
    ) -> CounselingMaterial | None:
        """按当前学生归属和导入幂等键读取材料。"""
        result = await self.db.execute(
            select(CounselingMaterial)
            .join(StudentRecord, StudentRecord.id == CounselingMaterial.student_id)
            .where(
                CounselingMaterial.department_id == department_id,
                CounselingMaterial.counselor_id == counselor_id,
                CounselingMaterial.import_request_id == request_id,
                StudentRecord.department_id == department_id,
                StudentRecord.counselor_id == counselor_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_material_by_source(
        self, work_item_id: str, run_id: str, path: str, department_id: int, counselor_id: int,
        *, for_update: bool = False
    ) -> CounselingMaterial | None:
        """按当前学生归属和指定 Run 已展示路径读取唯一材料。"""
        query = select(CounselingMaterial).join(
            StudentRecord, StudentRecord.id == CounselingMaterial.student_id
        ).where(
            CounselingMaterial.department_id == department_id,
            CounselingMaterial.counselor_id == counselor_id,
            StudentRecord.department_id == department_id,
            StudentRecord.counselor_id == counselor_id,
            CounselingMaterial.work_item_id == work_item_id,
            CounselingMaterial.source_run_id == run_id,
            CounselingMaterial.source_artifact_path == path,
        )
        if for_update:
            query = query.with_for_update(of=CounselingMaterial)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_materials(self, student_id: int, department_id: int, counselor_id: int) -> list[CounselingMaterial]:
        """列出本人档案的待整理和已确认材料。"""
        result = await self.db.execute(
            select(CounselingMaterial)
            .join(StudentRecord, StudentRecord.id == CounselingMaterial.student_id)
            .where(
                CounselingMaterial.student_id == student_id,
                StudentRecord.department_id == department_id,
                StudentRecord.counselor_id == counselor_id,
                CounselingMaterial.department_id == department_id,
                CounselingMaterial.counselor_id == counselor_id,
                CounselingMaterial.status.in_(("pending_review", "active")),
            )
            .order_by(CounselingMaterial.created_at.desc(), CounselingMaterial.id.desc())
        )
        return list(result.scalars().all())

    async def get_material(
        self, material_id: str, student_id: int, department_id: int, counselor_id: int, *, for_update: bool = False
    ) -> CounselingMaterial | None:
        """读取或持锁读取负责人名下材料。"""
        query = select(CounselingMaterial).join(
            StudentRecord, StudentRecord.id == CounselingMaterial.student_id
        ).where(
            StudentRecord.department_id == department_id,
            StudentRecord.counselor_id == counselor_id,
            CounselingMaterial.id == material_id,
            CounselingMaterial.student_id == student_id,
            CounselingMaterial.department_id == department_id,
            CounselingMaterial.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update(of=CounselingMaterial)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def require_presented_artifact(self, thread_id: str, uid: str, run_id: str, path: str) -> None:
        """要求完成 Run 的成功 present_artifacts 精确登记了路径。"""
        result = await self.db.execute(
            select(ToolCall.tool_input)
            .join(Message, Message.id == ToolCall.message_id)
            .join(AgentRun, AgentRun.id == Message.run_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                AgentRun.id == run_id,
                AgentRun.conversation_thread_id == thread_id,
                AgentRun.uid == str(uid),
                AgentRun.status == "completed",
                Conversation.thread_id == thread_id,
                Conversation.uid == str(uid),
                ToolCall.tool_name == "present_artifacts",
                ToolCall.status == "success",
            )
        )
        inputs = [item or {} for item in result.scalars().all()]
        if not any(path in list(item.get("filepaths") or []) for item in inputs):
            raise PermissionError("该文件未由指定 Run 成功展示")
