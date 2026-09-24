"""按平台、业务顺序执行完整存储迁移。"""

import asyncio

from counseling.storage.schema import migrate_schema as migrate_counseling_schema
from yuxi.storage_migration import main as migrate_yuxi_schema


async def main() -> None:
    """先迁移 Yuxi 平台事实，再迁移心理辅导领域事实。"""
    await migrate_yuxi_schema()
    await migrate_counseling_schema()


if __name__ == "__main__":
    asyncio.run(main())
