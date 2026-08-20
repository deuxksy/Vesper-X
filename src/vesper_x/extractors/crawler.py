from bs4 import BeautifulSoup


class CategoryCrawler:
    def extract_post_urls(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        post_urls = []
        for h2 in soup.find_all("h2", class_="post-box-title"):
            a_tag = h2.find("a", href=True)
            if a_tag and a_tag["href"] not in post_urls:
                post_urls.append(a_tag["href"])
        return post_urls

    def extract_pagination_urls(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        pagination_div = soup.find("div", class_="pagination")
        if not pagination_div:
            return []
        pages = []
        for a_tag in pagination_div.find_all("a", class_="page", href=True):
            href = a_tag["href"]
            if href not in pages:
                pages.append(href)
        return pages
