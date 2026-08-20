# tests/test_cosplaytele.py
from vesper_x.extractors.cosplaytele import CosplayteleParser, CosplayteleCrawler

def test_cosplaytele_parser_extract_links():
    html_content = '''
    <html>
      <body>
        <a href="https://ouo.io/test123">Download link</a>
        <a href="https://gofile.io/d/xyz">Gofile link</a>
      </body>
    </html>
    '''
    parser = CosplayteleParser()
    links = parser.extract_download_links(html_content)
    assert "https://ouo.io/test123" in links
    assert "https://gofile.io/d/xyz" in links

def test_cosplaytele_crawler_extract_post_urls():
    html_content = '''
    <html>
      <body>
        <a href="https://cosplaytele.com/eve-swimsuit-2/" class="plain">Eve Swimsuit Post</a>
        <a href="https://cosplaytele.com/columbina-6/" class="plain">Columbina Post</a>
      </body>
    </html>
    '''
    crawler = CosplayteleCrawler()
    post_urls = crawler.extract_post_urls(html_content)
    assert "https://cosplaytele.com/eve-swimsuit-2/" in post_urls
    assert "https://cosplaytele.com/columbina-6/" in post_urls
