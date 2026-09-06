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
# crawler 이름은 cli._select_crawler의 registry 키(category/cosplaytele)와 매칭.
DEFAULT_SITES = {
    "misskon.com": SiteConfig(crawler="category", subdir="misskon"),
    "cosplaytele.com": SiteConfig(crawler="cosplaytele", subdir="cosplaytele"),
}


@dataclass
class AppConfig:
    aria2_host: str = "ws://heritage.bun-bull.ts.net:6800"
    aria2_secret: str = ""
    download_dir: Optional[str] = None
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))
    proxy: Optional[str] = None
    sites: dict[str, SiteConfig] = field(default_factory=lambda: dict(DEFAULT_SITES))


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
    if not DEFAULT_CONFIG_PATH.exists():
        return AppConfig()
    with open(DEFAULT_CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    aria2_data = data.get("aria2", {})
    crawler_data = data.get("crawler", {})
    network_data = data.get("network", {})
    models = crawler_data.get("models", list(DEFAULT_MODELS))
    return AppConfig(
        aria2_host=aria2_data.get("host", "ws://heritage.bun-bull.ts.net:6800"),
        aria2_secret=aria2_data.get("secret", ""),
        download_dir=aria2_data.get("download_dir"),
        models=models,
        proxy=network_data.get("proxy"),
        sites=_parse_sites(data),
    )
