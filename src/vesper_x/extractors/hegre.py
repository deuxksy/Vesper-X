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
    "home": "https://www.hegre.com",              # 실측 2026-09-25
    "login": "https://www.hegre.com/login",       # 실측 2026-09-25 (form POST, CSRF)
    "model": "https://www.hegre.com/models/{slug}",   # 실측 2026-09-25
    "updates": "https://www.hegre.com",           # 신작: 홈페이지가 최신 films 노출
    # 콘텐츠 경로 패턴 (실측 2026-09-25): films=video, photos=photo.
    # collections(중복 큐레이션)/news/sexed는 제외
    "content_path": r"/(films?|photos?)/[\w-]+",
}

SELECTORS = {
    "download_links": "a[href*='.mp4']",          # 실측: content.hegre.com 정본/pp.hegre.com trailer
    "gallery_zip": "a[href*='.zip']",             # 실측: cc.hegre.com zip (?v= 쿼리 때문에 $= 불가)
    "model_name": "a.record-model",               # 실측: 모델명은 title 속성에 있음
    "next_page": "a.next, li.pagination-next a, a[rel='next']",
    "login_user": "#username",                    # 실측 2026-09-25
    "login_pass": "#password",                    # 실측 2026-09-25
    "login_submit": "input.submit.not-on-phone",  # 실측 2026-09-25
}

# trailer(공개)와 정본(인증) 구분: 정본 CDN host (실측 2026-09-25)
CDN_HOSTS = {"content.hegre.com", "cc.hegre.com"}

_RESOLUTION_RE = re.compile(r"(\d{3,4})\s*p", re.IGNORECASE)
_PIXELS_RE = re.compile(r"(\d{4,5})\s*px", re.IGNORECASE)


class HegreParser:
    @staticmethod
    def content_type(url: str) -> str:
        """/films → 'video', /photos(그 외) → 'photo' (실측 2026-09-25)."""
        if re.search(r"/films?/", urlparse(url).path):
            return "video"
        return "photo"

    def video_links(self, html: str) -> list[dict]:
        """해상도 내림차순 정본 mp4 목록 — trailer(pp.hegre.com) 제외, 중복 제거.

        실측 2026-09-25: 정본 href는 .../films/<slug>/<slug>-<res>p.mp4?d=attachment&v=<ts>.
        라벨에 해상도가 없어도 파일명에서 <res>p를 추출한다.
        """
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict] = []
        for a in soup.select(SELECTORS["download_links"]):
            href = a["href"]
            host = urlparse(href).hostname or ""
            path = href.split("?")[0]
            if host not in CDN_HOSTS or not path.endswith(".mp4"):
                continue
            label = a.get_text(" ", strip=True)
            m = _RESOLUTION_RE.search(label) or _RESOLUTION_RE.search(path)
            if m:
                links.append({"url": href, "resolution": int(m.group(1))})
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
        """픽셀 내림차순 ZIP 목록 — 최대 px가 곧 선택 기준이자 fallback.

        실측 2026-09-25: photo 갤러리는 cc.hegre.com/galleries/<slug>/zips/<slug>-<px>px.zip
        (10000/6000/3000/1200px 4종, 앵커 라벨 없음 — 파일명에서 px 추출).
        """
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict] = []
        for a in soup.select(SELECTORS["gallery_zip"]):
            href = a["href"]
            host = urlparse(href).hostname or ""
            if host not in CDN_HOSTS:
                continue
            m = _PIXELS_RE.search(a.get_text(" ", strip=True)) or _PIXELS_RE.search(href)
            if m:
                links.append({"url": href, "pixels": int(m.group(1))})
        links.sort(key=lambda x: -x["pixels"])
        return links

    def best_zip(self, html: str) -> Optional[dict]:
        """6000px 우선 (spec 3.2) — 없으면 가용 최대 px fallback."""
        links = self.zip_links(html)
        if not links:
            return None
        for link in links:
            if link["pixels"] == 6000:
                return link
        return links[0]

    @staticmethod
    def extract_model_name(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        a = soup.select_one(SELECTORS["model_name"])
        if not a:
            return None
        # 실측: <a class="record-model" title="Ani"> — 텍스트 노드가 없어 title 우선
        return a.get("title") or a.get_text(" ", strip=True) or None


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
        # fetch마다 persistent profile에서 갱신 - CDN 다운로드 인증용 (실측 2026-09-25:
        # login 쿠키만으로 content/cc.hegre.com 200, Referer/IP 바인딩 없음)
        self._session_cookie: Optional[str] = None

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
            cookies=self._session_cookie,
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
        """persistent Chrome 세션으로 페이지 HTML 반환 (매 launch, ouo 패턴)."""
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            HEGRE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                str(HEGRE_PROFILE_DIR), **self._launch_kwargs())
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                content = await page.content()
                # CDN 인증 쿠키 캐시 - aria2 Cookie 헤더로 전달된다
                for c in await context.cookies():
                    if c["name"] == "login" and c.get("value"):
                        self._session_cookie = f"login={c['value']}"
                        break
                return content
            finally:
                await context.close()

    async def login(self) -> bool:
        """hegre.com 로그인 → persistent profile에 세션 저장. 성공 여부 반환."""
        from playwright.async_api import async_playwright
        creds = self.ensure_credentials()
        async with async_playwright() as p:
            HEGRE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                str(HEGRE_PROFILE_DIR), **self._launch_kwargs())
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(URLS["login"], wait_until="domcontentloaded")
                await page.fill(SELECTORS["login_user"], creds.username)
                await page.fill(SELECTORS["login_pass"], creds.password)
                await page.click(SELECTORS["login_submit"])
                await page.wait_for_load_state("networkidle")
                # 로그인 실패 시 /login에 재머물거나 에러 박스가 뜬다
                return "login" not in page.url
            finally:
                await context.close()

    def _launch_kwargs(self) -> dict:
        kwargs: dict = {"channel": "chrome", "headless": False}
        if self.config.proxy:
            kwargs["proxy"] = {"server": self.config.proxy}
        return kwargs
