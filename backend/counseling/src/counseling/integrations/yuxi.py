"""通过 Yuxi 平台能力实现心理辅导业务端口。"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from counseling.documents.service import (
    SUMMARY_TITLES,
    CounselingGenerationError,
    validate_summary,
)
from yuxi.config.options import system_options
from yuxi.models.chat import select_model
from yuxi.services.conversation_service import create_thread_view
from counseling.identity.models import User


class YuxiConversationAdapter:
    """把档案会话请求适配为通用 Yuxi Conversation。"""

    async def create(
        self,
        *,
        db: AsyncSession,
        actor: User,
        agent_slug: str,
        request_id: str | None,
        title: str | None,
        server_metadata: dict,
    ) -> dict:
        """调用通用会话服务，不向 Yuxi 传递业务角色。"""
        return await create_thread_view(
            agent_slug=agent_slug,
            request_id=request_id,
            title=title,
            metadata=None,
            server_metadata=server_metadata,
            db=db,
            current_uid=str(actor.uid),
        )


class YuxiGenerationAdapter:
    """使用 Yuxi 当前默认模型生成业务摘要草稿。"""

    async def generate(self, db: AsyncSession, *, background: str, parsed_text: str) -> tuple[dict, str]:
        """只发送业务明确提供的背景和解析文本。"""
        model_spec = (await system_options.get(db))["default_model"]
        await db.rollback()
        model = select_model(model_spec=model_spec)
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是心理辅导文书助手。仅整理输入中明确出现的事实，不诊断、不推断风险、"
                    "不补造目标、量表或行动。只输出一个 JSON 对象，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "输出格式：{\"schema_version\":1,\"sections\":["
                    + ",".join(f'{{\"title\":\"{title}\",\"content\":\"\"}}' for title in SUMMARY_TITLES)
                    + "]}\n每个 content 使用简洁中文；材料没有的信息写“材料未提及”。\n"
                    f"<已确认背景>{background or '无'}</已确认背景>\n"
                    f"<记录文本>{parsed_text}</记录文本>"
                ),
            },
        ]
        response = await model.call(prompt)
        try:
            summary = validate_summary(json.loads(response.content))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise CounselingGenerationError("模型未返回有效的结构化摘要") from exc
        return summary, model_spec
