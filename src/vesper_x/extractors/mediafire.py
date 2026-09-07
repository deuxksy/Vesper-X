import re
from bs4 import BeautifulSoup
import httpx


class MediafireResolver:
    def extract_direct_url(self, html_content: str) -> str | None:
        soup = BeautifulSoup(html_content, "html.parser")
        
        # 1. By id="downloadButton"
        btn = soup.find("a", id="downloadButton")
        if btn and btn.get("href"):
            return btn["href"].strip()
            
        # 2. By aria-label="Download file"
        btn_aria = soup.find("a", attrs={"aria-label": "Download file"})
        if btn_aria and btn_aria.get("href"):
            return btn_aria["href"].strip()

        # 3. By class containing "popsok"
        btn_popsok = soup.find("a", class_=lambda c: c and "popsok" in c)
        if btn_popsok and btn_popsok.get("href"):
            return btn_popsok["href"].strip()

        # 4. By href matching download*.mediafire.com
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "download" in href and "mediafire.com" in href and not href.endswith(".php"):
                return href

        return None

    def resolve_folder(self, folder_url: str) -> list[str]:
        """Mediafire 폴더 URL에서 포함된 개별 파일 URL 목록을 추출한다."""
        match = re.search(r"/folder/([a-zA-Z0-9]+)", folder_url)
        if not match:
            return []
        folder_key = match.group(1)
        api_url = f"https://www.mediafire.com/api/1.4/folder/get_content.php?folder_key={folder_key}&content_type=files&response_format=json"
        try:
            resp = httpx.get(api_url, timeout=20.0)
            data = resp.json()
            files = data.get("response", {}).get("folder_content", {}).get("files", [])
            return [f"https://www.mediafire.com/file/{f['quickkey']}" for f in files if "quickkey" in f]
        except Exception:
            return []
