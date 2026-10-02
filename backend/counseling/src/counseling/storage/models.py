"""心理辅导档案与文书的 PostgreSQL 模型。"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
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


class CounselingAssessmentResult(Base):
    """冻结一次固定版本量表的答案与服务端计分结果。"""

    __tablename__ = "counseling_assessment_results"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_assessment_request"),
        CheckConstraint("scale_code = 'phq9' AND scale_version = 1", name="ck_counseling_assessment_scale"),
        CheckConstraint("total_score BETWEEN 0 AND 27", name="ck_counseling_assessment_score"),
        Index("ix_counseling_assessments_student", "student_id", "administered_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    scale_code = Column(String(32), nullable=False)
    scale_version = Column(Integer, nullable=False)
    answers = Column(JSON_VALUE, nullable=False)
    total_score = Column(Integer, nullable=False)
    severity = Column(String(32), nullable=False)
    administered_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingAppointment(Base):
    """保存负责人档案内的内部预约及其当前状态。"""

    __tablename__ = "counseling_appointments"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_appointment_request"),
        CheckConstraint(
            "status IN ('scheduled', 'arrived', 'completed', 'no_show', 'canceled')",
            name="ck_counseling_appointment_status",
        ),
        CheckConstraint("scheduled_end > scheduled_start", name="ck_counseling_appointment_time"),
        Index("ix_counseling_appointments_student", "student_id", "scheduled_start"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    scheduled_start = Column(DateTime, nullable=False)
    created_scheduled_start = Column(DateTime, nullable=False)
    created_scheduled_end = Column(DateTime, nullable=False)
    created_appointment_type = Column(String(32), nullable=False)
    created_location = Column(Text, nullable=False, default="", server_default="")
    created_note = Column(Text, nullable=False, default="", server_default="")
    scheduled_end = Column(DateTime, nullable=False)
    appointment_type = Column(String(32), nullable=False)
    location = Column(Text, nullable=False, default="", server_default="")
    note = Column(Text, nullable=False, default="", server_default="")
    status = Column(String(16), nullable=False, default="scheduled", server_default="scheduled")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingPlanVersion(Base):
    """保存不可覆盖的辅导方案版本。"""

    __tablename__ = "counseling_plan_versions"
    __table_args__ = (
        UniqueConstraint("student_id", "version_no", name="uq_counseling_plan_student_version"),
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_plan_request"),
        Index("ix_counseling_plan_student", "student_id", "version_no"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    stage_goals = Column(JSON_VALUE, nullable=False)
    action_plan = Column(JSON_VALUE, nullable=False)
    review_basis = Column(Text, nullable=False)
    source_record_id = Column(String(64), ForeignKey("counseling_records.id"), nullable=True)
    source_assessment_id = Column(String(64), ForeignKey("counseling_assessment_results.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingCrisisProtocol(Base):
    """保存业务管理员发布的部门危机协议版本。"""

    __tablename__ = "counseling_crisis_protocols"
    __table_args__ = (
        UniqueConstraint("department_id", "version_no", name="uq_counseling_protocol_department_version"),
        UniqueConstraint("department_id", "request_id", name="uq_counseling_protocol_request"),
        CheckConstraint("expires_at IS NULL OR expires_at > effective_from", name="ck_counseling_protocol_window"),
        Index("ix_counseling_protocol_active", "department_id", "effective_from"),
    )

    id = Column(String(64), primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    effective_from = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    published_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingCrisisCase(Base):
    """保存绑定人工风险事件和协议版本的危机工单。"""

    __tablename__ = "counseling_crisis_cases"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_crisis_case_request"),
        UniqueConstraint("risk_event_id", name="uq_counseling_crisis_case_risk"),
        CheckConstraint("status IN ('open', 'reviewed', 'closed')", name="ck_counseling_crisis_case_status"),
        Index("ix_counseling_crisis_case_student", "student_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    risk_event_id = Column(String(64), ForeignKey("counseling_risk_events.id"), nullable=False)
    protocol_id = Column(String(64), ForeignKey("counseling_crisis_protocols.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    deadline_at = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="open", server_default="open")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    last_event_id = Column(String(64), nullable=True)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingCrisisCaseEvent(Base):
    """追加记录危机工单的措施、复核和关闭。"""

    __tablename__ = "counseling_crisis_case_events"
    __table_args__ = (
        UniqueConstraint("actor_id", "request_id", name="uq_counseling_crisis_event_request"),
        UniqueConstraint("case_id", "applied_case_version", name="uq_counseling_crisis_event_version"),
        CheckConstraint("event_type IN ('measure', 'review', 'close')", name="ck_counseling_crisis_event_type"),
        Index("ix_counseling_crisis_event_case", "case_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    case_id = Column(String(64), ForeignKey("counseling_crisis_cases.id"), nullable=False)
    event_type = Column(String(16), nullable=False)
    note = Column(Text, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    applied_case_version = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingReferral(Base):
    """保存内部转介与回访的独立状态。"""

    __tablename__ = "counseling_referrals"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_referral_request"),
        CheckConstraint("authorization_status IN ('granted', 'denied')", name="ck_counseling_referral_authorization"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'completed')", name="ck_counseling_referral_status"
        ),
        Index("ix_counseling_referral_student", "student_id", "created_at"),
        Index("ix_counseling_referral_department", "department_id", "status"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=False)
    authorization_status = Column(String(16), nullable=False)
    material_scope = Column(JSON_VALUE, nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    decision_note = Column(Text, nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    follow_up_at = Column(DateTime, nullable=True)
    follow_up_result = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingRiskHintEvaluation(Base):
    """保存不含样本正文的风险提示质量门禁结果。"""

    __tablename__ = "counseling_risk_hint_evaluations"
    __table_args__ = (
        UniqueConstraint("department_id", "request_id", name="uq_counseling_risk_hint_eval_request"),
        CheckConstraint("threshold >= 0 AND threshold <= 1", name="ck_counseling_risk_hint_eval_threshold"),
        CheckConstraint("recall >= 0 AND recall <= 1", name="ck_counseling_risk_hint_eval_recall"),
        CheckConstraint(
            "false_positive_rate >= 0 AND false_positive_rate <= 1",
            name="ck_counseling_risk_hint_eval_fpr",
        ),
        CheckConstraint(
            "true_positive + false_negative > 0 AND false_positive + true_negative > 0",
            name="ck_counseling_risk_hint_eval_classes",
        ),
        Index("ix_counseling_risk_hint_eval_department", "department_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    dataset_reference = Column(String(256), nullable=False)
    dataset_fingerprint = Column(String(64), nullable=False)
    model_reference = Column(String(256), nullable=False)
    threshold = Column(Float, nullable=False)
    true_positive = Column(Integer, nullable=False)
    false_negative = Column(Integer, nullable=False)
    false_positive = Column(Integer, nullable=False)
    true_negative = Column(Integer, nullable=False)
    recall = Column(Float, nullable=False)
    false_positive_rate = Column(Float, nullable=False)
    passed = Column(Boolean, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CounselingRiskHint(Base):
    """保存待辅导员人工核实且不自动干预的风险提示。"""

    __tablename__ = "counseling_risk_hints"
    __table_args__ = (
        UniqueConstraint("counselor_id", "request_id", name="uq_counseling_risk_hint_request"),
        UniqueConstraint("reviewed_by", "decision_request_id", name="uq_counseling_risk_hint_decision_request"),
        UniqueConstraint("source_message_id", name="uq_counseling_risk_hint_source_message"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_counseling_risk_hint_score"),
        CheckConstraint("status IN ('pending_review', 'accepted', 'rejected')", name="ck_counseling_risk_hint_status"),
        Index("ix_counseling_risk_hint_student", "student_id", "status", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    student_id = Column(Integer, ForeignKey("counseling_students.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    counselor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    evaluation_id = Column(String(64), ForeignKey("counseling_risk_hint_evaluations.id"), nullable=False)
    protocol_id = Column(String(64), ForeignKey("counseling_crisis_protocols.id"), nullable=False)
    source_work_item_id = Column(String(64), ForeignKey("counseling_ai_work_items.id"), nullable=False)
    source_run_id = Column(String(64), ForeignKey("agent_runs.id"), nullable=False)
    source_message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    score = Column(Float, nullable=False)
    evidence_summary = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="pending_review", server_default="pending_review")
    decision_note = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    decision_request_id = Column(String(64), nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    request_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CounselingDataUseAcknowledgment(Base):
    """保存业务用户对指定版本数据用途告知的阅读确认。"""

    __tablename__ = "counseling_data_use_acknowledgments"
    __table_args__ = (Index("ix_counseling_notice_user_time", "user_id", "acknowledged_at"),)

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    notice_version = Column(String(32), primary_key=True)
    acknowledged_at = Column(DateTime, nullable=False, server_default=func.now())
