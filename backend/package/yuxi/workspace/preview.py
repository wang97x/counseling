"""UserWorkspace 文件字节预览。"""

from __future__ import annotations

from pathlib import PurePosixPath

from yuxi.utils.filepreview import (
    PreviewResult,
    convert_office_to_html,
    is_office_html_preview_file,
    render_preview,
)


async def preview_workspace_file(
    path: str,
    raw_content: bytes,
) -> PreviewResult:
    """把 UserWorkspace 文件字节渲染为预览结果。"""
    if is_office_html_preview_file(path):
        html_content = await convert_office_to_html(PurePosixPath(path).name, raw_content)
        return PreviewResult(
            content=html_content,
            preview_type="html",
            supported=True,
        )

    return render_preview(path, raw_content)
