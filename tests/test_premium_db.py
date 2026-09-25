"""premium.db — 프리미엄 부류(H/W4B) 운영 이력 단일 소스."""
import pytest
from vesper_x.premium_db import PremiumDB


@pytest.fixture
def db(tmp_path):
    instance = PremiumDB(tmp_path / "premium.db")
    yield instance
    instance.close()


def test_first_connect_creates_schema(db, tmp_path):
    assert (tmp_path / "premium.db").exists()


def test_upsert_model_idempotent(db):
    a = db.upsert_model("Charlie Atropos", "H", slug="charlie-atropos")
    b = db.upsert_model("Charlie Atropos", "H")
    assert a == b


def test_upsert_model_same_name_different_site(db):
    h = db.upsert_model("Nella", "H")
    w = db.upsert_model("Nella", "W4B")
    assert h != w


def test_upsert_gallery_url_unique(db):
    m = db.upsert_model("Nella", "H")
    g1 = db.upsert_gallery(m, "title", "https://hegre.com/films/x", "H", "video")
    g2 = db.upsert_gallery(None, "other", "https://hegre.com/films/x", "H", "video")
    assert g1 == g2


def test_record_and_is_downloaded(db):
    m = db.upsert_model("Nella", "H")
    g = db.upsert_gallery(m, "t", "https://hegre.com/films/x", "H", "video")
    assert not db.is_downloaded("https://hegre.com/films/x")
    db.record_download(g, "https://hegre.com/films/x", "x.mp4")
    assert db.is_downloaded("https://hegre.com/films/x")
    db.record_download(g, "https://hegre.com/films/x", "x.mp4")  # 재시도 기록 안전


def test_checkpoint_roundtrip(db):
    assert db.get_crawl_checkpoint("H") is None
    db.update_crawl_checkpoint("H", "2026-09-25T17:00", page_url="https://hegre.com/update/3")
    assert db.get_crawl_checkpoint("H") == "2026-09-25T17:00"
    db.update_crawl_checkpoint("H", "2026-09-26T09:00")
    assert db.get_crawl_checkpoint("H") == "2026-09-26T09:00"  # 1행 갱신


def test_reopen_preserves_data(tmp_path):
    db1 = PremiumDB(tmp_path / "premium.db")
    mid = db1.upsert_model("Nella", "H")
    db1.update_crawl_checkpoint("H", "cp1")
    db1.close()
    db2 = PremiumDB(tmp_path / "premium.db")
    assert db2.get_crawl_checkpoint("H") == "cp1"          # 데이터 보존
    assert db2.upsert_model("Nella", "H") == mid            # 스키마 재실행 안전
    db2.close()
