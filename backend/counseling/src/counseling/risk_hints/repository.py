"""AI 风险提示评测与人工核实的隔离查询。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.storage.models import CounselingAIWorkItem, CounselingRiskHint, CounselingRiskHintEvaluation
from yuxi.storage.postgres.models_business import AgentRun, Message


class RiskHintRepository:
    """在部门评测与负责人档案边界内维护风险提示。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, value: object) -> None:
        """把新状态加入当前用例事务。"""
        self.db.add(value)

    async def get_evaluation_by_request(self, department_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingRiskHintEvaluation).where(
                CounselingRiskHintEvaluation.department_id == department_id,
                CounselingRiskHintEvaluation.request_id == request_id,
            )
        )

    async def get_evaluation(self, evaluation_id: str, department_id: int):
        return await self.db.scalar(
            select(CounselingRiskHintEvaluation).where(
                CounselingRiskHintEvaluation.id == evaluation_id,
                CounselingRiskHintEvaluation.department_id == department_id,
            )
        )

    async def list_evaluations(self, department_id: int):
        result = await self.db.execute(
            select(CounselingRiskHintEvaluation)
            .where(CounselingRiskHintEvaluation.department_id == department_id)
            .order_by(CounselingRiskHintEvaluation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_verified_run_output(
        self, work_item_id: str, run_id: str, student_id: int, department_id: int, counselor_id: int, uid: str
    ):
        """读取当前档案协作任务中已完成 Run 的显式输出消息。"""
        result = await self.db.execute(
            select(AgentRun, Message)
            .join(
                CounselingAIWorkItem,
                CounselingAIWorkItem.conversation_thread_id == AgentRun.conversation_thread_id,
            )
            .join(Message, Message.id == AgentRun.output_message_id)
            .where(
                CounselingAIWorkItem.id == work_item_id,
                CounselingAIWorkItem.student_id == student_id,
                CounselingAIWorkItem.department_id == department_id,
                CounselingAIWorkItem.counselor_id == counselor_id,
                CounselingAIWorkItem.status == "ready",
                AgentRun.id == run_id,
                AgentRun.uid == uid,
                AgentRun.status == "completed",
                Message.run_id == run_id,
                Message.role == "assistant",
                Message.delivery_status == "complete",
            )
        )
        return result.one_or_none()

    async def get_hint_by_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingRiskHint).where(
                CounselingRiskHint.counselor_id == counselor_id,
                CounselingRiskHint.request_id == request_id,
            )
        )

    async def get_hint_by_decision_request(self, counselor_id: int, request_id: str):
        return await self.db.scalar(
            select(CounselingRiskHint).where(
                CounselingRiskHint.reviewed_by == counselor_id,
                CounselingRiskHint.decision_request_id == request_id,
            )
        )

    async def get_hint_for_owner(
        self,
        hint_id: str,
        student_id: int,
        department_id: int,
        counselor_id: int,
        *,
        for_update: bool = False,
    ):
        query = select(CounselingRiskHint).where(
            CounselingRiskHint.id == hint_id,
            CounselingRiskHint.student_id == student_id,
            CounselingRiskHint.department_id == department_id,
            CounselingRiskHint.counselor_id == counselor_id,
        )
        if for_update:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_hints(self, student_id: int, department_id: int, counselor_id: int):
        result = await self.db.execute(
            select(CounselingRiskHint)
            .where(
                CounselingRiskHint.student_id == student_id,
                CounselingRiskHint.department_id == department_id,
                CounselingRiskHint.counselor_id == counselor_id,
            )
            .order_by(CounselingRiskHint.created_at.desc())
        )
        return list(result.scalars().all())
