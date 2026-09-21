"""学生档案最小 HTTP 入口。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.counseling import create_student, get_student, list_students, update_student
from yuxi.storage.postgres.models_business import User

counseling = APIRouter(prefix="/counseling/students", tags=["counseling"])


class StudentCreate(BaseModel):
    """辅导员创建本人负责的档案。"""

    model_config = ConfigDict(extra="forbid")
    student_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class StudentUpdate(BaseModel):
    """负责人维护当前背景和状态。"""

    model_config = ConfigDict(extra="forbid")
    background_summary: str = Field(max_length=10000)
    status: Literal["active", "closed"]


def _raise_counseling_error(exc: Exception) -> None:
    """把业务边界错误映射为稳定 HTTP 状态。"""
    if isinstance(exc, PermissionError):
        code = 403
    elif isinstance(exc, LookupError):
        code = 404
    elif isinstance(exc, FileExistsError):
        code = 409
    else:
        code = 422
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@counseling.post("", status_code=status.HTTP_201_CREATED)
async def create_student_route(
    payload: StudentCreate, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """辅导员为自己创建档案。"""
    try:
        return await create_student(db, actor, payload.student_code)
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
        return await update_student(db, actor, student_id, payload.background_summary, payload.status)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)


@counseling.get("/{student_id}/conversations")
async def list_student_conversations_route(
    student_id: int, actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """负责人从档案重开本人关联会话。"""
    from yuxi.services.counseling import list_student_conversations

    try:
        return await list_student_conversations(db, actor, student_id)
    except (PermissionError, LookupError) as exc:
        _raise_counseling_error(exc)
