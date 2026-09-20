"""Knowledge 文件的 MinIO 预览。"""

from __future__ import annotations

from yuxi.knowledge.utils.kb_utils import is_minio_url, parse_minio_url
from yuxi.repositories.knowledge_file_repository import KnowledgeFileRepository
from yuxi.storage.minio import get_minio_client
from yuxi.utils.filepreview import (
    MAX_BINARY_PREVIEW_SIZE_BYTES,
    OfficePreviewConversionError,
    convert_office_to_html,
    is_office_html_preview_file,
    preview_too_large,
    render_preview,
)


async def read_knowledge_file_preview(kb_id: str, file_id: str) -> dict:
    """从 Knowledge metadata 与 MinIO 对象生成只读文件预览。"""
    file_record = await KnowledgeFileRepository().get_by_file_id(file_id)
    if file_record is None or file_record.kb_id != kb_id:
        raise ValueError(f"File {file_id} not found")
    if file_record.is_folder:
        raise ValueError("Cannot preview a folder")

    filename = file_record.filename or file_record.original_filename or file_id
    response = {
        "source": "knowledge",
        "kb_id": kb_id,
        "file_id": file_id,
        "filename": filename,
        "readonly": True,
    }
    original_path = file_record.minio_url or file_record.path
    if not original_path:
        return {
            **response,
            "content": None,
            "preview_type": "unsupported",
            "supported": False,
            "message": "文件没有可预览的原始内容",
        }

    file_size = file_record.file_size
    if file_size is None:
        file_size = await _get_minio_file_size(original_path)
    if file_size is not None and int(file_size) > MAX_BINARY_PREVIEW_SIZE_BYTES:
        return {**response, **preview_too_large().payload()}

    if is_office_html_preview_file(filename):
        raw_content = await _read_minio_bytes(original_path)
        if len(raw_content) > MAX_BINARY_PREVIEW_SIZE_BYTES:
            return {**response, **preview_too_large().payload()}
        try:
            html_content = await convert_office_to_html(filename, raw_content)
        except OfficePreviewConversionError as exc:
            raise ValueError(str(exc)) from exc
        return {
            **response,
            "content": html_content,
            "preview_type": "html",
            "supported": True,
            "message": None,
        }

    raw_content = await _read_minio_bytes(original_path)
    if len(raw_content) > MAX_BINARY_PREVIEW_SIZE_BYTES:
        return {**response, **preview_too_large().payload()}
    result = render_preview(filename, raw_content)
    if isinstance(result.content, bytes):
        return {
            **response,
            "content": result.content,
            "media_type": result.media_type,
            "preview_type": result.preview_type,
            "supported": result.supported,
            "message": result.message,
            "binary": True,
        }
    return {**response, **result.payload()}


async def _get_minio_file_size(file_path: str) -> int | None:
    bucket_name, object_name = _parse_minio_path(file_path)
    return await get_minio_client().astat_file(bucket_name, object_name)


async def _read_minio_bytes(file_path: str) -> bytes:
    bucket_name, object_name = _parse_minio_path(file_path)
    return await get_minio_client().adownload_file(bucket_name, object_name)


def _parse_minio_path(file_path: str) -> tuple[str, str]:
    if not file_path or not is_minio_url(file_path):
        raise ValueError(f"Invalid MinIO path format: {file_path}")
    return parse_minio_url(file_path)
