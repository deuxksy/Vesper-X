# Hegre(H) 크롤러 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hegre 프리미엄 사이트 인증 크롤러를 추가해 4K 영상/6000px ZIP을 aria2로 전송한다.

**Architecture:** 기존 파이프라인(ouo bypass → filehost resolver)을 타지 않는 별도 경로다. HegreCrawler가 persistent Chrome 프로필로 로그인 세션을 유지하고(ouo 검증 패턴), 크롤은 갤러리 URL만 수집한 뒤 CDN 직링크는 dispatch 직전에 resolve한다(spec 4.3 — 서명 TTL/IP 바인딩 방어). 다운로드 이력은 `premium.db`(프리미엄 부류 단일 소스)가 관리하며 `cosplay.db`(구 models.db)와 부류를 분담한다.

**Tech Stack:** Python 3.12 표준 library(tomllib, sqlite3), Playwright(real Chrome `channel="chrome"`), BeautifulSoup, aria2p, Typer

**Spec:** `docs/superpowers/specs/2026-09-25-hegre-crawler-design.md`

## Global Constraints

- Python >= 3.12 표준 library 우선 — ORM/신규 의존성 추가 금지 (spec 5.3)
- 전 테스트는 mock 기반 — 실 network 호출 금지 (`.ai/RULES.md`)
- 완료 조건: `uv run pytest` 전체 통과
- 외부 사이트 실접속(recon/E2E)은 사용자 승인 후에만 실행 (CLAUDE.md)
- Hegre 파이프라인은 `cosplay.db`의 dispatch_log를 참조하지 않는다 (spec 4.4 부류 분담)
- DOM selector/URL 패턴은 실측 전 가정값 — `SELECTORS`/`URLS` 상수로 격리해 Task 6에서 확정한다 (spec 7장)

## Review Focus

스펙이 암시하지만 개별 태스크가 자동으로 cover하지 않는 실패 모드 — 각 항목의 test는 지정 태스크에 포함한다:

1. 로컬 config가 `[sites]`를 부분 오버라이드해도 default.toml의 나머지 사이트(misskon/cosplaytele/hegre)가 유실되면 안 된다 → Task 1 `test_deep_merge_sites_partial_override`
2. premium.db 재오픈 시 기존 데이터가 보존되고 스키마 재생성이 안전해야 한다 → Task 2 `test_reopen_preserves_data`
3. 동일 갤러리 재크롤 시 url unique로 skip되고, dispatch 재시도 기록도 안전해야 한다 → Task 2 `test_record_and_is_downloaded`, Task 5 `test_run_hegre_crawl_skips_dispatched`
4. credentials 누락/로그인 실패 시 크래시 없이 명확한 에러로 종료해야 한다 → Task 4 `test_ensure_credentials_missing_raises`, Task 5 `test_run_hegre_crawl_no_credentials_exits`
5. 4K가 없는 과거 작품은 가용 최고 해상도로, ZIP이 1종이면 그것으로 fallback해야 한다 → Task 3 `test_best_video_falls_back_without_4k`, `test_best_zip_single_option`

---

### Task 0: models.db → cosplay.db 리네임 (선결)

**Files:**
- Modify: `src/vesper_x/models_db.py` (docstring + `DEFAULT_DB_PATH`)
- Modify: `scripts/build_models_db.py:2,120,121,294`
- Modify: `src/vesper_x/cli.py:66,459,460`
- Modify: `tests/test_models_db.py:1,20,36`
- Modify: `.gitignore:18`
- Modify: `.ai/RULES.md` (models.db 언급 전부)

**Interfaces:**
- Consumes: 없음 (독립 선결 작업)
- Produces: `DEFAULT_DB_PATH = ... / "data" / "cosplay.db"` — 이후 태스크가 참조하는 파일명. 모듈명 `models_db`/클래스명 `ModelRegistry`는 그대로 (코드 심볼은 불변, 파일명만 변경)

- [ ] **Step 1: 전 참조 위치 치환**

대상 (grep 실측 완료). 각 파일에서 `models.db` → `cosplay.db`:

```python
# src/vesper_x/models_db.py:14
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "cosplay.db"
```

`scripts/build_models_db.py` 4곳 (docstring:2, `_existing_model_prefs(DATA_DIR / "cosplay.db")`:120, `sqlite3.connect(DATA_DIR / 'cosplay.db')`:121, print문:294), `src/vesper_x/cli.py` 3곳 (docstring:66, 에러메시지:459, 안내:460), `tests/test_models_db.py` 3곳 (docstring:1, sqlite3.connect:20, 반환:36), `.gitignore:18` (`data/models.db` → `data/cosplay.db`), `.ai/RULES.md`의 `models.db` 전부 (Commands 표, Architecture, Gotchas 3곳).

- [ ] **Step 2: 로컬 DB 파일 이동 (dispatch_log 이력 보존)**

```bash
mv data/models.db data/cosplay.db
```

`data/models.db`가 없으면 skip (신규 클론). mv는 사용자 확인 후 진행한다.

- [ ] **Step 3: 재생성 동작 확인**

```bash
uv run python scripts/build_models_db.py
```

Expected: `data/cosplay.db 재생성 완료` 출력. grade/dispatch_log 보존 로직(`_existing_model_prefs`)이 새 파일명으로 동작하는지 출력에서 확인.

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `uv run pytest`
Expected: 전 기존 테스트 PASS (파일명 치환만으로 깨지는 테스트 없음)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: models.db를 cosplay.db로 리네임 - 프리미엄 부류 premium.db와 부류 분담"
```

---

### Task 1: Config 2중 분리

**Files:**
- Create: `config/default.toml`
- Modify: `src/vesper_x/config.py`
- Test: `tests/test_config_merge.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `CredentialConfig` dataclass — `username: str`, `password: str`
  - `AppConfig.credentials: dict[str, CredentialConfig]`
  - `DEFAULT_TOML_PATH: Path` (repo 내 `config/default.toml`)
  - `load_config()` 시그니처 불변 — deep merge 결과 반환

- [ ] **Step 1: failing test 작성**

```python
"""Config 2중 분리 — config/default.toml + 로컬 config.toml deep merge."""
import pytest
from vesper_x.config import load_config, AppConfig

DEFAULT_TOML = """\
[aria2]
download_dir = "/downloads"

[sites]
"misskon.com" = { crawler = "category", subdir = "misskon" }
"cosplaytele.com" = { crawler = "cosplaytele", subdir = "cosplaytele" }
"hegre.com" = { crawler = "hegre", subdir = "H" }
"""

LOCAL_TOML = """\
[aria2]
host = "ws://other:6800"

[credentials.hegre]
username = "user@example.com"
password = "secret"
"""


def _patch(monkeypatch, tmp_path, default_toml=None, local_toml=None):
    default_path = tmp_path / "default.toml"
    local_path = tmp_path / "config.toml"
    if default_toml is not None:
        default_path.write_text(default_toml)
    if local_toml is not None:
        local_path.write_text(local_toml)
    monkeypatch.setattr("vesper_x.config.DEFAULT_TOML_PATH", default_path)
    monkeypatch.setattr("vesper_x.config.DEFAULT_CONFIG_PATH", local_path)


def test_deep_merge_local_overrides_scalar(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, DEFAULT_TOML, LOCAL_TOML)
    cfg = load_config()
    assert cfg.aria2_host == "ws://other:6800"      # 로컬 우선
    assert cfg.download_dir == "/downloads"          # default 유지


def test_deep_merge_sites_partial_override(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, DEFAULT_TOML,
           '[sites]\n"misskon.com" = { crawler = "category", subdir = "mk-local" }\n')
    cfg = load_config()
    assert cfg.sites["misskon.com"].subdir == "mk-local"          # 로컬 덮어씀
    assert cfg.sites["cosplaytele.com"].subdir == "cosplaytele"   # default 유지
    assert cfg.sites["hegre.com"].subdir == "H"                   # default 유지


def test_credentials_parsing(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, DEFAULT_TOML, LOCAL_TOML)
    cfg = load_config()
    assert cfg.credentials["hegre"].username == "user@example.com"
    assert cfg.credentials["hegre"].password == "secret"


def test_both_missing_falls_back_to_code_defaults(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)  # 두 파일 모두 부재
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.credentials == {}
    assert cfg.sites["misskon.com"].subdir == "misskon"


def test_default_sites_code_fallback_includes_hegre(monkeypatch, tmp_path):
    # default.toml에 [sites] 없어도 코드 DEFAULT_SITES 폴백에 hegre가 있다
    _patch(monkeypatch, tmp_path, '[aria2]\ndownload_dir = "/downloads"\n')
    cfg = load_config()
    assert cfg.sites["hegre.com"].crawler == "hegre"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_config_merge.py -v`
Expected: FAIL — `DEFAULT_TOML_PATH` 없음 / `credentials` 속성 없음

- [ ] **Step 3: config/default.toml 생성**

```toml
# 환경 무관 고정 설정 — 로컬(~/.config/url-resolver/config.toml)이 우선한다
[aria2]
download_dir = "/downloads"

[sites]
"misskon.com" = { crawler = "category", subdir = "misskon" }
"cosplaytele.com" = { crawler = "cosplaytele", subdir = "cosplaytele" }
"hegre.com" = { crawler = "hegre", subdir = "H" }
```

- [ ] **Step 4: config.py 구현**

`DEFAULT_SITES`에 hegre 추가, `CredentialConfig`/`DEFAULT_TOML_PATH`/`_load_toml`/`_deep_merge`/`_parse_credentials` 신설, `load_config` 재작성:

```python
@dataclass
class CredentialConfig:
    username: str = ""
    password: str = ""


# repo 내 고정 설정 (models_db.DEFAULT_DB_PATH와 동일한 탐색 관행)
DEFAULT_TOML_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.toml"

DEFAULT_SITES = {
    "misskon.com": SiteConfig(crawler="category", subdir="misskon"),
    "cosplaytele.com": SiteConfig(crawler="cosplaytele", subdir="cosplaytele"),
    "hegre.com": SiteConfig(crawler="hegre", subdir="H"),
}


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    """dict은 재귀 병합(로컬 우선), 스칼라/리스트는 로컬이 덮어쓴다."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_credentials(data: dict) -> dict[str, CredentialConfig]:
    return {
        name: CredentialConfig(username=entry.get("username", ""),
                               password=entry.get("password", ""))
        for name, entry in data.get("credentials", {}).items()
    }
```

`AppConfig`에 필드 추가:

```python
    credentials: dict[str, CredentialConfig] = field(default_factory=dict)
```

`load_config()` 교체:

```python
def load_config() -> AppConfig:
    data = _deep_merge(_load_toml(DEFAULT_TOML_PATH), _load_toml(DEFAULT_CONFIG_PATH))
    aria2_data = data.get("aria2", {})
    crawler_data = data.get("crawler", {})
    network_data = data.get("network", {})
    return AppConfig(
        aria2_host=aria2_data.get("host", "ws://heritage.bun-bull.ts.net:6800"),
        aria2_secret=aria2_data.get("secret", ""),
        download_dir=aria2_data.get("download_dir"),
        models=crawler_data.get("models", list(DEFAULT_MODELS)),
        proxy=network_data.get("proxy"),
        sites=_parse_sites(data),
        skip_gofile=crawler_data.get("skip_gofile", False),
        credentials=_parse_credentials(data),
    )
```

주의: 기존의 `if not DEFAULT_CONFIG_PATH.exists(): return AppConfig()` early return은 제거한다 (`_load_toml`이 빈 dict 반환으로 통합).

- [ ] **Step 5: 신규 + 기존 테스트 통과 확인**

Run: `uv run pytest tests/test_config_merge.py tests/test_models_and_config.py tests/test_sites_config.py -v`
Expected: 전부 PASS (기존 `test_load_default_config` 등은 monkeypatch된 `DEFAULT_CONFIG_PATH`만 쓰므로 영향 없음)

- [ ] **Step 6: Commit**

```bash
git add config/default.toml src/vesper_x/config.py tests/test_config_merge.py
git commit -m "feat: config 2중 분리 - default.toml 고정설정과 로컬 deep merge, credentials 추가"
```

---

### Task 2: premium_db.py — 스키마 + CRUD

**Files:**
- Create: `src/vesper_x/premium_db.py`
- Test: `tests/test_premium_db.py`

**Interfaces:**
- Consumes: 없음 (독립)
- Produces:
  - `DEFAULT_DB_PATH = Path.home() / ".config" / "url-resolver" / "premium.db"`
  - `class PremiumDB`:
    - `__init__(db_path: Optional[Path] = None)`
    - `close() -> None`
    - `upsert_model(name: str, site: str, slug: Optional[str] = None, url: Optional[str] = None) -> int` (model id)
    - `upsert_gallery(model_id: Optional[int], title: str, url: str, site: str, gtype: str, date: Optional[str] = None, resolution: Optional[str] = None) -> int` (gallery id)
    - `record_download(gallery_id: Optional[int], url: str, filename: Optional[str] = None) -> None`
    - `is_downloaded(url: str) -> bool`
    - `get_crawl_checkpoint(site: str) -> Optional[str]`
    - `update_crawl_checkpoint(site: str, checkpoint: str, page_url: Optional[str] = None) -> None`

- [ ] **Step 1: failing test 작성**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_premium_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vesper_x.premium_db'`

- [ ] **Step 3: premium_db.py 구현**

```python
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
            (page_url, checkpoint))
        conn.commit()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_premium_db.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/vesper_x/premium_db.py tests/test_premium_db.py
git commit -m "feat: premium_db 신규 - 프리미엄 부류 운영 이력/체크포인트 단일 소스"
```

---

### Task 3: HegreParser — 콘텐츠 페이지 정적 파싱

**Files:**
- Create: `src/vesper_x/extractors/hegre.py`
- Test: `tests/test_hegre.py`

**Interfaces:**
- Consumes: `DownloadMetadata`(models.py) — resolve_content에서만 사용, 본 태스크는 파싱만
- Produces:
  - `SELECTORS: dict[str, str]`, `URLS: dict[str, str]` — 실측(Task 6)이 갱신하는 상수
  - `class HegreParser`:
    - `content_type(url: str) -> str` — `'video'` | `'photo'`
    - `video_links(html: str) -> list[dict]` — `[{"url": str, "resolution": int}]` 내림차순
    - `best_video(html: str) -> Optional[dict]`
    - `zip_links(html: str) -> list[dict]` — `[{"url": str, "pixels": int}]` 내림차순
    - `best_zip(html: str) -> Optional[dict]`
    - `extract_model_name(html: str) -> Optional[str]`

- [ ] **Step 1: failing test 작성**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_hegre.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vesper_x.extractors.hegre'`

- [ ] **Step 3: hegre.py에 파서 구현 (crawler는 다음 태스크)**

```python
"""Hegre 크롤러/파서 — 인증 세션으로 4K 영상·6000px ZIP 직링크 추출.

DOM selector와 URL 패턴은 실측 전 가정값이다 — SELECTORS/URLS 상수로 격리해
Task 6 실접속 recon에서 상수만 갱신한다 (파싱 로직과 분리).
CDN 직링크는 dispatch 직전에만 resolve한다 (spec 4.3 — 서명 TTL/IP 바인딩 방어).
"""
import re
from typing import Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup

URLS = {
    "model": "https://hegre.com/models/{slug}",   # 가정 — Task 6 확정
    "updates": "https://hegre.com/update",        # 가정 — Task 6 확정
}

SELECTORS = {
    "download_links": "div.download a[href]",     # 가정 — Task 6 확정
    "gallery_zip": "a[href$='.zip']",             # 가정 — Task 6 확정
    "model_name": "a.model",                      # 가정 — Task 6 확정
}

_RESOLUTION_RE = re.compile(r"(\d{3,4})\s*p", re.IGNORECASE)
_PIXELS_RE = re.compile(r"(\d{4,5})\s*px", re.IGNORECASE)


class HegreParser:
    @staticmethod
    def content_type(url: str) -> str:
        """/films|/movies → 'video', 그 외(/galleries|/magazines) → 'photo'."""
        if re.search(r"/(films?|movies?|videos?)/", urlparse(url).path):
            return "video"
        return "photo"

    def video_links(self, html: str) -> list[dict]:
        """해상도 내림차순 mp4 목록 — 동일 해상도 중복은 제거."""
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict] = []
        for a in soup.select(SELECTORS["download_links"]):
            label = a.get_text(" ", strip=True) or a.get("data-resolution", "")
            m = _RESOLUTION_RE.search(label)
            if m and a["href"].endswith(".mp4"):
                links.append({"url": a["href"], "resolution": int(m.group(1))})
        links.sort(key=lambda x: -x["resolution"])
        seen, out = set(), []
        for link in links:
            if link["resolution"] not in seen:
                seen.add(link["resolution"])
                out.append(link)
        return out

    def best_video(self, html: str) -> Optional[dict]:
        links = self.video_links(html)
        return links[0] if links else None

    def zip_links(self, html: str) -> list[dict]:
        """픽셀 내림차순 ZIP 목록 — 6000px 우선, 소팅이 곧 fallback이다."""
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict] = []
        for a in soup.select(SELECTORS["gallery_zip"]):
            label = a.get_text(" ", strip=True) or a.get("data-size", "")
            m = _PIXELS_RE.search(label)
            if m:
                links.append({"url": a["href"], "pixels": int(m.group(1))})
        links.sort(key=lambda x: -x["pixels"])
        return links

    def best_zip(self, html: str) -> Optional[dict]:
        links = self.zip_links(html)
        return links[0] if links else None

    @staticmethod
    def extract_model_name(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        a = soup.select_one(SELECTORS["model_name"])
        return a.get_text(" ", strip=True) if a else None
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_hegre.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/vesper_x/extractors/hegre.py tests/test_hegre.py
git commit -m "feat: HegreParser - 영상 해상도/ZIP 픽셀 우선순위 파싱 (selector 상수 격리)"
```

---

### Task 4: HegreCrawler — 인증 세션 + 목록 수집 + resolve_content

**Files:**
- Modify: `src/vesper_x/extractors/hegre.py` (crawler 추가)
- Test: `tests/test_hegre.py` (확장)

**Interfaces:**
- Consumes:
  - `AppConfig`(`config.proxy`, `config.credentials`), `CredentialConfig`
  - `HegreParser` (Task 3), `DownloadMetadata`, `DEFAULT_USER_AGENT`(`cli.py`에 있으므로 hegre.py에 상수 직접 정의)
- Produces:
  - `HEGRE_PROFILE_DIR = Path.home() / ".config" / "url-resolver" / "hegre_profile"`
  - `class HegreCrawler`:
    - `__init__(config: AppConfig)`
    - `ensure_credentials() -> CredentialConfig` — 없으면 `ValueError`
    - `resolve_content(html: str, page_url: str) -> list[DownloadMetadata]` — video 최고 해상도 / photo 최대 ZIP 1건
    - `extract_gallery_refs(html: str, base_url: str) -> list[dict]` (staticmethod) — `[{"url": str, "title": str}]`
    - `extract_next_page_url(html: str, base_url: str) -> Optional[str]` (staticmethod)
    - `login() -> bool`, `fetch(url: str) -> str` — Playwright 라이프사이클. 구현은 Task 6 실측에서 selector와 함께 확정 (본 태스크는 세션 골격 + 실패 처리만)

- [ ] **Step 1: failing test 작성 (tests/test_hegre.py에 추가)**

```python
from vesper_x.config import AppConfig, CredentialConfig
from vesper_x.extractors.hegre import HegreCrawler

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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_hegre.py -v -k "crawler or refs or next_page or resolve_content or ensure"`
Expected: FAIL — `HegreCrawler` 없음

- [ ] **Step 3: HegreCrawler 구현 (hegre.py에 추가)**

```python
from pathlib import Path
from urllib.parse import urljoin

from vesper_x.config import AppConfig, CredentialConfig
from vesper_x.models import DownloadMetadata

HEGRE_PROFILE_DIR = Path.home() / ".config" / "url-resolver" / "hegre_profile"
DEFAULT_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/128.0.0.0 Safari/537.36")

_CONTENT_PATH_RE = re.compile(r"/(films?|galleries?|magazines?)/[\w-]+")


class HegreCrawler:
    """인증 세션(persistent Chrome profile) + 목록 수집.

    세션은 ouo와 동일한 launch_persistent_context 패턴이다 — 프로필 디렉토리에
    로그인 쿠키가 유지되어 storage_state 파일 관리가 불필요하다.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.parser = HegreParser()

    def ensure_credentials(self) -> CredentialConfig:
        creds = self.config.credentials.get("hegre")
        if not creds or not creds.username:
            raise ValueError(
                "config.toml [credentials.hegre] 미설정 - username/password를 추가한다")
        return creds

    # --- 목록 수집 (정적 — mock 테스트 대상) ---

    @staticmethod
    def extract_gallery_refs(html: str, base_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        refs: list[dict] = []
        seen: set[str] = set()
        for a in soup.select("a[href]"):
            href = urljoin(base_url, a["href"])
            if _CONTENT_PATH_RE.search(urlparse(href).path) and href not in seen:
                seen.add(href)
                refs.append({"url": href, "title": a.get_text(" ", strip=True)})
        return refs

    @staticmethod
    def extract_next_page_url(html: str, base_url: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        a = soup.select_one("a.next, li.pagination-next a, a[rel='next']")
        return urljoin(base_url, a["href"]) if a and a.get("href") else None

    # --- resolve (dispatch 직전 호출 — spec 4.3) ---

    def resolve_content(self, html: str, page_url: str) -> list[DownloadMetadata]:
        ctype = self.parser.content_type(page_url)
        model_name = self.parser.extract_model_name(html)
        best = (self.parser.best_video(html) if ctype == "video"
                else self.parser.best_zip(html))
        if not best:
            return []
        direct_url = best["url"]
        return [DownloadMetadata(
            direct_url=direct_url,
            referer=page_url,
            user_agent=DEFAULT_USER_AGENT,
            filename=direct_url.split("?")[0].rsplit("/", 1)[-1],
            source_page=page_url,
            models=[model_name] if model_name else [],
            file_page_url=page_url,
        )]

    # --- Playwright 세션 (골격 — selector는 Task 6 실측에서 확정) ---

    def _launch_kwargs(self) -> dict:
        kwargs: dict = {"channel": "chrome", "headless": False}
        if self.config.proxy:
            kwargs["proxy"] = {"server": self.config.proxy}
        return kwargs
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_hegre.py -v`
Expected: 전체 PASS (Task 3 분포 포함 14 tests)

- [ ] **Step 5: Commit**

```bash
git add src/vesper_x/extractors/hegre.py tests/test_hegre.py
git commit -m "feat: HegreCrawler - 목록 수집/resolve_content/credentials 검증"
```

---

### Task 5: CLI 통합 — run_hegre_crawl + crawl/parse 분기

**Files:**
- Modify: `src/vesper_x/cli.py` (import, `crawl` 커맨드, `run_hegre_crawl` 신규)
- Test: `tests/test_hegre.py` (CLI 테스트 추가)
- 불변: `src/vesper_x/dispatchers/aria2.py` — Cookie/Referer 헤더는 이미 `DownloadMetadata`로 전달되고 `H/` subdir은 config `[sites]`가 결정하므로 수정 불필요 (spec 4.2 "필요 시"의 결론)

**Interfaces:**
- Consumes:
  - `HegreCrawler.ensure_credentials/resolve_content/extract_*` (Task 4)
  - `PremiumDB.*` (Task 2), `Aria2Dispatcher.dispatch` (기존), `run_async` (cli.py:86)
- Produces:
  - `run_hegre_crawl(url: Optional[str], model: Optional[str], new_only: bool, extract_only: bool, limit: int, config: Optional[AppConfig] = None, db: Optional[PremiumDB] = None, crawler: Optional[HegreCrawler] = None) -> None` — 테스트가 config/db/crawler를 주입한다
  - `crawl` 커맨드 신규 옵션: `--site <name>`, `--model <name>`, `--new` — `url` 인자를 `Optional`로 변경 (기존 `vesper crawl <URL>` 사용법은 유지)

- [ ] **Step 1: failing test 작성 (tests/test_hegre.py에 추가)**

```python
import pytest
from vesper_x.cli import run_hegre_crawl


class FakeCrawler:
    """fetch/resolve_content를 HTML 응답으로 대체하는 테스트 더블."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.parser = HegreParser()

    def ensure_credentials(self):
        return CredentialConfig("u", "p")

    async def fetch(self, url: str) -> str:
        if url not in self.pages:
            raise RuntimeError(f"unexpected fetch: {url}")
        return self.pages[url]

    def resolve_content(self, html: str, page_url: str):
        return HegreCrawler.resolve_content(self, html, page_url)


def _cfg():
    return AppConfig(credentials={"hegre": CredentialConfig("u", "p")})


def test_run_hegre_crawl_dispatches_and_records(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({
        "https://hegre.com/films/massage-x": VIDEO_PAGE,
    })
    run_hegre_crawl(url="https://hegre.com/films/massage-x", model=None,
                    new_only=False, extract_only=True, limit=0,
                    config=_cfg(), db=db, crawler=crawler)
    assert db.is_downloaded("https://hegre.com/films/massage-x")


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
    import datetime
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({"https://hegre.com/films/massage-x": VIDEO_PAGE})
    run_hegre_crawl(url="https://hegre.com/films/massage-x", model=None,
                    new_only=True, extract_only=True, limit=0,
                    config=_cfg(), db=db, crawler=crawler)
    assert db.get_crawl_checkpoint("H") is not None


def test_run_hegre_crawl_no_credentials_exits(tmp_path):
    db = PremiumDB(tmp_path / "premium.db")
    crawler = FakeCrawler({})
    import typer
    with pytest.raises(typer.Exit):
        run_hegre_crawl(url="https://hegre.com/films/x", model=None,
                        new_only=False, extract_only=True, limit=0,
                        config=AppConfig(), db=db, crawler=crawler)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_hegre.py -v -k run_hegre`
Expected: FAIL — `run_hegre_crawl` import 불가

- [ ] **Step 3: cli.py 구현**

import 추가 (기존 import 블록 근처):

```python
from vesper_x.extractors.hegre import HegreCrawler
from vesper_x.premium_db import PremiumDB
```

`run_hegre_crawl` 함수 — `run_crawl` 근처에 배치:

```python
def run_hegre_crawl(url: Optional[str], model: Optional[str], new_only: bool,
                    extract_only: bool, limit: int,
                    config: Optional[AppConfig] = None,
                    db: Optional[PremiumDB] = None,
                    crawler: Optional[HegreCrawler] = None) -> None:
    """Hegre 크롤 — 목록 수집은 URL만, CDN resolve는 dispatch 직전 (spec 4.3)."""
    config = config or load_config()
    db = db or PremiumDB()
    crawler = crawler or HegreCrawler(config)
    creds = config.credentials.get("hegre")
    if not creds or not creds.username:
        console.print("[bold red]config.toml [credentials.hegre] 미설정 - "
                      "username/password를 추가한다[/bold red]")
        raise typer.Exit(1)

    if url:
        refs = [{"url": url, "title": url}]
    else:
        refs = run_async(crawler.collect(model_slug=model))
    if limit:
        refs = refs[:limit]

    dispatcher = None if extract_only else Aria2Dispatcher(config)
    for ref in refs:
        if db.is_downloaded(ref["url"]):
            console.print(f"[dim]skip (dispatched): {ref['url']}[/dim]")
            continue
        html = run_async(crawler.fetch(ref["url"]))
        metadata_list = crawler.resolve_content(html, ref["url"])
        if not metadata_list:
            console.print(f"[yellow]다운로드 링크 없음: {ref['url']}[/yellow]")
            continue
        for m in metadata_list:
            if dispatcher:
                gid = dispatcher.dispatch(m)
                console.print(f"[bold green]Dispatched to aria2[/bold green] "
                              f"(GID: [cyan]{gid}[/cyan]) - {m.filename}")
            model_name = m.models[0] if m.models else "Unknown"
            model_id = db.upsert_model(model_name, "H")
            ctype = "video" if m.direct_url.endswith(".mp4") else "photo"
            gallery_id = db.upsert_gallery(
                model_id, ref.get("title") or ref["url"], m.file_page_url, "H", ctype)
            db.record_download(gallery_id, m.file_page_url, m.filename)
    if new_only:
        db.update_crawl_checkpoint(
            "H", datetime.datetime.now(datetime.timezone.utc).isoformat())
```

`crawler.collect`는 Task 6 실측에서 붙이는 async 메서드다 — 본 태스크에서는 `HegreCrawler`에 최소 골격을 추가해 `run_async(crawler.collect(...))` 참조가 깨지지 않게 한다:

```python
    async def collect(self, model_slug: Optional[str] = None, max_pages: int = 10) -> list[dict]:
        """모델/신작 목록 순회 — fetch·selector는 Task 6 실측에서 확정."""
        base = (URLS["model"].format(slug=model_slug) if model_slug
                else URLS["updates"])
        refs: list[dict] = []
        url: Optional[str] = base
        for _ in range(max_pages):
            html = await self.fetch(url)
            refs.extend(self.extract_gallery_refs(html, url))
            url = self.extract_next_page_url(html, url)
            if not url:
                break
        return refs
```

`crawl` 커맨드 확장 — `url`을 `Optional[str]`로, 옵션 3개 추가, hegre 분기:

```python
@app.command()
def crawl(
    url: Optional[str] = typer.Argument(None, help="Target site URL (category/tag)"),
    # ... 기존 pages/limit/extract_only/output/json_output/skip_gofile 옵션 유지 ...,
    site: Optional[str] = typer.Option(None, "--site", help="사이트 명시 선택 (hegre)"),
    model: Optional[str] = typer.Option(None, "--model", help="모델 전체 크롤 (hegre)"),
    new: bool = typer.Option(False, "--new", help="신작 크롤 (체크포인트 기반)"),
):
    """Crawl category or tag listing across multiple pages and process all posts."""
    if site == "hegre" or (url and "hegre.com" in url):
        return run_hegre_crawl(url=url, model=model, new_only=new,
                               extract_only=extract_only, limit=limit)
    # 기존 경로 유지
    cfg = load_config()
    if skip_gofile:
        cfg.skip_gofile = True
    run_crawl(url, pages=pages, limit=limit, extract_only=extract_only,
              output=output, json_output=json_output, config=cfg)
```

`cli.py` 상단에 `import datetime`이 없으면 추가한다. `parse` 커맨드의 단일 Hegre URL 처리는 `resolve_post`가 hegre 도메인에서 `HegreCrawler.resolve_content`로 위임하게 분기한다 — 실접속 fetch가 필요하므로 골격만:

```python
    # resolve_post 상단, _fetch 정의 후:
    if "hegre.com" in post_url:
        crawler = HegreCrawler(config)
        html = run_async(crawler.fetch(post_url))
        return crawler.resolve_content(html, post_url)
```

`fetch`는 Playwright 세션 메서드로 Task 6에서 완성한다. 본 태스크의 CLI 테스트는 `run_hegre_crawl` 경로만 검증한다 (resolve_post 분기는 실 network이라 mock 불가).

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_hegre.py tests/test_cli.py -v`
Expected: 전체 PASS — 기존 `test_cli.py`는 url required 가정이 없는지 확인하고, `crawl` 시그니처 변경으로 깨지는 테스트가 있으면 url 인자를 명시하도록 갱신

- [ ] **Step 5: 전체 테스트**

Run: `uv run pytest`
Expected: 전체 PASS

- [ ] **Step 6: Commit**

```bash
git add src/vesper_x/cli.py tests/test_hegre.py
git commit -m "feat: Hegre CLI 통합 - crawl --site/--model/--new, dispatch 직전 resolve, premium.db 기록"
```

---

### Task 6: 실측 recon — selector 확정 + E2E (사용자 승인 필수)

**Files:**
- Modify: `src/vesper_x/extractors/hegre.py` (`SELECTORS`, `URLS`, `login`, `fetch` 완성)
- Modify: `docs/superpowers/specs/2026-09-25-hegre-crawler-design.md` (실측 결과 기록 — 선택)

**Interfaces:**
- Consumes: Task 1–5 전부
- Produces: 실측 확정 selector/URL 상수, `login() -> bool`, `fetch(url) -> str` (persistent Chrome + proxy), CDN URL 특성 기록 (spec 4.3 완화 여부)

**⚠️ 본 태스크는 실 network 접속(hegre.com)을 포함한다 — 실행 전 사용자 승인을 받는다 (CLAUDE.md).**

- [ ] **Step 1: 사용자 승인**

hegre.com 실접속 recon 승인 요청. 승인 전까지 본 태스크는 대기.

- [ ] **Step 2: 로그인 흐름 실측**

real Chrome headed(`channel="chrome"`, proxy)로 `hegre.com/login` 접속 → 로그인 폼 selector 확인 → `login()` 구현 (폼 입력 → submit → 세션 확인). 프로필 디렉토리(`HEGRE_PROFILE_DIR`)에 쿠키가 유지되는지 재실행으로 확인.

구현 지침: `login() -> bool`은 Task 4의 `_launch_kwargs()`로 persistent context를 열고(ouo의 `_run_playwright_bypass` 구조 참조), 실측한 폼 selector로 username/password 채워 submit한다. 로그인 성공 판정(세션 쿠키 존재 또는 리다이렉트 목적지) 후 True, 비번 오류/차단 시 False를 반환한다. `fetch(url) -> str`은 동일 context에서 `page.goto(url)` → `page.content()`로 구현한다.

- [ ] **Step 3: URL/selector 확정**

`URLS["updates"]`/`URLS["model"]` 실제 경로 확인, 인덱스 페이지에서 `extract_gallery_refs`·`extract_next_page_url` 동작 확인, 콘텐츠 페이지에서 `video_links`/`zip_links` selector 확인 → `SELECTORS` 상수 갱신. fixture HTML을 실측 DOM 구조에 맞게 갱신하고 `uv run pytest tests/test_hegre.py` 재실행.

- [ ] **Step 4: CDN URL 특성 실측**

resolve한 직링크의 (a) 서명 TTL 존재 여부 (b) 쿠키/Referer 필수 여부 (c) IP 바인딩 여부 — curl/브라우저 외부에서 접근 테스트. 결과를 spec 7장에 기록하고, TTL 없음이 확인되면 spec 4.3의 완화(일괄 resolve) 검토.

- [ ] **Step 5: E2E 1건**

```bash
uv run vesper parse "https://hegre.com/films/<실측-slug>" --extract-only
```

Expected: CDN 직링크 + filename 출력. 이후 사용자 승인 하에 dispatch 1건 (`--extract-only` 없이) → heritage aria2에서 다운로드 시작·`premium.db` 기록 확인.

- [ ] **Step 6: 전체 테스트 + 문서 갱신 + Commit**

Run: `uv run pytest` → 전체 PASS. `.ai/RULES.md` Commands/Architecture에 hegre 경로 한 줄 추가 (필요 시).

```bash
git add -A
git commit -m "feat: Hegre 실측 selector/로그인 확정 및 E2E 검증"
```
