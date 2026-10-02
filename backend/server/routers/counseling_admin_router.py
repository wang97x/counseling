"""心理辅导业务管理员最小统计入口。"""

from datetime import datetime
from typing import Literal

from counseling.administration.service import get_department_summary
from counseling.continuity.service import (
    ContinuityConflictError,
    decide_referral,
    list_crisis_protocols,
    list_department_referrals,
    publish_crisis_protocol,
)
from counseling.identity.http.dependencies import get_db, get_required_user
from counseling.identity.models import User
from counseling.risk_hints.service import (
    RiskHintConflictError,
    list_evaluations,
    publish_evaluation,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt
from sqlalchemy.ext.asyncio import AsyncSession

from server.routers.counseling_governance_router import require_acknowledged_counseling_user

counseling_admin = APIRouter(
    prefix="/counseling/admin",
    tags=["counseling-admin"],
    dependencies=[Depends(require_acknowledged_counseling_user)],
)


class CrisisProtocolPublish(BaseModel):
    """发布部门危机协议版本。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=30000)
    effective_from: datetime
    expires_at: datetime | None = None


class ReferralDecision(BaseModel):
    """业务管理员处理内部转介。"""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    decision: Literal["accepted", "rejected"]
    note: str = Field(min_length=1, max_length=2000)


class RiskHintEvaluationPublish(BaseModel):
    """发布独立标注集的风险提示质量评测。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    dataset_reference: str = Field(min_length=1, max_length=256)
    model_reference: str = Field(min_length=1, max_length=256)
    threshold: StrictFloat | StrictInt
    labels: list[StrictBool] = Field(min_length=2, max_length=100000)
    scores: list[StrictFloat | StrictInt] = Field(min_length=2, max_length=100000)


def _raise_admin_error(exc: Exception) -> None:
    status_code = (
        403
        if isinstance(exc, PermissionError)
        else 404
        if isinstance(exc, LookupError)
        else 409
        if isinstance(exc, (ContinuityConflictError, RiskHintConflictError))
        else 422
    )
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@counseling_admin.get("/summary")
async def department_summary_route(actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """返回当前业务管理员部门的非正文聚合统计。"""
    try:
        return await get_department_summary(db, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@counseling_admin.post("/crisis-protocols", status_code=201)
async def publish_crisis_protocol_route(
    payload: CrisisProtocolPublish,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """发布本部门不可覆盖的危机协议版本。"""
    try:
        return await publish_crisis_protocol(
            db,
            actor,
            request_id=payload.request_id,
            title=payload.title,
            content=payload.content,
            effective_from=payload.effective_from,
            expires_at=payload.expires_at,
        )
    except (PermissionError, LookupError, ValueError, ContinuityConflictError) as exc:
        _raise_admin_error(exc)


@counseling_admin.get("/crisis-protocols")
async def list_crisis_protocols_route(
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出本部门危机协议历史。"""
    try:
        return await list_crisis_protocols(db, actor)
    except (PermissionError, ValueError) as exc:
        _raise_admin_error(exc)


@counseling_admin.get("/referrals")
async def list_department_referrals_route(
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出不含正文的部门内部转介队列。"""
    try:
        return await list_department_referrals(db, actor)
    except (PermissionError, ValueError) as exc:
        _raise_admin_error(exc)


@counseling_admin.post("/referrals/{referral_id}/decision")
async def decide_referral_route(
    referral_id: str,
    payload: ReferralDecision,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """接收或拒绝本部门内部转介。"""
    try:
        return await decide_referral(
            db,
            actor,
            referral_id,
            expected_version=payload.expected_version,
            decision=payload.decision,
            note=payload.note,
        )
    except (PermissionError, LookupError, ValueError, ContinuityConflictError) as exc:
        _raise_admin_error(exc)


@counseling_admin.post("/risk-hint-evaluations", status_code=201)
async def publish_risk_hint_evaluation_route(
    payload: RiskHintEvaluationPublish,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """计算并发布本部门不含样本正文的质量门禁。"""
    try:
        return await publish_evaluation(
            db,
            actor,
            request_id=payload.request_id,
            dataset_reference=payload.dataset_reference,
            model_reference=payload.model_reference,
            threshold=float(payload.threshold),
            labels=list(payload.labels),
            scores=[float(value) for value in payload.scores],
        )
    except (PermissionError, ValueError, RiskHintConflictError) as exc:
        _raise_admin_error(exc)


@counseling_admin.get("/risk-hint-evaluations")
async def list_risk_hint_evaluations_route(
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出本部门风险提示质量门禁历史。"""
    try:
        return await list_evaluations(db, actor)
    except (PermissionError, ValueError) as exc:
        _raise_admin_error(exc)
