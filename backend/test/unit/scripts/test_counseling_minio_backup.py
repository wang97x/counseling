"""心理辅导 MinIO 备份脚本的失败边界。"""

from types import SimpleNamespace

import pytest
from scripts import counseling_minio_backup as backup


class _FailingResponse:
    def __init__(self) -> None:
        self.closed = False
        self.released = False

    def read(self, _size: int = -1) -> bytes:
        return b"partial"

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _Storage:
    def __init__(self) -> None:
        self.response = _FailingResponse()

    def list_buckets(self):
        return [SimpleNamespace(name="materials")]

    def list_objects(self, _bucket, recursive=True):
        assert recursive is True
        return [SimpleNamespace(object_name="object-1", size=16)]

    def get_object(self, _bucket, _object_name):
        return self.response


def test_export_failure_preserves_previous_archive(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对象读取不足时不覆盖上一份归档，并清理临时文件。"""
    archive = tmp_path / "backup.tar"
    previous = b"known-good-backup"
    archive.write_bytes(previous)
    storage = _Storage()
    monkeypatch.setattr(
        backup,
        "get_minio_client",
        lambda: SimpleNamespace(client=storage),
    )

    with pytest.raises((OSError, RuntimeError)):
        backup.export_backup(archive)

    assert archive.read_bytes() == previous
    assert list(tmp_path.glob(f".{archive.name}.*.tmp")) == []
    assert storage.response.closed is True
    assert storage.response.released is True
