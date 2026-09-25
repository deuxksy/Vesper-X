"""Hegre 크롤러/파서 — 인증 세션으로 4K 영상·6000px ZIP 직링크 추출.

DOM selector와 URL 패턴은 실측 전 가정값이다 — SELECTORS/URLS 상수로 격리해
Task 6 실접속 recon에서 상수만 갱신한다 (파싱 로직과 분리).
CDN 직링크는 dispatch 직전에만 resolve한다 (spec 4.3 — 서명 TTL/IP 바인딩 방어).
"""
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from vesper_x.config import AppConfig, CredentialConfig
from vesper_x.models import DownloadMetadata

URLS = {
    "model": "https://hegre.com/models/{slug}",   # 가정 — Task 6 확정
    "updates": "https://hegre.com/update",        # 가정 — Task 6 확정
    # 콘텐츠 경로 패턴(가정 — Task 6 확정): 목록에서 films/galleries 링크 식별용
    "content_path": r"/(films?|galleries?|magazines?)/[\w-]+",
}

SELECTORS = {
    "download_links": "div.download a[href]",     # 가정 — Task 6 확정
    "gallery_zip": "a[href$='.zip']",             # 가정 — Task 6 확정
    "model_name": "a.model",                      # 가정 — Task 6 확정
    "next_page": "a.next, li.pagination-next a, a[rel='next']",  # 가정 — Task 6 확정
}

_RESOLUTION_RE = re.compile(r"(\d{3,4})\s*p", re.IGNORECASE)
_PIXELS_RE = re.compile(r"(\d{4,5})\s*px", re.IGNORECASE)


class HegreParser:
    @staticmethod
    def content_type(url: str) -> str:
        """/films|/movies → 'video', 그 외(/galleries|/magazines) → 'photo'."""
        if re.search(r"/(films?|movies?|videos?)/", urlparse(url).path):
            return "video"
        return "photo"

    def video_links(self, html: str) -> list[dict]:
        """해상도 내림차순 mp4 목록 — 동일 해상도 중복은 제거."""
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict] = []
        for a in soup.select(SELECTORS["download_links"]):
            label = a.get_text(" ", strip=True) or a.get("data-resolution", "")
            m = _RESOLUTION_RE.search(label)
            if m and a["href"].endswith(".mp4"):
                links.append({"url": a["href"], "resolution": int(m.group(1))})
        links.sort(key=lambda x: -x["resolution"])
        seen, out = set(), []
        for link in links:
            if link["resolution"] not in seen:
                seen.add(link["resolution"])
                out.append(link)
        return out

    def best_video(self, html: str) -> Optional[dict]:
        links = self.video_links(html)
        return links[0] if links else None

    def zip_links(self, html: str) -> list[dict]:
        """픽셀 내림차순 ZIP 목록 — 6000px 우선, 소팅이 곧 fallback이다."""
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict] = []
        for a in soup.select(SELECTORS["gallery_zip"]):
            label = a.get_text(" ", strip=True) or a.get("data-size", "")
            m = _PIXELS_RE.search(label)
            if m:
                links.append({"url": a["href"], "pixels": int(m.group(1))})
        links.sort(key=lambda x: -x["pixels"])
        return links

    def best_zip(self, html: str) -> Optional[dict]:
        links = self.zip_links(html)
        return links[0] if links else None

    @staticmethod
    def extract_model_name(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        a = soup.select_one(SELECTORS["model_name"])
        return a.get_text(" ", strip=True) if a else None


HEGRE_PROFILE_DIR = Path.home() / ".config" / "url-resolver" / "hegre_profile"
DEFAULT_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/128.0.0.0 Safari/537.36")

_CONTENT_PATH_RE = re.compile(URLS["content_path"])


class HegreCrawler:
    """인증 세션(persistent Chrome profile) + 목록 수집.

    세션은 ouo와 동일한 launch_persistent_context 패턴이다 — 프로필 디렉토리에
    로그인 쿠키가 유지되어 storage_state 파일 관리가 불필요하다.
    login/fetch의 Playwright 구현은 Task 6 실측에서 selector와 함께 완성한다.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.parser = HegreParser()

    def ensure_credentials(self) -> CredentialConfig:
        creds = self.config.credentials.get("hegre")
        if not creds or not creds.username:
            raise ValueError(
                "config.toml [credentials.hegre] 미설정 - username/password를 추가한다")
        return creds

    # --- 목록 수집 (정적 — mock 테스트 대상) ---

    @staticmethod
    def extract_gallery_refs(html: str, base_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        refs: list[dict] = []
        seen: set[str] = set()
        for a in soup.select("a[href]"):
            href = urljoin(base_url, a["href"])
            if _CONTENT_PATH_RE.search(urlparse(href).path) and href not in seen:
                seen.add(href)
                refs.append({"url": href, "title": a.get_text(" ", strip=True)})
        return refs

    @staticmethod
    def extract_next_page_url(html: str, base_url: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        a = soup.select_one(SELECTORS["next_page"])
        return urljoin(base_url, a["href"]) if a and a.get("href") else None

    # --- resolve (dispatch 직전 호출 — spec 4.3) ---

    def resolve_content(self, html: str, page_url: str) -> list[DownloadMetadata]:
        ctype = self.parser.content_type(page_url)
        model_name = self.parser.extract_model_name(html)
        best = (self.parser.best_video(html) if ctype == "video"
                else self.parser.best_zip(html))
        if not best:
            return []
        direct_url = best["url"]
        # spec 4.1 계층 H/{모델명}/{앨범 제목}/ - aria2 out은 dir 기준 상대경로라
        # filename에 모델/앨범 경로를 싣는다(dispatch는 aria2.py 불변)
        basename = direct_url.split("?")[0].rsplit("/", 1)[-1]
        album = urlparse(page_url).path.rstrip("/").rsplit("/", 1)[-1]
        model_dir = re.sub(r"[^\w\- .()]+", "_", model_name) if model_name else "Unknown"
        return [DownloadMetadata(
            direct_url=direct_url,
            referer=page_url,
            user_agent=DEFAULT_USER_AGENT,
            filename=f"{model_dir}/{album}/{basename}",
            source_page=page_url,
            models=[model_name] if model_name else [],
            file_page_url=page_url,
        )]

    # --- Playwright 세션 (골격 — selector는 Task 6 실측에서 확정) ---

    async def collect(self, model_slug: Optional[str] = None,
                      max_pages: int = 10) -> list[dict]:
        """모델/신작 목록 순회 — selector는 Task 6 실측에서 확정."""
        base = (URLS["model"].format(slug=model_slug) if model_slug
                else URLS["updates"])
        refs: list[dict] = []
        url: Optional[str] = base
        for _ in range(max_pages):
            html = await self.fetch(url)
            refs.extend(self.extract_gallery_refs(html, url))
            url = self.extract_next_page_url(html, url)
            if not url:
                break
        return refs

    async def fetch(self, url: str) -> str:
        """persistent Chrome 세션 fetch — Task 6 실측에서 구현한다."""
        raise NotImplementedError("HegreCrawler.fetch는 Task 6 실측 후 구현")

    def _launch_kwargs(self) -> dict:
        kwargs: dict = {"channel": "chrome", "headless": False}
        if self.config.proxy:
            kwargs["proxy"] = {"server": self.config.proxy}
        return kwargs
