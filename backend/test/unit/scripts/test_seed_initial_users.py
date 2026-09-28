"""初始身份种子数据测试。"""

import pytest

from counseling.identity.models import Department
from counseling.identity.permissions import BusinessRole
from scripts.seed_initial_users import DEPARTMENTS, SUPERADMIN_UID, build_initial_users

pytestmark = pytest.mark.unit


def test_seed_users_receive_explicit_business_roles() -> None:
    """新环境账号不能依赖平台角色推导业务权限。"""

    departments = {
        item["prefix"]: Department(id=index, name=item["name"])
        for index, item in enumerate(DEPARTMENTS, start=1)
    }

    users = build_initial_users(
        departments,
        superadmin_password_hash="superadmin-hash",
        default_password_hash="default-hash",
    )

    assert len(users) == 21
    roles_by_platform_role = {
        role: {tuple(user.business_roles) for user in users if user.role == role}
        for role in ("superadmin", "admin", "user")
    }
    assert roles_by_platform_role == {
        "superadmin": {(BusinessRole.SUPER_ADMIN,)},
        "admin": {(BusinessRole.BUSINESS_ADMIN,)},
        "user": {(BusinessRole.COUNSELOR,)},
    }
    assert next(user for user in users if user.uid == SUPERADMIN_UID).department_id == departments["dev"].id
