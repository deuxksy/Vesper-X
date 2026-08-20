from typing import Optional

from playwright.sync_api import sync_playwright

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 한국 ISP SNI 차단 회피용: Chrome ECH + secure DoH.
# Playwright 번들 Chromium은 ECH가 활성화되지 않아 misskon.com이 TLS 단계에서 차단된다.
ECH_LAUNCH_ARGS = [
    "--enable-features=EncryptedClientHello",
    "--dns-over-https-mode=secure",
    "--dns-over-https-templates=https://dns.google/dns-query",
]


class BrowserFetcher:
    """실제 Chrome(channel=chrome)을 1회 launch 후 page를 재사용하는 sync page fetcher.

    with BrowserFetcher() as fetcher:
        html = fetcher.fetch(url)
    """

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, proxy: Optional[str] = None, headless: bool = True):
        self.user_agent = user_agent
        self.proxy = proxy
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "BrowserFetcher":
        self._playwright = sync_playwright().start()
        launch_kwargs = {"channel": "chrome", "headless": self.headless, "args": ECH_LAUNCH_ARGS}
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        context = self._browser.new_context(user_agent=self.user_agent)
        self._page = context.new_page()
        return self

    def fetch(self, url: str, timeout_ms: int = 30000) -> str:
        self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return self._page.content()

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
