"""W4B 크롤러/파서 — 다운로드 링크는 Download 클릭 후 JS가 채운다 (2026-09-27 실측).

DOM/URL 상수는 실측값이며 구조 변경 시 상수만 갱신한다 (hegre.py 패턴).
mp4 서명 URL은 TTL이 있으므로 resolve는 dispatch 직전에만 호출한다.
"""
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from vesper_x.config import AppConfig, CredentialConfig
from vesper_x.models import DownloadMetadata

URLS = {
    "home": "https://www.watch4beauty.com",
    "login": "https://www.watch4beauty.com/login",
    "model": "https://www.watch4beauty.com/models/{slug}",
    "updates": "https://www.watch4beauty.com/updates",
}

SELECTORS = {
    "login_user": "#username-field",
    "login_pass": "#password-field",
    "model_content_links": "a.grid-item",
    "download_links": "a.button[href*='.zip'], a.button[href*='.mp4']",
}

_UPDATES_PATH_RE = re.compile(r"/updates/[\w-]+/?")
_RESOLUTION_RE = re.compile(r"/(\d{3,4})\.mp4")
_POPULAR_SLUGS = {"popular"}


class W4BParser:
    @staticmethod
    def pick_downloads(links: list[dict], base_url: str) -> list[dict]:
        """다운로드 패널 앵커에서 [zip, 최고 mp4]를 고른다 — 사진/영상 부재 허용.

        ZIP은 상대경로라 urljoin, mp4는 서명 절대경로라 그대로 사용한다.
        해상도는 라벨 대신 URL 경로(/2160.mp4)에서 추출한다.
        """
        picks: list[dict] = []
        for link in links:
            href = link.get("href") or ""
            if ".zip" in href:
                path = href.split("?")[0]
                picks.append({
                    "url": urljoin(base_url, href),
                    "type": "photo",
                    "basename": path.rsplit("/", 1)[-1],
                })

        videos: list[dict] = []
        for link in links:
            href = link.get("href") or ""
            path = href.split("?")[0]
            if path.endswith(".mp4"):
                m = _RESOLUTION_RE.search(path)
                if m:
                    videos.append({"url": href, "resolution": int(m.group(1))})
        if videos:
            # 2160 우선, 없으면 가용 최대 해상도
            best = max(videos, key=lambda v: (v["resolution"] == 2160, v["resolution"]))
            picks.append({
                "url": best["url"],
                "type": "video",
                "basename": best["url"].split("?")[0].rsplit("/", 1)[-1],
            })
        return picks

    @staticmethod
    def extract_model_name(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        a = soup.select_one("a[href*='/models/']")
        if not a:
            return None
        return a.get_text(" ", strip=True) or None


class W4BCrawler:
    def __init__(self, config: AppConfig):
        self.config = config
        self.parser = W4BParser()
        self._cookie_header: Optional[str] = None
        self._user_agent: Optional[str] = None

    @staticmethod
    def extract_model_content_refs(html: str, base_url: str) -> list[dict]:
        """모델 페이지 a.grid-item에서 /updates/<slug> 정본만 수집 — stories/노이즈 제외."""
        soup = BeautifulSoup(html, "html.parser")
        refs: list[dict] = []
        seen: set[str] = set()
        for a in soup.select("a.grid-item[href]"):
            href = urljoin(base_url, a["href"])
            parsed = urlparse(href)
            if not _UPDATES_PATH_RE.fullmatch(parsed.path):
                continue
            slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            if slug in _POPULAR_SLUGS:
                continue
            if href in seen:
                continue
            seen.add(href)
            refs.append({"url": href, "title": a.get("title")})
        return refs
