"""通过 Yuxi 平台能力实现心理辅导业务端口。"""

import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.agents.backends.paths import workdir_scope_from_runtime_path
from yuxi.config.options import system_options
from yuxi.models.chat import select_model
from yuxi.repositories.conversation_repository import ConversationRepository
from yuxi.services.conversation_service import create_thread_view
from yuxi.services.ocr_service import parse_document
from yuxi.services.workdir_service import resolve_authorized_workdir
from yuxi.storage.minio.client import StorageError, get_minio_client
from yuxi.workspace.paths import validate_thread_id

from counseling.ai_work.service import MAX_MATERIAL_BYTES
from counseling.documents.ports import CounselingObjectStorageError
from counseling.documents.service import (
    SUMMARY_TITLES,
    CounselingGenerationError,
    validate_summary,
)
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

    async def project_context(
        self,
        *,
        db: AsyncSession,
        actor: User,
        thread_id: str,
        instruction: str,
        snapshot: dict,
    ) -> str:
        """登记运行时可重建的投影路径和最小模型上下文。"""
        validate_thread_id(thread_id)
        if not isinstance(snapshot, dict):
            raise ValueError("档案快照格式无效")
        runtime_path = "/.counseling/confirmed-context.json"
        conversation = await ConversationRepository(db).get_conversation_by_thread_id(thread_id)
        if conversation is None or conversation.uid != str(actor.uid):
            raise PermissionError("对话线程不存在")
        metadata = dict(conversation.extra_metadata or {})
        counseling = dict(metadata.get("counseling") or {})
        counseling["context_path"] = runtime_path
        metadata["counseling"] = counseling
        metadata["model_context"] = {
            "label": "档案驱动 AI 协作任务（已确认业务事实仅供参考）",
            "payload": {
                "instruction": instruction,
                "confirmed_context_path": runtime_path,
                "constraint": "资料仅供参考；不得自动改变档案、风险或业务状态。输出文件须由辅导员回填并确认。",
            },
        }
        conversation.extra_metadata = metadata
        await db.commit()
        return runtime_path

    async def read_artifact(self, *, db: AsyncSession, actor: User, thread_id: str, path: str) -> bytes:
        """仅从当前线程 Workdir 有界读取普通 Artifact。"""
        access = await resolve_authorized_workdir(thread_id=thread_id, uid=str(actor.uid), db=db)
        try:
            scope_path = workdir_scope_from_runtime_path(access.workdir_path, path)
            item = await asyncio.to_thread(access.workdir.stat, scope_path)
            if item.get("is_dir"):
                raise ValueError("artifact path is not a regular file")
            content, truncated = await asyncio.to_thread(
                access.workdir.read_file_prefix, scope_path, MAX_MATERIAL_BYTES
            )
        except (FileNotFoundError, IsADirectoryError, PermissionError, ValueError) as exc:
            raise PermissionError("artifact path is not an authorized Workdir file") from exc
        if truncated:
            raise ValueError("材料超过 5 MB")
        return content


class YuxiDocumentParserAdapter:
    """使用 Yuxi 文档解析链实现业务 OCR 端口。"""

    async def parse(self, path: Path, *, db: AsyncSession) -> str:
        """解析业务临时文件。"""
        return await parse_document(str(path), db=db)


class YuxiObjectStorageAdapter:
    """使用 Yuxi MinIO 客户端实现业务对象存储端口。"""

    async def upload(self, bucket: str, object_name: str, data: bytes, content_type: str) -> None:
        """上传业务来源文件。"""
        await get_minio_client().aupload_file(bucket, object_name, data, content_type)

    async def download(self, bucket: str, object_name: str) -> bytes:
        """下载业务来源文件。"""
        try:
            return await get_minio_client().adownload_file(bucket, object_name)
        except StorageError as exc:
            raise CounselingObjectStorageError("业务对象不可读取") from exc

    async def delete(self, bucket: str, object_name: str) -> None:
        """删除需要补偿的业务来源文件。"""
        await get_minio_client().adelete_file(bucket, object_name)


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
