import json
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@dataclass
class GofileDownload:
    direct_url: str
    filename: str
    cookies: str


class GofileResolver:
    """gofile.io/d/<id> 폴더를 직링크 목록으로 변환한다.

    gofile은 익명 API 접근을 차단한다(error-notPremium). 웹 UI가 스스로 호출하는
    contents XHR을 Playwright로 캡처해 파일 목록(id/name/server)과 guest
    accountToken 쿠키를 얻는다. 직링크 형식(2026-08 실접속 검증):
      https://{server}.gofile.io/download/web/{fileId}/{quote(name)}
      인증은 Cookie: accountToken=<token>
    """

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy

    async def resolve(self, page_url: str) -> list[GofileDownload]:
        content_id = page_url.rstrip("/").split("/")[-1]
        body: bytes | None = None
        cookies: dict[str, str] = {}

        async with async_playwright() as p:
            launch_kwargs: dict = {"headless": True}
            if self.proxy:
                launch_kwargs["proxy"] = {"server": self.proxy}
            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()

            async def on_response(resp):
                nonlocal body
                if "/contents/" in resp.url and content_id in resp.url and body is None:
                    try:
                        body = await resp.body()
                    except Exception:
                        pass

            page.on("response", on_response)
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                for _ in range(20):
                    if body is not None:
                        break
                    await page.wait_for_timeout(1000)
                cookies = {c["name"]: c["value"] for c in await context.cookies()}
            except Exception as e:
                logger.warning(f"Error capturing gofile contents for {page_url}: {e}")
                return []
            finally:
                await browser.close()

        token = cookies.get("accountToken")
        if body is None or not token:
            logger.warning(f"gofile contents/accountToken not captured for {page_url}")
            return []
        try:
            response = json.loads(body)
        except ValueError:
            logger.warning(f"gofile contents response is not JSON for {page_url}")
            return []
        return self.build_downloads(response, token=token)

    @staticmethod
    def build_downloads(contents_response: dict, token: str) -> list[GofileDownload]:
        if contents_response.get("status") != "ok":
            return []

        files = []

        def walk(node):
            for child in (node.get("children") or {}).values():
                if child.get("type") == "file":
                    files.append(child)
                elif child.get("type") == "folder":
                    walk(child)

        walk(contents_response.get("data") or {})
        return [
            GofileDownload(
                direct_url=(
                    f"https://{f['serverSelected']}.gofile.io/download/web/"
                    f"{f['id']}/{quote(f['name'])}"
                ),
                filename=f["name"],
                cookies=f"accountToken={token}",
            )
            for f in files
        ]
