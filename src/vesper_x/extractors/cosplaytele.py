from bs4 import BeautifulSoup
from vesper_x.extractors.base import BaseExtractor

TARGET_DOMAINS = ["ouo.io", "ouo.press", "mediafire.com", "mega.nz", "gofile.io"]


class CosplayteleParser(BaseExtractor):
    def extract_download_links(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if any(domain in href for domain in TARGET_DOMAINS):
                # Filter out Mediafire static ad links and protocol-less URLs
                if "static.mediafire.com" in href or "af_link.php" in href:
                    continue
                if not href.startswith("http://") and not href.startswith("https://"):
                    continue
                links.append(href)
        return list(dict.fromkeys(links))


class CosplayteleCrawler:
    def extract_post_urls(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        post_urls = []
        for a in soup.find_all("a", class_="plain", href=True):
            href = a["href"].strip()
            if "cosplaytele.com/" in href and not any(x in href for x in ["/tag/", "/category/", "/page/", "/explore-categories/"]):
                if href not in post_urls:
                    post_urls.append(href)
        return post_urls

    def extract_pagination_urls(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        pages = []
        for a_tag in soup.find_all("a", class_="page-number", href=True):
            href = a_tag["href"].strip()
            if href not in pages:
                pages.append(href)
        return pages
