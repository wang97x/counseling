"""心理辅导档案与文书的 PostgreSQL 模型。"""

from sqlalchemy import (
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


class StudentRecord(Base):
    """以部门编号和负责人限定的当前学生档案。"""

    __tablename__ = "counseling_students"
    __table_args__ = (
        UniqueConstraint("department_id", "student_code", name="uq_counseling_students_department_code"),
        CheckConstraint("status IN ('active', 'closed')", name="ck_counseling_students_status"),
        CheckConstraint(
            "current_risk_level IN ('unassessed', 'normal', 'watch', 'urgent')",
            name="ck_counseling_students_risk_level",
        ),
        Index("ix_counseling_students_owner", "department_id", "counselor_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    student_code = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False, default="", server_default="")
    class_name = Column(String(128), nullable=False, default="", server_default="")
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    background_summary = Column(Text, nullable=False, default="", server_default="")
    status = Column(String(16), nullable=False, default="active", server_default="active")
    current_risk_level = Column(String(16), nullable=False, default="unassessed", server_default="unassessed")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    closed_at = Column(DateTime, nullable=True)
    closure_note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingRecordDraft(Base):
    """绑定学生档案、来源文件和当前修订的待确认记录。"""

    __tablename__ = "counseling_record_drafts"
    __table_args__ = (
        UniqueConstraint("counselor_id", "upload_request_id", name="uq_counseling_drafts_owner_request"),
        CheckConstraint(
            "status IN ('parsed', 'generating', 'draft', 'generation_failed', 'confirmed')",
            name="ck_counseling_drafts_status",
        ),
        CheckConstraint("record_kind IN ('manual', 'upload')", name="ck_counseling_drafts_kind"),
        Index("ix_counseling_drafts_student", "student_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    upload_request_id = Column(String(64), nullable=False)
    record_kind = Column(String(16), nullable=False, default="upload", server_default="upload")
    consulted_at = Column(DateTime, nullable=True)
    consultation_type = Column(String(32), nullable=True)
    source_bucket = Column(String(64), nullable=True)
    source_object_name = Column(String(1024), nullable=True)
    source_file_name = Column(String(512), nullable=True)
    source_content_type = Column(String(128), nullable=True)
    source_size = Column(Integer, nullable=True)
    source_sha256 = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="parsed", server_default="parsed")
    current_revision = Column(Integer, nullable=False, default=1, server_default="1")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    generation_request_id = Column(String(64), nullable=True)
    generation_base_version = Column(Integer, nullable=True)
    generation_started_at = Column(DateTime, nullable=True)
    generation_model_spec = Column(String(512), nullable=True)
    generation_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingRecordRevision(Base):
    """保存解析文本与摘要草稿的追加式修订。"""

    __tablename__ = "counseling_record_revisions"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision_no", name="uq_counseling_revisions_draft_no"),
        CheckConstraint("change_kind IN ('parsed', 'generated', 'manual')", name="ck_counseling_revisions_kind"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(String(64), ForeignKey("counseling_record_drafts.id"), nullable=False)
    revision_no = Column(Integer, nullable=False)
    change_kind = Column(String(16), nullable=False)
    parsed_text = Column(Text, nullable=False)
    summary = Column(JSON_VALUE, nullable=True)
    content = Column(JSON_VALUE, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingRecord(Base):
    """人工确认后不可覆盖或删除的正式文书快照。"""

    __tablename__ = "counseling_records"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_counseling_records_draft"),
        UniqueConstraint("confirmed_by", "confirmation_key", name="uq_counseling_records_confirmation"),
        Index("ix_counseling_records_student", "student_id", "confirmed_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    draft_id = Column(String(64), ForeignKey("counseling_record_drafts.id"), nullable=False)
    revision_no = Column(Integer, nullable=False)
    record_kind = Column(String(16), nullable=False, default="upload", server_default="upload")
    consulted_at = Column(DateTime, nullable=True)
    consultation_type = Column(String(32), nullable=True)
    source_bucket = Column(String(64), nullable=True)
    source_object_name = Column(String(1024), nullable=True)
    source_file_name = Column(String(512), nullable=True)
    source_content_type = Column(String(128), nullable=True)
    source_size = Column(Integer, nullable=True)
    source_sha256 = Column(String(64), nullable=True)
    parsed_text = Column(Text, nullable=False)
    summary = Column(JSON_VALUE, nullable=True)
    content = Column(JSON_VALUE, nullable=True)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    confirmation_key = Column(String(64), nullable=False)
    confirmed_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingRecordCorrection(Base):
    """引用正式记录的不可变追加更正。"""

    __tablename__ = "counseling_record_corrections"
    __table_args__ = (
        UniqueConstraint("created_by", "request_id", name="uq_counseling_corrections_request"),
        Index("ix_counseling_corrections_student", "student_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    record_id = Column(String(64), ForeignKey("counseling_records.id"), nullable=False)
    reason = Column(Text, nullable=False)
    corrected_content = Column(JSON_VALUE, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingRiskEvent(Base):
    """保存辅导员人工确认的风险等级及处置记录。"""

    __tablename__ = "counseling_risk_events"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_risks_request"),
        CheckConstraint("level IN ('normal', 'watch', 'urgent')", name="ck_counseling_risk_level"),
        CheckConstraint("status IN ('open', 'monitoring', 'closed')", name="ck_counseling_risk_status"),
        Index("ix_counseling_risks_student", "student_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    level = Column(String(16), nullable=False)
    basis = Column(Text, nullable=False)
    action_taken = Column(Text, nullable=False, default="", server_default="")
    status = Column(String(16), nullable=False)
    source_record_id = Column(String(64), ForeignKey("counseling_records.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingAIWorkItem(Base):
    """保存一次档案驱动 AI 协作的不可变上下文。"""

    __tablename__ = "counseling_ai_work_items"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_ai_work_owner_request"),
        UniqueConstraint("conversation_thread_id", name="uq_counseling_ai_work_thread"),
        CheckConstraint("status IN ('preparing', 'ready', 'failed')", name="ck_counseling_ai_work_status"),
        Index("ix_counseling_ai_work_student", "student_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    instruction = Column(Text, nullable=False)
    agent_slug = Column(String(64), nullable=False)
    conversation_thread_id = Column(String(64), nullable=True)
    context_snapshot = Column(JSON_VALUE, nullable=False)
    context_sha256 = Column(String(64), nullable=False)
    context_path = Column(String(1024), nullable=True)
    status = Column(String(16), nullable=False, default="preparing", server_default="preparing")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingMaterial(Base):
    """保存从指定 Run Artifact 导入的档案材料。"""

    __tablename__ = "counseling_materials"
    __table_args__ = (
        UniqueConstraint("counselor_id", "import_request_id", name="uq_counseling_material_import_request"),
        UniqueConstraint("counselor_id", "confirmation_key", name="uq_counseling_material_confirmation"),
        UniqueConstraint("counselor_id", "rejection_request_id", name="uq_counseling_material_rejection"),
        UniqueConstraint("work_item_id", "source_run_id", "source_artifact_path", name="uq_counseling_material_source"),
        CheckConstraint(
            "status IN ('importing', 'pending_review', 'active', 'rejected')",
            name="ck_counseling_material_status",
        ),
        Index("ix_counseling_material_student", "student_id", "status", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    work_item_id = Column(String(64), ForeignKey("counseling_ai_work_items.id"), nullable=False)
    source_thread_id = Column(String(64), nullable=False)
    source_run_id = Column(String(64), nullable=False)
    source_artifact_path = Column(String(1024), nullable=False)
    import_request_id = Column(String(64), nullable=False)
    file_name = Column(String(512), nullable=False)
    content_type = Column(String(128), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    bucket = Column(String(64), nullable=False)
    object_name = Column(String(1024), nullable=False)
    status = Column(String(16), nullable=False, default="importing", server_default="importing")
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmation_key = Column(String(64), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    rejected_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejection_request_id = Column(String(64), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingAuditEvent(Base):
    """只记录主体、动作和结果，不复制个案正文。"""

    __tablename__ = "counseling_audit_events"
    __table_args__ = (Index("ix_counseling_audit_student_time", "student_id", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    draft_id = Column(String(64), ForeignKey("counseling_record_drafts.id"), nullable=True)
    record_id = Column(String(64), ForeignKey("counseling_records.id"), nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    action = Column(String(64), nullable=False)
    outcome = Column(String(32), nullable=False)
    event_metadata = Column(JSON_VALUE, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingDataUseAcknowledgment(Base):
    """保存业务用户对指定版本数据用途告知的阅读确认。"""

    __tablename__ = "counseling_data_use_acknowledgments"
    __table_args__ = (
        Index("ix_counseling_notice_user_time", "user_id", "acknowledged_at"),
    )

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    notice_version = Column(String(32), primary_key=True)
    acknowledged_at = Column(DateTime, nullable=False, server_default=func.now())
