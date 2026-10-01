"""辅导文档用例依赖的外部能力端口。"""

from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class CounselingObjectStorageError(Exception):
    """表示业务对象存储暂时无法提供完整对象。"""


class CounselingDocumentParser(Protocol):
    """定义业务文件解析所需的最小能力。"""

    async def parse(self, path: Path, *, db: AsyncSession) -> str:
        """解析本地临时文件并返回文本。"""
        ...


class CounselingObjectStorage(Protocol):
    """定义业务来源文件所需的对象存储能力。"""

    async def upload(self, bucket: str, object_name: str, data: bytes, content_type: str) -> None:
        """上传完整对象。"""
        ...

    async def download(self, bucket: str, object_name: str) -> bytes:
        """下载完整对象。"""
        ...

    async def delete(self, bucket: str, object_name: str) -> None:
        """删除对象，用于补偿未提交的业务写入。"""
        ...
