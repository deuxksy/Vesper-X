"""premium.db 접근 계층 — 프리미엄 사이트(H/W4B) 운영 이력·체크포인트 단일 소스.

cosplay.db(무료 부류 사전+dispatch_log)와 부류를 분담한다 (spec 4.4):
Hegre/W4B 크롤의 skip 판정은 이 DB가 단일 소스며 dispatch_log를 참조하지 않는다.
ModelRegistry 검증 패턴을 따른다 — sqlite3 직접 사용, 자동 생성·마이그레이션.
차이: cosplay.db는 '조용히 비활성'이지만 운영 DB는 부재 시 자동 생성이 맞다.
"""
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path.home() / ".config" / "url-resolver" / "premium.db"

# spec 5.2 스키마에서 두 곳 단순화: crawl_state의 id 열 제거(site가 자연 키),
# downloads.status 기본 'pending' 유지하되 record_download가 'dispatched'로 기록
_SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT,
    site        TEXT NOT NULL,
    url         TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_models_site_name ON models(site, name);

CREATE TABLE IF NOT EXISTS galleries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    INTEGER REFERENCES models(id),
    title       TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    date        TEXT,
    type        TEXT NOT NULL,
    resolution  TEXT,
    site        TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS downloads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gallery_id      INTEGER REFERENCES galleries(id),
    url             TEXT NOT NULL,
    filename        TEXT,
    status          TEXT DEFAULT 'pending',
    dispatched_at   TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_downloads_url ON downloads(url);

CREATE TABLE IF NOT EXISTS crawl_state (
    site            TEXT PRIMARY KEY,
    last_crawl_at   TEXT,
    last_page_url   TEXT,
    checkpoint      TEXT
);
"""


class PremiumDB:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()  # 운영 DB는 생성 즉시 스키마를 확보한다

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def upsert_model(self, name: str, site: str, slug: Optional[str] = None,
                     url: Optional[str] = None) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT id FROM models WHERE site = ? AND name = ?", (site, name)).fetchone()
        if row:
            return row[0]
        cur = conn.execute(
            "INSERT INTO models (name, slug, site, url) VALUES (?, ?, ?, ?)",
            (name, slug, site, url))
        conn.commit()
        return cur.lastrowid

    def upsert_gallery(self, model_id: Optional[int], title: str, url: str, site: str,
                       gtype: str, date: Optional[str] = None,
                       resolution: Optional[str] = None) -> int:
        conn = self._connect()
        row = conn.execute("SELECT id FROM galleries WHERE url = ?", (url,)).fetchone()
        if row:
            return row[0]
        cur = conn.execute(
            "INSERT INTO galleries (model_id, title, url, date, type, resolution, site) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (model_id, title, url, date, gtype, resolution, site))
        conn.commit()
        return cur.lastrowid

    def record_download(self, gallery_id: Optional[int], url: str,
                        filename: Optional[str] = None) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO downloads (gallery_id, url, filename, status) "
            "VALUES (?, ?, ?, 'dispatched')", (gallery_id, url, filename))
        conn.commit()

    def is_downloaded(self, url: str) -> bool:
        conn = self._connect()
        return conn.execute(
            "SELECT 1 FROM downloads WHERE url = ?", (url,)).fetchone() is not None

    def get_crawl_checkpoint(self, site: str) -> Optional[str]:
        conn = self._connect()
        row = conn.execute(
            "SELECT checkpoint FROM crawl_state WHERE site = ?", (site,)).fetchone()
        return row[0] if row else None

    def update_crawl_checkpoint(self, site: str, checkpoint: str,
                                page_url: Optional[str] = None) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO crawl_state (site, last_crawl_at, last_page_url, checkpoint) "
            "VALUES (?, datetime('now'), ?, ?) "
            "ON CONFLICT(site) DO UPDATE SET last_crawl_at = datetime('now'), "
            "last_page_url = excluded.last_page_url, checkpoint = excluded.checkpoint",
            (site, page_url, checkpoint))
        conn.commit()
