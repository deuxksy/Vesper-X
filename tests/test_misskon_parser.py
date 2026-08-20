from vesper_x.extractors.misskon import MisskonParser

def test_extract_shortener_link_from_post_html():
    sample_html = '''
    <html>
      <body>
        <div class="entry-content">
          <p><a href="https://ouo.io/hHzh1N" class="shortc-button green">Download link: MediaFire</a></p>
        </div>
      </body>
    </html>
    '''
    parser = MisskonParser()
    links = parser.extract_download_links(sample_html)
    assert "https://ouo.io/hHzh1N" in links
