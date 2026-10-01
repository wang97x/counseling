"""迁移装配入口必须在干净进程中注册跨域 ORM。"""

import subprocess
import sys


def test_storage_migration_entrypoint_registers_identity_models() -> None:
    """平台外键配置前必须存在业务拥有的 users 表。"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from server import storage_migration; "
                "from sqlalchemy.orm import configure_mappers; "
                "from yuxi.storage.postgres.base import Base; "
                "assert 'users' in Base.metadata.tables; "
                "configure_mappers()"
            ),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
