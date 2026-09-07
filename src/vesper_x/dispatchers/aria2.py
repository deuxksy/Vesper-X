from urllib.parse import urlparse
import aria2p

from vesper_x.config import AppConfig, SiteConfig
from vesper_x.models import DownloadMetadata


def _site_subdir(source_page: str, sites: dict[str, SiteConfig]) -> str | None:
    """source_page 도메인 → 다운로드 서브디렉토리. heritage 압축 해제 스크립트가
    사이트별 고정 비번(misskon/cosplaytele)을 디렉토리로 판별한다."""
    host = urlparse(source_page).hostname or ""
    for domain, site in sites.items():
        if host == domain or host.endswith("." + domain):
            return site.subdir
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

    def waiting_count(self) -> int:
        """aria2 waiting 큐 개수 - crawl 게이트는 waiting이 비어있을 때만 dispatch한다."""
        return sum(1 for d in self.client.tell_waiting(0, 100) if d.get("status") == "waiting")

    def status_summary(self) -> dict:
        """aria2 전체 상태 집계 - crawl 진행 중 가시화용."""
        counts = {"active": 0, "waiting": 0, "paused": 0, "complete": 0, "error": 0, "total": 0}
        for d in self.client.tell_active():
            counts["active"] += 1
        for d in self.client.tell_waiting(0, 1000):
            status = d.get("status")
            if status in counts:
                counts[status] += 1
        for d in self.client.tell_stopped(0, 1000):
            status = d.get("status")
            if status in counts:
                counts[status] += 1
        counts["total"] = sum(counts[k] for k in ("active", "waiting", "paused", "complete", "error"))
        return counts

    def active_downloads(self) -> list[dict]:
        """진행 중 다운로드 상세 (이름/용량/진행/속도) - status 명령용."""
        items = []
        for d in self.client.tell_active():
            name = (d.get("files") or [{"path": ""}])[0].get("path", "").rsplit("/", 1)[-1]
            total = int(d.get("totalLength", 0))
            done = int(d.get("completedLength", 0))
            speed = int(d.get("downloadSpeed", 0))
            items.append({
                "name": name,
                "total_mb": total / 1048576,
                "done_mb": done / 1048576,
                "speed_mb": speed / 1048576,
            })
        return items

    @staticmethod
    def format_status(summary: dict) -> str:
        return (f"전체 {summary['total']} | ↓ {summary['active']} | "
                f"대기 {summary['waiting']} | 일시 {summary['paused']} | "
                f"완료 {summary['complete']} | 오류 {summary['error']}")

    def dispatch(self, metadata: DownloadMetadata) -> str:
        options = {
            "header": [
                f"Referer: {metadata.referer}",
                f"User-Agent: {metadata.user_agent}",
            ]
        }
        if metadata.cookies:
            options["header"].append(f"Cookie: {metadata.cookies}")
        if metadata.filename:
            options["out"] = metadata.filename
        if self.config.download_dir:
            subdir = _site_subdir(metadata.source_page, self.config.sites)
            if subdir:
                options["dir"] = self.config.download_dir.rstrip("/") + "/" + subdir

        download = self.api.add(metadata.direct_url, options=options)
        if isinstance(download, list):
            return download[0].gid
        return getattr(download, "gid", str(download))
