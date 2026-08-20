from bs4 import BeautifulSoup


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
