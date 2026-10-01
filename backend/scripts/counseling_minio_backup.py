"""导出 MinIO 对象并在隔离桶中执行恢复校验。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tarfile
import tempfile
import uuid
from pathlib import Path

from yuxi.storage.minio.client import get_minio_client


class _HashingReader:
    """流式读取对象并同步计算字节数和摘要。"""

    def __init__(self, response) -> None:
        self.response = response
        self.size = 0
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.response.read(size)
        if data:
            self.digest.update(data)
            self.size += len(data)
        return data


def _export_backup_file(path: Path, storage) -> dict:
    """把全部桶对象流式写入指定临时 tar。"""
    manifest = {"version": 1, "objects": []}
    with tarfile.open(path, "w") as archive:
        index = 0
        for bucket in storage.list_buckets():
            for item in storage.list_objects(bucket.name, recursive=True):
                response = storage.get_object(bucket.name, item.object_name)
                reader = _HashingReader(response)
                try:
                    member_name = f"objects/{index:08d}"
                    info = tarfile.TarInfo(member_name)
                    info.size = int(item.size)
                    archive.addfile(info, reader)
                    if reader.size != info.size:
                        raise RuntimeError(f"object size changed during backup: {item.object_name}")
                finally:
                    response.close()
                    response.release_conn()
                manifest["objects"].append(
                    {
                        "bucket": bucket.name,
                        "object_name": item.object_name,
                        "member": member_name,
                        "size": reader.size,
                        "sha256": reader.digest.hexdigest(),
                    }
                )
                index += 1
        payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return manifest


def export_backup(path: Path) -> dict:
    """原子替换目标文件，失败时保留上一份可用备份。"""
    storage = get_minio_client().client
    path = path.resolve()
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        manifest = _export_backup_file(temporary_path, storage)
        os.replace(temporary_path, path)
        return manifest
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def verify_restore(
    path: Path,
    *,
    expected_object: tuple[str, str, int, str] | None = None,
) -> dict:
    """恢复到随机隔离桶并逐对象回读哈希，结束后删除隔离桶。"""
    storage = get_minio_client().client
    token = uuid.uuid4().hex[:10]
    created: set[str] = set()
    verified = 0
    expected_verified = expected_object is None
    try:
        with tarfile.open(path, "r") as archive:
            manifest_file = archive.extractfile("manifest.json")
            if manifest_file is None:
                raise RuntimeError("backup manifest is missing")
            manifest = json.load(manifest_file)
            if manifest.get("version") != 1:
                raise RuntimeError("unsupported backup version")
            bucket_map: dict[str, str] = {}
            for entry in manifest.get("objects", []):
                source_bucket = str(entry["bucket"])
                restore_bucket = bucket_map.setdefault(
                    source_bucket,
                    f"drill-{token}-{hashlib.sha256(source_bucket.encode()).hexdigest()[:12]}",
                )
                if restore_bucket not in created:
                    storage.make_bucket(restore_bucket)
                    created.add(restore_bucket)
                member = archive.extractfile(str(entry["member"]))
                if member is None:
                    raise RuntimeError(f"backup member is missing: {entry['member']}")
                data = member.read()
                digest = hashlib.sha256(data).hexdigest()
                if len(data) != int(entry["size"]) or digest != entry["sha256"]:
                    raise RuntimeError(f"backup checksum mismatch: {entry['member']}")
                storage.put_object(
                    restore_bucket,
                    str(entry["object_name"]),
                    io.BytesIO(data),
                    len(data),
                )
                response = storage.get_object(restore_bucket, str(entry["object_name"]))
                try:
                    restored = response.read()
                finally:
                    response.close()
                    response.release_conn()
                if hashlib.sha256(restored).hexdigest() != entry["sha256"]:
                    raise RuntimeError(f"restored object mismatch: {entry['object_name']}")
                if expected_object is not None and (
                    source_bucket,
                    str(entry["object_name"]),
                ) == expected_object[:2]:
                    restored_digest = hashlib.sha256(restored).hexdigest()
                    if len(restored) != expected_object[2] or restored_digest != expected_object[3]:
                        raise RuntimeError("restored synthetic object mismatch")
                    expected_verified = True
                verified += 1
        if not expected_verified:
            raise RuntimeError("restore drill did not verify the synthetic object")
        return {"verified_objects": verified, "restore_buckets": len(created)}
    finally:
        for bucket in created:
            for item in storage.list_objects(bucket, recursive=True):
                storage.remove_object(bucket, item.object_name)
            storage.remove_bucket(bucket)


def run_drill(path: Path) -> dict:
    """加入合成探针后备份，并验证隔离恢复至少包含该对象。"""
    storage = get_minio_client().client
    bucket = "counseling-backup-drill"
    object_name = f"synthetic/{uuid.uuid4().hex}.txt"
    data = b"counseling backup restore drill\n"
    created_bucket = not storage.bucket_exists(bucket)
    if created_bucket:
        storage.make_bucket(bucket)
    try:
        storage.put_object(bucket, object_name, io.BytesIO(data), len(data), content_type="text/plain")
        exported = export_backup(path)
    finally:
        storage.remove_object(bucket, object_name)
        if created_bucket:
            storage.remove_bucket(bucket)
    restored = verify_restore(
        path,
        expected_object=(
            bucket, object_name, len(data), hashlib.sha256(data).hexdigest()
        ),
    )
    return {"exported_objects": len(exported["objects"]), **restored}


def main() -> None:
    """执行导出或隔离恢复校验。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("export", "verify", "drill"))
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.action == "export":
        result = export_backup(args.archive)
    elif args.action == "verify":
        result = verify_restore(args.archive)
    else:
        result = run_drill(args.archive)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
