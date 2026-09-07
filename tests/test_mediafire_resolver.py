from vesper_x.extractors.mediafire import MediafireResolver

def test_extract_mediafire_direct_url():
    sample_html = '''
    <html>
      <body>
        <a id="downloadButton" href="https://download1586.mediafire.com/xyz/test_file.rar" class="input popsok">Download (120MB)</a>
      </body>
    </html>
    '''
    resolver = MediafireResolver()
    direct_url = resolver.extract_direct_url(sample_html)
    assert direct_url == "https://download1586.mediafire.com/xyz/test_file.rar"

def test_extract_mediafire_exact_user_provided_html():
    sample_html = '''
    <a class="input popsok" aria-label="Download file" href="https://download2329.mediafire.com/i8tsblcccfbgbC5lzna450bW0Ryoadrg8fnoIevIzX-l-svO6AGFYGOK0R9Pm-k_WIt4_htwmQ0-FsLaibFvTA5aPuO0Jd0R3WRYNFMK6b5oAiNqByISeY4NljCPAX2doqOT8EBNIKGAbuym22KLNhSxoJjEWd4-tLml6chzc3K6UC4/hwn2zp6raz1j7n9/%5BSW%23%23TB0X%5D+Nyangsarang+%28%EB%83%A5%EC%82%AC%EB%9E%91%29+-+SWTB+Vol.61+Miyao+Debut.rar" id="downloadButton" rel="nofollow">
            Download (2.16GB)
    </a>
    '''
    resolver = MediafireResolver()
    direct_url = resolver.extract_direct_url(sample_html)
    assert direct_url.startswith("https://download2329.mediafire.com/")
    assert "Nyangsarang" in direct_url

def test_extract_mediafire_direct_url_aria_label():
    sample_html = '''
    <html>
      <body>
        <a aria-label="Download file" href="https://download1586.mediafire.com/xyz/test_file_aria.rar">Download</a>
      </body>
    </html>
    '''
    resolver = MediafireResolver()
    direct_url = resolver.extract_direct_url(sample_html)
    assert direct_url == "https://download1586.mediafire.com/xyz/test_file_aria.rar"

def test_extract_mediafire_direct_url_not_found():
    sample_html = '''
    <html>
      <body>
        <p>No download button here</p>
      </body>
    </html>
    '''
    resolver = MediafireResolver()
    direct_url = resolver.extract_direct_url(sample_html)
    assert direct_url is None
 
 
def test_resolve_mediafire_folder():
    from unittest.mock import patch
    resolver = MediafireResolver()
    mock_resp = {
        "response": {
            "folder_content": {
                "files": [
                    {"quickkey": "k1", "filename": "part1.rar"},
                    {"quickkey": "k2", "filename": "part2.rar"},
                ]
            }
        }
    }
    with patch("vesper_x.extractors.mediafire.httpx.get") as mock_get:
        mock_get.return_value.json.return_value = mock_resp
        files = resolver.resolve_folder("https://www.mediafire.com/folder/c7uo499i7wf1r")
        assert files == [
            "https://www.mediafire.com/file/k1",
            "https://www.mediafire.com/file/k2",
        ]
