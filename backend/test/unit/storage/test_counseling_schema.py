"""心理辅导 Schema 由独立领域迁移拥有。"""

from unittest.mock import AsyncMock

import pytest
from counseling.storage import schema

from server import storage_migration


async def test_counseling_schema_validation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺失或超前的业务 Schema 版本都不能启动 API。"""
    monkeypatch.setattr(schema.pg_manager, "get_schema_versions", AsyncMock(return_value={}))
    with pytest.raises(RuntimeError, match="counseling=missing"):
        await schema.require_current_schema()

    monkeypatch.setattr(
        schema.pg_manager,
        "get_schema_versions",
        AsyncMock(return_value={"counseling": schema.COUNSELING_SCHEMA_VERSION + 1}),
    )
    with pytest.raises(RuntimeError, match=f"counseling={schema.COUNSELING_SCHEMA_VERSION + 1}"):
        await schema.require_current_schema()


async def test_composed_migrator_orders_platform_before_counseling(monkeypatch: pytest.MonkeyPatch) -> None:
    """业务外键依赖的平台表必须先于业务表迁移。"""
    calls: list[str] = []

    async def migrate_platform(**_kwargs) -> None:
        calls.append("platform")

    async def migrate_counseling() -> None:
        calls.append("counseling")

    monkeypatch.setattr(storage_migration, "migrate_yuxi_schema", migrate_platform)
    monkeypatch.setattr(storage_migration, "migrate_counseling_schema", migrate_counseling)

    await storage_migration.main()

    assert calls == ["platform", "counseling"]


def test_counseling_schema_backfills_generic_model_context() -> None:
    """旧档案会话升级后继续把原确认快照提供给模型。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_STATEMENTS)

    assert "UPDATE conversations" in migration_sql
    assert "(extra_metadata::jsonb)->'counseling'" in migration_sql
    assert "extra_metadata::jsonb ? 'counseling'" in migration_sql
    assert "'{model_context}'" in migration_sql


def test_counseling_schema_v2_adds_minimal_workflow_guards() -> None:
    """v2 同时拥有风险历史、追加更正和数据库不可变保护。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V2_STATEMENTS)

    assert schema.COUNSELING_SCHEMA_VERSION == 14
    assert "current_risk_level" in migration_sql
    assert "counseling_risk_events" in migration_sql
    assert "counseling_record_corrections" in migration_sql
    assert "trg_counseling_corrections_immutable" in migration_sql
    assert "ALTER COLUMN summary DROP NOT NULL" in migration_sql


def test_counseling_schema_v3_owns_business_role_migration() -> None:
    """v3 将旧技术角色转换为业务模块拥有的超级管理角色。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V3_STATEMENTS)

    assert "technical_admin" in migration_sql
    assert "super_admin" in migration_sql
    assert "ck_users_business_roles" in migration_sql


def test_counseling_schema_v4_adds_ai_work_items_and_materials() -> None:
    """v4 独立保存协作任务与人工审核材料。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V4_STATEMENTS)

    assert "counseling_ai_work_items" in migration_sql
    assert "counseling_materials" in migration_sql
    assert "preparing', 'ready', 'failed" in migration_sql
    assert "importing', 'pending_review', 'active', 'rejected" in migration_sql
    assert "DEFAULT 'importing'" in migration_sql
    assert "uq_counseling_material_source" in migration_sql


def test_counseling_schema_v6_adds_assessments_and_appointments() -> None:
    """v6 保存冻结量表结果与带乐观版本的内部预约。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V6_STATEMENTS)

    assert schema.COUNSELING_SCHEMA_VERSION == 14
    assert "counseling_assessment_results" in migration_sql
    assert "scale_code = 'phq9' AND scale_version = 1" in migration_sql
    assert "trg_counseling_assessments_immutable" in migration_sql
    assert "counseling_appointments" in migration_sql
    assert "scheduled_end > scheduled_start" in migration_sql
    assert "'scheduled', 'arrived', 'completed', 'no_show', 'canceled'" in migration_sql


def test_counseling_schema_v7_freezes_appointment_creation_intent() -> None:
    """v7 回填并冻结预约创建时的幂等比较字段。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V7_STATEMENTS)

    assert "created_scheduled_start" in migration_sql
    assert "COALESCE(created_scheduled_start, scheduled_start)" in migration_sql
    assert "ALTER COLUMN created_note SET NOT NULL" in migration_sql


def test_counseling_schema_v8_guards_appointment_creation_intent() -> None:
    """v8 在数据库边界拒绝修改预约创建意图。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V8_STATEMENTS)

    assert "creation intent is immutable" in migration_sql
    assert "IS DISTINCT FROM OLD.created_note" in migration_sql
    assert "BEFORE UPDATE ON counseling_appointments" in migration_sql


def test_counseling_schema_v9_adds_immutable_continuity_history() -> None:
    """v9 保存方案、协议、工单和内部转介并冻结追加历史。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V9_STATEMENTS)

    assert "counseling_plan_versions" in migration_sql
    assert "counseling_crisis_protocols" in migration_sql
    assert "counseling_crisis_cases" in migration_sql
    assert "counseling_crisis_case_events" in migration_sql
    assert "counseling_referrals" in migration_sql
    assert "counseling P2 history is immutable" in migration_sql
    assert "trg_counseling_plan_immutable" in migration_sql


def test_counseling_schema_v10_adds_gated_human_reviewed_risk_hints() -> None:
    """v10 冻结评测与提示来源，并只允许一次人工核实状态迁移。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V10_STATEMENTS)

    assert "counseling_risk_hint_evaluations" in migration_sql
    assert "counseling_risk_hints" in migration_sql
    assert "dataset_fingerprint" in migration_sql
    assert "pending_review', 'accepted', 'rejected" in migration_sql
    assert "trg_counseling_risk_hint_eval_immutable" in migration_sql
    assert "counseling risk hint origin is immutable" in migration_sql
    assert "counseling risk hint transition is invalid" in migration_sql


def test_counseling_schema_v5_adds_immutable_data_use_acknowledgments() -> None:
    """v5 持久保存按版本确认且数据库拒绝覆盖。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V5_STATEMENTS)

    assert "counseling_data_use_acknowledgments" in migration_sql
    assert "PRIMARY KEY (user_id, notice_version)" in migration_sql
    assert "trg_counseling_notice_immutable" in migration_sql
    assert "BEFORE UPDATE OR DELETE" in migration_sql


def test_counseling_schema_v11_enforces_metrics_and_p2_transitions() -> None:
    """v11 在数据库边界验证评测派生值并绑定状态迁移事实。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V11_STATEMENTS)

    assert "ck_counseling_risk_hint_eval_consistent" in migration_sql
    assert "passed = (recall >= 0.95 AND false_positive_rate <= 0.05)" in migration_sql
    assert "last_event_id" in migration_sql
    assert "enforce_counseling_crisis_case_transition" in migration_sql
    assert "enforce_counseling_referral_transition" in migration_sql

def test_counseling_schema_v12_binds_hints_to_immutable_run_outputs() -> None:
    """v12 要求提示绑定已完成 Run 的唯一输出消息。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V12_STATEMENTS)

    assert "source_work_item_id" in migration_sql
    assert "source_run_id" in migration_sql
    assert "source_message_id" in migration_sql
    assert "uq_counseling_risk_hint_source_message" in migration_sql
    assert "cannot bind legacy risk hints" in migration_sql
    assert "DROP CONSTRAINT IF EXISTS fk_counseling_risk_hint_work_item" in migration_sql


def test_counseling_schema_v13_prevents_event_reuse_and_decision_rewrite() -> None:
    """v13 将危机事件绑定唯一版本，并冻结已作出的转介决定。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V13_STATEMENTS)

    assert "applied_case_version <> NEW.version" in migration_sql
    assert "uq_counseling_crisis_event_version" in migration_sql
    assert "counseling referral decision metadata is immutable" in migration_sql
    assert "cannot reconstruct legacy crisis event application order" in migration_sql


def test_counseling_schema_v14_rejects_inconsistent_event_history() -> None:
    """v14 在发布版本前拒绝不连续或末事件不一致的历史。"""
    migration_sql = "\n".join(schema.COUNSELING_SCHEMA_V14_STATEMENTS)

    assert "event_count <> cases.version" in migration_sql
    assert "cases.version < 1" in migration_sql
    assert "last_event.applied_case_version IS DISTINCT FROM cases.version" in migration_sql
