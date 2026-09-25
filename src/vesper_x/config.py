from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "url-resolver" / "config.toml"
DEFAULT_MODELS = ["幼水铃衣", "you-shui-ling-yi", "luo-li-lolisama"]


@dataclass
class SiteConfig:
    crawler: str
    subdir: str


# 사이트 추가는 config.toml [sites]에 도메인을 등록한다 (코드 수정 불필요).
# crawler 이름은 cli._select_crawler의 registry 키(category/cosplaytele/hegre)와 매칭.
DEFAULT_SITES = {
    "misskon.com": SiteConfig(crawler="category", subdir="misskon"),
    "cosplaytele.com": SiteConfig(crawler="cosplaytele", subdir="cosplaytele"),
    "hegre.com": SiteConfig(crawler="hegre", subdir="H"),
}


@dataclass
class CredentialConfig:
    username: str = ""
    password: str = ""


# repo 내 고정 설정 (models_db.DEFAULT_DB_PATH와 동일한 탐색 관행)
DEFAULT_TOML_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.toml"


@dataclass
class AppConfig:
    aria2_host: str = "ws://heritage.bun-bull.ts.net:6800"
    aria2_secret: str = ""
    download_dir: Optional[str] = None
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))
    proxy: Optional[str] = None
    sites: dict[str, SiteConfig] = field(default_factory=lambda: dict(DEFAULT_SITES))
    skip_gofile: bool = False
    credentials: dict[str, CredentialConfig] = field(default_factory=dict)


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    """dict은 재귀 병합(로컬 우선), 스칼라/리스트는 로컬이 덮어쓴다."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_credentials(data: dict) -> dict[str, CredentialConfig]:
    return {
        name: CredentialConfig(username=entry.get("username", ""),
                               password=entry.get("password", ""))
        for name, entry in data.get("credentials", {}).items()
    }


def _parse_sites(data: dict) -> dict[str, SiteConfig]:
    sites_data = data.get("sites", {})
    # [sites] 섹션이 없으면 기본 테이블로 동작한다 (기존 설정 호환)
    if not sites_data:
        return dict(DEFAULT_SITES)
    return {
        domain: SiteConfig(crawler=entry["crawler"], subdir=entry["subdir"])
        for domain, entry in sites_data.items()
    }


def load_config() -> AppConfig:
    data = _deep_merge(_load_toml(DEFAULT_TOML_PATH), _load_toml(DEFAULT_CONFIG_PATH))
    aria2_data = data.get("aria2", {})
    crawler_data = data.get("crawler", {})
    network_data = data.get("network", {})
    return AppConfig(
        aria2_host=aria2_data.get("host", "ws://heritage.bun-bull.ts.net:6800"),
        aria2_secret=aria2_data.get("secret", ""),
        download_dir=aria2_data.get("download_dir"),
        models=crawler_data.get("models", list(DEFAULT_MODELS)),
        proxy=network_data.get("proxy"),
        sites=_parse_sites(data),
        skip_gofile=crawler_data.get("skip_gofile", False),
        credentials=_parse_credentials(data),
    )
