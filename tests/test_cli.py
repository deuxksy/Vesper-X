from unittest.mock import MagicMock, patch
import asyncio
from typer.testing import CliRunner
from vesper_x.cli import app, resolve_post, run_async
from vesper_x.config import AppConfig

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

def test_resolve_post_expands_gofile_folder_links():
    """ouo bypass가 gofile 폴더로 끝나면 파일 수만큼 metadata가 확장된다."""
    from unittest.mock import AsyncMock

    from vesper_x.extractors.gofile import GofileDownload

    post_html = """
    <html><body>
    <a href="https://ouo.io/abc123" rel="nofollow">download</a>
    </body></html>
    """
    fetcher = MagicMock()
    fetcher.fetch.return_value = post_html

    with patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://gofile.io/d/N09Oj1mA"), \
         patch("vesper_x.extractors.gofile.GofileResolver.resolve", AsyncMock(return_value=[
             GofileDownload("https://store3.gofile.io/download/web/id1/a%20b.rar", "a b.rar", "accountToken=tok"),
             GofileDownload("https://store3.gofile.io/download/web/id2/c.rar", "c.rar", "accountToken=tok"),
         ])):
        results = resolve_post("https://cosplaytele.com/cantarella-9/", fetcher=fetcher, config=AppConfig(skip_gofile=False))

    assert len(results) == 2
    assert results[0].filename == "a b.rar"
    assert results[0].cookies == "accountToken=tok"
    assert results[1].direct_url.endswith("c.rar")


def test_resolve_post_skips_gofile_when_skip_gofile_enabled():
    post_html = '<html><body><a href="https://gofile.io/d/N09Oj1mA">link</a></body></html>'
    fetcher = MagicMock()
    fetcher.fetch.return_value = post_html
    results = resolve_post("https://cosplaytele.com/test/", fetcher=fetcher, config=AppConfig(skip_gofile=True))
    assert results == []


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

    registry_stub = MagicMock()
    registry_stub.is_dispatched.return_value = False
    with patch("vesper_x.cli.BrowserFetcher") as bf_cls, \
         patch("vesper_x.cli.load_config", return_value=AppConfig(proxy=None)), \
         patch("vesper_x.cli.resolve_post", return_value=[meta]) as mock_resolve, \
         patch("vesper_x.cli.ModelRegistry", return_value=registry_stub), \
         patch("vesper_x.cli.Aria2Dispatcher") as disp_cls:
        bf_cls.return_value.__enter__.return_value = fetcher
        disp_cls.return_value.dispatch.return_value = "gid123"
        disp_cls.return_value.waiting_count.return_value = 0
        result = runner.invoke(app, ["crawl", "https://misskon.com/tag/t/", "--pages", "0"])
        assert result.exit_code == 0

    # post 2건 각각 dispatch (페이지 페치 직후)
    assert mock_resolve.call_count == 2
    assert disp_cls.return_value.dispatch.call_count == 2


def test_resolve_post_follows_post_pagination_pages():
    """misskon 멀티페이지 포스트는 뒷 페이지의 다운로드 링크까지 본다."""
    page1 = '<html><body><div class="page-link"><a href="https://misskon.com/post-a/2/" class="post-page-numbers">2</a></div></body></html>'
    page2 = '<html><body><a href="https://ouo.io/abc999" rel="nofollow">dl</a></body></html>'
    fetcher = MagicMock()
    fetcher.fetch.side_effect = [page1, page2]
    with patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://www.mediafire.com/file/x/s.rar"), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url", return_value="https://download2299.mediafire.com/x/s.rar"), \
         patch("vesper_x.cli.httpx.get") as mock_httpx:
        mf_resp = MagicMock()
        mf_resp.text = "<html></html>"
        mock_httpx.return_value = mf_resp
        results = resolve_post("https://misskon.com/post-a/", fetcher=fetcher)
    assert fetcher.fetch.call_count == 2
    assert fetcher.fetch.call_args_list[0].args[0] == "https://misskon.com/post-a/"
    assert fetcher.fetch.call_args_list[1].args[0] == "https://misskon.com/post-a/2/"
    assert len(results) == 1


def test_crawl_waits_when_aria2_queue_is_full():
    """aria2 waiting 큐가 있으면(대역 포화) 소화될 때까지 대기한다."""
    from vesper_x.config import AppConfig
    from vesper_x.models import DownloadMetadata

    page1 = '<h2 class="post-box-title"><a href="https://misskon.com/p1/">P1</a></h2>'
    fetcher = MagicMock()
    fetcher.fetch.return_value = page1
    meta = DownloadMetadata(direct_url="https://dl/x.rar", referer="https://misskon.com/p1/",
                            user_agent="ua", filename="x.rar", source_page="https://misskon.com/p1/")
    registry_stub = MagicMock()
    registry_stub.is_dispatched.return_value = False
    with patch("vesper_x.cli.BrowserFetcher") as bf_cls, \
         patch("vesper_x.cli.load_config", return_value=AppConfig()), \
         patch("vesper_x.cli.resolve_post", return_value=[meta]), \
         patch("vesper_x.cli.ModelRegistry", return_value=registry_stub), \
         patch("vesper_x.cli.Aria2Dispatcher") as disp_cls, \
         patch("vesper_x.cli.time.sleep") as mock_sleep:
        bf_cls.return_value.__enter__.return_value = fetcher
        disp_cls.return_value.waiting_count.side_effect = [2, 2, 0, 0]  # resolve 전 두 번 적체, 통과 + dispatch 직전 통과
        disp_cls.return_value.dispatch.return_value = "gid1"
        result = runner.invoke(app, ["crawl", "https://misskon.com/tag/t/"])
        assert result.exit_code == 0
    assert mock_sleep.call_count >= 2


# --- collect/dispatch 2-phase 분리 ---

def test_crawl_collect_mode_queues_without_dispatch():
    """crawl --collect: resolve 결과를 dispatch_log 큐에만 넣고 dispatch는 안 한다."""
    from unittest.mock import MagicMock
    from vesper_x.config import AppConfig
    from vesper_x.models import DownloadMetadata

    page1 = '<h2 class="post-box-title"><a href="https://misskon.com/p1/">P1</a></h2>'
    meta = DownloadMetadata(
        direct_url="https://download.mediafire.net/x/set.rar",
        referer="https://misskon.com/p1/", user_agent="ua",
        filename="set.rar", source_page="https://misskon.com/p1/",
        file_page_url="https://www.mediafire.com/file/abc123/set.rar")
    fetcher = MagicMock()
    fetcher.fetch.side_effect = [page1]

    registry_stub = MagicMock()
    registry_stub.is_dispatched.return_value = False
    with patch("vesper_x.cli.BrowserFetcher") as bf_cls, \
         patch("vesper_x.cli.load_config", return_value=AppConfig(proxy=None)), \
         patch("vesper_x.cli.resolve_post", return_value=[meta]), \
         patch("vesper_x.cli.ModelRegistry", return_value=registry_stub), \
         patch("vesper_x.cli.Aria2Dispatcher") as disp_cls:
        bf_cls.return_value.__enter__.return_value = fetcher
        result = runner.invoke(app, ["crawl", "https://misskon.com/tag/t/",
                                     "--pages", "1", "--collect"])
        assert result.exit_code == 0
        disp_cls.assert_not_called()  # dispatcher 생성 없음
        registry_stub.record_collect.assert_called_once()
        call = registry_stub.record_collect.call_args.kwargs
        assert call["file_page_url"] == "https://www.mediafire.com/file/abc123/set.rar"
        assert call["post_url"] == "https://misskon.com/p1/"
        assert call["filename"] == "set.rar"


def test_dispatch_command_resolves_mediafire_and_marks_dispatched():
    """dispatch: mediafire는 dispatch 직전 재 resolve, 성공 시 mark_dispatched."""
    from unittest.mock import MagicMock
    from vesper_x.config import AppConfig

    pending = [{
        "url": "https://www.mediafire.com/file/abc123/set.rar",
        "post_url": "https://misskon.com/p1/", "title": "P1",
        "site": "misskon", "note": "set.rar",
        "direct_url": "https://old.mediafire.net/stale.rar", "status": "collected",
    }]
    registry_stub = MagicMock()
    registry_stub.pending_collects.return_value = pending
    mf_resp = MagicMock()
    mf_resp.text = "<html>mf page</html>"
    with patch("vesper_x.cli.load_config", return_value=AppConfig(proxy=None)), \
         patch("vesper_x.cli.ModelRegistry", return_value=registry_stub), \
         patch("vesper_x.cli.Aria2Dispatcher") as disp_cls, \
         patch("vesper_x.cli.httpx.get", return_value=mf_resp) as mock_get, \
         patch("vesper_x.cli.MediafireResolver") as mf_cls:
        disp_cls.return_value.waiting_count.return_value = 0
        disp_cls.return_value.dispatch.return_value = "gid9"
        mf_cls.return_value.extract_direct_url.return_value = "https://new.mediafire.net/set.rar"
        result = runner.invoke(app, ["dispatch"])
        assert result.exit_code == 0
        # mediafire 재 resolve는 직접 경로 (IP 바인딩 - proxy=None)
        assert mock_get.call_args.kwargs.get("proxy", "MISSING") is None
        # dispatch된 direct_url은 재 resolve 결과
        dispatched_meta = disp_cls.return_value.dispatch.call_args.args[0]
        assert dispatched_meta.direct_url == "https://new.mediafire.net/set.rar"
        assert dispatched_meta.filename == "set.rar"
        registry_stub.mark_dispatched.assert_called_once_with(
            pending[0]["url"], direct_url="https://new.mediafire.net/set.rar")


def test_dispatch_command_non_mediafire_uses_stored_direct_url():
    """mega 등 재 resolve 불가 링크는 저장된 direct_url을 그대로 dispatch한다."""
    from unittest.mock import MagicMock
    from vesper_x.config import AppConfig

    pending = [{
        "url": "https://mega.nz/file/xyz", "post_url": "https://misskon.com/p2/",
        "title": "P2", "site": "misskon", "note": "m.rar",
        "direct_url": "https://mega.nz/file/xyz", "status": "collected",
    }]
    registry_stub = MagicMock()
    registry_stub.pending_collects.return_value = pending
    with patch("vesper_x.cli.load_config", return_value=AppConfig(proxy=None)), \
         patch("vesper_x.cli.ModelRegistry", return_value=registry_stub), \
         patch("vesper_x.cli.Aria2Dispatcher") as disp_cls, \
         patch("vesper_x.cli.httpx.get") as mock_get:
        disp_cls.return_value.waiting_count.return_value = 0
        disp_cls.return_value.dispatch.return_value = "gid8"
        result = runner.invoke(app, ["dispatch"])
        assert result.exit_code == 0
        mock_get.assert_not_called()  # 재 resolve 없음
        registry_stub.mark_dispatched.assert_called_once()

def test_dispatch_command_failure_marks_failed():
    from unittest.mock import MagicMock
    from vesper_x.config import AppConfig

    pending = [{
        "url": "https://www.mediafire.com/file/dead/x.rar",
        "post_url": "https://misskon.com/p3/", "title": "P3",
        "site": "misskon", "note": "x.rar",
        "direct_url": None, "status": "collected",
    }]
    registry_stub = MagicMock()
    registry_stub.pending_collects.return_value = pending
    mf_resp = MagicMock()
    mf_resp.text = "<html>expired</html>"
    with patch("vesper_x.cli.load_config", return_value=AppConfig(proxy=None)), \
         patch("vesper_x.cli.ModelRegistry", return_value=registry_stub), \
         patch("vesper_x.cli.Aria2Dispatcher") as disp_cls, \
         patch("vesper_x.cli.httpx.get", return_value=mf_resp), \
         patch("vesper_x.cli.MediafireResolver") as mf_cls:
        disp_cls.return_value.waiting_count.return_value = 0
        mf_cls.return_value.extract_direct_url.return_value = None  # 재 resolve도 실패
        result = runner.invoke(app, ["dispatch"])
        assert result.exit_code == 0
        registry_stub.mark_failed.assert_called_once()
        registry_stub.mark_dispatched.assert_not_called()
        disp_cls.return_value.dispatch.assert_not_called()
