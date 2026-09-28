"""心理辅导业务与 Yuxi 平台包的依赖边界。"""

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[3]
YUXI_ROOT = BACKEND_ROOT / "package" / "yuxi"
COUNSELING_ROOT = BACKEND_ROOT / "counseling" / "src" / "counseling"
RUNTIME_ROOTS = (
    COUNSELING_ROOT,
    YUXI_ROOT,
    BACKEND_ROOT / "server",
    BACKEND_ROOT / "scripts",
)
IDENTITY_MODEL_NAMES = {"APIKey", "CLIAuthSession", "Department", "OperationLog", "User"}


def _imports(path: Path) -> set[str]:
    """返回 Python 文件中的绝对导入模块。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_yuxi_package_only_imports_identity_contract_from_counseling_domain() -> None:
    """AI 包只能读取业务身份契约，不得依赖档案等业务领域。"""
    violations = {
        str(path.relative_to(BACKEND_ROOT)): sorted(
            module
            for module in _imports(path)
            if (module == "counseling" or module.startswith("counseling."))
            and not module.startswith("counseling.identity")
        )
        for path in YUXI_ROOT.rglob("*.py")
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_counseling_domain_is_not_kept_under_yuxi_namespace() -> None:
    """新增业务模型、仓储和用例只能位于独立业务包。"""
    assert COUNSELING_ROOT.is_dir()
    assert not list((YUXI_ROOT / "services").glob("counseling*.py"))
    assert not list((YUXI_ROOT / "repositories").glob("counseling*.py"))
    assert not list((YUXI_ROOT / "storage" / "postgres").glob("models_counseling*.py"))
    manager_source = (YUXI_ROOT / "storage" / "postgres" / "manager.py").read_text(encoding="utf-8")
    assert "COUNSELING_RECORD_SCHEMA_STATEMENTS" not in manager_source


def test_runtime_consumers_import_identity_models_from_business_owner() -> None:
    """仓库运行时代码不能把 Yuxi 兼容出口继续当成身份 Owner。"""

    compatibility_module = YUXI_ROOT / "storage" / "postgres" / "models_business.py"
    violations: dict[str, list[str]] = {}
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*.py"):
            if path == compatibility_module:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported_names = sorted(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and node.module == "yuxi.storage.postgres.models_business"
                for alias in node.names
                if alias.name in IDENTITY_MODEL_NAMES
            )
            if imported_names:
                violations[str(path.relative_to(BACKEND_ROOT))] = imported_names

    assert not violations


def test_yuxi_no_longer_defines_identity_lifecycle_modules() -> None:
    """旧身份实现不能以双 Owner 形式重新出现。"""

    removed_paths = (
        YUXI_ROOT / "permissions" / "business_roles.py",
        YUXI_ROOT / "repositories" / "api_key_repository.py",
        YUXI_ROOT / "repositories" / "department_repository.py",
        YUXI_ROOT / "repositories" / "user_repository.py",
        YUXI_ROOT / "services" / "auth_service.py",
        YUXI_ROOT / "services" / "identity_admin_service.py",
        YUXI_ROOT / "services" / "login_rate_limit_service.py",
        YUXI_ROOT / "services" / "oidc_service.py",
        YUXI_ROOT / "services" / "operation_log_service.py",
        YUXI_ROOT / "services" / "user_identity_service.py",
        YUXI_ROOT / "utils" / "auth_utils.py",
    )
    assert not [path for path in removed_paths if path.exists()]
