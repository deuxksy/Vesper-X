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


def test_resolve_post_mediafire_fetch_is_direct_not_proxied():
    """mediafire 직링크는 요청 IP에 묶인다 - 프록시(SG)로 resolve하면 heritage가
    홈페이지 HTML을 받는다 (2026-09-07 실측). mediafire 페이지 fetch는 직접 경로."""
    post_resp = MagicMock()
    post_resp.text = '<html><body><a href="https://www.mediafire.com/file/abc/set.rar">dl</a></body></html>'
    mf_resp = MagicMock()
    mf_resp.text = '<a href="https://download123.mediafire.com/xyz/set.rar">download</a>'
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("proxy")))
        return mf_resp if "mediafire" in url else post_resp

    with patch("vesper_x.cli.httpx.get", side_effect=fake_get), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url",
               return_value="https://download123.mediafire.com/xyz/set.rar"):
        results = resolve_post("https://misskon.com/post-1/", config=AppConfig(proxy=PROXY))
    mf_calls = [c for c in calls if "mediafire.com" in c[0] and "download" not in c[0]]
    assert mf_calls and all(p is None for _, p in mf_calls)
    assert len(results) == 1
    assert results[0].direct_url == "https://download123.mediafire.com/xyz/set.rar"


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
    # ouo는 한국 미차단이며 Cloudflare challenge에 데이터센터 IP가 불리해 프록시 미사용.
    # gofile은 프록시 경유.
    ouo_cls.assert_called_once_with()
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
        chromium=SimpleNamespace(launch_persistent_context=launch_mock)
    ))
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _persistent_context_mock(page):
    return AsyncMock(return_value=SimpleNamespace(
        pages=[page], new_page=AsyncMock(return_value=page), close=AsyncMock(),
        cookies=AsyncMock(return_value=[]), clear_cookies=AsyncMock(), add_cookies=AsyncMock()))


def _fake_playwright_capturing_plain_launch(launch_mock):
    """gofile용 - 여전히 일반 launch를 쓰는 resolver용 fake."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=SimpleNamespace(
        chromium=SimpleNamespace(launch=launch_mock)
    ))
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_ouo_bypasser_launches_browser_with_proxy():
    launch_mock = _persistent_context_mock(_NoOpPage())
    with patch("vesper_x.extractors.ouo.async_playwright", _fake_playwright_capturing_launch(launch_mock)):
        await OuoBypasser(proxy=PROXY)._run_playwright_bypass("https://ouo.io/abc123")
    assert launch_mock.call_args.kwargs.get("proxy") == {"server": PROXY}


@pytest.mark.asyncio
async def test_ouo_bypasser_launches_real_chrome_headed():
    """ouo.io는 Cloudflare challenge가 있어 번들/headless Chromium은 막힌다 - real Chrome headed만 통과."""
    launch_mock = _persistent_context_mock(_NoOpPage())
    with patch("vesper_x.extractors.ouo.async_playwright", _fake_playwright_capturing_launch(launch_mock)):
        await OuoBypasser()._run_playwright_bypass("https://ouo.io/abc123")
    assert launch_mock.call_args.kwargs.get("channel") == "chrome"
    assert launch_mock.call_args.kwargs.get("headless") is False


@pytest.mark.asyncio
async def test_ouo_bypasser_without_proxy_launches_plain():
    launch_mock = _persistent_context_mock(_NoOpPage())
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
    with patch("vesper_x.extractors.gofile.async_playwright", _fake_playwright_capturing_plain_launch(launch_mock)):
        result = await GofileResolver(proxy=PROXY).resolve("https://gofile.io/d/xyz")
    # body를 캡처하지 못하면 [] 반환 - 이 테스트의 관심사는 launch kwargs
    assert result == []
    assert launch_mock.call_args.kwargs.get("proxy") == {"server": PROXY}


def test_resolve_post_records_file_page_url():
    """dispatch_log용: CDN 직링크(만료/IP묶임)가 아니라 파일호스트 페이지 URL
    (mediafire.com/file/<id>)를 metadata에 남긴다."""
    post_resp = MagicMock()
    post_resp.text = '<html><body><a href="https://ouo.io/abc">dl</a></body></html>'
    mf_resp = MagicMock()
    mf_resp.text = "<html></html>"

    def fake_get(url, **kwargs):
        return mf_resp if "mediafire" in url else post_resp

    with patch("vesper_x.cli.httpx.get", side_effect=fake_get), \
         patch("vesper_x.extractors.ouo.OuoBypasser.resolve",
               return_value="https://www.mediafire.com/file/heiwusaxysbl7k0"), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url",
               return_value="https://download2292.mediafire.com/signed-token/heiwusaxysbl7k0/set.rar"):
        results = resolve_post("https://misskon.com/post/", config=AppConfig())
    assert results[0].direct_url.startswith("https://download2292.mediafire.com")
    assert results[0].file_page_url == "https://www.mediafire.com/file/heiwusaxysbl7k0"
