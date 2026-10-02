"""P3 授权协作、督导与外发的 PostgreSQL 模型。"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from yuxi.storage.postgres.base import JSON_VALUE, Base


class CounselingSupervisionAuthorization(Base):
    """保存个案级督导授权及当前有效状态。"""

    __tablename__ = "counseling_supervision_authorizations"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_supervision_auth_request"),
        CheckConstraint(
            "status IN ('pending', 'active', 'rejected', 'revoked')", name="ck_counseling_supervision_auth_status"
        ),
        CheckConstraint("expires_at > effective_from", name="ck_counseling_supervision_auth_window"),
        Index("ix_counseling_supervision_auth_supervisor", "supervisor_id", "status", "expires_at"),
        Index("ix_counseling_supervision_auth_student", "student_id", "created_at"),
    )
    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scopes = Column(JSON_VALUE, nullable=False)
    purpose = Column(String(500), nullable=False)
    effective_from = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    revoked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    decision_note = Column(String(1000), nullable=True)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingSupervisionMaterial(Base):
    """保存不含自由正文的结构化去标识督导材料。"""

    __tablename__ = "counseling_supervision_materials"
    __table_args__ = (
        UniqueConstraint("authorization_id", "version_no", name="uq_counseling_supervision_material_version"),
        UniqueConstraint("created_by", "request_id", name="uq_counseling_supervision_material_request"),
        CheckConstraint(
            "stage IN ('engagement', 'assessment', 'intervention', 'review', 'closure')",
            name="ck_counseling_supervision_material_stage",
        ),
        CheckConstraint(
            "session_count >= 0 AND assessment_count >= 0 AND risk_event_count >= 0",
            name="ck_counseling_supervision_material_counts",
        ),
    )
    id = Column(String(64), primary_key=True)
    authorization_id = Column(String(64), ForeignKey("counseling_supervision_authorizations.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    case_alias = Column(String(32), nullable=False)
    stage = Column(String(32), nullable=False)
    concern_tags = Column(JSON_VALUE, nullable=False)
    session_count = Column(Integer, nullable=False)
    assessment_count = Column(Integer, nullable=False)
    risk_event_count = Column(Integer, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingSupervisionFeedback(Base):
    """保存督导在有效授权内追加的意见。"""

    __tablename__ = "counseling_supervision_feedback"
    __table_args__ = (
        UniqueConstraint("supervisor_id", "request_id", name="uq_counseling_supervision_feedback_request"),
        CheckConstraint(
            "focus_area IN ('case_conceptualization', 'process', 'ethics', 'risk', 'referral')",
            name="ck_counseling_supervision_feedback_focus",
        ),
        Index("ix_counseling_supervision_feedback_auth", "authorization_id", "created_at"),
    )
    id = Column(String(64), primary_key=True)
    authorization_id = Column(String(64), ForeignKey("counseling_supervision_authorizations.id"), nullable=False)
    material_id = Column(String(64), ForeignKey("counseling_supervision_materials.id"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    focus_area = Column(String(32), nullable=False)
    comment = Column(Text, nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingSupervisionSummary(Base):
    """保存负责人生成并确认的结构化督导摘要。"""

    __tablename__ = "counseling_supervision_summaries"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_supervision_summary_request"),
        Index("ix_counseling_supervision_summary_auth", "authorization_id", "created_at"),
    )
    id = Column(String(64), primary_key=True)
    authorization_id = Column(String(64), ForeignKey("counseling_supervision_authorizations.id"), nullable=False)
    material_id = Column(String(64), ForeignKey("counseling_supervision_materials.id"), nullable=False)
    feedback_count = Column(Integer, nullable=False)
    focus_areas = Column(JSON_VALUE, nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingExternalRecipient(Base):
    """保存业务管理员核验的外部接收方。"""

    __tablename__ = "counseling_external_recipients"
    __table_args__ = (
        UniqueConstraint("department_id", "recipient_code", name="uq_counseling_external_recipient_code"),
        UniqueConstraint("department_id", "request_id", name="uq_counseling_external_recipient_request"),
        Index("ix_counseling_external_recipient_active", "department_id", "active"),
    )
    id = Column(String(64), primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    recipient_code = Column(String(64), nullable=False)
    display_name = Column(String(200), nullable=False)
    purpose = Column(String(500), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingExternalAuthorization(Base):
    """保存对指定接收方、范围和期限的个案外发授权。"""

    __tablename__ = "counseling_external_authorizations"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_external_auth_request"),
        CheckConstraint(
            "status IN ('pending', 'active', 'rejected', 'revoked')", name="ck_counseling_external_auth_status"
        ),
        CheckConstraint("expires_at > effective_from", name="ck_counseling_external_auth_window"),
        Index("ix_counseling_external_auth_student", "student_id", "status", "expires_at"),
    )
    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(String(64), ForeignKey("counseling_external_recipients.id"), nullable=False)
    scopes = Column(JSON_VALUE, nullable=False)
    effective_from = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    revoked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    decision_note = Column(String(1000), nullable=True)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingExternalDelivery(Base):
    """保存最小材料交付、一次性令牌和真实领取结果。"""

    __tablename__ = "counseling_external_deliveries"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_external_delivery_request"),
        UniqueConstraint("token_hash", name="uq_counseling_external_delivery_token"),
        CheckConstraint(
            "status IN ('ready', 'delivered', 'failed', 'withdrawn')", name="ck_counseling_external_delivery_status"
        ),
        CheckConstraint("token_expires_at > created_at", name="ck_counseling_external_delivery_window"),
        CheckConstraint("failed_attempts >= 0", name="ck_counseling_external_delivery_attempts"),
        Index("ix_counseling_external_delivery_auth", "authorization_id", "created_at"),
    )
    id = Column(String(64), primary_key=True)
    authorization_id = Column(String(64), ForeignKey("counseling_external_authorizations.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(String(64), ForeignKey("counseling_external_recipients.id"), nullable=False)
    scopes = Column(JSON_VALUE, nullable=False)
    resource_codes = Column(JSON_VALUE, nullable=False)
    referral_id = Column(String(64), ForeignKey("counseling_referrals.id"), nullable=True)
    token_hash = Column(String(64), nullable=False)
    token_expires_at = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="ready", server_default="ready")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(String(200), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
