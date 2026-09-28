"""Yuxi 消费业务身份事实的只读端口。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class IdentitySnapshot:
    """AI 平台所需的最小不可变身份快照。"""

    id: int
    uid: str
    username: str
    avatar: str | None
    role: str
    business_roles: tuple[str, ...]
    department_id: int | None
    is_deleted: bool

    def to_dict(self) -> dict:
        """返回不含认证秘密的兼容展示字段。"""
        payload = asdict(self)
        payload["business_roles"] = list(self.business_roles)
        return payload


class IdentityReader(Protocol):
    """定义 Yuxi 允许执行的身份只读查询。"""

    async def get_by_uid(
        self,
        db: AsyncSession | None,
        uid: str,
        *,
        active_only: bool = False,
        for_update: bool = False,
    ) -> IdentitySnapshot | None:
        """读取指定 uid；可在调用方事务中锁定有效账号。"""
        ...

    async def list_by_uids(
        self, db: AsyncSession | None, uids: list[str]
    ) -> list[IdentitySnapshot]:
        """批量读取身份快照。"""
        ...

    async def list_active_uids(self, db: AsyncSession) -> list[str]:
        """按稳定顺序返回全部有效 uid。"""
        ...

    async def search_uids(self, db: AsyncSession, query: str) -> list[str]:
        """返回 uid 或用户名匹配的账号 uid。"""
        ...

    async def count_active(self, db: AsyncSession) -> int:
        """返回有效账号数量。"""
        ...

    async def has_any(self, db: AsyncSession) -> bool:
        """判断是否已经存在账号。"""
        ...


_reader: IdentityReader | None = None


def configure_identity_reader(reader: IdentityReader) -> None:
    """由应用 composition root 注册唯一身份读取适配器。"""
    global _reader
    _reader = reader


def get_identity_reader() -> IdentityReader:
    """返回已注册端口；漏装配时 fail-closed。"""
    if _reader is None:
        raise RuntimeError("Yuxi identity reader is not configured")
    return _reader
