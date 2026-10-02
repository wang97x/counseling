"""P3 授权协作、质量看板与受控外发 HTTP 入口。"""

from datetime import datetime
from typing import Literal

from counseling.collaboration import service
from counseling.identity.http.dependencies import get_db, get_required_user
from counseling.identity.models import User
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.routers.counseling_governance_router import require_acknowledged_counseling_user

collaboration = APIRouter(
    prefix="/counseling/collaboration",
    tags=["counseling-collaboration"],
    dependencies=[Depends(require_acknowledged_counseling_user)],
)
external_claim = APIRouter(prefix="/counseling/external-deliveries", tags=["counseling-external-delivery"])


class Window(BaseModel):
    """授权时间窗与范围。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    scopes: list[str] = Field(min_length=1, max_length=3)
    effective_from: datetime
    expires_at: datetime


class SupervisionCreate(Window):
    """督导授权请求。"""

    supervisor_id: int = Field(gt=0)
    purpose: str = Field(min_length=1, max_length=500)


class ExternalAuthorizationCreate(Window):
    """外发授权请求。"""

    recipient_id: str = Field(min_length=1, max_length=64)


class Decision(BaseModel):
    """授权决定。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    decision: Literal["approved", "rejected"]
    note: str = Field(min_length=1, max_length=1000)


class Revoke(BaseModel):
    """授权撤回请求。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=1000)


class MaterialCreate(BaseModel):
    """结构化去标识材料。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    stage: Literal["engagement", "assessment", "intervention", "review", "closure"]
    concern_tags: list[Literal["adjustment", "anxiety", "mood", "relationships", "study", "sleep", "risk", "other"]] = (
        Field(max_length=8)
    )


class FeedbackCreate(BaseModel):
    """督导意见。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    material_id: str = Field(min_length=1, max_length=64)
    focus_area: Literal["case_conceptualization", "process", "ethics", "risk", "referral"]
    comment: str = Field(min_length=1, max_length=10000)


class SummaryCreate(BaseModel):
    """结构化督导摘要请求。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    material_id: str = Field(min_length=1, max_length=64)


class RecipientCreate(BaseModel):
    """外部接收方核验请求。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    recipient_code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=500)


class DeliveryCreate(BaseModel):
    """一次性交付准备请求。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    scopes: list[Literal["resource_catalog", "referral_status"]] = Field(min_length=1, max_length=2)
    resource_codes: list[str] = Field(max_length=20)
    referral_id: str | None = Field(default=None, max_length=64)
    token_expires_at: datetime


class Retry(BaseModel):
    """失败交付重试请求。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    token_expires_at: datetime


class Version(BaseModel):
    """乐观锁版本。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class Claim(BaseModel):
    """一次性领取令牌。"""

    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=256)


def _raise(exc: Exception) -> None:
    code = 403 if isinstance(exc, PermissionError) else 404 if isinstance(exc, LookupError) else 409
    if isinstance(exc, ValueError):
        code = 422
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@collaboration.post("/students/{student_id}/supervision-authorizations", status_code=201)
async def create_supervision(
    student_id: int,
    payload: SupervisionCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """提出督导授权。"""
    try:
        return await service.create_supervision_authorization(
            db,
            actor,
            student_id,
            request_id=payload.request_id,
            supervisor_id=payload.supervisor_id,
            scopes=list(payload.scopes),
            purpose=payload.purpose,
            effective_from=payload.effective_from,
            expires_at=payload.expires_at,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.get("/supervision-authorizations")
async def list_supervision(
    student_id: int | None = None,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """按当前角色范围列出督导授权。"""
    try:
        return await service.list_supervision_authorizations(db, actor, student_id=student_id)
    except (PermissionError, LookupError, ValueError) as exc:
        _raise(exc)


@collaboration.post("/supervision-authorizations/{authorization_id}/decision")
async def decide_supervision(
    authorization_id: str,
    payload: Decision,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """处理督导授权。"""
    try:
        return await service.decide_supervision_authorization(
            db,
            actor,
            authorization_id,
            expected_version=payload.expected_version,
            decision=payload.decision,
            note=payload.note,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.post("/supervision-authorizations/{authorization_id}/revoke")
async def revoke_supervision(
    authorization_id: str,
    payload: Revoke,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """撤回督导授权。"""
    try:
        return await service.revoke_supervision_authorization(
            db, actor, authorization_id, expected_version=payload.expected_version, note=payload.note
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.post("/students/{student_id}/supervision-authorizations/{authorization_id}/materials")
async def publish_material(
    student_id: int,
    authorization_id: str,
    payload: MaterialCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """发布结构化去标识材料。"""
    try:
        return await service.publish_supervision_material(
            db,
            actor,
            student_id,
            authorization_id,
            request_id=payload.request_id,
            stage=payload.stage,
            concern_tags=list(payload.concern_tags),
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.get("/supervision-authorizations/{authorization_id}/materials")
async def list_materials(
    authorization_id: str,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出去标识材料。"""
    try:
        return await service.list_supervision_materials(db, actor, authorization_id)
    except (PermissionError, LookupError) as exc:
        _raise(exc)


@collaboration.post("/supervision-authorizations/{authorization_id}/feedback")
async def create_feedback(
    authorization_id: str,
    payload: FeedbackCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """追加督导意见。"""
    try:
        return await service.create_supervision_feedback(
            db,
            actor,
            authorization_id,
            request_id=payload.request_id,
            material_id=payload.material_id,
            focus_area=payload.focus_area,
            comment=payload.comment,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.get("/supervision-authorizations/{authorization_id}/feedback")
async def list_feedback(
    authorization_id: str,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出督导意见。"""
    try:
        return await service.list_supervision_feedback(db, actor, authorization_id)
    except (PermissionError, LookupError) as exc:
        _raise(exc)


@collaboration.post("/supervision-authorizations/{authorization_id}/summaries")
async def create_summary(
    authorization_id: str,
    payload: SummaryCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """生成结构化督导摘要。"""
    try:
        return await service.create_supervision_summary(
            db,
            actor,
            authorization_id,
            request_id=payload.request_id,
            material_id=payload.material_id,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.get("/quality-dashboard")
async def quality_dashboard(
    window: Literal["month", "quarter", "year"],
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取固定口径质量看板。"""
    try:
        return await service.get_quality_dashboard(db, actor, window=window)
    except (PermissionError, ValueError) as exc:
        _raise(exc)


@collaboration.post("/external-recipients", status_code=201)
async def create_recipient(
    payload: RecipientCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """核验外部接收方。"""
    try:
        return await service.register_external_recipient(
            db,
            actor,
            request_id=payload.request_id,
            recipient_code=payload.recipient_code,
            display_name=payload.display_name,
            purpose=payload.purpose,
        )
    except (PermissionError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.get("/external-recipients")
async def list_recipients(
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出已核验接收方。"""
    try:
        return await service.list_external_recipients(db, actor)
    except (PermissionError, ValueError) as exc:
        _raise(exc)


@collaboration.post("/students/{student_id}/external-authorizations", status_code=201)
async def create_external_authorization(
    student_id: int,
    payload: ExternalAuthorizationCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """提出外发授权。"""
    try:
        return await service.create_external_authorization(
            db,
            actor,
            student_id,
            request_id=payload.request_id,
            recipient_id=payload.recipient_id,
            scopes=list(payload.scopes),
            effective_from=payload.effective_from,
            expires_at=payload.expires_at,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.get("/external-authorizations")
async def list_external_authorization(
    student_id: int | None = None,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出外发授权。"""
    try:
        return await service.list_external_authorizations(db, actor, student_id=student_id)
    except (PermissionError, LookupError, ValueError) as exc:
        _raise(exc)


@collaboration.post("/external-authorizations/{authorization_id}/decision")
async def decide_external(
    authorization_id: str,
    payload: Decision,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """处理外发授权。"""
    try:
        return await service.decide_external_authorization(
            db,
            actor,
            authorization_id,
            expected_version=payload.expected_version,
            decision=payload.decision,
            note=payload.note,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.post("/external-authorizations/{authorization_id}/revoke")
async def revoke_external(
    authorization_id: str,
    payload: Revoke,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """撤回外发授权。"""
    try:
        return await service.revoke_external_authorization(
            db, actor, authorization_id, expected_version=payload.expected_version, note=payload.note
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.post("/students/{student_id}/external-authorizations/{authorization_id}/deliveries")
async def create_delivery(
    student_id: int,
    authorization_id: str,
    payload: DeliveryCreate,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """准备一次性交付。"""
    try:
        return await service.create_external_delivery(
            db,
            actor,
            student_id,
            authorization_id,
            request_id=payload.request_id,
            scopes=list(payload.scopes),
            resource_codes=list(payload.resource_codes),
            referral_id=payload.referral_id,
            token_expires_at=payload.token_expires_at,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.get("/students/{student_id}/external-deliveries")
async def list_deliveries(
    student_id: int,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出交付事实。"""
    try:
        return await service.list_external_deliveries(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise(exc)


@collaboration.post("/external-deliveries/{delivery_id}/retry")
async def retry_delivery(
    delivery_id: str,
    payload: Retry,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """失败交付轮换令牌。"""
    try:
        return await service.retry_external_delivery(
            db,
            actor,
            delivery_id,
            expected_version=payload.expected_version,
            token_expires_at=payload.token_expires_at,
        )
    except (PermissionError, LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)


@collaboration.post("/external-deliveries/{delivery_id}/withdraw")
async def withdraw_delivery(
    delivery_id: str,
    payload: Version,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """撤回交付或记录撤回请求。"""
    try:
        return await service.withdraw_external_delivery(
            db, actor, delivery_id, expected_version=payload.expected_version
        )
    except (PermissionError, LookupError, service.CollaborationConflictError) as exc:
        _raise(exc)


@external_claim.post("/claim")
async def claim_delivery(payload: Claim, db: AsyncSession = Depends(get_db)):
    """使用一次性令牌领取最小材料。"""
    try:
        return await service.redeem_external_delivery(db, payload.token)
    except (LookupError, ValueError, service.CollaborationConflictError) as exc:
        _raise(exc)
