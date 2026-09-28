"""复合业务角色下的身份管理路由权限测试。"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from counseling.identity.auth import AuthUtils
from counseling.identity.http.auth import auth
from counseling.identity.http.dependencies import get_db, get_identity_admin_user, get_superadmin_user
from counseling.identity.models import Department, User
from counseling.identity.permissions import BusinessRole
from yuxi.storage.postgres.models_business import Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


@pytest_asyncio.fixture()
async def composed_superadmin_client(monkeypatch: pytest.MonkeyPatch):
    """创建同时持有业务管理与超级管理角色的隔离应用。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        department = Department(name="复合角色部门")
        current_user = User(
            username="Composite Admin",
            uid="composite_admin",
            password_hash="$argon2id$placeholder",
            role="superadmin",
            business_roles=[BusinessRole.BUSINESS_ADMIN, BusinessRole.SUPER_ADMIN],
            department=department,
        )
        managed_admin = User(
            username="Managed Admin",
            uid="managed_admin",
            password_hash="$argon2id$placeholder",
            role="admin",
            business_roles=[BusinessRole.BUSINESS_ADMIN],
            department=department,
        )
        target_superadmin = User(
            username="Target Superadmin",
            uid="target_superadmin",
            password_hash="$argon2id$placeholder",
            role="superadmin",
            business_roles=[BusinessRole.SUPER_ADMIN],
            department=department,
        )
        db.add_all([department, current_user, managed_admin, target_superadmin])
        await db.commit()
        await db.refresh(current_user)
        await db.refresh(managed_admin)
        await db.refresh(target_superadmin)

        app = FastAPI()
        app.include_router(auth, prefix="/api")

        async def override_db():
            yield db

        async def override_admin():
            return current_user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_identity_admin_user] = override_admin
        app.dependency_overrides[get_superadmin_user] = override_admin
        monkeypatch.setattr(AuthUtils, "create_access_token", lambda _data: "impersonation-token")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, managed_admin.id, target_superadmin.id
    await engine.dispose()


async def test_composed_superadmin_keeps_system_management_permissions(composed_superadmin_client) -> None:
    """附加业务管理角色不能降低超级管理员的账号管理权限。"""

    client, managed_admin_id, _target_superadmin_id = composed_superadmin_client

    create_response = await client.post(
        "/api/auth/users",
        json={"username": "created_admin", "password": "CreatedAdmin123!", "role": "admin"},
    )
    assert create_response.status_code == 200, create_response.text

    update_response = await client.put(
        f"/api/auth/users/{managed_admin_id}",
        json={"username": "renamed_admin"},
    )
    assert update_response.status_code == 200, update_response.text

    delete_response = await client.delete(f"/api/auth/users/{managed_admin_id}")
    assert delete_response.status_code == 200, delete_response.text


async def test_impersonation_checks_target_business_role(composed_superadmin_client) -> None:
    """模拟登录允许普通目标，但拒绝显式超级管理员目标。"""

    client, managed_admin_id, target_superadmin_id = composed_superadmin_client

    allowed_response = await client.post(f"/api/auth/impersonate/{managed_admin_id}")
    assert allowed_response.status_code == 200, allowed_response.text
    assert allowed_response.json()["access_token"] == "impersonation-token"

    rejected_response = await client.post(f"/api/auth/impersonate/{target_superadmin_id}")
    assert rejected_response.status_code == 403, rejected_response.text
    assert rejected_response.json()["detail"] == "不能模拟超级管理员账户"
