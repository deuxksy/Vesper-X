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


def test_pick_downloads_resolves_relative_mp4():
    href = "/api/media/download/issues/2022/02/x/backstage/2160.mp4?ttl=1&token=a"
    picks = W4BParser.pick_downloads([{"href": href, "text": "Download 4K"}], BASE)
    assert picks[0]["url"] == "https://www.watch4beauty.com" + href
    assert picks[0]["basename"] == "2160.mp4"


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


def test_extract_model_name_skips_empty_anchor_and_starring_prefix():
    page = ('<html><body>'
            '<a href="/models/christy-white"></a>'
            '<a href="/models/christy-white">STARRING CHRISTY WHITE</a>'
            '<a href="/models">Popular models</a>'
            '</body></html>')
    assert W4BParser.extract_model_name(page) == "CHRISTY WHITE"


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


# --- W4BCrawler (Task 2) ---
import pytest

from vesper_x.config import AppConfig


def test_build_cookie_header_filters_and_formats():
    cookies = [{"name": "other", "value": "1"},
               {"name": "session", "value": "abc"},
               {"name": "cf_clearance", "value": "xyz"}]
    assert W4BCrawler.build_cookie_header(cookies) == "session=abc; cf_clearance=xyz"
    assert W4BCrawler.build_cookie_header([]) == ""


def test_ensure_credentials_missing_raises():
    with pytest.raises(ValueError, match="credentials.w4b"):
        W4BCrawler(AppConfig()).ensure_credentials()


def test_launch_kwargs_uses_chrome_channel_and_proxy():
    crawler = W4BCrawler(AppConfig(proxy="http://x:1"))
    kwargs = crawler._launch_kwargs()
    assert kwargs["channel"] == "chrome"
    assert kwargs["headless"] is False
    assert kwargs["proxy"] == {"server": "http://x:1"}


# --- CLI/설정 연결 (Task 5) ---
from vesper_x.cli import _is_w4b_url, _select_crawler


def test_is_w4b_url_hostname_based():
    assert _is_w4b_url("https://watch4beauty.com/updates/x")
    assert _is_w4b_url("https://WATCH4BEAUTY.COM/updates/x")      # 대소문자 무관
    assert _is_w4b_url("https://www.watch4beauty.com/updates/x")  # 서브도메인
    assert not _is_w4b_url("https://watch4beauty.com.evil.example/x")  # 접미 위장
    assert not _is_w4b_url("https://evil.example/?ref=watch4beauty.com")  # 쿼리 위장


def test_select_crawler_registry_has_w4b():
    crawler = _select_crawler("https://www.watch4beauty.com/updates/x", AppConfig())
    assert isinstance(crawler, W4BCrawler)


def test_default_sites_contain_w4b():
    sites = AppConfig().sites
    assert "watch4beauty.com" in sites
    assert sites["watch4beauty.com"].subdir == "W4B"
    assert sites["watch4beauty.com"].crawler == "w4b"


# --- premium.db site 컬럼 (Task 6) ---
from vesper_x.premium_db import PremiumDB


def test_holding_by_model_includes_site(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    model_id = db.upsert_model("Christy White", "W4B")
    gallery_id = db.upsert_gallery(
        model_id, "Quickie By The Pool",
        "https://www.watch4beauty.com/updates/quickie-by-the-pool", "W4B", "photo")
    db.record_download(
        gallery_id, "https://www.watch4beauty.com/updates/quickie-by-the-pool")
    rows = db.holding_by_model("christy")
    assert rows[0]["site"] == "W4B"
    assert rows[0]["videos"] == 0
    assert rows[0]["photos"] == 1


def test_dual_type_set_records_both_files(tmp_path):
    """겸용 세트(ZIP+mp4)는 type별로 분리 기록된다 - models 보유 집계가 거짓말하지 않게.

    같은 세트 URL에 photo/video가 연달아 기록되면 gallery 행이 분리되고,
    downloads 키도 파일별로 분리된다. is_downloaded는 세트 단위 skip을 유지한다.
    """
    db = PremiumDB(tmp_path / "premium.db")
    mid = db.upsert_model("Christy White", "W4B")
    set_url = "https://www.watch4beauty.com/updates/quickie-by-the-pool"
    g1 = db.upsert_gallery(mid, "Quickie By The Pool", set_url, "W4B", "photo")
    db.record_download(g1, set_url + "#photo", "20220227-max.zip",
                       direct_url="https://www.watch4beauty.com/api/media/20220227-max.zip")
    g2 = db.upsert_gallery(mid, "Quickie By The Pool", set_url, "W4B", "video")
    db.record_download(g2, set_url + "#video", "2160.mp4",
                       direct_url="https://www.watch4beauty.com/api/media/download/issues/x/2160.mp4")
    assert g1 != g2
    rows = db.holding_by_model("christy")
    assert (rows[0]["videos"], rows[0]["photos"]) == (1, 1)
    assert db.is_downloaded(set_url)  # 세트 단위 skip 판정 유지


def test_holding_by_model_hegre_regression(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    model_id = db.upsert_model("Ani", "H")
    g1 = db.upsert_gallery(model_id, "Massage X",
                           "https://hegre.com/films/massage-x", "H", "video")
    g2 = db.upsert_gallery(model_id, "Serenity",
                           "https://hegre.com/photos/serenity", "H", "photo")
    db.record_download(g1, "https://hegre.com/films/massage-x")
    db.record_download(g2, "https://hegre.com/photos/serenity")
    rows = db.holding_by_model("ani")
    assert rows[0]["site"] == "H"
    assert rows[0]["videos"] == 1
    assert rows[0]["photos"] == 1
