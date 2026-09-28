"""Counseling 业务能力到 Yuxi 平台端口的统一契约测试。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from counseling.integrations.capabilities import CounselingBusinessCapabilityMapper
from counseling.integrations.identity import CounselingIdentityReader
from counseling.integrations.yuxi import YuxiDocumentParserAdapter, YuxiObjectStorageAdapter
from yuxi.permissions import ResourcePermission


@pytest.mark.parametrize(
    ("business_roles", "department_id", "expected"),
    [
        ([], 1, ResourcePermission.NONE),
        (["counselor"], 1, ResourcePermission.READ),
        (["business_admin"], 1, ResourcePermission.MANAGE),
        (["super_admin"], 1, ResourcePermission.NONE),
        (["counselor", "business_admin"], 1, ResourcePermission.MANAGE),
        (["business_admin"], 2, ResourcePermission.NONE),
    ],
)
def test_business_roles_map_to_team_knowledge_permission(
    business_roles: list[str],
    department_id: int,
    expected: ResourcePermission,
) -> None:
    """显式业务角色稳定映射为 Yuxi 团队知识权限，且不发生角色继承。"""
    user = SimpleNamespace(
        uid="actor",
        role="superadmin",
        business_roles=business_roles,
        department_id=department_id,
    )
    resource = SimpleNamespace(
        created_by="owner",
        share_config={
            "version": 2,
            "read_scope": {"access_level": "department", "department_ids": [1]},
            "manage_scope": {"access_level": "department", "department_ids": [1]},
        },
    )

    assert CounselingBusinessCapabilityMapper().resolve_knowledge_permission(user, resource) == expected


def test_personal_knowledge_requires_counselor_owner() -> None:
    """个人知识只映射给具有个人知识能力的资源所有者。"""
    mapper = CounselingBusinessCapabilityMapper()
    personal = SimpleNamespace(
        created_by="owner",
        share_config={"version": 2, "read_scope": None, "manage_scope": None},
    )

    assert mapper.resolve_knowledge_permission(
        SimpleNamespace(uid="owner", role="user", business_roles=["counselor"], department_id=1),
        personal,
    ) == ResourcePermission.MANAGE
    assert mapper.resolve_knowledge_permission(
        SimpleNamespace(uid="owner", role="admin", business_roles=["business_admin"], department_id=1),
        personal,
    ) == ResourcePermission.NONE


@pytest.mark.asyncio
async def test_identity_adapter_returns_secret_free_snapshot(monkeypatch) -> None:
    """身份适配器只暴露平台需要的不可变非秘密字段。"""
    user = SimpleNamespace(
        id=7,
        uid="actor",
        username="辅导员",
        avatar=None,
        role="user",
        business_roles=["counselor"],
        department_id=3,
        is_deleted=0,
        password_hash="secret",
    )
    repository = SimpleNamespace(get_by_uid=AsyncMock(return_value=user))
    monkeypatch.setattr(
        "counseling.integrations.identity.UserRepository",
        lambda _db: repository,
    )

    snapshot = await CounselingIdentityReader().get_by_uid(object(), "actor")

    assert snapshot is not None
    assert snapshot.to_dict() == {
        "id": 7,
        "uid": "actor",
        "username": "辅导员",
        "avatar": None,
        "role": "user",
        "business_roles": ["counselor"],
        "department_id": 3,
        "is_deleted": False,
    }
    assert "password_hash" not in snapshot.to_dict()


@pytest.mark.asyncio
async def test_document_and_storage_adapters_delegate_without_business_fallback(monkeypatch, tmp_path) -> None:
    """OCR 与对象存储端口一一映射到 Yuxi 能力，不在业务侧静默降级。"""
    parse = AsyncMock(return_value="解析文本")
    storage = SimpleNamespace(
        aupload_file=AsyncMock(),
        adownload_file=AsyncMock(return_value=b"source"),
        adelete_file=AsyncMock(),
    )
    monkeypatch.setattr("counseling.integrations.yuxi.parse_document", parse)
    monkeypatch.setattr("counseling.integrations.yuxi.get_minio_client", lambda: storage)
    path = Path(tmp_path) / "source.pdf"

    assert await YuxiDocumentParserAdapter().parse(path, db="db") == "解析文本"
    parse.assert_awaited_once_with(str(path), db="db")

    adapter = YuxiObjectStorageAdapter()
    await adapter.upload("bucket", "object", b"data", "application/pdf")
    assert await adapter.download("bucket", "object") == b"source"
    await adapter.delete("bucket", "object")
    storage.aupload_file.assert_awaited_once_with("bucket", "object", b"data", "application/pdf")
    storage.adownload_file.assert_awaited_once_with("bucket", "object")
    storage.adelete_file.assert_awaited_once_with("bucket", "object")
