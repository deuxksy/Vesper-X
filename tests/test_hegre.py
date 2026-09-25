"""Hegre 파서/크롤러 — selector는 실측 전 가정(Task 6에서 확정)."""
import pytest
from vesper_x.extractors.hegre import HegreParser

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
