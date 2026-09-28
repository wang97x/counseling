"""Yuxi 消费业务能力映射的端口。"""

from typing import Any, Protocol

from yuxi.permissions import ResourcePermission


class BusinessCapabilityMapper(Protocol):
    """把业务角色能力映射为平台资源权限。"""

    def resolve_knowledge_permission(self, user: Any, resource: Any) -> ResourcePermission:
        """解析调用身份对知识库资源的有效权限。"""
        ...


_mapper: BusinessCapabilityMapper | None = None


def configure_business_capability_mapper(mapper: BusinessCapabilityMapper) -> None:
    """由应用 composition root 注册业务能力映射器。"""
    global _mapper
    _mapper = mapper


def get_business_capability_mapper() -> BusinessCapabilityMapper:
    """返回已注册映射器；漏装配时拒绝继续授权。"""
    if _mapper is None:
        raise RuntimeError("Yuxi business capability mapper is not configured")
    return _mapper
