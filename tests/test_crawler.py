from vesper_x.extractors.crawler import CategoryCrawler


def test_extract_post_urls_from_category_html():
    sample_html = """
    <html>
      <body>
        <div class="post-listing">
          <h2 class="post-box-title">
            <a href="https://misskon.com/114764-post1/">Post 1 Title</a>
          </h2>
          <h2 class="post-box-title">
            <a href="https://misskon.com/114765-post2/">Post 2 Title</a>
          </h2>
        </div>
        <div class="pagination">
          <span class="current">1</span>
          <a href="https://misskon.com/tag/test/page/2/" class="page" title="2">2</a>
          <a href="https://misskon.com/tag/test/page/3/" class="page" title="3">3</a>
        </div>
      </body>
    </html>
    """
    crawler = CategoryCrawler()
    urls = crawler.extract_post_urls(sample_html)
    pages = crawler.extract_pagination_urls(sample_html)
    assert urls == [
        "https://misskon.com/114764-post1/",
        "https://misskon.com/114765-post2/",
    ]
    assert pages == [
        "https://misskon.com/tag/test/page/2/",
        "https://misskon.com/tag/test/page/3/",
    ]
