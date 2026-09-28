from types import SimpleNamespace

import pytest

from counseling.identity.permissions import (
    BusinessCapability,
    BusinessRole,
    normalize_business_roles,
    resolve_business_capabilities,
    resolve_business_roles,
)


def test_platform_roles_do_not_imply_business_permissions():
    for role in ("user", "admin", "superadmin"):
        user = SimpleNamespace(role=role)
        assert resolve_business_roles(user) == ()
        assert resolve_business_capabilities(user) == frozenset()


def test_multiple_business_roles_merge_capabilities_without_role_inheritance():
    user = SimpleNamespace(
        role="user",
        business_roles=[BusinessRole.SUPER_ADMIN, BusinessRole.COUNSELOR, BusinessRole.COUNSELOR],
    )

    assert resolve_business_roles(user) == (BusinessRole.COUNSELOR, BusinessRole.SUPER_ADMIN)
    assert resolve_business_capabilities(user) == frozenset(
        {
            BusinessCapability.MANAGE_ASSIGNED_STUDENTS,
            BusinessCapability.CREATE_OWN_STUDENT_RECORD,
            BusinessCapability.MANAGE_PERSONAL_KNOWLEDGE,
            BusinessCapability.READ_AUTHORIZED_TEAM_KNOWLEDGE,
            BusinessCapability.MANAGE_SYSTEM,
        }
    )


def test_persisted_empty_roles_do_not_fall_back_to_legacy_role():
    user = SimpleNamespace(role="superadmin", business_roles=[])

    assert resolve_business_roles(user) == ()
    assert resolve_business_capabilities(user) == frozenset()


def test_unknown_business_role_fails_closed():
    with pytest.raises(ValueError, match="not a valid BusinessRole"):
        normalize_business_roles(["unknown"])
