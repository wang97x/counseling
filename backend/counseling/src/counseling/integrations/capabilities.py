"""把 Counseling 业务能力映射到 Yuxi 资源权限。"""

from typing import Any

from counseling.identity.knowledge import resolve_knowledge_base_permission
from yuxi.permissions import ResourcePermission


class CounselingBusinessCapabilityMapper:
    """使用业务角色规则解析平台知识资源权限。"""

    def resolve_knowledge_permission(self, user: Any, resource: Any) -> ResourcePermission:
        """返回业务身份对知识库的有效权限。"""
        return resolve_knowledge_base_permission(user, resource)
