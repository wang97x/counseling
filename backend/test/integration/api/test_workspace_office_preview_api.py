from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_office_preview_returns_structured_html_without_converter_cache(test_client, admin_headers):
    """真实上传和预览直接返回结构化 HTML。"""
    fixture = Path(__file__).resolve().parents[2] / "data" / "测试文档.docx"
    filename = f"pytest-office-preview-{uuid4().hex}.docx"
    workspace_path = f"/{filename}"
    try:
        with fixture.open("rb") as source:
            upload = await test_client.post(
                "/api/workspace/upload",
                data={"parent_path": "/"},
                files={
                    "files": (
                        filename,
                        source,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                headers=admin_headers,
            )
        assert upload.status_code == 200, upload.text

        first = await test_client.get("/api/workspace/file", params={"path": workspace_path}, headers=admin_headers)
        second = await test_client.get("/api/workspace/file", params={"path": workspace_path}, headers=admin_headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.headers["content-type"].startswith("application/json")
        assert first.json()["preview_type"] == "html"
        assert first.json()["supported"] is True
        assert "20XX个人述职报告" in first.json()["content"]
        assert second.json()["content"] == first.json()["content"]
    finally:
        await test_client.delete("/api/workspace/file", params={"path": workspace_path}, headers=admin_headers)
