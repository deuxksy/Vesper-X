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


def _fake_playwright(page: FakePage):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=SimpleNamespace(chromium=SimpleNamespace(
        launch=AsyncMock(return_value=SimpleNamespace(
            new_context=AsyncMock(return_value=SimpleNamespace(new_page=AsyncMock(return_value=page))),
            close=AsyncMock(),
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
