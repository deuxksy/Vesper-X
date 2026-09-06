"""cup2d.com 지원 — gridshow 테마 리스팅 크롤러 + 기존 ZIP 파이프라인(ouo) 재사용 검증."""
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from vesper_x.cli import app, resolve_post
from vesper_x.config import AppConfig
from vesper_x.extractors.cup2d import Cup2dCrawler

runner = CliRunner()

LISTING_HTML = """
<html><body>
<div class="gridshow-grid-post-thumbnail">
  <a href="https://cup2d.com/coserbyoru-ahri-immortalized/" class="gridshow-grid-post-thumbnail-link"><img src="x"></a>
</div>
<h3 class="gridshow-grid-post-title"><a href="https://cup2d.com/coserbyoru-ahri-immortalized/" rel="bookmark">Byoru Ahri</a></h3>
<h3 class="gridshow-grid-post-title"><a href="https://cup2d.com/coserbyoru-brazilian-miku/" rel="bookmark">Byoru Miku</a></h3>
<a href="https://cup2d.com/category/ai-art/">AI Art</a>
<nav class="navigation pagination"><div class="nav-links">
<span class="page-numbers current">1</span>
<a href="https://cup2d.com/category/ai-art/page/2/" class="page-numbers">2</a>
<a href="https://cup2d.com/category/ai-art/page/17/" class="page-numbers">17</a>
</div></nav>
</body></html>
"""


def test_cup2d_crawler_extracts_post_urls_from_gridshow_titles():
    urls = Cup2dCrawler().extract_post_urls(LISTING_HTML)
    # 썸네일 링크와 제목 링크가 같은 post를 가리킨다 - dedup 후 2건
    assert urls == [
        "https://cup2d.com/coserbyoru-ahri-immortalized/",
        "https://cup2d.com/coserbyoru-brazilian-miku/",
    ]


def test_cup2d_crawler_extracts_pagination_urls():
    pages = Cup2dCrawler().extract_pagination_urls(LISTING_HTML)
    assert "https://cup2d.com/category/ai-art/page/2/" in pages
    assert "https://cup2d.com/category/ai-art/page/17/" in pages


def test_crawl_uses_cup2d_crawler_for_cup2d_url():
    fetcher = MagicMock()
    fetcher.fetch.return_value = LISTING_HTML
    with patch("vesper_x.cli.BrowserFetcher") as bf_cls, \
         patch("vesper_x.cli.load_config", return_value=AppConfig(proxy=None)), \
         patch("vesper_x.cli.resolve_post", return_value=[]) as mock_resolve, \
         patch("vesper_x.cli.Cup2dCrawler") as crawler_cls:
        bf_cls.return_value.__enter__.return_value = fetcher
        crawler_cls.return_value.extract_post_urls.return_value = ["https://cup2d.com/post1/"]
        crawler_cls.return_value.extract_pagination_urls.return_value = []
        result = runner.invoke(app, ["crawl", "https://cup2d.com/category/ai-art/", "--pages", "1", "--extract-only"])
        assert result.exit_code == 0
    crawler_cls.assert_called_once()
    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.args[0] == "https://cup2d.com/post1/"
    assert mock_resolve.call_args.kwargs.get("fetcher") is fetcher


def test_resolve_post_cup2d_routes_through_ouo_pipeline():
    """cup2d post는 MisskonParser 경로(ouo 링크 스캔)로 파이프라인을 탄다."""
    post_html = '<html><body><a href="https://ouo.io/5MFdEu">download</a></body></html>'
    fetcher = MagicMock()
    fetcher.fetch.return_value = post_html
    with patch("vesper_x.extractors.ouo.OuoBypasser.resolve", return_value="https://www.mediafire.com/file/x/set.zip"), \
         patch("vesper_x.extractors.mediafire.MediafireResolver.extract_direct_url", return_value="https://download.mediafire.net/xyz/set.zip"):
        results = resolve_post("https://cup2d.com/coserbyoru-ahri-immortalized/", fetcher=fetcher)
    assert len(results) == 1
    assert results[0].filename == "set.zip"
    assert results[0].source_page == "https://cup2d.com/coserbyoru-ahri-immortalized/"


def _dispatch_options(source_page: str, download_dir=None) -> dict:
    """dispatch()에 전달된 aria2 options를 mock으로 캡처해서 반환한다."""
    from vesper_x.dispatchers.aria2 import Aria2Dispatcher
    from vesper_x.models import DownloadMetadata

    config = AppConfig(aria2_host="ws://localhost:6800", aria2_secret="s", download_dir=download_dir)
    meta = DownloadMetadata(
        direct_url="https://download.mediafire.com/file.rar",
        referer=source_page,
        user_agent="Mozilla/5.0 Test",
        filename="file.rar",
        source_page=source_page,
    )
    with patch("vesper_x.dispatchers.aria2.aria2p") as mock_aria2p:
        mock_api = MagicMock()
        mock_aria2p.API.return_value = mock_api
        mock_api.add.return_value.gid = "gid12345"
        Aria2Dispatcher(config).dispatch(meta)
        _, kwargs = mock_api.add.call_args
        return kwargs["options"]


def test_dispatch_sets_dir_to_cup2d_subdir_for_cup2d_source():
    options = _dispatch_options("https://cup2d.com/coserbyoru-ahri-immortalized/", download_dir="/data/aria")
    assert options["dir"] == "/data/aria/cup2d"
