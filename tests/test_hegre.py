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
    assert m.filename == "Charlie Atropos/massage-x/2160.mp4"
    assert m.source_page == "https://hegre.com/films/massage-x"
    assert m.file_page_url == "https://hegre.com/films/massage-x"
    assert m.models == ["Charlie Atropos"]


def test_resolve_content_photo_zip():
    crawler = _crawler()
    results = crawler.resolve_content(GALLERY_PAGE, "https://hegre.com/galleries/serenity")
    assert results[0].direct_url == "https://cdn.hegre.com/zip/large.zip"
    # GALLERY_PAGE에는 모델 링크가 없다 - Unknown 폴백
    assert results[0].filename == "Unknown/serenity/large.zip"


def test_resolve_content_empty_page():
    assert _crawler().resolve_content(EMPTY_PAGE, "https://hegre.com/films/x") == []


def test_ensure_credentials_missing_raises():
    with pytest.raises(ValueError, match="credentials.hegre"):
        _crawler().ensure_credentials()


def test_ensure_credentials_present():
    cfg = AppConfig(credentials={"hegre": CredentialConfig("u", "p")})
    creds = HegreCrawler(cfg).ensure_credentials()
    assert creds.username == "u"


# --- CLI 통합 (Task 5) ---

import typer
from vesper_x.cli import run_hegre_crawl
from vesper_x.premium_db import PremiumDB


class FakeCrawler:
    """fetch/resolve_content를 HTML 응답으로 대체하는 테스트 더블."""

    def __init__(self, pages: dict[str, str], refs: list[dict] | None = None):
        self.pages = pages
        self.refs = refs or []
        self.parser = HegreParser()

    def ensure_credentials(self):
        return CredentialConfig("u", "p")

    async def fetch(self, url: str) -> str:
        if url not in self.pages:
            raise RuntimeError(f"unexpected fetch: {url}")
        return self.pages[url]

    async def collect(self, model_slug=None, max_pages=10):
        return self.refs

    def resolve_content(self, html: str, page_url: str):
        return HegreCrawler.resolve_content(self, html, page_url)


def _cfg():
    return AppConfig(credentials={"hegre": CredentialConfig("u", "p")})


def test_run_hegre_crawl_dispatches_and_records(tmp_path, monkeypatch):
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({
        "https://hegre.com/films/massage-x": VIDEO_PAGE,
    })

    class FakeDispatcher:
        def dispatch(self, m):
            return "gid-1"

    monkeypatch.setattr("vesper_x.cli.Aria2Dispatcher", lambda cfg: FakeDispatcher())
    run_hegre_crawl(url="https://hegre.com/films/massage-x", model=None,
                    new_only=False, extract_only=False, limit=0,
                    config=_cfg(), db=db, crawler=crawler)
    assert db.is_downloaded("https://hegre.com/films/massage-x")


def test_run_hegre_crawl_extract_only_does_not_record(tmp_path):
    """extract-only는 dispatch하지 않으므로 skip 상태를 오염시키지 않는다."""
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({
        "https://hegre.com/films/massage-x": VIDEO_PAGE,
    })
    run_hegre_crawl(url="https://hegre.com/films/massage-x", model=None,
                    new_only=False, extract_only=True, limit=0,
                    config=_cfg(), db=db, crawler=crawler)
    assert not db.is_downloaded("https://hegre.com/films/massage-x")


def test_run_hegre_crawl_skips_dispatched(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    db.record_download(None, "https://hegre.com/films/massage-x")
    crawler = FakeCrawler({})  # fetch되면 안 된다 — skip이 먼저다
    run_hegre_crawl(url="https://hegre.com/films/massage-x", model=None,
                    new_only=False, extract_only=True, limit=0,
                    config=_cfg(), db=db, crawler=crawler)


def test_run_hegre_crawl_no_links_continues(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({"https://hegre.com/films/empty": EMPTY_PAGE})
    run_hegre_crawl(url="https://hegre.com/films/empty", model=None,
                    new_only=False, extract_only=True, limit=0,
                    config=_cfg(), db=db, crawler=crawler)
    assert not db.is_downloaded("https://hegre.com/films/empty")


def test_run_hegre_crawl_updates_checkpoint_for_new(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({"https://hegre.com/films/massage-x": VIDEO_PAGE})
    run_hegre_crawl(url="https://hegre.com/films/massage-x", model=None,
                    new_only=True, extract_only=True, limit=0,
                    config=_cfg(), db=db, crawler=crawler)
    assert db.get_crawl_checkpoint("H") is not None


def test_run_hegre_crawl_no_credentials_exits(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({})
    with pytest.raises(typer.Exit):
        run_hegre_crawl(url="https://hegre.com/films/x", model=None,
                        new_only=False, extract_only=True, limit=0,
                        config=AppConfig(), db=db, crawler=crawler)


# --- final review fix pass ---

def test_select_crawler_registry_has_hegre():
    from vesper_x.cli import _select_crawler
    crawler = _select_crawler("https://hegre.com/films/x", AppConfig())
    assert isinstance(crawler, HegreCrawler)


def test_is_hegre_url_hostname_based():
    from vesper_x.cli import _is_hegre_url
    assert _is_hegre_url("https://hegre.com/films/x")
    assert _is_hegre_url("https://HEGRE.COM/films/x")      # 대소문자 무관
    assert _is_hegre_url("https://www.hegre.com/films/x")
    assert not _is_hegre_url("https://hegre.com.evil.example/x")  # 접미 도메인 위장
    assert not _is_hegre_url("https://evil.example/?ref=hegre.com")


def test_run_hegre_crawl_continues_after_item_failure(tmp_path, monkeypatch):
    db = PremiumDB(tmp_path / "premium.db")

    class FakeDispatcher:
        def dispatch(self, m):
            return "gid"

    monkeypatch.setattr("vesper_x.cli.Aria2Dispatcher", lambda cfg: FakeDispatcher())
    # broken은 pages에 없어 fetch가 RuntimeError → 해당 ref만 건너뛰고 ok는 dispatch+기록
    crawler = FakeCrawler({
        "https://hegre.com/films/ok": VIDEO_PAGE,
    }, refs=[
        {"url": "https://hegre.com/films/broken", "title": "broken"},
        {"url": "https://hegre.com/films/ok", "title": "ok"},
    ])
    run_hegre_crawl(url=None, model=None, new_only=False,
                    extract_only=False, limit=0,
                    config=_cfg(), db=db, crawler=crawler)
    assert db.is_downloaded("https://hegre.com/films/ok")
    assert not db.is_downloaded("https://hegre.com/films/broken")


def test_placeholder_selectors_registered():
    from vesper_x.extractors.hegre import SELECTORS, URLS
    assert SELECTORS["next_page"]
    assert URLS["content_path"]


def test_resolve_content_filename_includes_model_album():
    """spec 4.1: H/{모델명}/{앨범 제목}/ 계층 — filename에 상대경로 포함."""
    crawler = _crawler()
    results = crawler.resolve_content(VIDEO_PAGE, "https://hegre.com/films/massage-x")
    assert results[0].filename == "Charlie Atropos/massage-x/2160.mp4"


def test_hegre_crawler_fetch_not_implemented_before_task6():
    import asyncio
    crawler = _crawler()
    with pytest.raises(NotImplementedError):
        asyncio.run(crawler.fetch("https://hegre.com/films/x"))
