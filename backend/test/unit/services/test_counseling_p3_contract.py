"""P3 独立角色与数据库约束契约。"""

from types import SimpleNamespace

from counseling.identity.permissions import (
    BusinessCapability,
    BusinessRole,
    resolve_business_capabilities,
    resolve_business_roles,
)
from counseling.storage import schema


def test_supervisor_is_independent_business_role() -> None:
    """督导只获得授权督导能力，不继承任何管理员或档案能力。"""
    actor = SimpleNamespace(business_roles=["supervisor"])

    assert resolve_business_roles(actor) == (BusinessRole.SUPERVISOR,)
    assert resolve_business_capabilities(actor) == {
        BusinessCapability.VIEW_AUTHORIZED_SUPERVISION,
        BusinessCapability.WRITE_AUTHORIZED_SUPERVISION,
    }


def test_schema_v15_owns_authorized_collaboration_and_delivery_guards() -> None:
    """v15 保存授权、去标识材料和真实领取状态并在数据库拒绝非法写入。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V15_STATEMENTS + schema.COUNSELING_SCHEMA_V16_STATEMENTS)

    assert schema.COUNSELING_SCHEMA_VERSION == 16
    assert '"supervisor"' in migration_sql
    assert "counseling_supervision_authorizations" in migration_sql
    assert "ck_counseling_supervision_auth_scopes" in migration_sql
    assert "counseling_supervision_materials" in migration_sql
    assert "ck_counseling_supervision_material_tags" in migration_sql
    assert "counseling_external_recipients" in migration_sql
    assert "counseling_external_authorizations" in migration_sql
    assert "counseling_external_deliveries" in migration_sql
    assert "enforce_counseling_authorization_transition" in migration_sql
    assert "enforce_counseling_delivery_transition" in migration_sql
    assert "counseling P3 append-only record is immutable" in migration_sql
    assert "enforce_counseling_p3_relation_consistency" in migration_sql
