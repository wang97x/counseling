"""档案驱动 AI 协作、Artifact 回填与人工确认用例。"""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from pathlib import PurePosixPath
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.repositories.agent_repository import DEFAULT_AGENT_SLUG
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

from counseling.ai_work.repository import CounselingAIWorkRepository
from counseling.documents.ports import (
    CounselingObjectStorage,
    CounselingObjectStorageError,
)
from counseling.documents.repository import CounselingRecordRepository
from counseling.identity.models import User
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.risks.repository import CounselingRiskRepository
from counseling.storage.models import CounselingAIWorkItem, CounselingAuditEvent, CounselingMaterial
from counseling.students.repository import StudentRepository

MATERIAL_BUCKET = "counseling-materials"
MAX_MATERIAL_BYTES = 5 * 1024 * 1024
ALLOWED_MATERIAL_SUFFIXES = {".txt", ".md", ".docx", ".pdf"}
MATERIAL_CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class AIWorkConflictError(Exception):
    """表示幂等意图或材料状态冲突。"""


class AIWorkConversationPort(Protocol):
    """定义协作任务使用的最小 Yuxi 能力。"""

    async def create(self, *, db, actor, agent_slug, request_id, title, server_metadata) -> dict: ...

    async def project_context(
        self, *, db: AsyncSession, actor: User, thread_id: str, instruction: str, snapshot: dict
    ) -> str: ...

    async def read_artifact(self, *, db: AsyncSession, actor: User, thread_id: str, path: str) -> bytes: ...


def _require_owner(actor: User) -> None:
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")


def _stable_snapshot(student, records, corrections, risks) -> tuple[dict, str]:
    """按稳定顺序构造完整的已确认业务事实和指纹。"""
    snapshot = {
        "schema_version": 1,
        "captured_at": format_utc_datetime(utc_now_naive()),
        "student": {
            "id": student.id,
            "student_code": student.student_code,
            "display_name": student.display_name,
            "class_name": student.class_name,
            "background_summary": student.background_summary,
            "status": student.status,
            "current_risk_level": student.current_risk_level,
            "version": student.version,
            "closure_note": student.closure_note,
            "closed_at": format_utc_datetime(student.closed_at),
        },
        "formal_records": [
            {
                "id": item.id,
                "record_kind": item.record_kind,
                "consulted_at": format_utc_datetime(item.consulted_at),
                "consultation_type": item.consultation_type,
                "source_file_name": item.source_file_name,
                "source_content_type": item.source_content_type,
                "source_size": item.source_size,
                "source_sha256": item.source_sha256,
                "parsed_text": item.parsed_text,
                "summary": item.summary,
                "content": item.content,
                "confirmed_at": format_utc_datetime(item.confirmed_at),
            }
            for item in sorted(records, key=lambda value: (value.confirmed_at, value.id))
        ],
        "corrections": [
            {
                "id": item.id,
                "record_id": item.record_id,
                "reason": item.reason,
                "corrected_content": item.corrected_content,
                "created_at": format_utc_datetime(item.created_at),
            }
            for item in sorted(corrections, key=lambda value: (value.created_at, value.id))
        ],
        "risk_events": [
            {
                "id": item.id,
                "level": item.level,
                "basis": item.basis,
                "action_taken": item.action_taken,
                "status": item.status,
                "source_record_id": item.source_record_id,
                "created_at": format_utc_datetime(item.created_at),
            }
            for item in sorted(risks, key=lambda value: (value.created_at, value.id))
        ],
    }
    confirmed_facts = {key: value for key, value in snapshot.items() if key != "captured_at"}
    canonical = json.dumps(confirmed_facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return snapshot, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _work_item_payload(item: CounselingAIWorkItem) -> dict:
    return {
        "work_item_id": item.id,
        "thread_id": item.conversation_thread_id,
        "instruction": item.instruction,
        "status": item.status,
        "error_message": item.error_message,
        "context_sha256": item.context_sha256,
        "snapshot_at": item.context_snapshot.get("captured_at"),
        "route": (
            f"/agent/{item.conversation_thread_id}?student_id={item.student_id}&work_item_id={item.id}"
            if item.conversation_thread_id
            else None
        ),
    }


def _material_payload(item: CounselingMaterial) -> dict:
    return {
        "id": item.id,
        "work_item_id": item.work_item_id,
        "run_id": item.source_run_id,
        "path": item.source_artifact_path,
        "file_name": item.file_name,
        "content_type": item.content_type,
        "size": item.size,
        "sha256": item.sha256,
        "status": item.status,
        "source": "ai_generated",
        "created_at": format_utc_datetime(item.created_at),
        "confirmed_at": format_utc_datetime(item.confirmed_at),
    }


async def create_work_item(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    instruction: str,
    port: AIWorkConversationPort,
) -> dict:
    """冻结档案事实并为任务创建独立 Conversation。"""
    _require_owner(actor)
    request_id = request_id.strip()
    instruction = instruction.strip()
    if not _KEY_PATTERN.fullmatch(request_id):
        raise ValueError("request_id 格式无效")
    if not instruction:
        raise ValueError("任务说明不能为空")
    repository = CounselingAIWorkRepository(db)
    existing = await repository.get_by_request(actor.department_id, actor.id, request_id, for_update=True)
    if existing is not None:
        if existing.student_id != student_id or existing.instruction != instruction:
            raise AIWorkConflictError("request_id 已用于其他 AI 协作任务")
        work_item = existing
    else:
        # 认证读取可能已经打开 READ COMMITTED 事务；重开为一致性快照，避免多表事实混读。
        await db.rollback()
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        await db.refresh(actor)
        repository = CounselingAIWorkRepository(db)
        existing = await repository.get_by_request(actor.department_id, actor.id, request_id, for_update=True)
        if existing is not None:
            if existing.student_id != student_id or existing.instruction != instruction:
                raise AIWorkConflictError("request_id 已用于其他 AI 协作任务")
            work_item = existing
        else:
            student = await StudentRepository(db).get_for_owner(student_id, actor.department_id, actor.id)
            if student is None:
                raise LookupError("学生档案不存在")
            records = await CounselingRecordRepository(db).list_formal(student_id, actor.department_id, actor.id)
            corrections = await CounselingRecordRepository(db).list_corrections(
                student_id, actor.department_id, actor.id
            )
            risks = await CounselingRiskRepository(db).list_for_owner(student_id, actor.department_id, actor.id)
            snapshot, fingerprint = _stable_snapshot(student, records, corrections, risks)
            work_item = CounselingAIWorkItem(
                id=str(uuid.uuid4()),
                student_id=student_id,
                department_id=actor.department_id,
                counselor_id=actor.id,
                request_id=request_id,
                instruction=instruction,
                agent_slug=DEFAULT_AGENT_SLUG,
                context_snapshot=snapshot,
                context_sha256=fingerprint,
            )
            repository.add(work_item)
            try:
                await db.flush()
            except IntegrityError:
                await db.rollback()
                existing = await repository.get_by_request(actor.department_id, actor.id, request_id, for_update=True)
                if existing is None:
                    raise
                if existing.student_id != student_id or existing.instruction != instruction:
                    raise AIWorkConflictError("request_id 已用于其他 AI 协作任务")
                work_item = existing
    if (
        await StudentRepository(db).get_for_owner(
            work_item.student_id,
            actor.department_id,
            actor.id,
        )
        is None
    ):
        raise LookupError("学生档案不存在")
    try:
        if not work_item.conversation_thread_id:
            conversation = await port.create(
                db=db,
                actor=actor,
                agent_slug=DEFAULT_AGENT_SLUG,
                request_id=f"counseling-ai-{work_item.id}",
                title=f"{work_item.context_snapshot['student']['student_code']} · AI 协助",
                server_metadata={
                    "counseling": {
                        "student_id": student_id,
                        "student_code": work_item.context_snapshot["student"]["student_code"],
                        "work_item_id": work_item.id,
                        "instruction": instruction,
                        "context_sha256": work_item.context_sha256,
                        "snapshot_at": work_item.context_snapshot["captured_at"],
                        "context_scope": [
                            "学生信息、背景、状态、当前风险、结束说明",
                            "全部正式咨询记录、追加更正和人工风险事件",
                        ],
                        "return_route": f"/counseling/students/{student_id}",
                    }
                },
            )
            work_item.conversation_thread_id = conversation["id"]
            await db.commit()
        work_item.context_path = await port.project_context(
            db=db,
            actor=actor,
            thread_id=work_item.conversation_thread_id,
            instruction=instruction,
            snapshot=work_item.context_snapshot,
        )
        work_item.status = "ready"
        work_item.error_message = None
        db.add(
            CounselingAuditEvent(
                student_id=student_id,
                actor_id=actor.id,
                department_id=actor.department_id,
                action="ai_work.create",
                outcome="success",
                event_metadata={"work_item_id": work_item.id},
            )
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        persisted = await repository.get_by_request(actor.department_id, actor.id, request_id)
        if persisted is not None:
            persisted.status = "failed"
            persisted.error_message = str(exc)[:2000]
            await db.commit()
        raise
    return _work_item_payload(work_item)


def _validate_material_bytes(file_name: str, data: bytes) -> tuple[str, str]:
    """重新校验扩展名、签名、文本编码与 DOCX 解压边界。"""
    if not data or len(data) > MAX_MATERIAL_BYTES:
        raise ValueError("材料为空或超过 5 MB")
    name = PurePosixPath(file_name).name
    if name != file_name or any(ord(char) < 32 for char in name):
        raise ValueError("文件名不安全")
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in ALLOWED_MATERIAL_SUFFIXES:
        raise ValueError("仅支持 TXT、Markdown、DOCX 和 PDF")
    if suffix in {".txt", ".md"}:
        data.decode("utf-8")
    elif suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("PDF 文件签名无效")
    elif suffix == ".docx":
        if not data.startswith(b"PK"):
            raise ValueError("DOCX 文件签名无效")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 1000 or "[Content_Types].xml" not in archive.namelist():
                    raise ValueError("DOCX 结构无效")
                if sum(entry.file_size for entry in entries) > 50 * 1024 * 1024:
                    raise ValueError("DOCX 解压后过大")
                if any(entry.flag_bits & 0x1 for entry in entries):
                    raise ValueError("不支持加密 DOCX")
        except zipfile.BadZipFile as exc:
            raise ValueError("DOCX 文件签名无效") from exc
    return name, MATERIAL_CONTENT_TYPES[suffix]


async def preflight_material(
    db: AsyncSession,
    actor: User,
    student_id: int,
    work_item_id: str,
    *,
    run_id: str,
    path: str,
    port: AIWorkConversationPort,
) -> dict:
    """只读校验回填来源并返回服务端识别的文件元数据。"""
    _require_owner(actor)
    repository = CounselingAIWorkRepository(db)
    work_item = await repository.get_work_item(work_item_id, student_id, actor.department_id, actor.id)
    if work_item is None or work_item.status != "ready" or not work_item.conversation_thread_id:
        raise LookupError("AI 协作任务不存在或尚未就绪")
    await repository.require_presented_artifact(work_item.conversation_thread_id, actor.uid, run_id, path)
    data = await port.read_artifact(
        db=db,
        actor=actor,
        thread_id=work_item.conversation_thread_id,
        path=path,
    )
    file_name, content_type = _validate_material_bytes(PurePosixPath(path).name, data)
    return {
        "file_name": file_name,
        "content_type": content_type,
        "size": len(data),
    }


async def import_material(
    db: AsyncSession,
    actor: User,
    student_id: int,
    work_item_id: str,
    *,
    request_id: str,
    run_id: str,
    path: str,
    port: AIWorkConversationPort,
    storage: CounselingObjectStorage,
) -> dict:
    """从已完成 Run 的成功展示路径有界复制材料。"""
    _require_owner(actor)
    if not _KEY_PATTERN.fullmatch(request_id.strip()):
        raise ValueError("request_id 格式无效")
    if (
        await StudentRepository(db).get_for_owner(
            student_id,
            actor.department_id,
            actor.id,
            for_update=True,
        )
        is None
    ):
        raise LookupError("学生档案不存在")
    repository = CounselingAIWorkRepository(db)
    existing = await repository.get_material_by_request(
        actor.department_id, actor.id, request_id
    )
    if existing is not None:
        if (
            existing.work_item_id != work_item_id
            or existing.source_run_id != run_id
            or existing.source_artifact_path != path
        ):
            raise AIWorkConflictError("request_id 已用于其他材料导入")
        if existing.status != "importing":
            return _material_payload(existing)
    work_item = await repository.get_work_item(work_item_id, student_id, actor.department_id, actor.id, for_update=True)
    if work_item is None or work_item.status != "ready" or not work_item.conversation_thread_id:
        raise LookupError("AI 协作任务不存在或尚未就绪")
    source_existing = await repository.get_material_by_source(
        work_item_id, run_id, path, actor.department_id, actor.id
    )
    if source_existing is not None and source_existing.status != "importing":
        return _material_payload(source_existing)
    await repository.require_presented_artifact(work_item.conversation_thread_id, actor.uid, run_id, path)
    data = await port.read_artifact(db=db, actor=actor, thread_id=work_item.conversation_thread_id, path=path)
    file_name, content_type = _validate_material_bytes(PurePosixPath(path).name, data)
    digest = hashlib.sha256(data).hexdigest()
    material_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{work_item_id}:{run_id}:{path}"))
    object_name = f"counseling/{actor.uid}/{student_id}/materials/{material_id}/{file_name}"
    if source_existing is None:
        material = CounselingMaterial(
            id=material_id,
            student_id=student_id,
            department_id=actor.department_id,
            counselor_id=actor.id,
            work_item_id=work_item_id,
            source_thread_id=work_item.conversation_thread_id,
            source_run_id=run_id,
            source_artifact_path=path,
            import_request_id=request_id,
            file_name=file_name,
            content_type=content_type,
            size=len(data),
            sha256=digest,
            bucket=MATERIAL_BUCKET,
            object_name=object_name,
            status="importing",
        )
        repository.add(material)
        try:
            # 上传前先发布可恢复意图；任何已写对象始终有 PostgreSQL Owner。
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            recovered = await repository.get_material_by_source(
                work_item_id, run_id, path, actor.department_id, actor.id
            )
            if recovered is None:
                raise AIWorkConflictError("材料导入幂等键已被其他请求使用") from exc
            if recovered.status != "importing":
                return _material_payload(recovered)
        except Exception:
            await db.rollback()
            raise

    if (
        await StudentRepository(db).get_for_owner(
            student_id,
            actor.department_id,
            actor.id,
            for_update=True,
        )
        is None
    ):
        raise LookupError("学生档案不存在")
    material = await repository.get_material_by_source(
        work_item_id,
        run_id,
        path,
        actor.department_id,
        actor.id,
        for_update=True,
    )
    if material is None:
        raise AIWorkConflictError("材料导入意图不存在")
    if material.status != "importing":
        return _material_payload(material)
    material.file_name = file_name
    material.content_type = content_type
    material.size = len(data)
    material.sha256 = digest
    material.object_name = object_name
    try:
        await storage.upload(MATERIAL_BUCKET, object_name, data, content_type)
    except Exception:
        await db.rollback()
        raise
    material.status = "pending_review"
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="material.import",
            outcome="success",
            event_metadata={"material_id": material_id, "work_item_id": work_item_id, "run_id": run_id},
        )
    )
    try:
        await db.commit()
    except Exception:
        # importing 行已在上传前提交；回滚仅撤销状态跃迁，同来源重试会接管已知对象。
        await db.rollback()
        raise
    return _material_payload(material)


async def list_materials(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出本人档案的待整理和正式材料。"""
    _require_owner(actor)
    if await StudentRepository(db).get_for_owner(student_id, actor.department_id, actor.id) is None:
        raise LookupError("学生档案不存在")
    items = await CounselingAIWorkRepository(db).list_materials(student_id, actor.department_id, actor.id)
    payloads = [_material_payload(item) for item in items]
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="material.list",
            outcome="success",
            event_metadata={"count": len(items)},
        )
    )
    await db.commit()
    return payloads


async def get_material_content(
    db: AsyncSession, actor: User, student_id: int, material_id: str, storage: CounselingObjectStorage
) -> tuple[CounselingMaterial, bytes]:
    """鉴权后读取材料对象。"""
    _require_owner(actor)
    item = await CounselingAIWorkRepository(db).get_material(material_id, student_id, actor.department_id, actor.id)
    if item is None or item.status not in {"pending_review", "active"}:
        raise LookupError("材料不存在")
    data = await storage.download(item.bucket, item.object_name)
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="material.content.read",
            outcome="success",
            event_metadata={"material_id": material_id},
        )
    )
    await db.commit()
    return item, data


async def confirm_material(
    db: AsyncSession,
    actor: User,
    student_id: int,
    material_id: str,
    confirmation_key: str,
    storage: CounselingObjectStorage,
) -> dict:
    """幂等确认材料进入档案材料列表。"""
    _require_owner(actor)
    if not _KEY_PATTERN.fullmatch(confirmation_key.strip()):
        raise ValueError("confirmation_key 格式无效")
    if (
        await StudentRepository(db).get_for_owner(
            student_id,
            actor.department_id,
            actor.id,
            for_update=True,
        )
        is None
    ):
        raise LookupError("学生档案不存在")
    item = await CounselingAIWorkRepository(db).get_material(
        material_id, student_id, actor.department_id, actor.id, for_update=True
    )
    if item is None:
        raise LookupError("材料不存在")
    if item.status == "active" and item.confirmation_key == confirmation_key:
        return _material_payload(item)
    if item.status != "pending_review":
        raise AIWorkConflictError("材料已完成审核")
    try:
        data = await storage.download(item.bucket, item.object_name)
    except CounselingObjectStorageError as exc:
        raise AIWorkConflictError("材料对象缺失或暂时不可读取") from exc
    if len(data) != item.size or hashlib.sha256(data).hexdigest() != item.sha256:
        raise AIWorkConflictError("材料对象缺失或完整性校验失败")

    item.status = "active"
    item.confirmed_by = actor.id
    item.confirmation_key = confirmation_key
    item.confirmed_at = utc_now_naive()
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="material.confirm",
            outcome="success",
            event_metadata={"material_id": material_id},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AIWorkConflictError("confirmation_key 已用于其他材料") from exc
    return _material_payload(item)


async def reject_material(db: AsyncSession, actor: User, student_id: int, material_id: str, request_id: str) -> dict:
    """幂等拒绝材料并保留对象供审计策略处理。"""
    _require_owner(actor)
    if not _KEY_PATTERN.fullmatch(request_id.strip()):
        raise ValueError("request_id 格式无效")
    if (
        await StudentRepository(db).get_for_owner(
            student_id,
            actor.department_id,
            actor.id,
            for_update=True,
        )
        is None
    ):
        raise LookupError("学生档案不存在")
    item = await CounselingAIWorkRepository(db).get_material(
        material_id, student_id, actor.department_id, actor.id, for_update=True
    )
    if item is None:
        raise LookupError("材料不存在")
    if item.status == "rejected" and item.rejection_request_id == request_id:
        return _material_payload(item)
    if item.status != "pending_review":
        raise AIWorkConflictError("材料已完成审核")
    item.status = "rejected"
    item.rejected_by = actor.id
    item.rejection_request_id = request_id
    item.rejected_at = utc_now_naive()
    db.add(
        CounselingAuditEvent(
            student_id=student_id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="material.reject",
            outcome="success",
            event_metadata={"material_id": material_id},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AIWorkConflictError("request_id 已用于其他材料拒绝") from exc
    return _material_payload(item)
