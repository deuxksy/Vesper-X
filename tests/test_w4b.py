"""W4B 파서/크롤러 — selector는 2026-09-27 실측값."""
from vesper_x.extractors.w4b import W4BParser, W4BCrawler, URLS, SELECTORS

BASE = "https://www.watch4beauty.com/updates/quickie-by-the-pool"
ZIP_HREF = "/api/media/20220227-max.zip"
MP4_2160 = ("https://www.watch4beauty.com/api/media/download/issues/2022/02/"
            "quickie-by-the-pool/backstage/2160.mp4?ttl=1&token=a")
MP4_1080 = ("https://www.watch4beauty.com/api/media/download/issues/2022/02/"
            "quickie-by-the-pool/1080.mp4?ttl=1&token=b")

SET_PAGE = """
<html><body>
<h1>Quickie By The Pool</h1>
<a href="/models/christy-white">CHRISTY WHITE</a>
<a href="/models">Popular models</a>
</body></html>
"""

MODEL_LISTING = """
<html><body>
<a class="grid-item" href="/updates/quickie-by-the-pool"></a>
<a href="/updates/noise-non-grid"></a>
<a class="grid-item" href="/updates/new-talent-christy-white"></a>
<a class="grid-item" href="/stories/fun-in-park"></a>
<a class="grid-item" href="/updates/popular"></a>
<a class="grid-item" href="/updates/quickie-by-the-pool"></a>
</body></html>
"""


def test_pick_downloads_returns_zip_and_4k():
    links = [
        {"href": ZIP_HREF, "text": "Download"},
        {"href": MP4_2160, "text": "Download 4K"},
    ]
    picks = W4BParser.pick_downloads(links, BASE)
    assert picks == [
        {"url": "https://www.watch4beauty.com/api/media/20220227-max.zip",
         "type": "photo", "basename": "20220227-max.zip"},
        {"url": MP4_2160, "type": "video", "basename": "2160.mp4"},
    ]


def test_pick_downloads_prefers_2160_over_1080():
    picks = W4BParser.pick_downloads(
        [{"href": MP4_1080, "text": "Download HD"},
         {"href": MP4_2160, "text": "Download 4K"}], BASE)
    assert [p["basename"] for p in picks] == ["2160.mp4"]


def test_pick_downloads_falls_back_to_1080():
    picks = W4BParser.pick_downloads([{"href": MP4_1080, "text": "Download HD"}], BASE)
    assert picks[0]["basename"] == "1080.mp4"


def test_pick_downloads_video_only_set():
    picks = W4BParser.pick_downloads([{"href": MP4_2160, "text": "Download 4K"}], BASE)
    assert [p["type"] for p in picks] == ["video"]


def test_pick_downloads_photo_only_set():
    picks = W4BParser.pick_downloads([{"href": ZIP_HREF, "text": "Download"}], BASE)
    assert [p["type"] for p in picks] == ["photo"]


def test_pick_downloads_empty():
    assert W4BParser.pick_downloads([], BASE) == []


def test_extract_model_name_verbatim():
    assert W4BParser.extract_model_name(SET_PAGE) == "CHRISTY WHITE"
    assert W4BParser.extract_model_name("<html><body></body></html>") is None


def test_extract_model_content_refs_updates_only():
    refs = W4BCrawler.extract_model_content_refs(
        MODEL_LISTING, "https://www.watch4beauty.com/models/christy-white")
    assert [r["url"] for r in refs] == [
        "https://www.watch4beauty.com/updates/quickie-by-the-pool",
        "https://www.watch4beauty.com/updates/new-talent-christy-white",
    ]


def test_extract_model_content_refs_excludes_popular():
    page = '<html><body><a class="grid-item" href="/updates/popular"></a></body></html>'
    refs = W4BCrawler.extract_model_content_refs(
        page, "https://www.watch4beauty.com/models/x")
    assert refs == []


def test_extract_model_content_refs_dedupes():
    page = ('<html><body>'
            '<a class="grid-item" href="/updates/x"></a>'
            '<a class="grid-item" href="/updates/x"></a>'
            '</body></html>')
    refs = W4BCrawler.extract_model_content_refs(
        page, "https://www.watch4beauty.com/models/x")
    assert len(refs) == 1


def test_url_and_selector_constants_registered():
    assert URLS["login"] and URLS["model"] and URLS["updates"]
    assert SELECTORS["login_user"] and SELECTORS["login_pass"]
    assert SELECTORS["model_content_links"] and SELECTORS["download_links"]
