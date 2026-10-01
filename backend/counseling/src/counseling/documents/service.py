"""辅导记录上传、生成、审阅和确认归档用例。"""

from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from counseling.appointments.repository import AppointmentRepository
from counseling.assessments.repository import AssessmentRepository
from sqlalchemy.ext.asyncio import AsyncSession

from counseling.documents.ports import CounselingDocumentParser, CounselingObjectStorage
from counseling.documents.repository import CounselingRecordRepository
from counseling.risks.repository import CounselingRiskRepository
from counseling.storage.models import (
    CounselingRecord,
    CounselingRecordCorrection,
    CounselingRecordDraft,
    CounselingRecordRevision,
)
from counseling.students.repository import StudentRepository
from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from counseling.identity.models import User
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive
from yuxi.utils.upload_utils import read_upload_with_limit

RECORD_BUCKET = "counseling-records"
MAX_RECORD_FILE_BYTES = 5 * 1024 * 1024
MAX_PARSED_TEXT_CHARS = 120_000
ALLOWED_RECORD_SUFFIXES = {".txt", ".docx", ".pdf"}
SUMMARY_TITLES = ("会谈概述", "关键内容", "辅导员观察", "已讨论行动", "后续计划")
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class CounselingConflictError(Exception):
    """表示版本、状态或幂等意图冲突。"""


class CounselingGenerationError(Exception):
    """表示模型调用或模型输出无法形成合规草稿。"""


class SummarySection(BaseModel):
    """通用摘要中的一个人工可编辑段落。"""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=32)
    content: str = Field(max_length=10_000)


class SummaryDocument(BaseModel):
    """P0 通用摘要的稳定结构。"""

    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(1, ge=1, le=1)
    sections: list[SummarySection] = Field(min_length=1, max_length=5)


class ConsultationContent(BaseModel):
    """人工咨询记录的最小稳定字段。"""

    model_config = ConfigDict(extra="forbid")
    overview: str = Field(min_length=1, max_length=10_000)
    observation: str = Field(default="", max_length=10_000)
    action_taken: str = Field(default="", max_length=10_000)
    next_plan: str = Field(default="", max_length=10_000)
    risk_notes: str = Field(default="", max_length=10_000)


class CounselingGenerationPort(Protocol):
    """定义业务摘要生成所需的最小外部能力。"""

    async def generate(self, db: AsyncSession, *, background: str, parsed_text: str) -> tuple[dict, str]:
        """返回已校验摘要与实际模型标识。"""
        ...


def validate_summary(value: object) -> dict:
    """校验摘要结构、固定标题及非空内容。"""
    document = SummaryDocument.model_validate(value)
    titles = [section.title for section in document.sections]
    if titles != list(SUMMARY_TITLES):
        raise ValueError("摘要段落必须使用规定标题和顺序")
    if any(not section.content.strip() for section in document.sections):
        raise ValueError("摘要段落内容不能为空")
    return document.model_dump()


def _validate_key(value: str, label: str) -> str:
    value = value.strip()
    if not _KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{label}格式无效")
    return value


def _validate_source(name: str, data: bytes) -> tuple[str, str]:
    """校验扩展名与最小内容签名，拒绝伪装或空文件。"""
    safe_name = Path(name or "").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_RECORD_SUFFIXES:
        raise ValueError("仅支持 TXT、DOCX、PDF 记录文件")
    if not data:
        raise ValueError("记录文件不能为空")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("PDF 文件内容与扩展名不一致")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(__import__("io").BytesIO(data)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ValueError("DOCX 文件结构无效")
                if len(names) > 1000 or sum(item.file_size for item in archive.infolist()) > 20 * 1024 * 1024:
                    raise ValueError("DOCX 解压内容超过限制")
        except zipfile.BadZipFile as exc:
            raise ValueError("DOCX 文件结构无效") from exc
    if suffix == ".txt":
        if b"\x00" in data:
            raise ValueError("TXT 文件包含二进制内容")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("TXT 文件必须使用 UTF-8 编码") from exc
    return safe_name, suffix


async def _require_owner(db: AsyncSession, actor: User, student_id: int):
    """校验辅导员权限并返回当前负责档案。"""
    if BusinessCapability.MANAGE_ASSIGNED_STUDENTS not in resolve_business_capabilities(actor):
        raise PermissionError("需要负责学生权限")
    student = await StudentRepository(db).get_for_owner(student_id, actor.department_id, actor.id)
    if student is None:
        raise LookupError("学生档案不存在")
    return student


def _draft_payload(draft: CounselingRecordDraft, revision: CounselingRecordRevision) -> dict:
    """装配不暴露对象存储内部路径的草稿响应。"""
    source = None
    if draft.record_kind == "upload":
        source = {
            "file_name": draft.source_file_name,
            "file_type": draft.source_content_type,
            "file_size": draft.source_size,
            "download_url": f"/api/counseling/students/{draft.student_id}/record-drafts/{draft.id}/source",
        }
    return {
        "id": draft.id,
        "student_id": draft.student_id,
        "record_kind": draft.record_kind,
        "status": draft.status,
        "version": draft.version,
        "consulted_at": format_utc_datetime(draft.consulted_at),
        "consultation_type": draft.consultation_type,
        "source": source,
        "parsed_text": revision.parsed_text,
        "summary": revision.summary,
        "content": revision.content,
        "created_at": format_utc_datetime(draft.created_at),
        "updated_at": format_utc_datetime(draft.updated_at),
    }


def _record_payload(record: CounselingRecord) -> dict:
    """装配正式记录响应。"""
    source = None
    if record.record_kind == "upload":
        source = {
            "file_name": record.source_file_name,
            "file_type": record.source_content_type,
            "file_size": record.source_size,
            "download_url": f"/api/counseling/students/{record.student_id}/record-drafts/{record.draft_id}/source",
        }
    return {
        "id": record.id,
        "student_id": record.student_id,
        "draft_id": record.draft_id,
        "version": record.revision_no,
        "record_kind": record.record_kind,
        "consulted_at": format_utc_datetime(record.consulted_at),
        "consultation_type": record.consultation_type,
        "source": source,
        "parsed_text": record.parsed_text,
        "summary": record.summary,
        "content": record.content,
        "confirmed_at": format_utc_datetime(record.confirmed_at),
    }


async def _owned_draft(
    db: AsyncSession, actor: User, student_id: int, draft_id: str, *, for_update: bool = False
) -> tuple[CounselingRecordRepository, CounselingRecordDraft, CounselingRecordRevision]:
    """校验档案归属并读取草稿及当前修订。"""
    await _require_owner(db, actor, student_id)
    repository = CounselingRecordRepository(db)
    draft = await repository.get_draft(
        draft_id, student_id, actor.department_id, actor.id, for_update=for_update
    )
    if draft is None:
        raise LookupError("辅导记录草稿不存在")
    return repository, draft, await repository.latest_revision(draft)


async def upload_record_draft(
    db: AsyncSession,
    actor: User,
    student_id: int,
    upload: UploadFile,
    request_id: str,
    *,
    parser: CounselingDocumentParser,
    storage: CounselingObjectStorage,
) -> dict:
    """解析有效记录文件，稳定存储来源并创建首个修订。"""
    request_id = _validate_key(request_id, "request_id")
    student = await _require_owner(db, actor, student_id)
    repository = CounselingRecordRepository(db)
    existing = await repository.get_draft_by_request(actor.id, request_id)
    if existing is not None:
        if existing.student_id != student_id:
            raise CounselingConflictError("request_id 已用于其他学生档案")
        return _draft_payload(existing, await repository.latest_revision(existing))

    data = await read_upload_with_limit(
        upload, max_size_bytes=MAX_RECORD_FILE_BYTES, too_large_message="记录文件不得超过 5 MB"
    )
    safe_name, suffix = _validate_source(upload.filename or "", data)
    with tempfile.NamedTemporaryFile(suffix=suffix) as temp_file:
        temp_file.write(data)
        temp_file.flush()
        try:
            parsed_text = (await parser.parse(Path(temp_file.name), db=db)).strip()
        except Exception as exc:
            raise ValueError(f"记录文件解析失败: {exc}") from exc
    if not parsed_text:
        raise ValueError("记录文件没有可用文本")
    if len(parsed_text) > MAX_PARSED_TEXT_CHARS:
        raise ValueError("解析文本超过 120000 字符限制")

    draft_id = uuid.uuid4().hex
    object_name = f"counseling/{actor.uid}/{student_id}/{draft_id}/{safe_name}"
    content_type = upload.content_type or "application/octet-stream"
    await db.rollback()
    await storage.upload(RECORD_BUCKET, object_name, data, content_type)
    repository = CounselingRecordRepository(db)
    draft = CounselingRecordDraft(
        id=draft_id,
        student_id=student_id,
        department_id=actor.department_id,
        counselor_id=actor.id,
        upload_request_id=request_id,
        record_kind="upload",
        source_bucket=RECORD_BUCKET,
        source_object_name=object_name,
        source_file_name=safe_name,
        source_content_type=content_type,
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest(),
    )
    revision = CounselingRecordRevision(
        draft_id=draft_id, revision_no=1, change_kind="parsed", parsed_text=parsed_text, created_by=actor.id
    )
    repository.add(draft)
    repository.add(revision)
    try:
        await db.flush([draft])
        repository.audit(
            student_id=student_id,
            draft_id=draft_id,
            record_id=None,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="record_draft.upload",
            metadata={"source_size": len(data), "source_type": suffix.lstrip(".")},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        await storage.delete(RECORD_BUCKET, object_name)
        raise
    await db.refresh(draft)
    return _draft_payload(draft, revision)


async def list_record_drafts(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """列出当前负责人可见的记录草稿。"""
    await _require_owner(db, actor, student_id)
    repository = CounselingRecordRepository(db)
    result = []
    for draft in await repository.list_drafts(student_id, actor.department_id, actor.id):
        result.append(_draft_payload(draft, await repository.latest_revision(draft)))
    repository.audit(
        student_id=student_id,
        draft_id=None,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_draft.list",
    )
    await db.commit()
    return result


async def get_record_draft(db: AsyncSession, actor: User, student_id: int, draft_id: str) -> dict:
    """读取当前负责人可见的单个记录草稿。"""
    repository, draft, revision = await _owned_draft(db, actor, student_id, draft_id)
    result = _draft_payload(draft, revision)
    repository.audit(
        student_id=student_id,
        draft_id=draft_id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_draft.read",
    )
    await db.commit()
    return result


async def update_parsed_text(
    db: AsyncSession, actor: User, student_id: int, draft_id: str, expected_version: int, parsed_text: str
) -> dict:
    """追加人工修订并使旧摘要失效。"""
    parsed_text = parsed_text.strip()
    if not parsed_text:
        raise ValueError("解析文本不能为空")
    if len(parsed_text) > MAX_PARSED_TEXT_CHARS:
        raise ValueError("解析文本超过 120000 字符限制")
    repository, draft, _ = await _owned_draft(db, actor, student_id, draft_id, for_update=True)
    if draft.record_kind != "upload":
        raise CounselingConflictError("手工咨询记录不支持解析文本修订")
    if draft.version != expected_version or draft.status == "confirmed":
        raise CounselingConflictError("草稿版本已变化或已归档")
    next_revision = draft.current_revision + 1
    revision = CounselingRecordRevision(
        draft_id=draft.id,
        revision_no=next_revision,
        change_kind="manual",
        parsed_text=parsed_text,
        summary=None,
        created_by=actor.id,
    )
    repository.add(revision)
    draft.current_revision = next_revision
    draft.version += 1
    draft.status = "parsed"
    draft.generation_request_id = None
    draft.generation_error = None
    draft.updated_at = utc_now_naive()
    repository.audit(
        student_id=student_id,
        draft_id=draft.id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_draft.parsed_text.update",
    )
    await db.commit()
    return _draft_payload(draft, revision)


async def generate_summary(
    db: AsyncSession,
    actor: User,
    student_id: int,
    draft_id: str,
    expected_version: int,
    request_id: str,
    port: CounselingGenerationPort,
) -> dict:
    """在事务外生成摘要，并仅写回未变化的原版本。"""
    request_id = _validate_key(request_id, "request_id")
    repository, draft, revision = await _owned_draft(db, actor, student_id, draft_id, for_update=True)
    if draft.record_kind != "upload":
        raise CounselingConflictError("手工咨询记录不支持摘要生成")
    if draft.status == "draft" and draft.generation_request_id == request_id:
        return _draft_payload(draft, revision)
    if draft.version != expected_version or draft.status == "confirmed":
        raise CounselingConflictError("草稿版本已变化或已归档")
    if draft.status == "generating" and draft.generation_started_at:
        if draft.generation_started_at > utc_now_naive() - timedelta(minutes=10):
            raise CounselingConflictError("摘要正在生成")
    base_version = draft.version
    parsed_text = revision.parsed_text
    background = (await _require_owner(db, actor, student_id)).background_summary
    draft.status = "generating"
    draft.generation_request_id = request_id
    draft.generation_base_version = base_version
    draft.generation_started_at = utc_now_naive()
    draft.generation_error = None
    repository.audit(
        student_id=student_id,
        draft_id=draft.id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_draft.summary.start",
    )
    await db.commit()

    try:
        summary, model_spec = await port.generate(
            db, background=background, parsed_text=parsed_text
        )
    except Exception as exc:
        await db.rollback()
        repository = CounselingRecordRepository(db)
        current = await repository.get_draft(
            draft_id, student_id, actor.department_id, actor.id, for_update=True
        )
        if current and current.status == "generating" and current.generation_request_id == request_id:
            current.status = "generation_failed"
            current.generation_error = str(exc)[:1000]
            repository.audit(
                student_id=student_id,
                draft_id=draft_id,
                record_id=None,
                actor_id=actor.id,
                department_id=actor.department_id,
                action="record_draft.summary.generate",
                outcome="failed",
                metadata={"error_type": type(exc).__name__},
            )
            await db.commit()
        if isinstance(exc, CounselingGenerationError):
            raise
        raise CounselingGenerationError("摘要生成失败") from exc

    await db.rollback()
    repository = CounselingRecordRepository(db)
    current = await repository.get_draft(draft_id, student_id, actor.department_id, actor.id, for_update=True)
    if (
        current is None
        or current.status != "generating"
        or current.version != base_version
        or current.generation_request_id != request_id
    ):
        await db.rollback()
        raise CounselingConflictError("生成期间草稿已变化，结果未保存")
    next_revision = current.current_revision + 1
    generated = CounselingRecordRevision(
        draft_id=draft_id,
        revision_no=next_revision,
        change_kind="generated",
        parsed_text=parsed_text,
        summary=summary,
        created_by=actor.id,
    )
    repository.add(generated)
    current.current_revision = next_revision
    current.version += 1
    current.status = "draft"
    current.generation_model_spec = model_spec
    current.generation_error = None
    current.updated_at = utc_now_naive()
    repository.audit(
        student_id=student_id,
        draft_id=draft_id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_draft.summary.generate",
    )
    await db.commit()
    return _draft_payload(current, generated)


async def update_summary(
    db: AsyncSession, actor: User, student_id: int, draft_id: str, expected_version: int, summary: object
) -> dict:
    """追加人工编辑后的结构化摘要修订。"""
    normalized = validate_summary(summary)
    repository, draft, current = await _owned_draft(db, actor, student_id, draft_id, for_update=True)
    if draft.record_kind != "upload":
        raise CounselingConflictError("手工咨询记录不支持摘要修订")
    if draft.version != expected_version or draft.status != "draft" or current.summary is None:
        raise CounselingConflictError("草稿版本已变化或尚无可编辑摘要")
    next_revision = draft.current_revision + 1
    revision = CounselingRecordRevision(
        draft_id=draft.id,
        revision_no=next_revision,
        change_kind="manual",
        parsed_text=current.parsed_text,
        summary=normalized,
        created_by=actor.id,
    )
    repository.add(revision)
    draft.current_revision = next_revision
    draft.version += 1
    draft.updated_at = utc_now_naive()
    repository.audit(
        student_id=student_id,
        draft_id=draft.id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_draft.summary.update",
    )
    await db.commit()
    return _draft_payload(draft, revision)


async def build_archive_preview(
    db: AsyncSession, actor: User, student_id: int, draft_id: str, expected_version: int
) -> dict:
    """展示确认后实际写入的记录和唯一时间线影响。"""
    repository, draft, revision = await _owned_draft(db, actor, student_id, draft_id)
    if draft.record_kind != "upload":
        raise CounselingConflictError("手工咨询记录不使用文件归档预览")
    if draft.version != expected_version or draft.status != "draft" or revision.summary is None:
        raise CounselingConflictError("草稿版本已变化或尚不能归档")
    repository.audit(
        student_id=student_id,
        draft_id=draft.id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_draft.archive.preview",
    )
    await db.commit()
    return {
        "draft_id": draft.id,
        "version": draft.version,
        "source": _draft_payload(draft, revision)["source"],
        "parsed_text": revision.parsed_text,
        "summary": revision.summary,
        "impacts": [{"target": "timeline", "action": "add_record"}],
    }


async def confirm_archive(
    db: AsyncSession,
    actor: User,
    student_id: int,
    draft_id: str,
    expected_version: int,
    confirmation_key: str,
) -> dict:
    """持锁创建唯一正式快照，重复同意图返回同一记录。"""
    confirmation_key = _validate_key(confirmation_key, "confirmation_key")
    repository, draft, revision = await _owned_draft(db, actor, student_id, draft_id, for_update=True)
    if draft.record_kind != "upload":
        raise CounselingConflictError("手工咨询记录必须使用咨询记录确认接口")
    existing = await repository.formal_for_draft(draft.id)
    if existing is not None:
        if existing.confirmation_key == confirmation_key:
            return _record_payload(existing)
        raise CounselingConflictError("该草稿已使用其他确认请求归档")
    if draft.version != expected_version or draft.status != "draft" or revision.summary is None:
        raise CounselingConflictError("草稿版本已变化或尚不能归档")
    record = CounselingRecord(
        id=uuid.uuid4().hex,
        student_id=student_id,
        draft_id=draft.id,
        revision_no=draft.current_revision,
        source_bucket=draft.source_bucket,
        source_object_name=draft.source_object_name,
        source_file_name=draft.source_file_name,
        source_content_type=draft.source_content_type,
        source_size=draft.source_size,
        source_sha256=draft.source_sha256,
        parsed_text=revision.parsed_text,
        summary=revision.summary,
        confirmed_by=actor.id,
        confirmation_key=confirmation_key,
    )
    repository.add(record)
    draft.status = "confirmed"
    draft.updated_at = utc_now_naive()
    try:
        await db.flush([record])
        repository.audit(
            student_id=student_id,
            draft_id=draft.id,
            record_id=record.id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="record.archive.confirm",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CounselingConflictError("归档确认发生并发冲突") from exc
    await db.refresh(record)
    return _record_payload(record)


async def download_source(
    db: AsyncSession,
    actor: User,
    student_id: int,
    draft_id: str,
    *,
    storage: CounselingObjectStorage,
) -> tuple[bytes, str, str]:
    """鉴权读取草稿来源文件并记录访问审计。"""
    repository, draft, _ = await _owned_draft(db, actor, student_id, draft_id)
    if draft.record_kind != "upload" or not draft.source_bucket or not draft.source_object_name:
        raise LookupError("该咨询记录没有来源文件")
    data = await storage.download(draft.source_bucket, draft.source_object_name)
    repository.audit(
        student_id=student_id,
        draft_id=draft.id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="record_source.read",
    )
    await db.commit()
    return data, draft.source_file_name, draft.source_content_type


def _normalize_consulted_at(value: datetime) -> datetime:
    """把带时区时间统一为 UTC naive 后入库。"""
    if value.tzinfo is None:
        raise ValueError("咨询时间必须包含时区")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def create_manual_record_draft(
    db: AsyncSession,
    actor: User,
    student_id: int,
    *,
    request_id: str,
    consulted_at: datetime,
    consultation_type: str,
    content: object,
) -> dict:
    """创建可恢复、无需模型的手工咨询记录草稿。"""
    request_id = _validate_key(request_id, "request_id")
    normalized = ConsultationContent.model_validate(content).model_dump()
    consultation_type = consultation_type.strip()
    if not consultation_type:
        raise ValueError("咨询方式不能为空")
    await _require_owner(db, actor, student_id)
    actor_id = actor.id
    department_id = actor.department_id
    repository = CounselingRecordRepository(db)
    existing = await repository.get_draft_by_request(actor_id, request_id)
    if existing is not None:
        if existing.student_id != student_id or existing.record_kind != "manual":
            raise CounselingConflictError("request_id 已用于其他记录")
        return _draft_payload(existing, await repository.latest_revision(existing))

    draft_id = uuid.uuid4().hex
    draft = CounselingRecordDraft(
        id=draft_id,
        student_id=student_id,
        department_id=department_id,
        counselor_id=actor_id,
        upload_request_id=request_id,
        record_kind="manual",
        consulted_at=_normalize_consulted_at(consulted_at),
        consultation_type=consultation_type,
        status="draft",
    )
    revision = CounselingRecordRevision(
        draft_id=draft_id,
        revision_no=1,
        change_kind="manual",
        parsed_text="",
        summary=None,
        content=normalized,
        created_by=actor_id,
    )
    repository.add(draft)
    repository.add(revision)
    try:
        await db.flush([draft])
        repository.audit(
            student_id=student_id,
            draft_id=draft_id,
            record_id=None,
            actor_id=actor_id,
            department_id=department_id,
            action="consultation_draft.create",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        repository = CounselingRecordRepository(db)
        existing = await repository.get_draft_by_request(actor_id, request_id)
        if existing is None or existing.student_id != student_id or existing.record_kind != "manual":
            raise CounselingConflictError("咨询记录创建发生并发冲突") from exc
        return _draft_payload(existing, await repository.latest_revision(existing))
    await db.refresh(draft)
    return _draft_payload(draft, revision)


async def update_manual_record_draft(
    db: AsyncSession,
    actor: User,
    student_id: int,
    draft_id: str,
    *,
    expected_version: int,
    consulted_at: datetime,
    consultation_type: str,
    content: object,
) -> dict:
    """按乐观版本追加手工咨询记录修订。"""
    normalized = ConsultationContent.model_validate(content).model_dump()
    consultation_type = consultation_type.strip()
    if not consultation_type:
        raise ValueError("咨询方式不能为空")
    repository, draft, _ = await _owned_draft(db, actor, student_id, draft_id, for_update=True)
    if draft.record_kind != "manual" or draft.status != "draft" or draft.version != expected_version:
        raise CounselingConflictError("咨询记录草稿版本已变化或不可编辑")
    revision = CounselingRecordRevision(
        draft_id=draft.id,
        revision_no=draft.current_revision + 1,
        change_kind="manual",
        parsed_text="",
        summary=None,
        content=normalized,
        created_by=actor.id,
    )
    repository.add(revision)
    draft.current_revision += 1
    draft.version += 1
    draft.consulted_at = _normalize_consulted_at(consulted_at)
    draft.consultation_type = consultation_type
    draft.updated_at = utc_now_naive()
    repository.audit(
        student_id=student_id,
        draft_id=draft.id,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="consultation_draft.update",
    )
    await db.commit()
    return _draft_payload(draft, revision)


async def confirm_manual_record(
    db: AsyncSession,
    actor: User,
    student_id: int,
    draft_id: str,
    *,
    expected_version: int,
    confirmation_key: str,
) -> dict:
    """人工确认手工草稿并创建唯一正式咨询记录。"""
    confirmation_key = _validate_key(confirmation_key, "confirmation_key")
    repository, draft, revision = await _owned_draft(db, actor, student_id, draft_id, for_update=True)
    existing = await repository.formal_for_draft(draft.id)
    if existing is not None:
        if existing.confirmation_key == confirmation_key:
            return _record_payload(existing)
        raise CounselingConflictError("该草稿已使用其他确认请求归档")
    if (
        draft.record_kind != "manual"
        or draft.status != "draft"
        or draft.version != expected_version
        or revision.content is None
    ):
        raise CounselingConflictError("咨询记录草稿版本已变化或尚不能归档")
    record = CounselingRecord(
        id=uuid.uuid4().hex,
        student_id=student_id,
        draft_id=draft.id,
        revision_no=draft.current_revision,
        record_kind="manual",
        consulted_at=draft.consulted_at,
        consultation_type=draft.consultation_type,
        parsed_text="",
        summary=None,
        content=revision.content,
        confirmed_by=actor.id,
        confirmation_key=confirmation_key,
    )
    repository.add(record)
    draft.status = "confirmed"
    draft.updated_at = utc_now_naive()
    try:
        await db.flush([record])
        repository.audit(
            student_id=student_id,
            draft_id=draft.id,
            record_id=record.id,
            actor_id=actor.id,
            department_id=actor.department_id,
            action="consultation_record.confirm",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CounselingConflictError("咨询记录确认发生并发冲突") from exc
    await db.refresh(record)
    return _record_payload(record)


async def add_record_correction(
    db: AsyncSession,
    actor: User,
    student_id: int,
    record_id: str,
    *,
    request_id: str,
    reason: str,
    corrected_content: object,
) -> dict:
    """为正式记录追加不可变更正，不覆盖原记录。"""
    request_id = _validate_key(request_id, "request_id")
    reason = reason.strip()
    if not reason:
        raise ValueError("更正原因不能为空")
    normalized = ConsultationContent.model_validate(corrected_content).model_dump()
    await _require_owner(db, actor, student_id)
    repository = CounselingRecordRepository(db)
    existing = await repository.get_correction_by_request(actor.id, request_id)
    if existing is not None:
        if existing.student_id != student_id or existing.record_id != record_id:
            raise CounselingConflictError("request_id 已用于其他更正")
        return {
            "id": existing.id,
            "student_id": existing.student_id,
            "record_id": existing.record_id,
            "reason": existing.reason,
            "corrected_content": existing.corrected_content,
            "created_at": format_utc_datetime(existing.created_at),
        }
    record = await repository.get_formal(record_id, student_id, actor.department_id, actor.id)
    if record is None:
        raise LookupError("正式咨询记录不存在")
    if record.record_kind != "manual":
        raise CounselingConflictError("文件型记录暂不支持结构化更正")
    correction = CounselingRecordCorrection(
        id=uuid.uuid4().hex,
        student_id=student_id,
        record_id=record_id,
        reason=reason,
        corrected_content=normalized,
        created_by=actor.id,
        request_id=request_id,
    )
    repository.add(correction)
    repository.audit(
        student_id=student_id,
        draft_id=record.draft_id,
        record_id=record.id,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="consultation_record.correct",
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await CounselingRecordRepository(db).get_correction_by_request(actor.id, request_id)
        if existing is None or existing.student_id != student_id or existing.record_id != record_id:
            raise CounselingConflictError("更正请求发生并发冲突") from exc
        return {
            "id": existing.id,
            "student_id": existing.student_id,
            "record_id": existing.record_id,
            "reason": existing.reason,
            "corrected_content": existing.corrected_content,
            "created_at": format_utc_datetime(existing.created_at),
        }
    await db.refresh(correction)
    return {
        "id": correction.id,
        "student_id": correction.student_id,
        "record_id": correction.record_id,
        "reason": correction.reason,
        "corrected_content": correction.corrected_content,
        "created_at": format_utc_datetime(correction.created_at),
    }


async def list_timeline(db: AsyncSession, actor: User, student_id: int) -> list[dict]:
    """合并正式文书与既有会话为单一按时间倒序的时间线。"""
    await _require_owner(db, actor, student_id)
    repository = CounselingRecordRepository(db)
    records = await repository.list_formal(student_id, actor.department_id, actor.id)
    corrections = await repository.list_corrections(student_id, actor.department_id, actor.id)
    risk_events = await CounselingRiskRepository(db).list_for_owner(student_id, actor.department_id, actor.id)
    conversations = await StudentRepository(db).list_conversations(student_id, actor.uid)
    assessments = await AssessmentRepository(db).list_for_owner(
        student_id, actor.department_id, actor.id
    )
    appointments = await AppointmentRepository(db).list_for_owner(
        student_id, actor.department_id, actor.id
    )
    items = []
    for record in records:
        if record.record_kind == "manual":
            items.append(
                {
                    "id": record.id,
                    "type": "consultation_record",
                    "title": f"{record.consultation_type or '咨询'}记录",
                    "occurred_at": format_utc_datetime(record.consulted_at or record.confirmed_at),
                    "summary": (record.content or {}).get("overview", ""),
                    "content": record.content,
                    "source": None,
                }
            )
        else:
            items.append(
                {
                    "id": record.id,
                    "type": "record",
                    "title": record.source_file_name,
                    "occurred_at": format_utc_datetime(record.confirmed_at),
                    "summary": record.summary,
                    "source": _record_payload(record)["source"],
                }
            )
    items.extend(
        {
            "id": correction.id,
            "type": "record_correction",
            "title": "咨询记录更正",
            "occurred_at": format_utc_datetime(correction.created_at),
            "summary": correction.reason,
            "record_id": correction.record_id,
            "content": correction.corrected_content,
        }
        for correction in corrections
    )
    items.extend(
        {
            "id": event.id,
            "type": "risk_event",
            "title": "人工风险记录",
            "occurred_at": format_utc_datetime(event.created_at),
            "summary": event.basis,
            "risk_level": event.level,
            "risk_status": event.status,
            "source_record_id": event.source_record_id,
        }
        for event in risk_events
    )
    items.extend(
        {
            "id": result.id,
            "type": "assessment",
            "title": "PHQ-9 量表",
            "occurred_at": format_utc_datetime(result.administered_at),
            "summary": f"总分 {result.total_score}",
            "scale_code": result.scale_code,
            "scale_version": result.scale_version,
            "total_score": result.total_score,
            "severity": result.severity,
        }
        for result in assessments
    )
    items.extend(
        {
            "id": appointment.id,
            "type": "appointment",
            "title": f"{appointment.appointment_type}预约",
            "occurred_at": format_utc_datetime(appointment.scheduled_start),
            "summary": appointment.note,
            "scheduled_start": format_utc_datetime(appointment.scheduled_start),
            "scheduled_end": format_utc_datetime(appointment.scheduled_end),
            "appointment_status": appointment.status,
            "location": appointment.location,
        }
        for appointment in appointments
    )
    items.extend(
        {
            "id": item.thread_id,
            "type": "conversation",
            "title": item.title,
            "occurred_at": format_utc_datetime(item.created_at),
            "agent_id": item.agent_id,
        }
        for item in conversations
    )
    repository.audit(
        student_id=student_id,
        draft_id=None,
        record_id=None,
        actor_id=actor.id,
        department_id=actor.department_id,
        action="timeline.read",
    )
    await db.commit()
    return sorted(items, key=lambda item: item["occurred_at"] or "", reverse=True)
