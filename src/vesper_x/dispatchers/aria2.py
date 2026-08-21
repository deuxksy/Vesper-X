from urllib.parse import urlparse
import aria2p

from vesper_x.config import AppConfig
from vesper_x.models import DownloadMetadata

# source_page 도메인 → 다운로드 서브디렉토리. heritage 압축 해제 스크립트가
# 사이트별 고정 비번(misskon/cosplaytele)을 디렉토리로 판별한다.
SITE_DIRS = {
    "misskon.com": "misskon",
    "cosplaytele.com": "cosplaytele",
}


def _site_subdir(source_page: str) -> str | None:
    host = urlparse(source_page).hostname or ""
    for domain, subdir in SITE_DIRS.items():
        if host == domain or host.endswith("." + domain):
            return subdir
    return None


class Aria2Dispatcher:
    def __init__(self, config: AppConfig):
        self.config = config

        parsed = urlparse(config.aria2_host)
        scheme = "https" if parsed.scheme in ("wss", "https") else "http"
        host = f"{scheme}://{parsed.hostname}" if parsed.hostname else "http://localhost"
        port = parsed.port if parsed.port is not None else 6800

        self.client = aria2p.Client(
            host=host,
            port=port,
            secret=config.aria2_secret,
        )
        self.api = aria2p.API(self.client)

    def dispatch(self, metadata: DownloadMetadata) -> str:
        options = {
            "header": [
                f"Referer: {metadata.referer}",
                f"User-Agent: {metadata.user_agent}",
            ]
        }
        if metadata.filename:
            options["out"] = metadata.filename
        if self.config.download_dir:
            subdir = _site_subdir(metadata.source_page)
            if subdir:
                options["dir"] = self.config.download_dir.rstrip("/") + "/" + subdir

        download = self.api.add(metadata.direct_url, options=options)
        if isinstance(download, list):
            return download[0].gid
        return getattr(download, "gid", str(download))
