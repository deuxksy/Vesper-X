from unittest.mock import MagicMock, patch
import asyncio
from typer.testing import CliRunner
from vesper_x.cli import app, resolve_post, run_async

runner = CliRunner()

def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "direct link extractor" in result.output.lower() or "usage" in result.output.lower()

def test_parse_command_extract_only():
    with patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://mediafire.com/file/123"):
        result = runner.invoke(app, ["parse", "https://ouo.io/test123", "--extract-only"])
        assert result.exit_code == 0

def test_resolve_post_uses_fetcher_when_provided():
    post_html = """
    <html><body>
    <a href="https://ouo.io/abc123" rel="nofollow">download</a>
    <a href="https://misskon.com/tag/sometag/" rel="tag">sometag</a>
    </body></html>
    """
    fetcher = MagicMock()
    fetcher.fetch.return_value = post_html
    http_resp = MagicMock()
    http_resp.text = "<html></html>"
    with patch("vesper_x.cli.httpx.get", return_value=http_resp) as mock_httpx, \
         patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://www.mediafire.com/file/xyz"), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url", return_value="https://download.mediafire.net/xyz/misskon.zip"):
        results = resolve_post("https://misskon.com/123-test/", fetcher=fetcher)
    # post page는 fetcher로, mediafire page만 httpx로 가져온다
    fetcher.fetch.assert_called_once_with("https://misskon.com/123-test/")
    assert mock_httpx.call_count == 1
    assert "mediafire.com" in mock_httpx.call_args.args[0]
    assert len(results) == 1
    assert results[0].direct_url == "https://download.mediafire.net/xyz/misskon.zip"
    assert "misskon.zip" == results[0].filename

def test_parse_command_json_output():
    with patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://mediafire.com/file/123"), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url", return_value="https://download.mediafire.com/123.zip"):
        result = runner.invoke(app, ["parse", "https://ouo.io/test123", "--extract-only", "--json"])
        assert result.exit_code == 0
        assert "direct_url" in result.output
        assert "tags" in result.output
        assert "models" in result.output

def test_run_async_inside_running_loop():
    """Playwright sync 세션처럼 main thread에 running loop가 있어도 coroutine 실행 가능해야 한다."""
    async def inner():
        return 42

    async def caller():
        return run_async(inner())

    # asyncio.run 내부(=running loop 존재)에서 run_async 호출 - 기존 asyncio.run이면 RuntimeError
    assert asyncio.run(caller()) == 42


def test_crawl_dispatches_each_post_immediately():
    """페이지를 페치할 때마다 해당 post를 즉시 resolve+dispatch 한다 (최신순 스트리밍)."""
    from unittest.mock import MagicMock
    from vesper_x.config import AppConfig
    from vesper_x.models import DownloadMetadata

    page1 = '<h2 class="post-box-title"><a href="https://misskon.com/p1/">P1</a></h2><div class="pagination"><a class="page" href="https://misskon.com/tag/t/page/2/">2</a></div>'
    page2 = '<h2 class="post-box-title"><a href="https://misskon.com/p2/">P2</a></h2>'
    meta = DownloadMetadata(
        direct_url="https://download.mediafire.net/x/set.rar", referer="https://misskon.com/p1/",
        user_agent="ua", filename="set.rar", source_page="https://misskon.com/p1/",
    )

    fetcher = MagicMock()
    # resolve_post가 mock이라 fetch는 tag pagination 페이지에만 호출된다
    fetcher.fetch.side_effect = [page1, page2]

    with patch("vesper_x.cli.BrowserFetcher") as bf_cls, \
         patch("vesper_x.cli.load_config", return_value=AppConfig(proxy=None)), \
         patch("vesper_x.cli.resolve_post", return_value=[meta]) as mock_resolve, \
         patch("vesper_x.cli.Aria2Dispatcher") as disp_cls:
        bf_cls.return_value.__enter__.return_value = fetcher
        disp_cls.return_value.dispatch.return_value = "gid123"
        result = runner.invoke(app, ["crawl", "https://misskon.com/tag/t/", "--pages", "0"])
        assert result.exit_code == 0

    # post 2건 각각 dispatch (페이지 페치 직후)
    assert mock_resolve.call_count == 2
    assert disp_cls.return_value.dispatch.call_count == 2
