"""知伴业务角色及其能力映射。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any


class BusinessRole(StrEnum):
    """第一版固定业务角色。"""

    COUNSELOR = "counselor"
    SUPERVISOR = "supervisor"
    BUSINESS_ADMIN = "business_admin"
    SUPER_ADMIN = "super_admin"


class BusinessCapability(StrEnum):
    """后续业务入口使用的最小授权能力。"""

    MANAGE_ASSIGNED_STUDENTS = "students.manage_assigned"
    CREATE_OWN_STUDENT_RECORD = "students.create_own"
    VIEW_DEPARTMENT_STUDENTS = "students.view_department"
    VIEW_AUTHORIZED_SUPERVISION = "supervision.view_authorized"
    WRITE_AUTHORIZED_SUPERVISION = "supervision.write_authorized"
    MANAGE_PERSONAL_KNOWLEDGE = "knowledge.personal.manage"
    READ_AUTHORIZED_TEAM_KNOWLEDGE = "knowledge.team.read_authorized"
    MANAGE_TEAM_KNOWLEDGE = "knowledge.team.manage"
    MANAGE_SYSTEM = "system.manage"


BUSINESS_ROLE_ORDER = (
    BusinessRole.COUNSELOR,
    BusinessRole.SUPERVISOR,
    BusinessRole.BUSINESS_ADMIN,
    BusinessRole.SUPER_ADMIN,
)

BUSINESS_ROLE_CAPABILITIES = {
    BusinessRole.COUNSELOR: frozenset(
        {
            BusinessCapability.MANAGE_ASSIGNED_STUDENTS,
            BusinessCapability.CREATE_OWN_STUDENT_RECORD,
            BusinessCapability.MANAGE_PERSONAL_KNOWLEDGE,
            BusinessCapability.READ_AUTHORIZED_TEAM_KNOWLEDGE,
        }
    ),
    BusinessRole.SUPERVISOR: frozenset(
        {
            BusinessCapability.VIEW_AUTHORIZED_SUPERVISION,
            BusinessCapability.WRITE_AUTHORIZED_SUPERVISION,
        }
    ),
    BusinessRole.BUSINESS_ADMIN: frozenset(
        {
            BusinessCapability.VIEW_DEPARTMENT_STUDENTS,
            BusinessCapability.MANAGE_TEAM_KNOWLEDGE,
        }
    ),
    BusinessRole.SUPER_ADMIN: frozenset({BusinessCapability.MANAGE_SYSTEM}),
}


def normalize_business_roles(values: Iterable[str | BusinessRole]) -> tuple[BusinessRole, ...]:
    """校验业务角色、去重并按固定顺序返回。"""

    roles = {BusinessRole.SUPER_ADMIN if value == "technical_admin" else BusinessRole(value) for value in values}
    return tuple(role for role in BUSINESS_ROLE_ORDER if role in roles)


def resolve_business_roles(user: Any) -> tuple[BusinessRole, ...]:
    """读取持久业务角色；缺失时不从平台角色推导权限。"""

    if isinstance(user, Mapping):
        stored_roles = user.get("business_roles")
    else:
        stored_roles = getattr(user, "business_roles", None)

    if stored_roles is None:
        return ()
    return normalize_business_roles(stored_roles)


def resolve_business_capabilities(user: Any) -> frozenset[BusinessCapability]:
    """合并用户兼任角色的能力，不引入角色继承。"""

    capabilities: set[BusinessCapability] = set()
    for role in resolve_business_roles(user):
        capabilities.update(BUSINESS_ROLE_CAPABILITIES[role])
    return frozenset(capabilities)


def has_business_role(user: Any, role: BusinessRole) -> bool:
    """判断账号是否显式持有指定业务角色。"""
    return role in resolve_business_roles(user)
