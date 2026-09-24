"""心理辅导业务与 Yuxi 平台包的依赖边界。"""

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[3]
YUXI_ROOT = BACKEND_ROOT / "package" / "yuxi"
COUNSELING_ROOT = BACKEND_ROOT / "counseling" / "src" / "counseling"


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


def test_yuxi_package_does_not_import_counseling_domain() -> None:
    """平台包不能反向依赖心理辅导业务包。"""
    violations = {
        str(path.relative_to(BACKEND_ROOT)): sorted(
            module for module in _imports(path) if module == "counseling" or module.startswith("counseling.")
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
