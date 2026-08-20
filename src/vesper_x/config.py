from dataclasses import dataclass, field
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "url-resolver" / "config.toml"
DEFAULT_MODELS = ["幼水铃衣", "you-shui-ling-yi", "luo-li-lolisama"]


@dataclass
class AppConfig:
    aria2_host: str = "ws://heritage.bun-bull.ts.net:6800"
    aria2_secret: str = ""
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))


def load_config() -> AppConfig:
    if not DEFAULT_CONFIG_PATH.exists():
        return AppConfig()
    with open(DEFAULT_CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    aria2_data = data.get("aria2", {})
    crawler_data = data.get("crawler", {})
    models = crawler_data.get("models", list(DEFAULT_MODELS))
    return AppConfig(
        aria2_host=aria2_data.get("host", "ws://heritage.bun-bull.ts.net:6800"),
        aria2_secret=aria2_data.get("secret", ""),
        models=models,
    )
