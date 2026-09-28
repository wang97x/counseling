"""把业务身份能力应用到 Yuxi 通用知识资源。"""

from typing import Any

from counseling.identity.permissions import BusinessCapability, resolve_business_capabilities
from yuxi.permissions.resource_permission import (
    ResourcePermission,
    ResourcePermissionDenied,
    is_personal_knowledge_base,
    normalize_permission_config,
    scope_matches,
)


def _value(source: Any, key: str, default: Any = None) -> Any:
    """兼容对象和字典形式的业务调用身份。"""
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def resolve_knowledge_base_permission(user: Any, resource: Any) -> ResourcePermission:
    """按业务角色、所有权和共享范围解析知识库权限。"""
    capabilities = resolve_business_capabilities(user)
    if is_personal_knowledge_base(resource):
        owner = str(_value(resource, "created_by", "") or "")
        if not owner or owner != str(_value(user, "uid", "") or ""):
            return ResourcePermission.NONE
        if BusinessCapability.MANAGE_PERSONAL_KNOWLEDGE in capabilities:
            return ResourcePermission.MANAGE
        return ResourcePermission.NONE

    if capabilities.intersection(
        {
            BusinessCapability.READ_AUTHORIZED_TEAM_KNOWLEDGE,
            BusinessCapability.MANAGE_TEAM_KNOWLEDGE,
        }
    ):
        config = normalize_permission_config(_value(resource, "share_config"))
        readable = scope_matches(user, config["read_scope"]) or (
            config["read_scope"] is None and scope_matches(user, config["manage_scope"])
        )
        if not readable:
            return ResourcePermission.NONE
        effective_manage_scope = config["manage_scope"] or config["read_scope"]
        if (
            BusinessCapability.MANAGE_TEAM_KNOWLEDGE in capabilities
            and scope_matches(user, effective_manage_scope)
        ):
            return ResourcePermission.MANAGE
        return ResourcePermission.READ

    return ResourcePermission.NONE


def require_knowledge_base_permission(user: Any, resource: Any, required: ResourcePermission) -> ResourcePermission:
    """要求业务身份达到知识库读取或管理权限。"""
    actual = resolve_knowledge_base_permission(user, resource)
    order = {ResourcePermission.NONE: 0, ResourcePermission.READ: 1, ResourcePermission.MANAGE: 2}
    if order[actual] < order[required]:
        raise ResourcePermissionDenied(f"需要 {required.value} 权限，当前为 {actual.value}")
    return actual
