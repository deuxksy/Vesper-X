"""proxy 통일 — config.proxy가 httpx / ouo / gofile 경로로 전달되는지 검증."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vesper_x.cli import resolve_post
from vesper_x.config import AppConfig
from vesper_x.extractors.gofile import GofileDownload, GofileResolver
from vesper_x.extractors.ouo import OuoBypasser

PROXY = "http://brla.bun-bull.ts.net:8888"


def test_resolve_post_passes_proxy_to_httpx_get():
    http_resp = MagicMock()
    http_resp.text = "<html><body>no download links</body></html>"
    with patch("vesper_x.cli.httpx.get", return_value=http_resp) as mock_get:
        results = resolve_post("https://misskon.com/some-post/", config=AppConfig(proxy=PROXY))
    assert mock_get.call_args.kwargs.get("proxy") == PROXY
    assert results == []


def test_resolve_post_constructs_resolvers_with_proxy():
    http_resp = MagicMock()
    http_resp.text = '<html><body><a href="https://ouo.io/abc123">dl</a></body></html>'
    with patch("vesper_x.cli.httpx.get", return_value=http_resp), \
         patch("vesper_x.cli.OuoBypasser") as ouo_cls, \
         patch("vesper_x.cli.GofileResolver") as gofile_cls:
        ouo_cls.return_value.resolve = AsyncMock(return_value="https://gofile.io/d/xyz")
        gofile_cls.return_value.resolve = AsyncMock(return_value=[
            GofileDownload("https://store3.gofile.io/download/web/id1/a.rar", "a.rar", "accountToken=t")
        ])
        results = resolve_post("https://misskon.com/x/", config=AppConfig(proxy=PROXY))
    ouo_cls.assert_called_once_with(proxy=PROXY)
    gofile_cls.assert_called_once_with(proxy=PROXY)
    assert len(results) == 1


class _NoOpPage:
    """bypass 흐름에서 버튼 없이 종료되는 최소 page fake."""

    url = "https://ouo.io/abc123"

    def on(self, event, handler):
        pass

    async def goto(self, url, **kwargs):
        pass

    async def wait_for_timeout(self, ms):
        pass

    async def query_selector(self, selector):
        return None


def _fake_playwright_capturing_launch(launch_mock):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=SimpleNamespace(
        chromium=SimpleNamespace(launch=launch_mock)
    ))
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_ouo_bypasser_launches_browser_with_proxy():
    launch_mock = AsyncMock(return_value=SimpleNamespace(
        new_context=AsyncMock(return_value=SimpleNamespace(
            new_page=AsyncMock(return_value=_NoOpPage())
        )),
        close=AsyncMock(),
    ))
    with patch("vesper_x.extractors.ouo.async_playwright", _fake_playwright_capturing_launch(launch_mock)):
        await OuoBypasser(proxy=PROXY)._run_playwright_bypass("https://ouo.io/abc123")
    assert launch_mock.call_args.kwargs.get("proxy") == {"server": PROXY}


@pytest.mark.asyncio
async def test_ouo_bypasser_without_proxy_launches_plain():
    launch_mock = AsyncMock(return_value=SimpleNamespace(
        new_context=AsyncMock(return_value=SimpleNamespace(
            new_page=AsyncMock(return_value=_NoOpPage())
        )),
        close=AsyncMock(),
    ))
    with patch("vesper_x.extractors.ouo.async_playwright", _fake_playwright_capturing_launch(launch_mock)):
        await OuoBypasser()._run_playwright_bypass("https://ouo.io/abc123")
    assert "proxy" not in launch_mock.call_args.kwargs or launch_mock.call_args.kwargs.get("proxy") is None


@pytest.mark.asyncio
async def test_gofile_resolver_launches_browser_with_proxy():
    page = SimpleNamespace(
        on=lambda *a, **k: None,
        goto=AsyncMock(),
        wait_for_timeout=AsyncMock(),
    )
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=page),
        cookies=AsyncMock(return_value=[]),
    )
    launch_mock = AsyncMock(return_value=SimpleNamespace(
        new_context=AsyncMock(return_value=context),
        close=AsyncMock(),
    ))
    with patch("vesper_x.extractors.gofile.async_playwright", _fake_playwright_capturing_launch(launch_mock)):
        result = await GofileResolver(proxy=PROXY).resolve("https://gofile.io/d/xyz")
    # body를 캡처하지 못하면 [] 반환 - 이 테스트의 관심사는 launch kwargs
    assert result == []
    assert launch_mock.call_args.kwargs.get("proxy") == {"server": PROXY}
