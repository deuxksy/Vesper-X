from bs4 import BeautifulSoup


class Cup2dCrawler:
    """cup2d.com 카테고리 리스팅 크롤러 (gridshow 테마).

    포스트 링크는 h3.gridshow-grid-post-title의 bookmark 링크에,
    페이지네이션은 표준 WP nav.pagination (page-numbers)에 있다.
    다운로드 링크(ouo) 추출은 기존 MisskonParser 경로를 그대로 탄다.
    """

    def extract_post_urls(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        post_urls = []
        for h3 in soup.find_all("h3", class_="gridshow-grid-post-title"):
            a_tag = h3.find("a", href=True)
            if a_tag and a_tag["href"] not in post_urls:
                post_urls.append(a_tag["href"])
        return post_urls

    def extract_pagination_urls(self, html_content: str) -> list[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        pagination_nav = soup.find("nav", class_="pagination")
        if not pagination_nav:
            return []
        pages = []
        for a_tag in pagination_nav.find_all("a", class_="page-numbers", href=True):
            if a_tag["href"] not in pages:
                pages.append(a_tag["href"])
        return pages
