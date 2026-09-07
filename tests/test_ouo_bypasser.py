from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from vesper_x.extractors.ouo import OuoBypasser

@pytest.mark.asyncio
async def test_ouo_resolve_destination():
    bypasser = OuoBypasser()
    with patch.object(bypasser, "_run_playwright_bypass", new_callable=AsyncMock) as mock_bypass:
        mock_bypass.return_value = "https://www.mediafire.com/file/sample/file.rar/file"
        result = await bypasser.resolve("https://ouo.io/hHzh1N")
        assert result == "https://www.mediafire.com/file/sample/file.rar/file"


class FakeButton:
    def __init__(self, page):
        self.page = page

    async def is_visible(self):
        return True

    async def click(self):
        self.page.url = self.page.after_click_url


class FakePage:
    """goto 시 ouo plain URL로 redirect되고, 버튼 클릭 시 목적지로 이동하는 페이지 흉내."""

    def __init__(self, start_url: str, after_click_url: str):
        self.url = start_url
        self.after_click_url = after_click_url
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, url, **kwargs):
        # 초기 request 이벤트(start_url) 발생 후 redirect로 plain ouo URL이 된다
        if "request" in self.handlers:
            self.handlers["request"](SimpleNamespace(url=url))
        self.url = "https://ouo.io/2kRFhZ"

    async def wait_for_timeout(self, ms):
        pass

    async def query_selector(self, selector):
        if self.url == "https://ouo.io/2kRFhZ":
            return FakeButton(self)
        return None

    async def evaluate(self, expression, element):
        return True

    async def close(self):
        pass


def _fake_playwright(page):
    """persistent context 흉내: launch_persistent_context가 pages=[page] 컨텍스트 반환."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=AsyncMock(return_value=SimpleNamespace(
            pages=[page],
            new_page=AsyncMock(return_value=page),
            close=AsyncMock(),
            cookies=AsyncMock(return_value=[]),
            clear_cookies=AsyncMock(),
            add_cookies=AsyncMock(),
        ))
    )))
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start_url,after_click_url",
    [
        # /st/ 형식: 목적지가 s= 파라미터에 평문으로 박혀 있다 - 부분문자열 오판으로
        # 클릭 체인을 건너뛰면 안 된다
        (
            "http://ouo.io/st/InMJ0J8u/?s=https%3A%2F%2Fgofile.io%2Fd%2FN09Oj1mA",
            "https://gofile.io/d/N09Oj1mA",
        ),
        # plain 형식: 기존 동작 회귀 방지
        (
            "https://ouo.io/hHzh1N",
            "https://download2293.mediafire.com/xyz/file.rar",
        ),
    ],
    ids=["st-form-with-embedded-target", "plain-form"],
)
async def test_run_bypass_clicks_through_to_destination(start_url, after_click_url):
    page = FakePage(start_url, after_click_url)
    with patch("vesper_x.extractors.ouo.async_playwright", _fake_playwright(page)):
        result = await OuoBypasser()._run_playwright_bypass(start_url)
    assert result == after_click_url


class ChainButton:
    def __init__(self, page):
        self.page = page

    async def is_visible(self):
        return True

    async def click(self):
        self.page.clicks += 1
        self.page.url = self.page.urls[min(self.page.clicks, len(self.page.urls) - 1)]


class ChainPage:
    """ouo 3중 체인 흉내 - 6번의 버튼 클릭 뒤에야 목적지 도착."""

    def __init__(self, urls):
        self.url = urls[0]
        self.urls = urls
        self.clicks = 0

    def on(self, event, handler):
        pass

    async def goto(self, url, **kwargs):
        pass

    async def wait_for_timeout(self, ms):
        pass

    async def query_selector(self, selector):
        return ChainButton(self)

    async def evaluate(self, expression, element):
        return True


@pytest.mark.asyncio
async def test_run_bypass_follows_multi_hop_ouo_chain():
    """ouo 다중 체인(6스테이지)도 스테이지 한계로 중도 포기하면 안 된다."""
    urls = [
        "https://ouo.io/aaa111", "https://ouo.press/go/aaa111",
        "https://ouo.io/bbb222", "https://ouo.io/go/bbb222",
        "https://ouo.io/ccc333", "https://ouo.io/go/ccc333",
        "https://www.mediafire.com/file/xyz/set.rar/file",
    ]
    page = ChainPage(urls)
    with patch("vesper_x.extractors.ouo.async_playwright", _fake_playwright(page)):
        result = await OuoBypasser()._run_playwright_bypass("https://ouo.io/aaa111")
    assert result == urls[-1]


@pytest.mark.asyncio
async def test_bypass_uses_persistent_profile():
    """링크마다 새 브라우저면 CF가 매번 challenge를 건다 - 전용 프로필을 재사용해
    cf_clearance 쿠키를 유지한다."""
    ctx = MagicMock()
    persistent_mock = AsyncMock(return_value=SimpleNamespace(
        pages=[_NoOpPageLike()],
        new_page=AsyncMock(),
        close=AsyncMock(),
        cookies=AsyncMock(return_value=[]),
        clear_cookies=AsyncMock(),
        add_cookies=AsyncMock(),
    ))
    ctx.__aenter__ = AsyncMock(return_value=SimpleNamespace(
        chromium=SimpleNamespace(launch_persistent_context=persistent_mock)))
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("vesper_x.extractors.ouo.async_playwright", MagicMock(return_value=ctx)):
        await OuoBypasser()._run_playwright_bypass("https://ouo.io/abc123")
    assert persistent_mock.call_args is not None
    assert persistent_mock.call_args.args  # 프로필 경로 위치 인자
    assert persistent_mock.call_args.kwargs.get("channel") == "chrome"


class _NoOpPageLike:
    url = "https://ouo.io/abc123"
    def on(self, *a): pass
    async def goto(self, *a, **k): pass
    async def wait_for_timeout(self, ms): pass
    async def query_selector(self, sel): return None


@pytest.mark.asyncio
async def test_bypass_prunes_cookies_before_goto():
    """persistent profile에 쿠키가 쌓이면 ouo nginx가 400을 돌려준다 -
    우회 전 cf_clearance만 남기고 정리한다 (2026-09-07 실측)."""
    page = FakePage("https://ouo.io/zZz9Zz", "https://download2293.mediafire.com/x/f.rar")
    ctx = MagicMock()
    context = SimpleNamespace(
        pages=[page],
        new_page=AsyncMock(),
        close=AsyncMock(),
        cookies=AsyncMock(return_value=[
            {"name": "cf_clearance", "value": "tok", "domain": ".ouo.io", "path": "/"},
            {"name": "ouo_session", "value": "x" * 4000, "domain": ".ouo.io", "path": "/"},
        ]),
        clear_cookies=AsyncMock(),
        add_cookies=AsyncMock(),
    )
    ctx.__aenter__ = AsyncMock(return_value=SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=AsyncMock(return_value=context))))
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("vesper_x.extractors.ouo.async_playwright", MagicMock(return_value=ctx)):
        result = await OuoBypasser()._run_playwright_bypass("https://ouo.io/zZz9Zz")
    context.clear_cookies.assert_awaited_once()
    kept = context.add_cookies.await_args.args[0]
    assert [c["name"] for c in kept] == ["cf_clearance"]
    assert result.endswith("f.rar")
