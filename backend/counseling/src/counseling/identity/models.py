"""业务账号、组织、凭证与身份审计模型。"""

from datetime import timedelta
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from yuxi.storage.minio.client import normalize_public_minio_url
from yuxi.storage.postgres.base import Base, JSON_VALUE
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

MAX_LOGIN_FAILED_ATTEMPTS = 5
LOGIN_LOCK_DURATION_SECONDS = 300


class Department(Base):
    """业务组织部门。"""

    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    users = relationship("User", back_populates="department", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": format_utc_datetime(self.created_at),
        }


class User(Base):
    """业务登录账号。"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True, index=True)
    uid = Column(String, nullable=False, unique=True, index=True)
    phone_number = Column(String, nullable=True, unique=True, index=True)
    avatar = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")
    business_roles = Column(JSON_VALUE, nullable=False, default=list, server_default="[]")
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    last_login = Column(DateTime, nullable=True)
    login_failed_count = Column(Integer, nullable=False, default=0)
    last_failed_login = Column(DateTime, nullable=True)
    login_locked_until = Column(DateTime, nullable=True)
    is_deleted = Column(Integer, nullable=False, default=0, index=True)
    deleted_at = Column(DateTime, nullable=True)

    operation_logs = relationship("OperationLog", back_populates="user", cascade="all, delete-orphan")
    department = relationship("Department", back_populates="users")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, include_password: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "username": self.username,
            "uid": self.uid,
            "phone_number": self.phone_number,
            "avatar": normalize_public_minio_url(self.avatar),
            "role": self.role,
            "business_roles": list(self.business_roles or []),
            "department_id": self.department_id,
            "created_at": format_utc_datetime(self.created_at),
            "last_login": format_utc_datetime(self.last_login),
            "login_failed_count": self.login_failed_count,
            "last_failed_login": format_utc_datetime(self.last_failed_login),
            "login_locked_until": format_utc_datetime(self.login_locked_until),
            "is_deleted": self.is_deleted,
            "deleted_at": format_utc_datetime(self.deleted_at),
        }
        if include_password:
            result["password_hash"] = self.password_hash
        return result

    def is_login_locked(self) -> bool:
        """判断账号是否仍在登录锁定期。"""
        return self.login_locked_until is not None and utc_now_naive() < self.login_locked_until

    def get_remaining_lock_time(self) -> int:
        """返回剩余登录锁定秒数。"""
        if self.login_locked_until is None:
            return 0
        return max(0, int((self.login_locked_until - utc_now_naive()).total_seconds()))

    def increment_failed_login(self) -> None:
        """累计失败并在达到阈值后锁定账号。"""
        self.login_failed_count += 1
        self.last_failed_login = utc_now_naive()
        if self.login_failed_count >= MAX_LOGIN_FAILED_ATTEMPTS:
            self.login_locked_until = self.last_failed_login + timedelta(seconds=LOGIN_LOCK_DURATION_SECONDS)

    def reset_failed_login(self) -> None:
        """清空登录失败与锁定状态。"""
        self.login_failed_count = 0
        self.last_failed_login = None
        self.login_locked_until = None


class OperationLog(Base):
    """身份与管理操作审计。"""

    __tablename__ = "operation_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    operation = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime, default=utc_now_naive)
    user = relationship("User", back_populates="operation_logs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "operation": self.operation,
            "details": self.details,
            "ip_address": self.ip_address,
            "timestamp": format_utc_datetime(self.timestamp),
        }


class APIKey(Base):
    """业务账号签发的 API 凭证。"""

    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(16), nullable=False)
    request_id = Column(String(64), nullable=True, unique=True, index=True)
    intent_hash = Column(String(64), nullable=True)
    name = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    last_used_at = Column(DateTime, nullable=True)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive)
    user = relationship("User", back_populates="api_keys")
    department = relationship("Department")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key_prefix": self.key_prefix,
            "name": self.name,
            "user_id": self.user_id,
            "department_id": self.department_id,
            "expires_at": format_utc_datetime(self.expires_at),
            "is_enabled": bool(self.is_enabled),
            "last_used_at": format_utc_datetime(self.last_used_at),
            "created_by": self.created_by,
            "created_at": format_utc_datetime(self.created_at),
        }

    def is_valid(self) -> bool:
        """判断凭证是否仍可使用。"""
        return bool(
            self.is_enabled
            and self.revoked_at is None
            and (not self.expires_at or utc_now_naive() <= self.expires_at)
        )


class CLIAuthSession(Base):
    """CLI 浏览器授权会话。"""

    __tablename__ = "cli_auth_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_code_hash = Column(String(64), nullable=False, unique=True, index=True)
    user_code = Column(String(16), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    key_name = Column(String(100), nullable=False)
    approved_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
    approved_user = relationship("User")
    api_key = relationship("APIKey")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_code": self.user_code,
            "status": self.status,
            "key_name": self.key_name,
            "approved_user_id": self.approved_user_id,
            "api_key_id": self.api_key_id,
            "created_at": format_utc_datetime(self.created_at),
            "expires_at": format_utc_datetime(self.expires_at),
            "approved_at": format_utc_datetime(self.approved_at),
            "consumed_at": format_utc_datetime(self.consumed_at),
        }
