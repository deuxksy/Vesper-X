from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from vesper_x.extractors.gofile import GofileResolver

# 실제 캡처한 응답 구조 (2026-08-21 실접속 검증)
CONTENTS_RESPONSE = {
    "status": "ok",
    "data": {
        "id": "8ce63d41-375c-47a5-b9b4-19a1cb546ba5",
        "type": "folder",
        "children": {
            "f1": {
                "type": "file",
                "id": "d43d2fa3-c6a5-4e05-a9fe-2e218240d0cb",
                "name": "NS - Akane Shinjo - Gridman.rar",
                "serverSelected": "store3",
                "size": 697570110,
            },
            "f2": {
                "type": "file",
                "id": "11111111-2222-3333-4444-555555555555",
                "name": "YU - Cantarella - Wuthering Waves.rar",
                "serverSelected": "store-eu-par-5",
                "size": 3730900078,
            },
        },
    },
}


def test_build_downloads_from_contents_response():
    downloads = GofileResolver.build_downloads(
        CONTENTS_RESPONSE, token="tok123"
    )
    assert len(downloads) == 2
    d = downloads[0]
    assert d.direct_url == (
        "https://store3.gofile.io/download/web/"
        "d43d2fa3-c6a5-4e05-a9fe-2e218240d0cb/"
        "NS%20-%20Akane%20Shinjo%20-%20Gridman.rar"
    )
    assert d.filename == "NS - Akane Shinjo - Gridman.rar"
    assert d.cookies == "accountToken=tok123"
    assert downloads[1].direct_url.startswith(
        "https://store-eu-par-5.gofile.io/download/web/11111111"
    )


def test_build_downloads_walks_nested_folders():
    nested = {
        "status": "ok",
        "data": {
            "children": {
                "dir1": {
                    "type": "folder",
                    "children": {
                        "f1": {
                            "type": "file",
                            "id": "aaaaaaaa-0000-0000-0000-000000000001",
                            "name": "part1.rar",
                            "serverSelected": "store3",
                        },
                    },
                },
            },
        },
    }
    downloads = GofileResolver.build_downloads(nested, token="t")
    assert [d.filename for d in downloads] == ["part1.rar"]


def test_build_downloads_skips_error_response():
    downloads = GofileResolver.build_downloads({"status": "error-notPremium"}, token="t")
    assert downloads == []


class FakeResponse:
    def __init__(self, url, body: bytes):
        self.url = url
        self._body = body

    async def body(self):
        return self._body


class FakeGoPage:
    """goto 시 사이트처럼 contents XHR 응답을 발생시키는 페이지 흉내."""

    def __init__(self, content_id: str, body: bytes):
        self.content_id = content_id
        self.body = body
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, url, **kwargs):
        resp = FakeResponse(
            f"https://api.gofile.io/contents/{self.content_id}?page=1",
            self.body,
        )
        if "response" in self.handlers:
            await self.handlers["response"](resp)
        self.url = url

    async def wait_for_timeout(self, ms):
        pass

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_resolve_captures_contents_response_and_cookie():
    import json

    page = FakeGoPage("N09Oj1mA", json.dumps(CONTENTS_RESPONSE).encode())
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(
        return_value=SimpleNamespace(
            chromium=SimpleNamespace(
                launch=AsyncMock(
                    return_value=SimpleNamespace(
                        new_context=AsyncMock(
                            return_value=SimpleNamespace(
                                new_page=AsyncMock(return_value=page),
                                cookies=AsyncMock(
                                    return_value=[
                                        {"name": "accountToken", "value": "tok123"},
                                        {"name": "other", "value": "x"},
                                    ]
                                ),
                            )
                        ),
                        close=AsyncMock(),
                    )
                )
            )
        )
    )
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("vesper_x.extractors.gofile.async_playwright", MagicMock(return_value=fake_ctx)):
        downloads = await GofileResolver().resolve("https://gofile.io/d/N09Oj1mA")

    assert len(downloads) == 2
    assert downloads[0].filename == "NS - Akane Shinjo - Gridman.rar"
    assert downloads[0].cookies == "accountToken=tok123"
