"""Hegre 파서/크롤러 — selector는 실측 전 가정(Task 6에서 확정)."""
import pytest
from vesper_x.extractors.hegre import HegreParser, HegreCrawler

VIDEO_PAGE = """
<html><body>
<div class="download">
  <a href="https://cdn.hegre.com/vid/1080.mp4">Full HD 1080p</a>
  <a href="https://cdn.hegre.com/vid/2160.mp4">4K Ultra HD 2160p</a>
  <a href="https://cdn.hegre.com/vid/720.mp4">HD 720p</a>
</div>
<a class="model" href="/models/charlie-atropos">Charlie Atropos</a>
</body></html>
"""

VIDEO_PAGE_NO_4K = """
<html><body><div class="download">
  <a href="https://cdn.hegre.com/vid/1080.mp4">Full HD 1080p</a>
</div></body></html>
"""

GALLERY_PAGE = """
<html><body>
<a href="https://cdn.hegre.com/zip/standard.zip">Standard Size Edition | 4000px</a>
<a href="https://cdn.hegre.com/zip/large.zip">Large Size Edition | 6000px</a>
</body></html>
"""

GALLERY_PAGE_SINGLE_ZIP = """
<html><body>
<a href="https://cdn.hegre.com/zip/only.zip">Standard Size Edition | 4000px</a>
</body></html>
"""

EMPTY_PAGE = "<html><body><p>login required</p></body></html>"


def test_best_video_prefers_4k():
    best = HegreParser().best_video(VIDEO_PAGE)
    assert best == {"url": "https://cdn.hegre.com/vid/2160.mp4", "resolution": 2160}


def test_best_video_falls_back_without_4k():
    best = HegreParser().best_video(VIDEO_PAGE_NO_4K)
    assert best["resolution"] == 1080


def test_best_video_empty_page():
    assert HegreParser().best_video(EMPTY_PAGE) is None


def test_best_zip_prefers_6000px():
    best = HegreParser().best_zip(GALLERY_PAGE)
    assert best == {"url": "https://cdn.hegre.com/zip/large.zip", "pixels": 6000}


def test_best_zip_single_option():
    best = HegreParser().best_zip(GALLERY_PAGE_SINGLE_ZIP)
    assert best["pixels"] == 4000


def test_content_type_from_url():
    assert HegreParser.content_type("https://hegre.com/films/massage-x") == "video"
    assert HegreParser.content_type("https://hegre.com/galleries/serenity") == "photo"


def test_extract_model_name():
    assert HegreParser.extract_model_name(VIDEO_PAGE) == "Charlie Atropos"
    assert HegreParser.extract_model_name(EMPTY_PAGE) is None


# --- HegreCrawler (Task 4) ---

from vesper_x.config import AppConfig, CredentialConfig

INDEX_PAGE = """
<html><body>
  <a href="/films/massage-x">Massage X</a>
  <a href="/galleries/serenity">Serenity</a>
  <a href="/models/charlie-atropos">Charlie Atropos</a>
  <a href="/join">Join</a>
  <a class="next" href="/update?page=2">Next</a>
</body></html>
"""


def _crawler():
    return HegreCrawler(AppConfig())


def test_extract_gallery_refs_filters_content_links():
    refs = HegreCrawler.extract_gallery_refs(INDEX_PAGE, "https://hegre.com/update")
    urls = [r["url"] for r in refs]
    assert "https://hegre.com/films/massage-x" in urls
    assert "https://hegre.com/galleries/serenity" in urls
    assert all("/models/" not in u and "/join" not in u for u in urls)


def test_extract_next_page_url():
    nxt = HegreCrawler.extract_next_page_url(INDEX_PAGE, "https://hegre.com/update")
    assert nxt == "https://hegre.com/update?page=2"
    assert HegreCrawler.extract_next_page_url(EMPTY_PAGE, "https://x") is None


def test_resolve_content_video():
    crawler = _crawler()
    results = crawler.resolve_content(VIDEO_PAGE, "https://hegre.com/films/massage-x")
    assert len(results) == 1
    m = results[0]
    assert m.direct_url == "https://cdn.hegre.com/vid/2160.mp4"
    assert m.filename == "2160.mp4"
    assert m.source_page == "https://hegre.com/films/massage-x"
    assert m.file_page_url == "https://hegre.com/films/massage-x"
    assert m.models == ["Charlie Atropos"]


def test_resolve_content_photo_zip():
    crawler = _crawler()
    results = crawler.resolve_content(GALLERY_PAGE, "https://hegre.com/galleries/serenity")
    assert results[0].direct_url == "https://cdn.hegre.com/zip/large.zip"
    assert results[0].filename == "large.zip"


def test_resolve_content_empty_page():
    assert _crawler().resolve_content(EMPTY_PAGE, "https://hegre.com/films/x") == []


def test_ensure_credentials_missing_raises():
    with pytest.raises(ValueError, match="credentials.hegre"):
        _crawler().ensure_credentials()


def test_ensure_credentials_present():
    cfg = AppConfig(credentials={"hegre": CredentialConfig("u", "p")})
    creds = HegreCrawler(cfg).ensure_credentials()
    assert creds.username == "u"
