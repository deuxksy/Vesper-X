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


def test_aria2_dispatcher_host_parsing():
    config = AppConfig(aria2_host="ws://heritage.bun-bull.ts.net:6800", aria2_secret="mysecret")

    with patch("vesper_x.dispatchers.aria2.aria2p") as mock_aria2p:
        Aria2Dispatcher(config)
        mock_aria2p.Client.assert_called_once_with(
            host="http://heritage.bun-bull.ts.net",
            port=6800,
            secret="mysecret",
        )
