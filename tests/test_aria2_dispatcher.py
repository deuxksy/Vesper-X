from unittest.mock import MagicMock, patch
import pytest

from vesper_x.config import AppConfig
from vesper_x.dispatchers.aria2 import Aria2Dispatcher
from vesper_x.models import DownloadMetadata


def test_aria2_dispatch_calls_add_with_options():
    config = AppConfig(aria2_host="ws://localhost:6800", aria2_secret="secret")
    meta = DownloadMetadata(
        direct_url="https://download.mediafire.com/file.rar",
        referer="https://misskon.com/123",
        user_agent="Mozilla/5.0 Test",
        filename="file.rar",
        source_page="https://misskon.com/123",
    )

    with patch("vesper_x.dispatchers.aria2.aria2p") as mock_aria2p:
        mock_api = MagicMock()
        mock_aria2p.API.return_value = mock_api
        mock_download = MagicMock()
        mock_download.gid = "gid12345"
        mock_api.add.return_value = mock_download

        dispatcher = Aria2Dispatcher(config)
        gid = dispatcher.dispatch(meta)

        assert gid == "gid12345"
        mock_api.add.assert_called_once_with(
            "https://download.mediafire.com/file.rar",
            options={
                "header": [
                    "Referer: https://misskon.com/123",
                    "User-Agent: Mozilla/5.0 Test",
                ],
                "out": "file.rar",
            },
        )


def _dispatch_options(source_page: str, download_dir=None) -> dict:
    """dispatch()에 전달된 aria2 options를 mock으로 캡처해서 반환한다."""
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


def test_dispatch_sets_dir_to_misskon_subdir_for_misskon_source():
    options = _dispatch_options("https://misskon.com/123", download_dir="/data/aria")
    assert options["dir"] == "/data/aria/misskon"


def test_dispatch_sets_dir_to_cosplaytele_subdir_for_cosplaytele_source():
    options = _dispatch_options("https://cosplaytele.com/xyz", download_dir="/data/aria")
    assert options["dir"] == "/data/aria/cosplaytele"


def test_dispatch_omits_dir_for_unknown_site():
    options = _dispatch_options("https://example.com/post/1", download_dir="/data/aria")
    assert "dir" not in options


def test_dispatch_omits_dir_when_download_dir_not_configured():
    options = _dispatch_options("https://misskon.com/123", download_dir=None)
    assert "dir" not in options



    config = AppConfig(aria2_host="ws://heritage.bun-bull.ts.net:6800", aria2_secret="mysecret")

    with patch("vesper_x.dispatchers.aria2.aria2p") as mock_aria2p:
        Aria2Dispatcher(config)
        mock_aria2p.Client.assert_called_once_with(
            host="http://heritage.bun-bull.ts.net",
            port=6800,
            secret="mysecret",
        )
