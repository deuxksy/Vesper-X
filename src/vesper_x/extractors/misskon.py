from bs4 import BeautifulSoup
from vesper_x.extractors.base import BaseExtractor

TARGET_DOMAINS = ["ouo.io", "ouo.press", "mediafire.com", "mega.nz", "gofile.io"]


class MisskonParser(BaseExtractor):
    def extract_download_links(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if any(domain in href for domain in TARGET_DOMAINS):
                if "static.mediafire.com" in href or "af_link.php" in href:
                    continue
                if not href.startswith("http://") and not href.startswith("https://"):
                    continue
                links.append(href)
        return list(dict.fromkeys(links))
