# Hegre(H) 크롤러 설계

> Vesper-X에 프리미엄 사이트 Hegre(H) 크롤러를 추가하여, 인증된 세션으로
> 영상/이미지를 추출하고 aria2(heritage)로 전송한다.

## 목표

- Hegre 프리미엄 계정으로 영상(4K 2160p)과 이미지(6000px ZIP) 다운로드
- 기존 Vesper-X 파이프라인(aria2 dispatch, dispatch_log)에 통합
- 모델/갤러리 메타데이터와 다운로드 이력을 SQLite DB로 관리

## 스코프

**포함:**
- H(Hegre) 크롤러 구현
- Config 2중 분리 (default.toml + 로컬 config.toml)
- SQLite DB 스키마 및 기본 CRUD
- aria2 dispatch 연동

**제외:**
- W4B(watch4beauty) — H 완성 후 동일 패턴으로 별도 구현
- DB sync (rsync/rclone/cloud) — 별도 이슈
- credentials 암호화 (sops) — 별도 이슈

## 사용 시나리오

| CLI | 동작 |
|---|---|
| `vesper parse "https://hegre.com/films/xxx"` | 단일 갤러리/영상 다운로드 URL 추출 → aria2 전송 |
| `vesper crawl --site hegre --model "모델명"` | 특정 모델의 전체 콘텐츠 크롤 → aria2 전송 |
| `vesper crawl --site hegre --new` | 신작 크롤 (마지막 체크포인트 이후) → aria2 전송 |

## 1. Config 2중 분리

### 1.1 고정 설정: `config/default.toml` (git 추적)

사이트 매핑, 기본값 등 환경에 무관한 고정 변수.

```toml
[aria2]
download_dir = "/downloads"

[sites]
"misskon.com" = { crawler = "category", subdir = "misskon" }
"cosplaytele.com" = { crawler = "cosplaytele", subdir = "cosplaytele" }
"hegre.com" = { crawler = "hegre", subdir = "H" }
```

### 1.2 로컬 설정: `~/.config/url-resolver/config.toml` (git 미추적)

계정 정보, 비밀키, 환경별 오버라이드.

```toml
[aria2]
host = "ws://heritage.bun-bull.ts.net:6800"
secret = "P3TERX"

[network]
proxy = "http://brla.bun-bull.ts.net:8888"

[credentials.hegre]
username = "user@example.com"
password = "secret"
```

### 1.3 로딩 우선순위

1. `config/default.toml` (프로젝트 내) 로드
2. `~/.config/url-resolver/config.toml` (로컬) 로드
3. Deep merge — 로컬이 우선 (같은 키면 로컬이 덮어씀)

`config.py` 변경:
- `AppConfig`에 `credentials: dict[str, CredentialConfig]` 필드 추가
- `CredentialConfig` dataclass: `username: str`, `password: str`
- `load_config()` → `_load_default()` + `_load_local()` + `_deep_merge()` 로 분리

## 2. 인증

### 2.1 로그인 흐름

1. Playwright (real Chrome, `channel="chrome"`) + proxy 경유
2. `hegre.com/login` 접속
3. username/password 입력 → 로그인 submit
4. 세션 쿠키 획득

### 2.2 쿠키 캐시

- 로그인 성공 시 쿠키를 `~/.config/url-resolver/hegre_cookies.json`에 저장
- 이후 요청 시 캐시된 쿠키로 시작, 만료/실패 시 자동 재로그인
- Playwright `storage_state` API 활용

## 3. Hegre Crawler

### 3.1 모듈 구조

```
src/vesper_x/extractors/hegre.py
```

두 클래스:
- `HegreCrawler` — 인증 세션 관리, 페이지 목록 수집 (모델별/신작별)
- `HegreParser` — 개별 콘텐츠 페이지에서 다운로드 URL 추출

### 3.2 다운로드 URL 추출

**영상:**
- 페이지 내 다운로드 섹션에서 해상도별 링크 파싱
- 우선순위: `4K Ultra HD 2160p` > `Full HD 1080p` > 가용 최고 해상도
- 과거 작품은 포맷이 적을 수 있으므로 최고 해상도 fallback

**이미지:**
- `Large Size Edition | 6000px` ZIP 링크 추출
- ZIP 없으면 가용 최대 사이즈 fallback

### 3.3 크롤 전략

**단일 (`vesper parse <URL>`):**
- URL에서 콘텐츠 유형 판별 (film/gallery/photo)
- 해당 페이지 파싱 → 다운로드 URL 추출 → `DownloadMetadata` 생성

**모델 전체 (`--model`):**
- 모델 프로필 페이지에서 콘텐츠 목록 수집
- 페이지네이션 순회
- 각 콘텐츠에 대해 파싱 + dispatch
- DB의 다운로드 이력으로 이미 받은 건 skip

**신작 (`--new`):**
- 사이트 최신 업데이트 페이지에서 크롤
- DB의 `crawl_state.last_crawl_at` 이후 콘텐츠만 수집
- 완료 시 체크포인트 갱신

## 4. aria2 Dispatch

### 4.1 디렉토리 구조

```
/mnt/data2/torrent/downloads/aria/H/{모델명}/{앨범 제목}/
```

- `H/` — Hegre 전용 최상위 (W4B 추가 시 `W4B/`로 분리)
- 모델명 — 사이트에서 사용하는 영문명
- 앨범 제목 — 갤러리/영상 제목

### 4.2 기존 파이프라인 재사용

- `DownloadMetadata` 생성 → `Aria2Dispatcher.dispatch()` 호출
- 인증 쿠키가 필요한 경우 aria2 `--header "Cookie: ..."` 옵션 전달
- Referer 헤더 필요 시 함께 전달

### 4.3 dispatch_log

- 기존 dispatch_log 메커니즘으로 이미 전송한 URL skip
- 향후 SQLite DB의 `downloads` 테이블로 통합 예정 (이번에는 병행)

## 5. SQLite DB

### 5.1 위치

```
~/.config/url-resolver/vesper.db
```

### 5.2 스키마

```sql
CREATE TABLE models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT,
    site        TEXT NOT NULL,  -- 'H' or 'W4B'
    url         TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX idx_models_site_name ON models(site, name);

CREATE TABLE galleries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    INTEGER REFERENCES models(id),
    title       TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    date        TEXT,           -- 공개일
    type        TEXT NOT NULL,  -- 'photo' or 'video'
    resolution  TEXT,           -- '2160p', '6000px' 등
    site        TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE downloads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gallery_id      INTEGER REFERENCES galleries(id),
    url             TEXT NOT NULL,
    filename        TEXT,
    status          TEXT DEFAULT 'pending',  -- pending / dispatched / completed
    dispatched_at   TEXT,
    completed_at    TEXT
);
CREATE UNIQUE INDEX idx_downloads_url ON downloads(url);

CREATE TABLE crawl_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site            TEXT NOT NULL UNIQUE,  -- 'H' or 'W4B'
    last_crawl_at   TEXT,
    last_page_url   TEXT,
    checkpoint      TEXT           -- 사이트별 추가 상태
);
```

### 5.3 DB 모듈

`src/vesper_x/db.py` 신규:
- `init_db()` — 테이블 생성 (IF NOT EXISTS)
- `upsert_model()`, `upsert_gallery()`, `record_download()` 등 기본 CRUD
- `get_crawl_checkpoint()`, `update_crawl_checkpoint()`
- `is_downloaded(url)` — 중복 체크
- 표준 `sqlite3` 모듈 사용 (외부 ORM 없음)

### 5.4 DB sync 로드맵 (이번 스코프 밖)

```
Local SQLite → rsync(Tailscale) → rclone(R2) → Cloud SQLite(Turso)
```

각 단계에서 SQLite 파일이라는 본질은 불변. sync 레이어만 교체.

## 6. CLI 통합

### 6.1 기존 커맨드 확장

`cli.py`의 `_select_crawler` registry에 `"hegre"` 추가:
- `hegre.com` URL → `HegreCrawler` 자동 선택

### 6.2 새 옵션

`vesper crawl` 에 추가:
- `--site hegre` — 사이트 명시 선택
- `--model <name>` — 특정 모델 전체 크롤
- `--new` — 신작 크롤 (체크포인트 기반)

## 7. 기술 제약 및 주의사항

- Hegre 사이트의 정확한 DOM 구조(로그인 폼 selector, 다운로드 URL 패턴 등)는
  구현 단계에서 실제 사이트를 분석하여 결정
- 프록시(brla gluetun) 경유 필수 — 기존 `[network] proxy` 설정 재사용
- 세션 만료/차단 시 재로그인 + 적절한 딜레이로 rate limit 준수
- aria2에 쿠키/헤더 전달 가능 여부는 구현 시 검증 필요
- 테스트는 mock 기반 (기존 패턴 준수, 실 network 호출 없음)

## 8. 영향 범위

| 파일 | 변경 |
|---|---|
| `config/default.toml` | 신규 — git 추적 고정 설정 |
| `src/vesper_x/config.py` | 수정 — 2중 config 로딩, CredentialConfig 추가 |
| `src/vesper_x/extractors/hegre.py` | 신규 — HegreCrawler + HegreParser |
| `src/vesper_x/db.py` | 신규 — SQLite DB 스키마 + CRUD |
| `src/vesper_x/cli.py` | 수정 — hegre 크롤러 등록, --model/--new 옵션 |
| `src/vesper_x/dispatchers/aria2.py` | 수정 — 쿠키/헤더 전달 지원 (필요 시) |
| `tests/test_hegre.py` | 신규 — mock 기반 테스트 |
| `tests/test_config_merge.py` | 신규 — 2중 config merge 테스트 |
| `tests/test_db.py` | 신규 — DB CRUD 테스트 |
