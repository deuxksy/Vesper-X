from urllib.parse import urlparse
import aria2p

from vesper_x.config import AppConfig
from vesper_x.models import DownloadMetadata


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

        download = self.api.add(metadata.direct_url, options=options)
        if isinstance(download, list):
            return download[0].gid
        return getattr(download, "gid", str(download))
