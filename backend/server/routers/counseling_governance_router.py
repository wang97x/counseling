"""心理辅导用途告知门禁与审计回读 HTTP 入口。"""

from counseling.governance.service import (
    DataUseNoticeRequiredError,
    acknowledge_data_use_notice,
    get_data_use_notice,
    list_audit_events,
    require_current_data_use_notice,
)
from counseling.identity.http.dependencies import get_db, get_required_user
from counseling.identity.models import User
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

counseling_governance = APIRouter(
    prefix="/counseling",
    tags=["counseling-governance"],
)


class DataUseNoticeAcknowledge(BaseModel):
    """确认当前数据用途告知版本。"""

    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=32)


async def require_acknowledged_counseling_user(
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """要求业务用户已确认当前数据用途告知。"""
    try:
        await require_current_data_use_notice(db, actor)
    except DataUseNoticeRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return actor


@counseling_governance.get("/data-use-notice")
async def data_use_notice_route(
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """返回当前告知和调用者的持久确认状态。"""
    try:
        return await get_data_use_notice(db, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@counseling_governance.post("/data-use-notice/acknowledgments")
async def acknowledge_data_use_notice_route(
    payload: DataUseNoticeAcknowledge,
    actor: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """幂等确认当前版本的数据用途告知。"""
    try:
        return await acknowledge_data_use_notice(db, actor, payload.version)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@counseling_governance.get("/audit-events")
async def audit_events_route(
    student_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    actor: User = Depends(require_acknowledged_counseling_user),
    db: AsyncSession = Depends(get_db),
):
    """返回当前业务可见范围内不含正文的审计事实。"""
    return {
        "items": await list_audit_events(
            db,
            actor,
            student_id=student_id,
            limit=limit,
        )
    }
