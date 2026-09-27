"""W4B 크롤러/파서 — 다운로드 링크는 Download 클릭 후 JS가 채운다 (2026-09-27 실측).

DOM/URL 상수는 실측값이며 구조 변경 시 상수만 갱신한다 (hegre.py 패턴).
mp4 서명 URL은 TTL이 있으므로 resolve는 dispatch 직전에만 호출한다.
"""
import re
from pathlib import Path
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

# 세션 쿠키 유지용 persistent profile - hegre_profile과 동일 패턴
W4B_PROFILE_DIR = Path.home() / ".config" / "url-resolver" / "w4b_profile"


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
            # 실측상 mp4 패널 href도 상대경로다 - aria2 전달을 위해 urljoin 필수
            mp4_url = urljoin(base_url, best["url"])
            picks.append({
                "url": mp4_url,
                "type": "video",
                "basename": mp4_url.split("?")[0].rsplit("/", 1)[-1],
            })
        return picks

    @staticmethod
    def extract_model_name(html: str) -> Optional[str]:
        """모델 페이지로 가는 앵커 중 텍스트 있는 것을 고른다 - 첫 앵커는 이미지라
        텍스트가 없다 (2026-09-28 E2E 실측). STARRING 라벨은 접두 제거한다."""
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/models/']"):
            text = a.get_text(" ", strip=True)
            if not text:
                continue
            return re.sub(r"(?i)^starring\s+", "", text).strip() or None
        return None


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

    @staticmethod
    def build_cookie_header(cookies: list[dict]) -> str:
        """aria2 전달용 Cookie 헤더 - session/cf_clearance만 k=v; k=v로 조립.

        cf_clearance는 UA·IP 바인딩이라 브라우저 세션의 실제 UA도 함께 stash한다
        (_stash_session). Cloudflare가 aria2를 챌린지하지 않으면 잉여다.
        """
        wanted = {"session", "cf_clearance"}
        pairs = [f"{c['name']}={c['value']}" for c in cookies if c.get("name") in wanted]
        return "; ".join(pairs)

    def ensure_credentials(self) -> CredentialConfig:
        creds = self.config.credentials.get("w4b")
        if not creds or not creds.username:
            raise ValueError(
                "config.toml [credentials.w4b] 미설정 - username/password를 추가한다")
        return creds

    def _launch_kwargs(self) -> dict:
        kwargs: dict = {"channel": "chrome", "headless": False}
        if self.config.proxy:
            kwargs["proxy"] = {"server": self.config.proxy}
        return kwargs

    async def _dismiss_age_gate(self, page) -> None:
        """Adults only 오버레이를 수락해 닫는다 - 수락 쿠키는 profile에 유지된다.

        미수락 상태로는 본문 클릭·다운로드 패널이 모두 막힌다 (2026-09-28 E2E 실측).
        """
        gate = page.locator("a.button.greenfull[title*='Yes, enter']")
        try:
            if await gate.count() > 0:
                await gate.first.click(timeout=3000)
        except Exception:
            pass  # 게이트 부재/지연 렌더 - 이후 단계에서 재시도 없이 진행

    async def _stash_session(self, context, page) -> None:
        """CDN/CF 인증용 쿠키와 실제 브라우저 UA를 stash - metadata로 전달된다."""
        self._cookie_header = self.build_cookie_header(await context.cookies())
        self._user_agent = await page.evaluate("navigator.userAgent")

    async def collect(self, model_slug: Optional[str] = None) -> list[dict]:
        """모델/신작 목록 수집 - updates 모드는 무한스크롤 대응 scroll 루프 (스펙 7.1)."""
        if model_slug:
            url = URLS["model"].format(slug=model_slug)
            html = await self.fetch(url)
            return self.extract_model_content_refs(html, url)
        html = await self.fetch(URLS["updates"], scrolls=5)
        return self.extract_model_content_refs(html, URLS["updates"])

    async def fetch(self, url: str, scrolls: int = 0) -> str:
        """persistent Chrome 세션으로 페이지 HTML 반환 (매 launch, ouo/hegre 패턴)."""
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            W4B_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                str(W4B_PROFILE_DIR), **self._launch_kwargs())
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                await self._dismiss_age_gate(page)
                for _ in range(scrolls):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1000)
                await self._stash_session(context, page)
                return await page.content()
            finally:
                await context.close()

    async def resolve(self, url: str) -> list[DownloadMetadata]:
        """세트 페이지에서 Download 패널을 열어 [zip, 최고 mp4] metadata를 만든다.

        링크는 클릭 후 JS가 채우므로 정적 fetch로는 불가능 - Playwright 상호작용 필수
        (스펙 3.1). 서명 TTL 방어는 루프가 dispatch 직전에만 resolve를 호출한다.
        """
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            W4B_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                str(W4B_PROFILE_DIR), **self._launch_kwargs())
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                await self._dismiss_age_gate(page)
                try:
                    # STARRING 섹션은 SPA 지연 렌더라 networkidle까지 대기해야
                    # 모델명을 안정적으로 추출한다 (2026-09-28 E2E 실측)
                    await page.wait_for_load_state("networkidle")
                except Exception:
                    pass
                try:
                    trigger = page.get_by_role("link", name="Download", exact=True).first
                    await trigger.click()
                    await page.wait_for_selector(SELECTORS["download_links"], timeout=10000)
                except Exception:
                    pass  # 패널 미오픈 - 아래 추출이 빈 목록이 되고 루프가 계속한다
                await self._stash_session(context, page)
                html = await page.content()
            finally:
                await context.close()

        soup = BeautifulSoup(html, "html.parser")
        links = [{"href": a.get("href"), "text": a.get_text(" ", strip=True)}
                 for a in soup.select(SELECTORS["download_links"])]
        picks = self.parser.pick_downloads(links, url)
        model_name = self.parser.extract_model_name(html)
        album = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        model_dir = re.sub(r"[^\w\- .()]+", "_", model_name) if model_name else "Unknown"
        return [DownloadMetadata(
            direct_url=pick["url"],
            referer=url,
            user_agent=self._user_agent,
            filename=f"{model_dir}/{album}/{pick['basename']}",
            source_page=url,
            models=[model_name] if model_name else [],
            file_page_url=url,
            cookies=self._cookie_header,
        ) for pick in picks]

    async def login(self) -> bool:
        """watch4beauty.com 로그인 → persistent profile에 세션 저장. 성공 여부 반환.

        클릭이 submit을 무시하는 사례가 있어(2026-09-27 실측) requestSubmit fallback.
        """
        from playwright.async_api import async_playwright
        creds = self.ensure_credentials()
        async with async_playwright() as p:
            W4B_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                str(W4B_PROFILE_DIR), **self._launch_kwargs())
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(URLS["login"], wait_until="domcontentloaded")
                await self._dismiss_age_gate(page)
                await page.fill(SELECTORS["login_user"], creds.username)
                await page.fill(SELECTORS["login_pass"], creds.password)
                # 연령 게이트 오버레이가 포인터를 가로채 click이 타임아웃된다
                # (2026-09-28 실측) - JS submit이 확실한 경로다
                await page.evaluate("document.querySelector('form').requestSubmit()")
                try:
                    await page.wait_for_load_state("networkidle")
                except Exception:
                    pass
                return "/login" not in page.url
            finally:
                await context.close()
