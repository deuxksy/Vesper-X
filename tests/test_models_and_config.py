import pytest
from vesper_x.models import DownloadMetadata
from vesper_x.config import AppConfig, load_config

def test_download_metadata_creation():
    meta = DownloadMetadata(
        direct_url="https://download.mediafire.com/file.rar",
        referer="https://misskon.com/123",
        user_agent="Mozilla/5.0",
        filename="file.rar",
        source_page="https://misskon.com/123"
    )
    assert meta.direct_url == "https://download.mediafire.com/file.rar"
    assert meta.referer == "https://misskon.com/123"

def test_load_default_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[aria2]\nhost = "ws://heritage.bun-bull.ts.net:6800"\nsecret = "test_secret"\n\n[crawler]\nmodels = ["幼水铃衣", "you-shui-ling-yi"]\n')
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", config_file)
    
    cfg = load_config()
    assert cfg.aria2_host == "ws://heritage.bun-bull.ts.net:6800"
    assert cfg.aria2_secret == "test_secret"
    assert "幼水铃衣" in cfg.models

def test_load_config_file_not_found(tmp_path, monkeypatch):
    non_existent = tmp_path / "non_existent.toml"
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", non_existent)

    cfg = load_config()
    assert cfg.aria2_host == "ws://heritage.bun-bull.ts.net:6800"
    assert "幼水铃衣" in cfg.models


def test_load_config_network_proxy(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[network]\nproxy = "http://127.0.0.1:7890"\n')
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", config_file)

    cfg = load_config()
    assert cfg.proxy == "http://127.0.0.1:7890"


def test_load_config_network_proxy_default_none(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[aria2]\nhost = "ws://example:6800"\n')
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", config_file)

    cfg = load_config()
    assert cfg.proxy is None
