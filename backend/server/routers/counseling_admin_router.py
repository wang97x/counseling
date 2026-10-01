"""心理辅导业务管理员最小统计入口。"""

from counseling.administration.service import get_department_summary
from counseling.identity.http.dependencies import get_db, get_required_user
from counseling.identity.models import User
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.routers.counseling_governance_router import require_acknowledged_counseling_user

counseling_admin = APIRouter(
    prefix="/counseling/admin",
    tags=["counseling-admin"],
    dependencies=[Depends(require_acknowledged_counseling_user)],
)


@counseling_admin.get("/summary")
async def department_summary_route(
    actor: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """返回当前业务管理员部门的非正文聚合统计。"""
    try:
        return await get_department_summary(db, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
