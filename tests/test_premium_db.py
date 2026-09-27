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


def test_record_download_stores_direct_url(db):
    """CDN 직링크 매핑 - 재크롤 없이 참조·재전송 근거로 사용."""
    db.record_download(None, "https://hegre.com/films/x", "x.mp4",
                       direct_url="https://content.hegre.com/films/x/x-2160p.mp4?v=1")
    row = db._connect().execute(
        "SELECT direct_url, status FROM downloads WHERE url = ?",
        ("https://hegre.com/films/x",)).fetchone()
    assert row == ("https://content.hegre.com/films/x/x-2160p.mp4?v=1", "dispatched")


def test_migration_adds_direct_url_column(tmp_path):
    """구 스키마(컬럼 없음) DB를 열면 자동 마이그레이션된다 - 기존 데이터 보존."""
    import sqlite3
    p = tmp_path / "premium.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "gallery_id INTEGER, url TEXT NOT NULL, filename TEXT, "
                 "status TEXT DEFAULT 'pending', dispatched_at TEXT DEFAULT (datetime('now')), "
                 "completed_at TEXT)")
    conn.execute("INSERT INTO downloads (url, filename) VALUES ('https://hegre.com/films/old', 'old.mp4')")
    conn.commit()
    conn.close()
    db = PremiumDB(p)
    cols = [r[1] for r in db._connect().execute("PRAGMA table_info(downloads)").fetchall()]
    assert "direct_url" in cols
    assert db.is_downloaded("https://hegre.com/films/old")  # 기존 데이터 보존
    db.close()


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
