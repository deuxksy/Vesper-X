import asyncio
import logging

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

TARGET_DOMAINS = ["mediafire.com", "mega.nz", "gofile.io", "pixeldrain.com"]

# ouo.io는 2단계 우회다: "I'M A HUMAN" 클릭 -> /go/ 페이지의 "Get Link" 버튼(countdown 후 활성화) 클릭 -> 목적지.
class OuoBypasser:
    async def resolve(self, short_url: str) -> str:
        return await self._run_playwright_bypass(short_url)

    async def _run_playwright_bypass(self, short_url: str) -> str:
        target_url = short_url

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            def check_and_update_url(url: str):
                nonlocal target_url
                if any(domain in url for domain in TARGET_DOMAINS):
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
                for _stage in range(4):
                    if any(domain in target_url for domain in TARGET_DOMAINS):
                        break
                    if any(domain in page.url for domain in TARGET_DOMAINS):
                        target_url = page.url
                        break

                    btn = await self._wait_button(page, timeout_s=20)
                    if btn is None:
                        break

                    prev_url = page.url
                    await btn.click()
                    for _ in range(25):
                        await page.wait_for_timeout(1000)
                        if any(domain in page.url for domain in TARGET_DOMAINS):
                            target_url = page.url
                            break
                        if page.url != prev_url:
                            break

                check_and_update_url(page.url)

            except Exception as e:
                logger.warning(f"Error during Playwright bypass for {short_url}: {e}")
            finally:
                await browser.close()

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
