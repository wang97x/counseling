"""心理辅导领域的 PostgreSQL Schema 版本与迁移。"""

from sqlalchemy import text
from yuxi.storage.postgres.manager import PostgresManager, pg_manager

COUNSELING_SCHEMA_VERSION = 5
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

COUNSELING_SCHEMA_STATEMENTS = (
    COUNSELING_SCHEMA_V1_STATEMENTS
    + COUNSELING_SCHEMA_V2_STATEMENTS
    + COUNSELING_SCHEMA_V3_STATEMENTS
    + COUNSELING_SCHEMA_V4_STATEMENTS
    + COUNSELING_SCHEMA_V5_STATEMENTS
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
            if actual not in {None, 1, 2, 3, 4, COUNSELING_SCHEMA_VERSION}:
                raise RuntimeError(
                    "Unsupported counseling schema version: "
                    f"{actual}; supported upgrade sources are empty, v1, v2, v3 or v4"
                )
            if actual != COUNSELING_SCHEMA_VERSION:
                if actual is None:
                    statements = COUNSELING_SCHEMA_STATEMENTS
                elif actual == 1:
                    statements = (
                        COUNSELING_SCHEMA_V2_STATEMENTS
                        + COUNSELING_SCHEMA_V3_STATEMENTS
                        + COUNSELING_SCHEMA_V4_STATEMENTS
                        + COUNSELING_SCHEMA_V5_STATEMENTS
                    )
                elif actual == 2:
                    statements = (
                        COUNSELING_SCHEMA_V3_STATEMENTS
                        + COUNSELING_SCHEMA_V4_STATEMENTS
                        + COUNSELING_SCHEMA_V5_STATEMENTS
                    )
                elif actual == 3:
                    statements = COUNSELING_SCHEMA_V4_STATEMENTS + COUNSELING_SCHEMA_V5_STATEMENTS
                else:
                    statements = COUNSELING_SCHEMA_V5_STATEMENTS
                async with pg_manager.async_engine.begin() as connection:
                    for statement in statements:
                        await connection.execute(text(statement))
                await pg_manager.record_schema_version("counseling", COUNSELING_SCHEMA_VERSION)
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
