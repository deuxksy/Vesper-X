"""Config 2중 분리 — config/default.toml + 로컬 config.toml deep merge."""
import pytest
from vesper_x.config import load_config, AppConfig

DEFAULT_TOML = """\
[aria2]
download_dir = "/downloads"

[sites]
"misskon.com" = { crawler = "category", subdir = "misskon" }
"cosplaytele.com" = { crawler = "cosplaytele", subdir = "cosplaytele" }
"hegre.com" = { crawler = "hegre", subdir = "H" }
"""

LOCAL_TOML = """\
[aria2]
host = "ws://other:6800"

[credentials.hegre]
username = "user@example.com"
password = "secret"
"""


def _patch(monkeypatch, tmp_path, default_toml=None, local_toml=None):
    default_path = tmp_path / "default.toml"
    local_path = tmp_path / "config.toml"
    if default_toml is not None:
        default_path.write_text(default_toml)
    if local_toml is not None:
        local_path.write_text(local_toml)
    monkeypatch.setattr("vesper_x.config.DEFAULT_TOML_PATH", default_path)
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", local_path)


def test_deep_merge_local_overrides_scalar(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, DEFAULT_TOML, LOCAL_TOML)
    cfg = load_config()
    assert cfg.aria2_host == "ws://other:6800"      # 로컬 우선
    assert cfg.download_dir == "/downloads"          # default 유지


def test_deep_merge_sites_partial_override(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, DEFAULT_TOML,
           '[sites]\n"misskon.com" = { crawler = "category", subdir = "mk-local" }\n')
    cfg = load_config()
    assert cfg.sites["misskon.com"].subdir == "mk-local"          # 로컬 덮어씀
    assert cfg.sites["cosplaytele.com"].subdir == "cosplaytele"   # default 유지
    assert cfg.sites["hegre.com"].subdir == "H"                   # default 유지


def test_credentials_parsing(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, DEFAULT_TOML, LOCAL_TOML)
    cfg = load_config()
    assert cfg.credentials["hegre"].username == "user@example.com"
    assert cfg.credentials["hegre"].password == "secret"


def test_both_missing_falls_back_to_code_defaults(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)  # 두 파일 모두 부재
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.credentials == {}
    assert cfg.sites["misskon.com"].subdir == "misskon"


def test_default_sites_code_fallback_includes_hegre(monkeypatch, tmp_path):
    # default.toml에 [sites] 없어도 코드 DEFAULT_SITES 폴백에 hegre가 있다
    _patch(monkeypatch, tmp_path, '[aria2]\ndownload_dir = "/downloads"\n')
    cfg = load_config()
    assert cfg.sites["hegre.com"].crawler == "hegre"
