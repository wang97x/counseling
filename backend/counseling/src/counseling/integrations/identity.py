"""把业务身份查询适配为 Yuxi 只读端口。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from counseling.identity.models import User
from counseling.identity.repositories.user import UserRepository
from yuxi.identity import IdentitySnapshot


def _snapshot(user: User) -> IdentitySnapshot:
    """复制 Yuxi 当前需要的非秘密身份字段。"""
    return IdentitySnapshot(
        id=int(user.id),
        uid=str(user.uid),
        username=str(user.username),
        avatar=str(user.avatar) if user.avatar else None,
        role=str(user.role),
        business_roles=tuple(str(role) for role in (user.business_roles or [])),
        department_id=int(user.department_id) if user.department_id is not None else None,
        is_deleted=bool(user.is_deleted),
    )


class CounselingIdentityReader:
    """使用业务身份仓储实现平台只读查询。"""

    async def get_by_uid(
        self,
        db: AsyncSession | None,
        uid: str,
        *,
        active_only: bool = False,
        for_update: bool = False,
    ) -> IdentitySnapshot | None:
        """读取账号快照；锁定只允许复用调用方事务。"""
        if for_update and db is None:
            raise ValueError("locking identity reads require a caller-owned transaction")
        repository = UserRepository(db)
        if active_only:
            user = await repository.get_active_by_uid(uid, for_update=for_update)
        else:
            if for_update:
                raise ValueError("locking deleted identities is not supported")
            user = await repository.get_by_uid(uid)
        return _snapshot(user) if user is not None else None

    async def list_by_uids(
        self, db: AsyncSession | None, uids: list[str]
    ) -> list[IdentitySnapshot]:
        """批量读取账号快照。"""
        users = await UserRepository(db).list_by_uids(uids)
        return [_snapshot(user) for user in users]

    async def list_active_uids(self, db: AsyncSession) -> list[str]:
        """返回全部有效 uid。"""
        return await UserRepository(db).list_active_uids()

    async def search_uids(self, db: AsyncSession, query: str) -> list[str]:
        """返回 uid 或用户名匹配的账号 uid。"""
        return await UserRepository(db).search_uids(query)

    async def count_active(self, db: AsyncSession) -> int:
        """返回有效账号数量。"""
        return await UserRepository(db).count_active()

    async def has_any(self, db: AsyncSession) -> bool:
        """判断是否已有账号。"""
        return not await UserRepository(db).is_first_run()
