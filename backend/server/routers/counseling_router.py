"""学生档案最小 HTTP 入口。"""

from datetime import datetime
from typing import Literal
from urllib.parse import quote

from counseling.ai_work.service import (
    AIWorkConflictError,
    confirm_material,
    create_work_item,
    get_material_content,
    import_material,
    list_materials,
    preflight_material,
    reject_material,
)
from counseling.documents.service import (
    ConsultationContent,
    CounselingConflictError,
    CounselingGenerationError,
    SummaryDocument,
    add_record_correction,
    build_archive_preview,
    confirm_archive,
    confirm_manual_record,
    create_manual_record_draft,
    download_source,
    generate_summary,
    get_record_draft,
    list_record_drafts,
    list_timeline,
    update_manual_record_draft,
    update_parsed_text,
    update_summary,
    upload_record_draft,
)
from counseling.identity.http.dependencies import get_db, get_required_user
from counseling.identity.models import User
from counseling.integrations.yuxi import (
    YuxiConversationAdapter,
    YuxiDocumentParserAdapter,
    YuxiGenerationAdapter,
    YuxiObjectStorageAdapter,
)
from counseling.risks.service import RiskConflictError, create_risk_event, list_risk_events
from counseling.students.service import (
    StudentConflictError,
    close_student,
    create_student,
    create_student_conversation,
    get_student,
    list_student_conversations,
    list_students,
    update_student,
)
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.routers.counseling_governance_router import require_acknowledged_counseling_user

counseling = APIRouter(
    prefix="/counseling/students",
    tags=["counseling"],
    dependencies=[Depends(require_acknowledged_counseling_user)],
)


class StudentCreate(BaseModel):
    """辅导员创建本人负责的档案。"""

    model_config = ConfigDict(extra="forbid")
    student_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(default="", max_length=128)
    class_name: str = Field(default="", max_length=128)


class StudentUpdate(BaseModel):
    """负责人维护当前背景和状态。"""

    model_config = ConfigDict(extra="forbid")
    background_summary: str | None = Field(default=None, max_length=10000)
    status: Literal["active", "closed"] | None = None
    display_name: str | None = Field(default=None, max_length=128)
    class_name: str | None = Field(default=None, max_length=128)
    expected_version: int | None = Field(default=None, ge=1)


class StudentConversationCreate(BaseModel):
    """从当前学生档案创建关联会话。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = Field(None, max_length=64)
    title: str | None = Field(None, max_length=200)
    agent_id: str
    background_snapshot: str = Field(max_length=10_000)


class AIWorkItemCreate(BaseModel):
    """从当前档案创建一次独立 AI 协作任务。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    instruction: str = Field(min_length=1, max_length=10000)


class MaterialImportRequest(BaseModel):
    """从指定 Run 回填已展示的 Artifact。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    run_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=1024)


class MaterialPreflightRequest(BaseModel):
    """预检指定 Run 的已展示 Artifact。"""

    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=1024)


class MaterialConfirmRequest(BaseModel):
    """人工确认材料。"""

    model_config = ConfigDict(extra="forbid")
    confirmation_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class MaterialRejectRequest(BaseModel):
    """人工拒绝材料。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class StudentClose(BaseModel):
    """带版本和说明的档案结束请求。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    closure_note: str = Field(min_length=1, max_length=10000)


class VersionedTextUpdate(BaseModel):
    """带乐观锁版本的解析文本修订。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    parsed_text: str = Field(min_length=1, max_length=120000)


class SummaryGenerateRequest(BaseModel):
    """带幂等键的摘要生成请求。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class SummaryUpdateRequest(BaseModel):
    """带版本的人工摘要修订。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    summary: SummaryDocument


class VersionRequest(BaseModel):
    """只校验当前草稿版本的请求。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class ConfirmArchiveRequest(VersionRequest):
    """带稳定幂等键的人工归档确认。"""

    confirmation_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ManualRecordCreate(BaseModel):
    """创建手工咨询记录草稿。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    consulted_at: datetime
    consultation_type: str = Field(min_length=1, max_length=32)
    content: ConsultationContent


class ManualRecordUpdate(BaseModel):
    """按版本修改手工咨询记录草稿。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    consulted_at: datetime
    consultation_type: str = Field(min_length=1, max_length=32)
    content: ConsultationContent


class RecordCorrectionCreate(BaseModel):
    """为正式记录追加更正。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    reason: str = Field(min_length=1, max_length=2000)
    corrected_content: ConsultationContent


class RiskEventCreate(BaseModel):
    """创建人工风险事件。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    level: Literal["normal", "watch", "urgent"]
    basis: str = Field(min_length=1, max_length=10000)
    action_taken: str = Field(default="", max_length=10000)
    status: Literal["open", "monitoring", "closed"]
    source_record_id: str | None = Field(default=None, max_length=64)


def _raise_counseling_error(exc: Exception) -> None:
    """把业务边界错误映射为稳定 HTTP 状态。"""
    if isinstance(exc, PermissionError):
        code = 403
    elif isinstance(exc, LookupError):
        code = 404
    elif isinstance(
        exc, (FileExistsError, AIWorkConflictError, CounselingConflictError, RiskConflictError, StudentConflictError)
    ):
        code = 409
    elif isinstance(exc, CounselingGenerationError):
        code = 502
    else:
        code = 422
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@counseling.post("", status_code=status.HTTP_201_CREATED)
async def create_student_route(
    payload: StudentCreate, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """辅导员为自己创建档案。"""
    try:
        return await create_student(
            db,
            actor,
            payload.student_code,
            display_name=payload.display_name,
            class_name=payload.class_name,
        )
    except (PermissionError, ValueError, FileExistsError) as exc:
        _raise_counseling_error(exc)


@counseling.get("")
async def list_students_route(actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """按角色列出可见档案的最小元数据。"""
    try:
        return await list_students(db, actor)
    except PermissionError as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}")
async def get_student_route(
    student_id: int, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """只向负责人返回背景。"""
    try:
        return await get_student(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.put("/{student_id}")
async def update_student_route(
    student_id: int,
    payload: StudentUpdate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """只允许负责人修改当前背景和状态。"""
    try:
        return await update_student(
            db,
            actor,
            student_id,
            background_summary=payload.background_summary,
            status=payload.status,
            display_name=payload.display_name,
            class_name=payload.class_name,
            expected_version=payload.expected_version,
        )
    except (PermissionError, LookupError, ValueError, StudentConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/close")
async def close_student_route(
    student_id: int,
    payload: StudentClose,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """由负责人填写说明并结束档案。"""
    try:
        return await close_student(
            db,
            actor,
            student_id,
            closure_note=payload.closure_note,
            expected_version=payload.expected_version,
        )
    except (PermissionError, LookupError, ValueError, StudentConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/conversations")
async def list_student_conversations_route(
    student_id: int, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """负责人从档案重开本人关联会话。"""
    try:
        return await list_student_conversations(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/conversations", status_code=status.HTTP_201_CREATED)
async def create_student_conversation_route(
    student_id: int,
    payload: StudentConversationCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """由业务边界授权并创建档案关联会话。"""
    try:
        return await create_student_conversation(
            db,
            actor,
            student_id,
            agent_slug=payload.agent_id,
            request_id=payload.request_id,
            title=payload.title,
            background_snapshot=payload.background_snapshot,
            port=YuxiConversationAdapter(),
        )
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/record-drafts", status_code=status.HTTP_201_CREATED)
async def upload_record_draft_route(
    student_id: int,
    file: UploadFile = File(...),
    request_id: str = Form(...),
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """上传并解析当前档案的 TXT、DOCX 或 PDF 记录。"""
    try:
        return await upload_record_draft(
            db,
            actor,
            student_id,
            file,
            request_id,
            parser=YuxiDocumentParserAdapter(),
            storage=YuxiObjectStorageAdapter(),
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/consultation-drafts", status_code=status.HTTP_201_CREATED)
async def create_manual_record_draft_route(
    student_id: int,
    payload: ManualRecordCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """创建不依赖模型的手工咨询记录草稿。"""
    try:
        return await create_manual_record_draft(
            db,
            actor,
            student_id,
            request_id=payload.request_id,
            consulted_at=payload.consulted_at,
            consultation_type=payload.consultation_type,
            content=payload.content.model_dump(),
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.put("/{student_id}/consultation-drafts/{draft_id}")
async def update_manual_record_draft_route(
    student_id: int,
    draft_id: str,
    payload: ManualRecordUpdate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """按版本追加手工咨询记录修订。"""
    try:
        return await update_manual_record_draft(
            db,
            actor,
            student_id,
            draft_id,
            expected_version=payload.expected_version,
            consulted_at=payload.consulted_at,
            consultation_type=payload.consultation_type,
            content=payload.content.model_dump(),
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/consultation-drafts/{draft_id}/confirm")
async def confirm_manual_record_route(
    student_id: int,
    draft_id: str,
    payload: ConfirmArchiveRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认并归档手工咨询记录。"""
    try:
        return await confirm_manual_record(
            db,
            actor,
            student_id,
            draft_id,
            expected_version=payload.expected_version,
            confirmation_key=payload.confirmation_key,
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/records/{record_id}/corrections", status_code=status.HTTP_201_CREATED)
async def add_record_correction_route(
    student_id: int,
    record_id: str,
    payload: RecordCorrectionCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """为正式咨询记录追加不可变更正。"""
    try:
        return await add_record_correction(
            db,
            actor,
            student_id,
            record_id,
            request_id=payload.request_id,
            reason=payload.reason,
            corrected_content=payload.corrected_content.model_dump(),
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/risk-events", status_code=status.HTTP_201_CREATED)
async def create_risk_event_route(
    student_id: int,
    payload: RiskEventCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """追加人工风险事件并更新当前风险等级。"""
    try:
        return await create_risk_event(
            db,
            actor,
            student_id,
            request_id=payload.request_id,
            level=payload.level,
            basis=payload.basis,
            action_taken=payload.action_taken,
            status=payload.status,
            source_record_id=payload.source_record_id,
        )
    except (PermissionError, LookupError, ValueError, RiskConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/risk-events")
async def list_risk_events_route(
    student_id: int,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出负责人档案的人工风险历史。"""
    try:
        return await list_risk_events(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/record-drafts")
async def list_record_drafts_route(
    student_id: int, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """列出当前档案的记录草稿。"""
    try:
        return await list_record_drafts(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/record-drafts/{draft_id}")
async def get_record_draft_route(
    student_id: int,
    draft_id: str,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取单个记录草稿及其当前修订。"""
    try:
        return await get_record_draft(db, actor, student_id, draft_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/record-drafts/{draft_id}/source")
async def download_record_source_route(
    student_id: int,
    draft_id: str,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """经档案归属校验下载原始记录文件。"""
    try:
        data, file_name, content_type = await download_source(
            db,
            actor,
            student_id,
            draft_id,
            storage=YuxiObjectStorageAdapter(),
        )
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)
    encoded = quote(file_name)
    return Response(
        data,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@counseling.put("/{student_id}/record-drafts/{draft_id}/parsed-text")
async def update_parsed_text_route(
    student_id: int,
    draft_id: str,
    payload: VersionedTextUpdate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工核对并追加解析文本修订。"""
    try:
        return await update_parsed_text(
            db, actor, student_id, draft_id, payload.expected_version, payload.parsed_text
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/record-drafts/{draft_id}/summary")
async def generate_summary_route(
    student_id: int,
    draft_id: str,
    payload: SummaryGenerateRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """从当前已核对文本生成结构化摘要草稿。"""
    try:
        return await generate_summary(
            db,
            actor,
            student_id,
            draft_id,
            payload.expected_version,
            payload.request_id,
            YuxiGenerationAdapter(),
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError, CounselingGenerationError) as exc:
        _raise_counseling_error(exc)


@counseling.put("/{student_id}/record-drafts/{draft_id}/summary")
async def update_summary_route(
    student_id: int,
    draft_id: str,
    payload: SummaryUpdateRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """保存辅导员人工修订后的摘要。"""
    try:
        return await update_summary(
            db, actor, student_id, draft_id, payload.expected_version, payload.summary.model_dump()
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/record-drafts/{draft_id}/archive-preview")
async def archive_preview_route(
    student_id: int,
    draft_id: str,
    payload: VersionRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """展示本次确认的正式内容和时间线影响。"""
    try:
        return await build_archive_preview(db, actor, student_id, draft_id, payload.expected_version)
    except (PermissionError, LookupError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/record-drafts/{draft_id}/confirm")
async def confirm_archive_route(
    student_id: int,
    draft_id: str,
    payload: ConfirmArchiveRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认并创建不可变的正式记录。"""
    try:
        return await confirm_archive(
            db,
            actor,
            student_id,
            draft_id,
            payload.expected_version,
            payload.confirmation_key,
        )
    except (PermissionError, LookupError, ValueError, CounselingConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/timeline")
async def list_timeline_route(
    student_id: int, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """返回档案的正式记录和既有沟通统一时间线。"""
    try:
        return await list_timeline(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/ai-work-items", status_code=status.HTTP_201_CREATED)
async def create_ai_work_item_route(
    student_id: int,
    payload: AIWorkItemCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """冻结已确认事实并创建独立协作会话。"""
    try:
        return await create_work_item(
            db,
            actor,
            student_id,
            request_id=payload.request_id,
            instruction=payload.instruction,
            port=YuxiConversationAdapter(),
        )
    except (PermissionError, LookupError, ValueError, AIWorkConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/ai-work-items/{work_item_id}/materials/preflight")
async def preflight_ai_material_route(
    student_id: int,
    work_item_id: str,
    payload: MaterialPreflightRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """回填前验证来源并返回真实文件元数据。"""
    try:
        return await preflight_material(
            db,
            actor,
            student_id,
            work_item_id,
            run_id=payload.run_id,
            path=payload.path,
            port=YuxiConversationAdapter(),
        )
    except (PermissionError, LookupError, ValueError, AIWorkConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/ai-work-items/{work_item_id}/materials/import", status_code=status.HTTP_201_CREATED)
async def import_ai_material_route(
    student_id: int,
    work_item_id: str,
    payload: MaterialImportRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """把指定 Run 成功展示的文件导入待整理区。"""
    try:
        return await import_material(
            db,
            actor,
            student_id,
            work_item_id,
            request_id=payload.request_id,
            run_id=payload.run_id,
            path=payload.path,
            port=YuxiConversationAdapter(),
            storage=YuxiObjectStorageAdapter(),
        )
    except (PermissionError, LookupError, ValueError, AIWorkConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/materials")
async def list_materials_route(
    student_id: int, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """返回待整理和已确认材料。"""
    try:
        return await list_materials(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/materials/{material_id}/content")
async def material_content_route(
    student_id: int,
    material_id: str,
    mode: Literal["preview", "download"] = "preview",
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """鉴权后预览或下载档案材料。"""
    try:
        item, data = await get_material_content(db, actor, student_id, material_id, YuxiObjectStorageAdapter())
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)
    disposition = "inline" if mode == "preview" else "attachment"
    encoded = quote(item.file_name)
    return Response(
        content=data,
        media_type=item.content_type,
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded}"},
    )


@counseling.post("/{student_id}/materials/{material_id}/confirm")
async def confirm_material_route(
    student_id: int,
    material_id: str,
    payload: MaterialConfirmRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人工确认材料进入档案材料列表。"""
    try:
        return await confirm_material(
            db,
            actor,
            student_id,
            material_id,
            payload.confirmation_key,
            YuxiObjectStorageAdapter(),
        )
    except (PermissionError, LookupError, ValueError, AIWorkConflictError) as exc:
        _raise_counseling_error(exc)


@counseling.post("/{student_id}/materials/{material_id}/reject")
async def reject_material_route(
    student_id: int,
    material_id: str,
    payload: MaterialRejectRequest,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """拒绝待整理材料并保留审计对象。"""
    try:
        return await reject_material(db, actor, student_id, material_id, payload.request_id)
    except (PermissionError, LookupError, ValueError, AIWorkConflictError) as exc:
        _raise_counseling_error(exc)
