import asyncio
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# 우회 전용 Chrome 프로필 - cf_clearance 쿠키가 유지되어 링크마다 새 지문으로
# 보이는 것을 방지한다 (challenge 빈도 대폭 감소, 2026-09-07)
OUO_PROFILE_DIR = Path.home() / ".config" / "url-resolver" / "ouo_profile"

TARGET_DOMAINS = ["mediafire.com", "mega.nz", "gofile.io", "pixeldrain.com"]


def _is_target_url(url: str) -> bool:
    """도착 판정은 URL 전체 부분문자열이 아니라 hostname 기준으로 한다.

    /st/ 형식 ouo 링크는 목적지가 s= 파라미터에 평문으로 박혀 있어
    부분문자열 검사 시 입력 URL 자체가 목적지로 오판된다.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in TARGET_DOMAINS)

# ouo.io는 2단계 우회다: "I'M A HUMAN" 클릭 -> /go/ 페이지의 "Get Link" 버튼(countdown 후 활성화) 클릭 -> 목적지.
class OuoBypasser:
    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy

    async def resolve(self, short_url: str) -> str:
        # Fast path: /st/ links often contain the target directly in the query parameter '?s='
        parsed = urlparse(short_url)
        if "/st/" in parsed.path and parsed.query:
            from urllib.parse import parse_qs, unquote
            qs = parse_qs(parsed.query)
            if "s" in qs and qs["s"]:
                target = unquote(qs["s"][0])
                if _is_target_url(target):
                    return target

        return await self._run_playwright_bypass(short_url)

    async def _run_playwright_bypass(self, short_url: str) -> str:
        target_url = short_url

        async with async_playwright() as p:
            # ouo.io가 Cloudflare challenge를 앞에 뒀다 - 번들/headless Chromium은
            # "Just a moment..."에서 막히며 real Chrome headed만 통과한다 (2026-09-05 실측)
            launch_kwargs: dict = {"channel": "chrome", "headless": False}
            if self.proxy:
                launch_kwargs["proxy"] = {"server": self.proxy}
            OUO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(str(OUO_PROFILE_DIR), **launch_kwargs)
            # persistent profile에 쿠키가 쌓이면 ouo nginx가 400
            # (Request Header Or Cookie Too Large)을 돌려준다 -
            # cf_clearance만 남기고 정리한다 (2026-09-07 실측)
            cookies = await context.cookies()
            keep = [c for c in cookies if c.get("name") == "cf_clearance"]
            if len(cookies) != len(keep):
                await context.clear_cookies()
                if keep:
                    await context.add_cookies(keep)
            # UA를 덮어쓰지 않는다 - 가짜 UA(Chrome/120)과 실제 Chrome 바이너리 지문의
            # 불일치가 Cloudflare challenge를 유발한다 (2026-09-05 실측)
            page = context.pages[0] if context.pages else await context.new_page()

            def check_and_update_url(url: str):
                nonlocal target_url
                if _is_target_url(url):
                    target_url = url

            def on_response(response):
                check_and_update_url(response.url)

            def on_request(request):
                check_and_update_url(request.url)

            def on_popup(popup):
                # 버튼 클릭 시 광고 popup이 뜬다 - 즉시 닫는다
                asyncio.ensure_future(popup.close())

            page.on("response", on_response)
            page.on("request", on_request)
            page.on("popup", on_popup)

            try:
                await page.goto(short_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)

                # 각 단계: 버튼이 나타나고 활성화될 때까지 기다렸다 클릭, 목적지 도달 시 종료.
                # stage-2(/go/)는 Cloudflare Turnstile 검증 후 버튼이 늦게 생성되기도 한다.
                # 일부 사이트는 ouo 3중 체인(6스테이지)을 쓴다 - 여유를 두고 12까지 허용.
                for _stage in range(12):
                    if _is_target_url(target_url):
                        break
                    if _is_target_url(page.url):
                        target_url = page.url
                        break

                    btn = await self._wait_button(page, timeout_s=20)
                    if btn is None:
                        break

                    prev_url = page.url
                    await btn.click()
                    for _ in range(25):
                        await page.wait_for_timeout(1000)
                        if _is_target_url(page.url):
                            target_url = page.url
                            break
                        if page.url != prev_url:
                            break

                check_and_update_url(page.url)

            except Exception as e:
                logger.warning(f"Error during Playwright bypass for {short_url}: {e}")
            finally:
                await context.close()

            return target_url

    @staticmethod
    async def _wait_button(page, timeout_s: int):
        """버튼이 DOM에 나타나고 countdown/Turnstile 이후 활성화될 때까지 폴링한다."""
        for _ in range(timeout_s):
            for selector in ["#btn-main", "form button", "button[type='submit']"]:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    enabled = await page.evaluate(
                        "el => !el.disabled && !el.classList.contains('disabled')", btn
                    )
                    if enabled:
                        return btn
            await page.wait_for_timeout(1000)
        return None
