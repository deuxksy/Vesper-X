"""[sites] config 이관 — 도메인 → crawler/subdir 매핑을 code가 아닌 config가 구동한다."""
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from vesper_x.cli import app
from vesper_x.config import AppConfig, SiteConfig, load_config
from vesper_x.models import DownloadMetadata

runner = CliRunner()

SITES_TOML = """
[sites]
"misskon.com" = { crawler = "category", subdir = "misskon" }
"cup2d.com" = { crawler = "cup2d", subdir = "cup2d" }
"""


def test_load_config_parses_sites_section(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(SITES_TOML)
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", config_file)

    cfg = load_config()
    assert cfg.sites["cup2d.com"].crawler == "cup2d"
    assert cfg.sites["misskon.com"].subdir == "misskon"


def test_load_config_sites_defaults_when_section_absent(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[aria2]\nhost = "ws://example:6800"\n')
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", config_file)

    cfg = load_config()
    assert cfg.sites["misskon.com"].crawler == "category"
    assert cfg.sites["cup2d.com"].subdir == "cup2d"


def test_app_config_has_builtin_default_sites():
    cfg = AppConfig()
    assert set(cfg.sites) == {"misskon.com", "cosplaytele.com", "cup2d.com"}


def test_crawl_crawler_selection_driven_by_sites_config():
    """config가 cup2d.com을 category crawler로 지정하면 Cup2dCrawler를 쓰지 않는다."""
    fetcher = MagicMock()
    fetcher.fetch.return_value = "<html></html>"
    config = AppConfig(proxy=None, sites={
        "cup2d.com": SiteConfig(crawler="category", subdir="cup2d"),
    })
    with patch("vesper_x.cli.BrowserFetcher") as bf_cls, \
         patch("vesper_x.cli.load_config", return_value=config), \
         patch("vesper_x.cli.resolve_post", return_value=[]), \
         patch("vesper_x.cli.Cup2dCrawler") as cup2d_cls, \
         patch("vesper_x.cli.CategoryCrawler") as category_cls:
        bf_cls.return_value.__enter__.return_value = fetcher
        category_cls.return_value.extract_post_urls.return_value = []
        category_cls.return_value.extract_pagination_urls.return_value = []
        result = runner.invoke(app, ["crawl", "https://cup2d.com/category/x/", "--pages", "1", "--extract-only"])
        assert result.exit_code == 0
    cup2d_cls.assert_not_called()
    category_cls.assert_called_once()


def _dispatch_options(config: AppConfig, source_page: str) -> dict:
    from vesper_x.dispatchers.aria2 import Aria2Dispatcher

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


def test_dispatch_dir_uses_sites_config_subdir():
    """subdir을 config에서 읽는다 - 코드의 고정 테이블이 아니다."""
    config = AppConfig(
        aria2_host="ws://localhost:6800", aria2_secret="s", download_dir="/data/aria",
        sites={"cup2d.com": SiteConfig(crawler="cup2d", subdir="custom_dir")},
    )
    options = _dispatch_options(config, "https://cup2d.com/some-post/")
    assert options["dir"] == "/data/aria/custom_dir"


def test_dispatch_dir_matches_subdomain():
    config = AppConfig(
        aria2_host="ws://localhost:6800", aria2_secret="s", download_dir="/data/aria",
        sites={"cup2d.com": SiteConfig(crawler="cup2d", subdir="cup2d")},
    )
    options = _dispatch_options(config, "https://www.cup2d.com/some-post/")
    assert options["dir"] == "/data/aria/cup2d"
