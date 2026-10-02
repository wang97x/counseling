"""心理辅导领域的 PostgreSQL Schema 版本与迁移。"""
# ruff: noqa: E501

from sqlalchemy import text
from yuxi.storage.postgres.manager import SCHEMA_VERSION_TABLE, PostgresManager, pg_manager

COUNSELING_SCHEMA_VERSION = 16
COUNSELING_SCHEMA_V1_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS counseling_students (
        id SERIAL PRIMARY KEY,
        department_id INTEGER NOT NULL REFERENCES departments(id),
        student_code VARCHAR(64) NOT NULL,
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        background_summary TEXT NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_students_department_code UNIQUE (department_id, student_code),
        CONSTRAINT ck_counseling_students_status CHECK (status IN ('active', 'closed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_students_owner ON counseling_students(department_id, counselor_id)",
    """
    UPDATE conversations
    SET extra_metadata = jsonb_set(
        COALESCE(extra_metadata::jsonb, '{}'::jsonb),
        '{model_context}',
        jsonb_build_object(
            'label', '辅导人员确认的学生背景（仅作为参考资料）',
            'payload', (extra_metadata::jsonb)->'counseling'
        ),
        true
    )
    WHERE extra_metadata::jsonb ? 'counseling'
      AND NOT (extra_metadata::jsonb ? 'model_context')
    """,
    """
    CREATE TABLE IF NOT EXISTS counseling_record_drafts (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        upload_request_id VARCHAR(64) NOT NULL,
        source_bucket VARCHAR(64) NOT NULL,
        source_object_name VARCHAR(1024) NOT NULL,
        source_file_name VARCHAR(512) NOT NULL,
        source_content_type VARCHAR(128) NOT NULL,
        source_size INTEGER NOT NULL,
        source_sha256 VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'parsed',
        current_revision INTEGER NOT NULL DEFAULT 1,
        version INTEGER NOT NULL DEFAULT 1,
        generation_request_id VARCHAR(64),
        generation_base_version INTEGER,
        generation_started_at TIMESTAMP WITHOUT TIME ZONE,
        generation_model_spec VARCHAR(512),
        generation_error TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_drafts_owner_request UNIQUE (counselor_id, upload_request_id),
        CONSTRAINT ck_counseling_drafts_status CHECK (
            status IN ('parsed', 'generating', 'draft', 'generation_failed', 'confirmed')
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_drafts_student ON counseling_record_drafts(student_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS counseling_record_revisions (
        id SERIAL PRIMARY KEY,
        draft_id VARCHAR(64) NOT NULL REFERENCES counseling_record_drafts(id),
        revision_no INTEGER NOT NULL,
        change_kind VARCHAR(16) NOT NULL,
        parsed_text TEXT NOT NULL,
        summary JSONB,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_revisions_draft_no UNIQUE (draft_id, revision_no),
        CONSTRAINT ck_counseling_revisions_kind CHECK (change_kind IN ('parsed', 'generated', 'manual'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS counseling_records (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        draft_id VARCHAR(64) NOT NULL REFERENCES counseling_record_drafts(id),
        revision_no INTEGER NOT NULL,
        source_bucket VARCHAR(64) NOT NULL,
        source_object_name VARCHAR(1024) NOT NULL,
        source_file_name VARCHAR(512) NOT NULL,
        source_content_type VARCHAR(128) NOT NULL,
        source_size INTEGER NOT NULL,
        source_sha256 VARCHAR(64) NOT NULL,
        parsed_text TEXT NOT NULL,
        summary JSONB NOT NULL,
        confirmed_by INTEGER NOT NULL REFERENCES users(id),
        confirmation_key VARCHAR(64) NOT NULL,
        confirmed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_records_draft UNIQUE (draft_id),
        CONSTRAINT uq_counseling_records_confirmation UNIQUE (confirmed_by, confirmation_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_records_student ON counseling_records(student_id, confirmed_at)",
    """
    CREATE TABLE IF NOT EXISTS counseling_audit_events (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        draft_id VARCHAR(64) REFERENCES counseling_record_drafts(id),
        record_id VARCHAR(64) REFERENCES counseling_records(id),
        actor_id INTEGER NOT NULL REFERENCES users(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        action VARCHAR(64) NOT NULL,
        outcome VARCHAR(32) NOT NULL,
        event_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_audit_student_time ON counseling_audit_events(student_id, created_at)",
    """
    CREATE OR REPLACE FUNCTION reject_counseling_record_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'counseling_records are immutable';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_records_immutable ON counseling_records",
    """
    CREATE TRIGGER trg_counseling_records_immutable
    BEFORE UPDATE OR DELETE ON counseling_records
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_record_mutation()
    """,
)

LEGACY_BUSINESS_V7_IDENTITY_STATEMENTS = (
    "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS business_roles JSONB",
    """
    UPDATE users
    SET business_roles = CASE role
        WHEN 'user' THEN '["counselor"]'::jsonb
        WHEN 'admin' THEN '["business_admin"]'::jsonb
        WHEN 'superadmin' THEN '["technical_admin"]'::jsonb
        ELSE '[]'::jsonb
    END
    WHERE business_roles IS NULL
    """,
    "ALTER TABLE IF EXISTS users ALTER COLUMN business_roles SET DEFAULT '[]'::jsonb",
    "ALTER TABLE IF EXISTS users ALTER COLUMN business_roles SET NOT NULL",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_users_business_roles'
              AND conrelid = 'users'::regclass
        ) THEN
            ALTER TABLE users
            ADD CONSTRAINT ck_users_business_roles
            CHECK (
                jsonb_typeof(business_roles) = 'array'
                AND business_roles <@ '["counselor", "business_admin", "technical_admin"]'::jsonb
            );
        END IF;
    END $$;
    """,
)
LEGACY_BUSINESS_V8_STUDENT_STATEMENTS = COUNSELING_SCHEMA_V1_STATEMENTS[:2]

COUNSELING_SCHEMA_V2_STATEMENTS = (
    "ALTER TABLE counseling_students ADD COLUMN IF NOT EXISTS display_name VARCHAR(128) NOT NULL DEFAULT ''",
    "ALTER TABLE counseling_students ADD COLUMN IF NOT EXISTS class_name VARCHAR(128) NOT NULL DEFAULT ''",
    """
    ALTER TABLE counseling_students
    ADD COLUMN IF NOT EXISTS current_risk_level VARCHAR(16) NOT NULL DEFAULT 'unassessed'
    """,
    "ALTER TABLE counseling_students ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE counseling_students ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITHOUT TIME ZONE",
    "ALTER TABLE counseling_students ADD COLUMN IF NOT EXISTS closure_note TEXT",
    """
    DO $$ BEGIN
        ALTER TABLE counseling_students ADD CONSTRAINT ck_counseling_students_risk_level
        CHECK (current_risk_level IN ('unassessed', 'normal', 'watch', 'urgent'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$
    """,
    "ALTER TABLE counseling_record_drafts ADD COLUMN IF NOT EXISTS record_kind VARCHAR(16) NOT NULL DEFAULT 'upload'",
    "ALTER TABLE counseling_record_drafts ADD COLUMN IF NOT EXISTS consulted_at TIMESTAMP WITHOUT TIME ZONE",
    "ALTER TABLE counseling_record_drafts ADD COLUMN IF NOT EXISTS consultation_type VARCHAR(32)",
    "ALTER TABLE counseling_record_drafts ALTER COLUMN source_bucket DROP NOT NULL",
    "ALTER TABLE counseling_record_drafts ALTER COLUMN source_object_name DROP NOT NULL",
    "ALTER TABLE counseling_record_drafts ALTER COLUMN source_file_name DROP NOT NULL",
    "ALTER TABLE counseling_record_drafts ALTER COLUMN source_content_type DROP NOT NULL",
    "ALTER TABLE counseling_record_drafts ALTER COLUMN source_size DROP NOT NULL",
    "ALTER TABLE counseling_record_drafts ALTER COLUMN source_sha256 DROP NOT NULL",
    """
    DO $$ BEGIN
        ALTER TABLE counseling_record_drafts ADD CONSTRAINT ck_counseling_drafts_kind
        CHECK (record_kind IN ('manual', 'upload'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$
    """,
    "ALTER TABLE counseling_record_revisions ADD COLUMN IF NOT EXISTS content JSONB",
    "ALTER TABLE counseling_records ADD COLUMN IF NOT EXISTS record_kind VARCHAR(16) NOT NULL DEFAULT 'upload'",
    "ALTER TABLE counseling_records ADD COLUMN IF NOT EXISTS consulted_at TIMESTAMP WITHOUT TIME ZONE",
    "ALTER TABLE counseling_records ADD COLUMN IF NOT EXISTS consultation_type VARCHAR(32)",
    "ALTER TABLE counseling_records ADD COLUMN IF NOT EXISTS content JSONB",
    "ALTER TABLE counseling_records ALTER COLUMN source_bucket DROP NOT NULL",
    "ALTER TABLE counseling_records ALTER COLUMN source_object_name DROP NOT NULL",
    "ALTER TABLE counseling_records ALTER COLUMN source_file_name DROP NOT NULL",
    "ALTER TABLE counseling_records ALTER COLUMN source_content_type DROP NOT NULL",
    "ALTER TABLE counseling_records ALTER COLUMN source_size DROP NOT NULL",
    "ALTER TABLE counseling_records ALTER COLUMN source_sha256 DROP NOT NULL",
    "ALTER TABLE counseling_records ALTER COLUMN summary DROP NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS counseling_record_corrections (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        record_id VARCHAR(64) NOT NULL REFERENCES counseling_records(id),
        reason TEXT NOT NULL,
        corrected_content JSONB NOT NULL,
        created_by INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_corrections_request UNIQUE (created_by, request_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_corrections_student
    ON counseling_record_corrections(student_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS counseling_risk_events (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        level VARCHAR(16) NOT NULL,
        basis TEXT NOT NULL,
        action_taken TEXT NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL,
        source_record_id VARCHAR(64) REFERENCES counseling_records(id),
        created_by INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_risks_request UNIQUE (counselor_id, request_id),
        CONSTRAINT ck_counseling_risk_level CHECK (level IN ('normal', 'watch', 'urgent')),
        CONSTRAINT ck_counseling_risk_status CHECK (status IN ('open', 'monitoring', 'closed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_risks_student ON counseling_risk_events(student_id, created_at)",
    """
    CREATE OR REPLACE FUNCTION reject_counseling_correction_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'counseling_record_corrections are immutable';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_corrections_immutable ON counseling_record_corrections",
    """
    CREATE TRIGGER trg_counseling_corrections_immutable
    BEFORE UPDATE OR DELETE ON counseling_record_corrections
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_correction_mutation()
    """,
)

COUNSELING_SCHEMA_V3_STATEMENTS = (
    "ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_business_roles",
    """
    UPDATE users
    SET business_roles = COALESCE(
        (
            SELECT jsonb_agg(
                CASE WHEN role.value = 'technical_admin' THEN 'super_admin' ELSE role.value END
                ORDER BY role.ordinality
            )
            FROM jsonb_array_elements_text(users.business_roles) WITH ORDINALITY AS role(value, ordinality)
        ),
        '[]'::jsonb
    )
    WHERE business_roles ? 'technical_admin'
    """,
    """
    ALTER TABLE users ADD CONSTRAINT ck_users_business_roles
    CHECK (
        jsonb_typeof(business_roles) = 'array'
        AND business_roles <@ '["counselor", "business_admin", "super_admin"]'::jsonb
    )
    """,
)

COUNSELING_SCHEMA_V4_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS counseling_ai_work_items (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        instruction TEXT NOT NULL,
        agent_slug VARCHAR(64) NOT NULL,
        conversation_thread_id VARCHAR(64),
        context_snapshot JSONB NOT NULL,
        context_sha256 VARCHAR(64) NOT NULL,
        context_path VARCHAR(1024),
        status VARCHAR(16) NOT NULL DEFAULT 'preparing',
        error_message TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_ai_work_owner_request UNIQUE (counselor_id, request_id),
        CONSTRAINT uq_counseling_ai_work_thread UNIQUE (conversation_thread_id),
        CONSTRAINT ck_counseling_ai_work_status CHECK (status IN ('preparing', 'ready', 'failed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_ai_work_student ON counseling_ai_work_items(student_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS counseling_materials (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        work_item_id VARCHAR(64) NOT NULL REFERENCES counseling_ai_work_items(id),
        source_thread_id VARCHAR(64) NOT NULL,
        source_run_id VARCHAR(64) NOT NULL,
        source_artifact_path VARCHAR(1024) NOT NULL,
        import_request_id VARCHAR(64) NOT NULL,
        file_name VARCHAR(512) NOT NULL,
        content_type VARCHAR(128) NOT NULL,
        size INTEGER NOT NULL,
        sha256 VARCHAR(64) NOT NULL,
        bucket VARCHAR(64) NOT NULL,
        object_name VARCHAR(1024) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'importing',
        confirmed_by INTEGER REFERENCES users(id),
        confirmation_key VARCHAR(64),
        confirmed_at TIMESTAMP WITHOUT TIME ZONE,
        rejected_by INTEGER REFERENCES users(id),
        rejection_request_id VARCHAR(64),
        rejected_at TIMESTAMP WITHOUT TIME ZONE,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_material_import_request UNIQUE (counselor_id, import_request_id),
        CONSTRAINT uq_counseling_material_confirmation UNIQUE (counselor_id, confirmation_key),
        CONSTRAINT uq_counseling_material_rejection UNIQUE (counselor_id, rejection_request_id),
        CONSTRAINT uq_counseling_material_source UNIQUE (work_item_id, source_run_id, source_artifact_path),
        CONSTRAINT ck_counseling_material_status CHECK (status IN ('importing', 'pending_review', 'active', 'rejected'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_material_student
    ON counseling_materials(student_id, status, created_at)
    """,
)

COUNSELING_SCHEMA_V5_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS counseling_data_use_acknowledgments (
        user_id INTEGER NOT NULL REFERENCES users(id),
        notice_version VARCHAR(32) NOT NULL,
        acknowledged_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        PRIMARY KEY (user_id, notice_version)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_notice_user_time
    ON counseling_data_use_acknowledgments(user_id, acknowledged_at)
    """,
    """
    CREATE OR REPLACE FUNCTION reject_counseling_notice_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'counseling_data_use_acknowledgments are immutable';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_notice_immutable ON counseling_data_use_acknowledgments",
    """
    CREATE TRIGGER trg_counseling_notice_immutable
    BEFORE UPDATE OR DELETE ON counseling_data_use_acknowledgments
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_notice_mutation()
    """,
)

COUNSELING_SCHEMA_V6_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS counseling_assessment_results (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        scale_code VARCHAR(32) NOT NULL,
        scale_version INTEGER NOT NULL,
        answers JSONB NOT NULL,
        total_score INTEGER NOT NULL,
        severity VARCHAR(32) NOT NULL,
        administered_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_assessment_request UNIQUE (counselor_id, request_id),
        CONSTRAINT ck_counseling_assessment_scale CHECK (scale_code = 'phq9' AND scale_version = 1),
        CONSTRAINT ck_counseling_assessment_score CHECK (total_score BETWEEN 0 AND 27)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_assessments_student
    ON counseling_assessment_results(student_id, administered_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS counseling_appointments (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        scheduled_start TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        scheduled_end TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        appointment_type VARCHAR(32) NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL DEFAULT 'scheduled',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_appointment_request UNIQUE (counselor_id, request_id),
        CONSTRAINT ck_counseling_appointment_status
            CHECK (status IN ('scheduled', 'arrived', 'completed', 'no_show', 'canceled')),
        CONSTRAINT ck_counseling_appointment_time CHECK (scheduled_end > scheduled_start)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_appointments_student
    ON counseling_appointments(student_id, scheduled_start)
    """,
    """
    CREATE OR REPLACE FUNCTION reject_counseling_assessment_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'counseling_assessment_results are immutable';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_assessments_immutable ON counseling_assessment_results",
    """
    CREATE TRIGGER trg_counseling_assessments_immutable
    BEFORE UPDATE OR DELETE ON counseling_assessment_results
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_assessment_mutation()
    """,
)

COUNSELING_SCHEMA_V7_STATEMENTS = (
    "ALTER TABLE counseling_appointments ADD COLUMN IF NOT EXISTS created_scheduled_start TIMESTAMP WITHOUT TIME ZONE",
    "ALTER TABLE counseling_appointments ADD COLUMN IF NOT EXISTS created_scheduled_end TIMESTAMP WITHOUT TIME ZONE",
    "ALTER TABLE counseling_appointments ADD COLUMN IF NOT EXISTS created_appointment_type VARCHAR(32)",
    "ALTER TABLE counseling_appointments ADD COLUMN IF NOT EXISTS created_location TEXT",
    "ALTER TABLE counseling_appointments ADD COLUMN IF NOT EXISTS created_note TEXT",
    """
    UPDATE counseling_appointments
    SET created_scheduled_start = COALESCE(created_scheduled_start, scheduled_start),
        created_scheduled_end = COALESCE(created_scheduled_end, scheduled_end),
        created_appointment_type = COALESCE(created_appointment_type, appointment_type),
        created_location = COALESCE(created_location, location),
        created_note = COALESCE(created_note, note)
    WHERE created_scheduled_start IS NULL
       OR created_scheduled_end IS NULL
       OR created_appointment_type IS NULL
       OR created_location IS NULL
       OR created_note IS NULL
    """,
    "ALTER TABLE counseling_appointments ALTER COLUMN created_scheduled_start SET NOT NULL",
    "ALTER TABLE counseling_appointments ALTER COLUMN created_scheduled_end SET NOT NULL",
    "ALTER TABLE counseling_appointments ALTER COLUMN created_appointment_type SET NOT NULL",
    "ALTER TABLE counseling_appointments ALTER COLUMN created_location SET NOT NULL",
    "ALTER TABLE counseling_appointments ALTER COLUMN created_note SET NOT NULL",
)

COUNSELING_SCHEMA_V8_STATEMENTS = (
    """
    CREATE OR REPLACE FUNCTION reject_counseling_appointment_creation_intent_mutation()
    RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.created_scheduled_start IS DISTINCT FROM OLD.created_scheduled_start
           OR NEW.created_scheduled_end IS DISTINCT FROM OLD.created_scheduled_end
           OR NEW.created_appointment_type IS DISTINCT FROM OLD.created_appointment_type
           OR NEW.created_location IS DISTINCT FROM OLD.created_location
           OR NEW.created_note IS DISTINCT FROM OLD.created_note THEN
            RAISE EXCEPTION 'counseling appointment creation intent is immutable';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_appointment_creation_intent_immutable ON counseling_appointments",
    """
    CREATE TRIGGER trg_counseling_appointment_creation_intent_immutable
    BEFORE UPDATE ON counseling_appointments
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_appointment_creation_intent_mutation()
    """,
)

COUNSELING_SCHEMA_V9_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS counseling_plan_versions (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        version_no INTEGER NOT NULL,
        stage_goals JSONB NOT NULL,
        action_plan JSONB NOT NULL,
        review_basis TEXT NOT NULL,
        source_record_id VARCHAR(64) REFERENCES counseling_records(id),
        source_assessment_id VARCHAR(64) REFERENCES counseling_assessment_results(id),
        created_by INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_plan_student_version UNIQUE (student_id, version_no),
        CONSTRAINT uq_counseling_plan_request UNIQUE (counselor_id, request_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_plan_student ON counseling_plan_versions(student_id, version_no)",
    """
    CREATE TABLE IF NOT EXISTS counseling_crisis_protocols (
        id VARCHAR(64) PRIMARY KEY,
        department_id INTEGER NOT NULL REFERENCES departments(id),
        version_no INTEGER NOT NULL,
        title VARCHAR(200) NOT NULL,
        content TEXT NOT NULL,
        effective_from TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        expires_at TIMESTAMP WITHOUT TIME ZONE,
        published_by INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_protocol_department_version UNIQUE (department_id, version_no),
        CONSTRAINT uq_counseling_protocol_request UNIQUE (department_id, request_id),
        CONSTRAINT ck_counseling_protocol_window CHECK (expires_at IS NULL OR expires_at > effective_from)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_protocol_active
    ON counseling_crisis_protocols(department_id, effective_from)
    """,
    """
    CREATE TABLE IF NOT EXISTS counseling_crisis_cases (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        risk_event_id VARCHAR(64) NOT NULL REFERENCES counseling_risk_events(id),
        protocol_id VARCHAR(64) NOT NULL REFERENCES counseling_crisis_protocols(id),
        owner_id INTEGER NOT NULL REFERENCES users(id),
        deadline_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'open',
        version INTEGER NOT NULL DEFAULT 1,
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_crisis_case_request UNIQUE (counselor_id, request_id),
        CONSTRAINT uq_counseling_crisis_case_risk UNIQUE (risk_event_id),
        CONSTRAINT ck_counseling_crisis_case_status CHECK (status IN ('open', 'reviewed', 'closed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_crisis_case_student ON counseling_crisis_cases(student_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS counseling_crisis_case_events (
        id VARCHAR(64) PRIMARY KEY,
        case_id VARCHAR(64) NOT NULL REFERENCES counseling_crisis_cases(id),
        event_type VARCHAR(16) NOT NULL,
        note TEXT NOT NULL,
        actor_id INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_crisis_event_request UNIQUE (actor_id, request_id),
        CONSTRAINT ck_counseling_crisis_event_type CHECK (event_type IN ('measure', 'review', 'close'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_crisis_event_case ON counseling_crisis_case_events(case_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS counseling_referrals (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        reason TEXT NOT NULL,
        authorization_status VARCHAR(16) NOT NULL,
        material_scope JSONB NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        decision_note TEXT,
        decided_by INTEGER REFERENCES users(id),
        decided_at TIMESTAMP WITHOUT TIME ZONE,
        follow_up_at TIMESTAMP WITHOUT TIME ZONE,
        follow_up_result TEXT,
        completed_at TIMESTAMP WITHOUT TIME ZONE,
        version INTEGER NOT NULL DEFAULT 1,
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_referral_request UNIQUE (counselor_id, request_id),
        CONSTRAINT ck_counseling_referral_authorization CHECK (authorization_status IN ('granted', 'denied')),
        CONSTRAINT ck_counseling_referral_status CHECK (status IN ('pending', 'accepted', 'rejected', 'completed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_counseling_referral_student ON counseling_referrals(student_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_counseling_referral_department ON counseling_referrals(department_id, status)",
    """
    CREATE OR REPLACE FUNCTION reject_counseling_p2_history_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'counseling P2 history is immutable';
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_plan_immutable ON counseling_plan_versions",
    """
    CREATE TRIGGER trg_counseling_plan_immutable BEFORE UPDATE OR DELETE ON counseling_plan_versions
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_p2_history_mutation()
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_protocol_immutable ON counseling_crisis_protocols",
    """
    CREATE TRIGGER trg_counseling_protocol_immutable BEFORE UPDATE OR DELETE ON counseling_crisis_protocols
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_p2_history_mutation()
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_crisis_event_immutable ON counseling_crisis_case_events",
    """
    CREATE TRIGGER trg_counseling_crisis_event_immutable BEFORE UPDATE OR DELETE ON counseling_crisis_case_events
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_p2_history_mutation()
    """,
    """
    CREATE OR REPLACE FUNCTION reject_counseling_crisis_case_intent_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.student_id IS DISTINCT FROM OLD.student_id
           OR NEW.department_id IS DISTINCT FROM OLD.department_id
           OR NEW.counselor_id IS DISTINCT FROM OLD.counselor_id
           OR NEW.risk_event_id IS DISTINCT FROM OLD.risk_event_id
           OR NEW.protocol_id IS DISTINCT FROM OLD.protocol_id
           OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.deadline_at IS DISTINCT FROM OLD.deadline_at
           OR NEW.request_id IS DISTINCT FROM OLD.request_id THEN
            RAISE EXCEPTION 'counseling crisis case intent is immutable';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION reject_counseling_referral_intent_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.student_id IS DISTINCT FROM OLD.student_id
           OR NEW.department_id IS DISTINCT FROM OLD.department_id
           OR NEW.counselor_id IS DISTINCT FROM OLD.counselor_id
           OR NEW.reason IS DISTINCT FROM OLD.reason
           OR NEW.authorization_status IS DISTINCT FROM OLD.authorization_status
           OR NEW.material_scope IS DISTINCT FROM OLD.material_scope
           OR NEW.follow_up_at IS DISTINCT FROM OLD.follow_up_at
           OR NEW.request_id IS DISTINCT FROM OLD.request_id THEN
            RAISE EXCEPTION 'counseling referral intent is immutable';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_crisis_case_intent_immutable ON counseling_crisis_cases",
    """
    CREATE TRIGGER trg_counseling_crisis_case_intent_immutable BEFORE UPDATE ON counseling_crisis_cases
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_crisis_case_intent_mutation()
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_referral_intent_immutable ON counseling_referrals",
    """
    CREATE TRIGGER trg_counseling_referral_intent_immutable BEFORE UPDATE ON counseling_referrals
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_referral_intent_mutation()
    """,
)

COUNSELING_SCHEMA_V10_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS counseling_risk_hint_evaluations (
        id VARCHAR(64) PRIMARY KEY,
        department_id INTEGER NOT NULL REFERENCES departments(id),
        dataset_reference VARCHAR(256) NOT NULL,
        dataset_fingerprint VARCHAR(64) NOT NULL,
        model_reference VARCHAR(256) NOT NULL,
        threshold DOUBLE PRECISION NOT NULL,
        true_positive INTEGER NOT NULL,
        false_negative INTEGER NOT NULL,
        false_positive INTEGER NOT NULL,
        true_negative INTEGER NOT NULL,
        recall DOUBLE PRECISION NOT NULL,
        false_positive_rate DOUBLE PRECISION NOT NULL,
        passed BOOLEAN NOT NULL,
        created_by INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_risk_hint_eval_request UNIQUE (department_id, request_id),
        CONSTRAINT ck_counseling_risk_hint_eval_threshold CHECK (threshold >= 0 AND threshold <= 1),
        CONSTRAINT ck_counseling_risk_hint_eval_recall CHECK (recall >= 0 AND recall <= 1),
        CONSTRAINT ck_counseling_risk_hint_eval_fpr CHECK (false_positive_rate >= 0 AND false_positive_rate <= 1),
        CONSTRAINT ck_counseling_risk_hint_eval_classes CHECK (
            true_positive + false_negative > 0 AND false_positive + true_negative > 0
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_risk_hint_eval_department
    ON counseling_risk_hint_evaluations(department_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS counseling_risk_hints (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        evaluation_id VARCHAR(64) NOT NULL REFERENCES counseling_risk_hint_evaluations(id),
        protocol_id VARCHAR(64) NOT NULL REFERENCES counseling_crisis_protocols(id),
        score DOUBLE PRECISION NOT NULL,
        evidence_summary TEXT NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending_review',
        decision_note TEXT,
        reviewed_by INTEGER REFERENCES users(id),
        reviewed_at TIMESTAMP WITHOUT TIME ZONE,
        decision_request_id VARCHAR(64),
        version INTEGER NOT NULL DEFAULT 1,
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_risk_hint_request UNIQUE (counselor_id, request_id),
        CONSTRAINT uq_counseling_risk_hint_decision_request UNIQUE (reviewed_by, decision_request_id),
        CONSTRAINT ck_counseling_risk_hint_score CHECK (score >= 0 AND score <= 1),
        CONSTRAINT ck_counseling_risk_hint_status CHECK (status IN ('pending_review', 'accepted', 'rejected'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_counseling_risk_hint_student
    ON counseling_risk_hints(student_id, status, created_at)
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_risk_hint_eval_immutable ON counseling_risk_hint_evaluations",
    """
    CREATE TRIGGER trg_counseling_risk_hint_eval_immutable
    BEFORE UPDATE OR DELETE ON counseling_risk_hint_evaluations
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_p2_history_mutation()
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_risk_hint_no_delete ON counseling_risk_hints",
    """
    CREATE TRIGGER trg_counseling_risk_hint_no_delete
    BEFORE DELETE ON counseling_risk_hints
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_p2_history_mutation()
    """,
    """
    CREATE OR REPLACE FUNCTION reject_counseling_risk_hint_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.student_id IS DISTINCT FROM OLD.student_id
           OR NEW.department_id IS DISTINCT FROM OLD.department_id
           OR NEW.counselor_id IS DISTINCT FROM OLD.counselor_id
           OR NEW.evaluation_id IS DISTINCT FROM OLD.evaluation_id
           OR NEW.protocol_id IS DISTINCT FROM OLD.protocol_id
           OR NEW.score IS DISTINCT FROM OLD.score
           OR NEW.evidence_summary IS DISTINCT FROM OLD.evidence_summary
           OR NEW.request_id IS DISTINCT FROM OLD.request_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'counseling risk hint origin is immutable';
        END IF;
        IF OLD.status <> 'pending_review'
           OR NEW.status NOT IN ('accepted', 'rejected')
           OR NEW.version <> OLD.version + 1
           OR NEW.reviewed_by IS NULL
           OR NEW.reviewed_at IS NULL
           OR NEW.decision_request_id IS NULL
           OR NEW.decision_note IS NULL THEN
            RAISE EXCEPTION 'counseling risk hint transition is invalid';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_risk_hint_mutation ON counseling_risk_hints",
    """
    CREATE TRIGGER trg_counseling_risk_hint_mutation
    BEFORE UPDATE ON counseling_risk_hints
    FOR EACH ROW EXECUTE FUNCTION reject_counseling_risk_hint_mutation()
    """,
)

COUNSELING_SCHEMA_V11_STATEMENTS = (
    "ALTER TABLE counseling_crisis_cases ADD COLUMN IF NOT EXISTS last_event_id VARCHAR(64)",
    """
    UPDATE counseling_crisis_cases AS cases SET last_event_id = (
        SELECT id FROM counseling_crisis_case_events
        WHERE case_id = cases.id ORDER BY created_at DESC, id DESC LIMIT 1
    ) WHERE last_event_id IS NULL
    """,
    "ALTER TABLE counseling_risk_hint_evaluations DROP CONSTRAINT IF EXISTS ck_counseling_risk_hint_eval_consistent",
    """
    ALTER TABLE counseling_risk_hint_evaluations
    ADD CONSTRAINT ck_counseling_risk_hint_eval_consistent CHECK (
        true_positive >= 0 AND false_negative >= 0 AND false_positive >= 0 AND true_negative >= 0
        AND abs(recall - true_positive::double precision / (true_positive + false_negative)) < 1e-12
        AND abs(false_positive_rate - false_positive::double precision / (false_positive + true_negative)) < 1e-12
        AND passed = (recall >= 0.95 AND false_positive_rate <= 0.05)
    )
    """,
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_crisis_case_transition() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE event_row counseling_crisis_case_events%ROWTYPE;
    BEGIN
        IF NEW.version <> OLD.version + 1 OR NEW.last_event_id IS NULL
           OR NEW.last_event_id IS NOT DISTINCT FROM OLD.last_event_id THEN
            RAISE EXCEPTION 'counseling crisis case transition requires one new event and version';
        END IF;
        SELECT * INTO event_row FROM counseling_crisis_case_events
        WHERE id = NEW.last_event_id AND case_id = NEW.id;
        IF NOT FOUND OR NOT (
            OLD.status = 'open' AND NEW.status = 'open' AND event_row.event_type = 'measure'
            OR OLD.status = 'open' AND NEW.status = 'reviewed' AND event_row.event_type = 'review'
            OR OLD.status = 'reviewed' AND NEW.status = 'reviewed' AND event_row.event_type = 'measure'
            OR OLD.status = 'reviewed' AND NEW.status = 'closed' AND event_row.event_type = 'close'
        ) THEN
            RAISE EXCEPTION 'counseling crisis case transition is invalid';
        END IF;
        INSERT INTO counseling_audit_events
            (student_id, actor_id, department_id, action, outcome, event_metadata)
        VALUES (NEW.student_id, event_row.actor_id, NEW.department_id,
                'crisis_case.' || event_row.event_type, 'success', jsonb_build_object('case_id', NEW.id));
        RETURN NEW;
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_crisis_case_transition ON counseling_crisis_cases",
    """
    CREATE TRIGGER trg_counseling_crisis_case_transition BEFORE UPDATE ON counseling_crisis_cases
    FOR EACH ROW EXECUTE FUNCTION enforce_counseling_crisis_case_transition()
    """,
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_referral_transition() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'counseling referral transition requires one version increment';
        END IF;
        IF OLD.status = 'pending' AND NEW.status IN ('accepted', 'rejected') THEN
            IF NEW.decision_note IS NULL OR NEW.decided_by IS NULL OR NEW.decided_at IS NULL
               OR NEW.follow_up_result IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
                RAISE EXCEPTION 'counseling referral decision metadata is incomplete';
            END IF;
            INSERT INTO counseling_audit_events
                (student_id, actor_id, department_id, action, outcome, event_metadata)
            VALUES (NEW.student_id, NEW.decided_by, NEW.department_id, 'referral.' || NEW.status,
                    'success', jsonb_build_object('referral_id', NEW.id));
        ELSIF OLD.status = 'accepted' AND NEW.status = 'completed' THEN
            IF NEW.follow_up_result IS NULL OR NEW.completed_at IS NULL THEN
                RAISE EXCEPTION 'counseling referral follow-up metadata is incomplete';
            END IF;
            INSERT INTO counseling_audit_events
                (student_id, actor_id, department_id, action, outcome, event_metadata)
            VALUES (NEW.student_id, NEW.counselor_id, NEW.department_id, 'referral.follow_up',
                    'success', jsonb_build_object('referral_id', NEW.id));
        ELSE
            RAISE EXCEPTION 'counseling referral transition is invalid';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_counseling_referral_transition ON counseling_referrals",
    """
    CREATE TRIGGER trg_counseling_referral_transition BEFORE UPDATE ON counseling_referrals
    FOR EACH ROW EXECUTE FUNCTION enforce_counseling_referral_transition()
    """,
)

COUNSELING_SCHEMA_V12_STATEMENTS = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM counseling_risk_hints) THEN
            RAISE EXCEPTION
                'counseling v12 cannot bind legacy risk hints to verified run outputs';
        END IF;
    END;
    $$
    """,
    "ALTER TABLE counseling_risk_hints ADD COLUMN IF NOT EXISTS source_work_item_id VARCHAR(64)",
    "ALTER TABLE counseling_risk_hints ADD COLUMN IF NOT EXISTS source_run_id VARCHAR(64)",
    "ALTER TABLE counseling_risk_hints ADD COLUMN IF NOT EXISTS source_message_id INTEGER",
    "ALTER TABLE counseling_risk_hints DROP CONSTRAINT IF EXISTS fk_counseling_risk_hint_work_item",
    """
    ALTER TABLE counseling_risk_hints
    ADD CONSTRAINT fk_counseling_risk_hint_work_item
    FOREIGN KEY (source_work_item_id) REFERENCES counseling_ai_work_items(id)
    """,
    "ALTER TABLE counseling_risk_hints DROP CONSTRAINT IF EXISTS fk_counseling_risk_hint_run",
    """
    ALTER TABLE counseling_risk_hints
    ADD CONSTRAINT fk_counseling_risk_hint_run FOREIGN KEY (source_run_id) REFERENCES agent_runs(id)
    """,
    "ALTER TABLE counseling_risk_hints DROP CONSTRAINT IF EXISTS fk_counseling_risk_hint_message",
    """
    ALTER TABLE counseling_risk_hints
    ADD CONSTRAINT fk_counseling_risk_hint_message FOREIGN KEY (source_message_id) REFERENCES messages(id)
    """,
    "ALTER TABLE counseling_risk_hints DROP CONSTRAINT IF EXISTS uq_counseling_risk_hint_source_message",
    """
    ALTER TABLE counseling_risk_hints
    ADD CONSTRAINT uq_counseling_risk_hint_source_message UNIQUE (source_message_id)
    """,
    "ALTER TABLE counseling_risk_hints ALTER COLUMN source_work_item_id SET NOT NULL",
    "ALTER TABLE counseling_risk_hints ALTER COLUMN source_run_id SET NOT NULL",
    "ALTER TABLE counseling_risk_hints ALTER COLUMN source_message_id SET NOT NULL",
    """
    CREATE OR REPLACE FUNCTION reject_counseling_risk_hint_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.student_id IS DISTINCT FROM OLD.student_id
           OR NEW.department_id IS DISTINCT FROM OLD.department_id
           OR NEW.counselor_id IS DISTINCT FROM OLD.counselor_id
           OR NEW.evaluation_id IS DISTINCT FROM OLD.evaluation_id
           OR NEW.protocol_id IS DISTINCT FROM OLD.protocol_id
           OR NEW.source_work_item_id IS DISTINCT FROM OLD.source_work_item_id
           OR NEW.source_run_id IS DISTINCT FROM OLD.source_run_id
           OR NEW.source_message_id IS DISTINCT FROM OLD.source_message_id
           OR NEW.score IS DISTINCT FROM OLD.score
           OR NEW.evidence_summary IS DISTINCT FROM OLD.evidence_summary
           OR NEW.request_id IS DISTINCT FROM OLD.request_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'counseling risk hint origin is immutable';
        END IF;
        IF OLD.status <> 'pending_review' OR NEW.status NOT IN ('accepted', 'rejected')
           OR NEW.version <> OLD.version + 1 OR NEW.reviewed_by IS NULL OR NEW.reviewed_at IS NULL
           OR NEW.decision_request_id IS NULL OR NEW.decision_note IS NULL THEN
            RAISE EXCEPTION 'counseling risk hint transition is invalid';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
)

COUNSELING_SCHEMA_V13_STATEMENTS = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM counseling_crisis_case_events) THEN
            RAISE EXCEPTION
                'counseling v13 cannot reconstruct legacy crisis event application order';
        END IF;
    END;
    $$
    """,
    "ALTER TABLE counseling_crisis_case_events ADD COLUMN IF NOT EXISTS applied_case_version INTEGER",
    "ALTER TABLE counseling_crisis_case_events ALTER COLUMN applied_case_version SET NOT NULL",
    "ALTER TABLE counseling_crisis_case_events DROP CONSTRAINT IF EXISTS uq_counseling_crisis_event_version",
    """
    ALTER TABLE counseling_crisis_case_events
    ADD CONSTRAINT uq_counseling_crisis_event_version UNIQUE (case_id, applied_case_version)
    """,
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_crisis_case_transition() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE event_row counseling_crisis_case_events%ROWTYPE;
    BEGIN
        IF NEW.version <> OLD.version + 1 OR NEW.last_event_id IS NULL
           OR NEW.last_event_id IS NOT DISTINCT FROM OLD.last_event_id THEN
            RAISE EXCEPTION 'counseling crisis case transition requires one new event and version';
        END IF;
        SELECT * INTO event_row FROM counseling_crisis_case_events
        WHERE id = NEW.last_event_id AND case_id = NEW.id;
        IF NOT FOUND OR event_row.applied_case_version <> NEW.version OR NOT (
            OLD.status = 'open' AND NEW.status = 'open' AND event_row.event_type = 'measure'
            OR OLD.status = 'open' AND NEW.status = 'reviewed' AND event_row.event_type = 'review'
            OR OLD.status = 'reviewed' AND NEW.status = 'reviewed' AND event_row.event_type = 'measure'
            OR OLD.status = 'reviewed' AND NEW.status = 'closed' AND event_row.event_type = 'close'
        ) THEN
            RAISE EXCEPTION 'counseling crisis case transition is invalid';
        END IF;
        INSERT INTO counseling_audit_events
            (student_id, actor_id, department_id, action, outcome, event_metadata)
        VALUES (NEW.student_id, event_row.actor_id, NEW.department_id,
                'crisis_case.' || event_row.event_type, 'success', jsonb_build_object('case_id', NEW.id));
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_referral_transition() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'counseling referral transition requires one version increment';
        END IF;
        IF OLD.status = 'pending' AND NEW.status IN ('accepted', 'rejected') THEN
            IF NEW.decision_note IS NULL OR NEW.decided_by IS NULL OR NEW.decided_at IS NULL
               OR NEW.follow_up_result IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
                RAISE EXCEPTION 'counseling referral decision metadata is incomplete';
            END IF;
            INSERT INTO counseling_audit_events
                (student_id, actor_id, department_id, action, outcome, event_metadata)
            VALUES (NEW.student_id, NEW.decided_by, NEW.department_id, 'referral.' || NEW.status,
                    'success', jsonb_build_object('referral_id', NEW.id));
        ELSIF OLD.status = 'accepted' AND NEW.status = 'completed' THEN
            IF NEW.decision_note IS DISTINCT FROM OLD.decision_note
               OR NEW.decided_by IS DISTINCT FROM OLD.decided_by
               OR NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN
                RAISE EXCEPTION 'counseling referral decision metadata is immutable';
            END IF;
            IF NEW.follow_up_result IS NULL OR NEW.completed_at IS NULL THEN
                RAISE EXCEPTION 'counseling referral follow-up metadata is incomplete';
            END IF;
            INSERT INTO counseling_audit_events
                (student_id, actor_id, department_id, action, outcome, event_metadata)
            VALUES (NEW.student_id, NEW.counselor_id, NEW.department_id, 'referral.follow_up',
                    'success', jsonb_build_object('referral_id', NEW.id));
        ELSE
            RAISE EXCEPTION 'counseling referral transition is invalid';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
)

COUNSELING_SCHEMA_V14_STATEMENTS = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM counseling_crisis_cases AS cases
            LEFT JOIN LATERAL (
                SELECT count(*) AS event_count,
                       min(applied_case_version) AS min_version,
                       max(applied_case_version) AS max_version
                FROM counseling_crisis_case_events
                WHERE case_id = cases.id
            ) AS event_stats ON TRUE
            LEFT JOIN counseling_crisis_case_events AS last_event
                ON last_event.id = cases.last_event_id AND last_event.case_id = cases.id
            WHERE cases.version < 1
               OR event_stats.event_count <> cases.version
               OR event_stats.min_version <> 1
               OR event_stats.max_version <> cases.version
               OR last_event.applied_case_version IS DISTINCT FROM cases.version
        ) THEN
            RAISE EXCEPTION 'counseling crisis event version history is inconsistent';
        END IF;
    END;
    $$
    """,
)

COUNSELING_SCHEMA_V15_STATEMENTS = (
    "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS business_roles JSONB",
    "UPDATE users SET business_roles = '[]'::jsonb WHERE business_roles IS NULL",
    "ALTER TABLE IF EXISTS users ALTER COLUMN business_roles SET DEFAULT '[]'::jsonb",
    "ALTER TABLE IF EXISTS users ALTER COLUMN business_roles SET NOT NULL",
    "ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_business_roles",
    """
    ALTER TABLE users ADD CONSTRAINT ck_users_business_roles
    CHECK (jsonb_typeof(business_roles) = 'array'
           AND business_roles <@ '["counselor", "supervisor", "business_admin", "super_admin"]'::jsonb)
    """,
    """
    CREATE TABLE counseling_supervision_authorizations (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        supervisor_id INTEGER NOT NULL REFERENCES users(id),
        scopes JSONB NOT NULL,
        purpose VARCHAR(500) NOT NULL,
        effective_from TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        version INTEGER NOT NULL DEFAULT 1,
        approved_by INTEGER REFERENCES users(id),
        approved_at TIMESTAMP WITHOUT TIME ZONE,
        rejected_by INTEGER REFERENCES users(id),
        rejected_at TIMESTAMP WITHOUT TIME ZONE,
        revoked_by INTEGER REFERENCES users(id),
        revoked_at TIMESTAMP WITHOUT TIME ZONE,
        decision_note VARCHAR(1000),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_supervision_auth_request UNIQUE (counselor_id, request_id),
        CONSTRAINT ck_counseling_supervision_auth_status CHECK (status IN ('pending', 'active', 'rejected', 'revoked')),
        CONSTRAINT ck_counseling_supervision_auth_window CHECK (expires_at > effective_from),
        CONSTRAINT ck_counseling_supervision_auth_scopes CHECK (
            jsonb_typeof(scopes) = 'array' AND jsonb_array_length(scopes) > 0
            AND scopes <@ '["case_overview", "supervision_feedback", "supervision_summary"]'::jsonb
        ),
        CONSTRAINT ck_counseling_supervision_auth_metadata CHECK (
            (status = 'pending' AND approved_by IS NULL AND rejected_by IS NULL AND revoked_by IS NULL)
            OR (status = 'active' AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND rejected_by IS NULL AND revoked_by IS NULL)
            OR (status = 'rejected' AND rejected_by IS NOT NULL AND rejected_at IS NOT NULL AND approved_by IS NULL AND revoked_by IS NULL)
            OR (status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
        )
    )
    """,
    "CREATE INDEX ix_counseling_supervision_auth_supervisor ON counseling_supervision_authorizations(supervisor_id, status, expires_at)",
    "CREATE INDEX ix_counseling_supervision_auth_student ON counseling_supervision_authorizations(student_id, created_at)",
    """
    CREATE TABLE counseling_supervision_materials (
        id VARCHAR(64) PRIMARY KEY,
        authorization_id VARCHAR(64) NOT NULL REFERENCES counseling_supervision_authorizations(id),
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        version_no INTEGER NOT NULL,
        case_alias VARCHAR(32) NOT NULL,
        stage VARCHAR(32) NOT NULL,
        concern_tags JSONB NOT NULL,
        session_count INTEGER NOT NULL,
        assessment_count INTEGER NOT NULL,
        risk_event_count INTEGER NOT NULL,
        created_by INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_supervision_material_version UNIQUE (authorization_id, version_no),
        CONSTRAINT uq_counseling_supervision_material_request UNIQUE (created_by, request_id),
        CONSTRAINT ck_counseling_supervision_material_stage CHECK (stage IN ('engagement', 'assessment', 'intervention', 'review', 'closure')),
        CONSTRAINT ck_counseling_supervision_material_counts CHECK (session_count >= 0 AND assessment_count >= 0 AND risk_event_count >= 0),
        CONSTRAINT ck_counseling_supervision_material_tags CHECK (
            jsonb_typeof(concern_tags) = 'array'
            AND concern_tags <@ '["adjustment", "anxiety", "mood", "relationships", "study", "sleep", "risk", "other"]'::jsonb)
    )
    """,
    """
    CREATE TABLE counseling_supervision_feedback (
        id VARCHAR(64) PRIMARY KEY,
        authorization_id VARCHAR(64) NOT NULL REFERENCES counseling_supervision_authorizations(id),
        material_id VARCHAR(64) NOT NULL REFERENCES counseling_supervision_materials(id),
        supervisor_id INTEGER NOT NULL REFERENCES users(id),
        focus_area VARCHAR(32) NOT NULL,
        comment TEXT NOT NULL,
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_supervision_feedback_request UNIQUE (supervisor_id, request_id),
        CONSTRAINT ck_counseling_supervision_feedback_focus CHECK (focus_area IN ('case_conceptualization', 'process', 'ethics', 'risk', 'referral'))
    )
    """,
    "CREATE INDEX ix_counseling_supervision_feedback_auth ON counseling_supervision_feedback(authorization_id, created_at)",
    """
    CREATE TABLE counseling_supervision_summaries (
        id VARCHAR(64) PRIMARY KEY,
        authorization_id VARCHAR(64) NOT NULL REFERENCES counseling_supervision_authorizations(id),
        material_id VARCHAR(64) NOT NULL REFERENCES counseling_supervision_materials(id),
        feedback_count INTEGER NOT NULL CHECK (feedback_count >= 0),
        focus_areas JSONB NOT NULL,
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_supervision_summary_request UNIQUE (counselor_id, request_id)
    )
    """,
    """
    CREATE TABLE counseling_external_recipients (
        id VARCHAR(64) PRIMARY KEY,
        department_id INTEGER NOT NULL REFERENCES departments(id),
        recipient_code VARCHAR(64) NOT NULL,
        display_name VARCHAR(200) NOT NULL,
        purpose VARCHAR(500) NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        verified_by INTEGER NOT NULL REFERENCES users(id),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_external_recipient_code UNIQUE (department_id, recipient_code),
        CONSTRAINT uq_counseling_external_recipient_request UNIQUE (department_id, request_id)
    )
    """,
    """
    CREATE TABLE counseling_external_authorizations (
        id VARCHAR(64) PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        department_id INTEGER NOT NULL REFERENCES departments(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        recipient_id VARCHAR(64) NOT NULL REFERENCES counseling_external_recipients(id),
        scopes JSONB NOT NULL,
        effective_from TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        version INTEGER NOT NULL DEFAULT 1,
        approved_by INTEGER REFERENCES users(id),
        approved_at TIMESTAMP WITHOUT TIME ZONE,
        rejected_by INTEGER REFERENCES users(id),
        rejected_at TIMESTAMP WITHOUT TIME ZONE,
        revoked_by INTEGER REFERENCES users(id),
        revoked_at TIMESTAMP WITHOUT TIME ZONE,
        decision_note VARCHAR(1000),
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_external_auth_request UNIQUE (counselor_id, request_id),
        CONSTRAINT ck_counseling_external_auth_status CHECK (status IN ('pending', 'active', 'rejected', 'revoked')),
        CONSTRAINT ck_counseling_external_auth_window CHECK (expires_at > effective_from),
        CONSTRAINT ck_counseling_external_auth_scopes CHECK (
            jsonb_typeof(scopes) = 'array' AND jsonb_array_length(scopes) > 0
            AND scopes <@ '["resource_catalog", "referral_status"]'::jsonb
        ),
        CONSTRAINT ck_counseling_external_auth_metadata CHECK (
            (status = 'pending' AND approved_by IS NULL AND rejected_by IS NULL AND revoked_by IS NULL)
            OR (status = 'active' AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND rejected_by IS NULL AND revoked_by IS NULL)
            OR (status = 'rejected' AND rejected_by IS NOT NULL AND rejected_at IS NOT NULL AND approved_by IS NULL AND revoked_by IS NULL)
            OR (status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE counseling_external_deliveries (
        id VARCHAR(64) PRIMARY KEY,
        authorization_id VARCHAR(64) NOT NULL REFERENCES counseling_external_authorizations(id),
        student_id INTEGER NOT NULL REFERENCES counseling_students(id),
        counselor_id INTEGER NOT NULL REFERENCES users(id),
        recipient_id VARCHAR(64) NOT NULL REFERENCES counseling_external_recipients(id),
        scopes JSONB NOT NULL,
        resource_codes JSONB NOT NULL,
        referral_id VARCHAR(64) REFERENCES counseling_referrals(id),
        token_hash VARCHAR(64) NOT NULL,
        token_expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'ready',
        version INTEGER NOT NULL DEFAULT 1,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        last_error VARCHAR(200),
        delivered_at TIMESTAMP WITHOUT TIME ZONE,
        withdrawn_at TIMESTAMP WITHOUT TIME ZONE,
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_counseling_external_delivery_request UNIQUE (counselor_id, request_id),
        CONSTRAINT uq_counseling_external_delivery_token UNIQUE (token_hash),
        CONSTRAINT ck_counseling_external_delivery_status CHECK (status IN ('ready', 'delivered', 'failed', 'withdrawn')),
        CONSTRAINT ck_counseling_external_delivery_window CHECK (token_expires_at > created_at),
        CONSTRAINT ck_counseling_external_delivery_attempts CHECK (failed_attempts >= 0),
        CONSTRAINT ck_counseling_external_delivery_scopes CHECK (
            jsonb_typeof(scopes) = 'array' AND jsonb_array_length(scopes) > 0
            AND scopes <@ '["resource_catalog", "referral_status"]'::jsonb
        ),
        CONSTRAINT ck_counseling_external_delivery_resources CHECK (
            jsonb_typeof(resource_codes) = 'array' AND jsonb_array_length(resource_codes) <= 20)
    )
    """,
    """
    CREATE OR REPLACE FUNCTION reject_counseling_p3_append_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'counseling P3 append-only record is immutable';
    END;
    $$
    """,
    "CREATE TRIGGER trg_counseling_supervision_material_immutable BEFORE UPDATE OR DELETE ON counseling_supervision_materials FOR EACH ROW EXECUTE FUNCTION reject_counseling_p3_append_mutation()",
    "CREATE TRIGGER trg_counseling_supervision_feedback_immutable BEFORE UPDATE OR DELETE ON counseling_supervision_feedback FOR EACH ROW EXECUTE FUNCTION reject_counseling_p3_append_mutation()",
    "CREATE TRIGGER trg_counseling_supervision_summary_immutable BEFORE UPDATE OR DELETE ON counseling_supervision_summaries FOR EACH ROW EXECUTE FUNCTION reject_counseling_p3_append_mutation()",
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_authorization_transition() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.student_id IS DISTINCT FROM OLD.student_id
           OR NEW.department_id IS DISTINCT FROM OLD.department_id
           OR NEW.counselor_id IS DISTINCT FROM OLD.counselor_id
           OR NEW.scopes IS DISTINCT FROM OLD.scopes
           OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
           OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
           OR NEW.request_id IS DISTINCT FROM OLD.request_id
           OR NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'counseling authorization origin or version is invalid';
        END IF;
        IF TG_TABLE_NAME = 'counseling_supervision_authorizations' THEN
            IF NEW.supervisor_id IS DISTINCT FROM OLD.supervisor_id OR NEW.purpose IS DISTINCT FROM OLD.purpose THEN
                RAISE EXCEPTION 'counseling supervision authorization target is immutable';
            END IF;
        ELSIF TG_TABLE_NAME = 'counseling_external_authorizations' THEN
            IF NEW.recipient_id IS DISTINCT FROM OLD.recipient_id THEN
                RAISE EXCEPTION 'counseling external authorization recipient is immutable';
            END IF;
        END IF;
        IF OLD.status = 'pending' AND NEW.status IN ('active', 'rejected') THEN
            RETURN NEW;
        ELSIF OLD.status = 'active' AND NEW.status = 'revoked' THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'counseling authorization transition is invalid';
    END;
    $$
    """,
    "CREATE TRIGGER trg_counseling_supervision_auth_transition BEFORE UPDATE ON counseling_supervision_authorizations FOR EACH ROW EXECUTE FUNCTION enforce_counseling_authorization_transition()",
    "CREATE TRIGGER trg_counseling_external_auth_transition BEFORE UPDATE ON counseling_external_authorizations FOR EACH ROW EXECUTE FUNCTION enforce_counseling_authorization_transition()",
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_delivery_transition() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.authorization_id IS DISTINCT FROM OLD.authorization_id
           OR NEW.student_id IS DISTINCT FROM OLD.student_id
           OR NEW.counselor_id IS DISTINCT FROM OLD.counselor_id
           OR NEW.recipient_id IS DISTINCT FROM OLD.recipient_id
           OR NEW.scopes IS DISTINCT FROM OLD.scopes
           OR NEW.resource_codes IS DISTINCT FROM OLD.resource_codes
           OR NEW.referral_id IS DISTINCT FROM OLD.referral_id
           OR NEW.request_id IS DISTINCT FROM OLD.request_id
           OR NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'counseling delivery origin or version is invalid';
        END IF;
        IF OLD.status = 'ready' AND NEW.status IN ('delivered', 'failed', 'withdrawn') THEN
            RETURN NEW;
        ELSIF OLD.status = 'failed' AND NEW.status IN ('ready', 'withdrawn') THEN
            RETURN NEW;
        ELSIF OLD.status = 'delivered' AND NEW.status = 'delivered'
              AND OLD.withdrawn_at IS NULL AND NEW.withdrawn_at IS NOT NULL THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'counseling delivery transition is invalid';
    END;
    $$
    """,
    "CREATE TRIGGER trg_counseling_external_delivery_transition BEFORE UPDATE ON counseling_external_deliveries FOR EACH ROW EXECUTE FUNCTION enforce_counseling_delivery_transition()",
)


COUNSELING_SCHEMA_V16_STATEMENTS = (
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_authorization_metadata() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.status = 'pending' AND (NEW.approved_by IS NOT NULL OR NEW.rejected_by IS NOT NULL OR NEW.revoked_by IS NOT NULL) THEN
            RAISE EXCEPTION 'counseling pending authorization metadata is invalid';
        ELSIF NEW.status = 'active' AND (NEW.approved_by IS NULL OR NEW.approved_at IS NULL OR NEW.rejected_by IS NOT NULL OR NEW.revoked_by IS NOT NULL) THEN
            RAISE EXCEPTION 'counseling active authorization metadata is invalid';
        ELSIF NEW.status = 'rejected' AND (NEW.rejected_by IS NULL OR NEW.rejected_at IS NULL OR NEW.approved_by IS NOT NULL OR NEW.revoked_by IS NOT NULL) THEN
            RAISE EXCEPTION 'counseling rejected authorization metadata is invalid';
        ELSIF NEW.status = 'revoked' AND (NEW.revoked_by IS NULL OR NEW.revoked_at IS NULL OR NEW.rejected_by IS NOT NULL) THEN
            RAISE EXCEPTION 'counseling revoked authorization metadata is invalid';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    "CREATE TRIGGER trg_counseling_supervision_auth_metadata BEFORE INSERT OR UPDATE ON counseling_supervision_authorizations FOR EACH ROW EXECUTE FUNCTION enforce_counseling_authorization_metadata()",
    "CREATE TRIGGER trg_counseling_external_auth_metadata BEFORE INSERT OR UPDATE ON counseling_external_authorizations FOR EACH ROW EXECUTE FUNCTION enforce_counseling_authorization_metadata()",
    """
    CREATE OR REPLACE FUNCTION enforce_counseling_p3_relation_consistency() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        expected_student INTEGER;
        expected_counselor INTEGER;
        expected_recipient VARCHAR(64);
        expected_authorization VARCHAR(64);
        expected_department INTEGER;
    BEGIN
        IF TG_TABLE_NAME = 'counseling_supervision_materials' THEN
            SELECT student_id INTO expected_student
            FROM counseling_supervision_authorizations WHERE id = NEW.authorization_id;
            IF expected_student IS NULL OR NEW.student_id <> expected_student THEN
                RAISE EXCEPTION 'counseling supervision material relation is invalid';
            END IF;
        ELSIF TG_TABLE_NAME = 'counseling_supervision_feedback' THEN
            SELECT authorization_id INTO expected_authorization
            FROM counseling_supervision_materials WHERE id = NEW.material_id;
            IF expected_authorization IS NULL OR NEW.authorization_id <> expected_authorization THEN
                RAISE EXCEPTION 'counseling supervision feedback relation is invalid';
            END IF;
        ELSIF TG_TABLE_NAME = 'counseling_supervision_summaries' THEN
            SELECT authorization_id INTO expected_authorization
            FROM counseling_supervision_materials WHERE id = NEW.material_id;
            IF expected_authorization IS NULL OR NEW.authorization_id <> expected_authorization THEN
                RAISE EXCEPTION 'counseling supervision summary relation is invalid';
            END IF;
        ELSIF TG_TABLE_NAME = 'counseling_external_deliveries' THEN
            SELECT student_id, counselor_id, recipient_id, department_id
              INTO expected_student, expected_counselor, expected_recipient, expected_department
            FROM counseling_external_authorizations WHERE id = NEW.authorization_id;
            IF expected_student IS NULL
               OR NEW.student_id <> expected_student
               OR NEW.counselor_id <> expected_counselor
               OR NEW.recipient_id <> expected_recipient
               OR NOT EXISTS (
                   SELECT 1 FROM counseling_external_recipients
                   WHERE id = NEW.recipient_id AND department_id = expected_department
               ) THEN
                RAISE EXCEPTION 'counseling external delivery relation is invalid';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    "CREATE TRIGGER trg_counseling_supervision_material_relation BEFORE INSERT OR UPDATE ON counseling_supervision_materials FOR EACH ROW EXECUTE FUNCTION enforce_counseling_p3_relation_consistency()",
    "CREATE TRIGGER trg_counseling_supervision_feedback_relation BEFORE INSERT OR UPDATE ON counseling_supervision_feedback FOR EACH ROW EXECUTE FUNCTION enforce_counseling_p3_relation_consistency()",
    "CREATE TRIGGER trg_counseling_supervision_summary_relation BEFORE INSERT OR UPDATE ON counseling_supervision_summaries FOR EACH ROW EXECUTE FUNCTION enforce_counseling_p3_relation_consistency()",
    "CREATE TRIGGER trg_counseling_external_delivery_relation BEFORE INSERT OR UPDATE ON counseling_external_deliveries FOR EACH ROW EXECUTE FUNCTION enforce_counseling_p3_relation_consistency()",
)


COUNSELING_SCHEMA_STATEMENTS = (
    COUNSELING_SCHEMA_V1_STATEMENTS
    + COUNSELING_SCHEMA_V2_STATEMENTS
    + COUNSELING_SCHEMA_V3_STATEMENTS
    + COUNSELING_SCHEMA_V4_STATEMENTS
    + COUNSELING_SCHEMA_V5_STATEMENTS
    + COUNSELING_SCHEMA_V6_STATEMENTS
    + COUNSELING_SCHEMA_V7_STATEMENTS
    + COUNSELING_SCHEMA_V8_STATEMENTS
    + COUNSELING_SCHEMA_V9_STATEMENTS
    + COUNSELING_SCHEMA_V10_STATEMENTS
    + COUNSELING_SCHEMA_V11_STATEMENTS
    + COUNSELING_SCHEMA_V12_STATEMENTS
    + COUNSELING_SCHEMA_V13_STATEMENTS
    + COUNSELING_SCHEMA_V14_STATEMENTS
    + COUNSELING_SCHEMA_V15_STATEMENTS
    + COUNSELING_SCHEMA_V16_STATEMENTS
)


async def migrate_legacy_business_schema(
    business_version: int,
    *,
    manager: PostgresManager | None = None,
) -> None:
    """在 business 版本发布前执行由业务侧拥有的历史兼容 DDL。"""
    if business_version not in {7, 8}:
        raise ValueError(f"Unsupported legacy business schema version: {business_version}")
    manager = manager or pg_manager
    statements = LEGACY_BUSINESS_V8_STUDENT_STATEMENTS
    if business_version == 7:
        statements = LEGACY_BUSINESS_V7_IDENTITY_STATEMENTS + statements
    async with manager.async_engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))


async def migrate_schema() -> None:
    """幂等创建业务表，并在全部成功后发布领域版本。"""
    pg_manager.initialize()
    try:
        async with pg_manager.schema_migration_lock():
            await pg_manager.create_schema_version_table()
            versions = await pg_manager.get_schema_versions()
            actual = versions.get("counseling")
            supported_versions = set(range(1, COUNSELING_SCHEMA_VERSION + 1))
            if actual is not None and actual not in supported_versions:
                raise RuntimeError(
                    "Unsupported counseling schema version: "
                    f"{actual}; supported upgrade sources are empty or v1 through v15"
                )
            if actual != COUNSELING_SCHEMA_VERSION:
                if actual is None:
                    statements = COUNSELING_SCHEMA_STATEMENTS
                else:
                    migrations = (
                        COUNSELING_SCHEMA_V1_STATEMENTS,
                        COUNSELING_SCHEMA_V2_STATEMENTS,
                        COUNSELING_SCHEMA_V3_STATEMENTS,
                        COUNSELING_SCHEMA_V4_STATEMENTS,
                        COUNSELING_SCHEMA_V5_STATEMENTS,
                        COUNSELING_SCHEMA_V6_STATEMENTS,
                        COUNSELING_SCHEMA_V7_STATEMENTS,
                        COUNSELING_SCHEMA_V8_STATEMENTS,
                        COUNSELING_SCHEMA_V9_STATEMENTS,
                        COUNSELING_SCHEMA_V10_STATEMENTS,
                        COUNSELING_SCHEMA_V11_STATEMENTS,
                        COUNSELING_SCHEMA_V12_STATEMENTS,
                        COUNSELING_SCHEMA_V13_STATEMENTS,
                        COUNSELING_SCHEMA_V14_STATEMENTS,
                        COUNSELING_SCHEMA_V15_STATEMENTS,
                        COUNSELING_SCHEMA_V16_STATEMENTS,
                    )
                    statements = tuple(statement for migration in migrations[actual:] for statement in migration)
                async with pg_manager.async_engine.begin() as connection:
                    for statement in statements:
                        await connection.execute(text(statement))
                    await connection.execute(
                        text(
                            f"""
                            INSERT INTO {SCHEMA_VERSION_TABLE} (domain, version, applied_at)
                            VALUES (:domain, :version, CURRENT_TIMESTAMP)
                            ON CONFLICT (domain) DO UPDATE
                            SET version = EXCLUDED.version, applied_at = EXCLUDED.applied_at
                            """
                        ),
                        {"domain": "counseling", "version": COUNSELING_SCHEMA_VERSION},
                    )
    finally:
        await pg_manager.close()


async def require_current_schema() -> None:
    """要求运行环境已完成心理辅导领域迁移。"""
    versions = await pg_manager.get_schema_versions()
    actual = versions.get("counseling")
    if actual != COUNSELING_SCHEMA_VERSION:
        raise RuntimeError(
            "Database schema migration is incomplete or incompatible: "
            f"counseling={actual if actual is not None else 'missing'} (required {COUNSELING_SCHEMA_VERSION})"
        )
