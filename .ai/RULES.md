# Vesper-X Common Rules

모든 AI agent 공통 rule. Vendor 별 rule은 각 root file에 둔다.

## Commands

| 작업 | Command |
| :--- | :--- |
| 의존성 설치 | `uv sync` |
| Test | `uv run pytest` |
| CLI 실행 | `uv run vesper parse "<url>" --extract-only` |
| 모델 조회 | `uv run vesper models <이름/slug>` — 사이트 실시간 카운트 + heritage 보유 + 크롤 추천 |
| cosplay.db 재생성 | `uv run python scripts/build_models_db.py` — data/*.tsv에서 (패키지 import 때문에 uv run 필수) |
| Browser 설치 | `uv run playwright install chromium` — gofile 캡처용 번들 Chromium (ouo/misskon은 실제 Chrome 사용) |

Lint 도구는 미설정. 도입 시 이 표를 갱신한다.

## Architecture

- `src/vesper_x/cli.py` — Typer entry. parse / crawl / clip / batch / models
- `src/vesper_x/extractors/` — Parser(misskon, cosplaytele) · Crawler(crawler) · Bypasser(ouo) · Resolver(mediafire, gofile)
- `src/vesper_x/fetchers.py` — `BrowserFetcher` (Chrome ECH page fetch, `crawl`이 사용)
- `src/vesper_x/dispatchers/aria2.py` — aria2p RPC 전송
- `src/vesper_x/models.py` — `DownloadMetadata` 전송 단위
- `src/vesper_x/config.py` — `~/.config/url-resolver/config.toml` 로드 (`[network] proxy`, `[sites]` 도메인→crawler/subdir 매핑)
- `src/vesper_x/models_db.py` — `ModelRegistry`: data/cosplay.db 이름 사전(변형→캐노니컬/slug). DB 부재 시 조용히 비활성
- `scripts/build_models_db.py` + `data/*.tsv` — 전수조사 스냅샷(TSV, git 추적)에서 cosplay.db 재생성(DB는 gitignore 재생산물)

Pipeline: CLI → BrowserFetcher(proxy+Chrome) → Crawler → Parser → Bypasser(ouo, real Chrome headed) → Resolver(mediafire, gofile) → DownloadMetadata → Dispatcher(aria2) → heritage extract

## Conventions

- 새 host 지원: `extractors/`에 Crawler 추가 + `config.toml [sites]`에 도메인 등록 — `crawler` 이름은 `cli._select_crawler` registry 키(`category`/`cosplaytele`)와 매칭, `subdir`은 aria2 라우팅 디렉토리. 다운로드 링크(ouo→파일호스트) 추출은 MisskonParser 공용 경로를 탄다
- **디지털 미디어 아카이브 수집 전략**:
  - **1차 주력 (Primary)**: `CosplayTele`, `MissKon` — 4K/8K 무손실 원본 통압축(ZIP) 미디어 최우선 파이프라인
  - **2차 보조 (Secondary)**: `EVERIA.CLUB`, `E-Hentai` — 1차 누락 앨범 및 아카이브 발굴용 (`gallery-dl` / 갤러리 덤프)
- **원격 아카이빙 디렉토리 분류 표준 (`/mnt/data2/torrent/downloads/aria/`)**:
  - 최상위 권역 분류: `KOR` / `JPN` / `CHN` / `SEA` / `WEST` (5대 독립 리그 우선 분류) ➡️ `ETC` (미분류 폴백)
  - 아티스트 디렉토리 명명: `영어 (원문)` 포맷 및 A-Z 정렬 기준 (예: `Byoru (ビョル)`, `Tiny Asa (アサ)`, `Aqua (水淼)`)
  - 계층 구조: `[권역] > [아티스트 (원문)] > [개별 앨범 세트]`
- Test는 실 network 없이 mock으로 작성 (전 test suite가 mock 기반)
- Python >= 3.12 표준 library 우선

## Gotchas

- pytest `asyncio_mode = "strict"` — async test에 `@pytest.mark.asyncio` 필수
- 모든 fetch 경로(cli httpx, ouo/gofile Playwright, BrowserFetcher)는 `[network] proxy`(brla gluetun, Surfshark SG egress)를 탄다 — 한국 SNI/NextDNS/geo 차단은 이걸로 우회. 다운로드 자체는 heritage aria2가 직접 받는다 (프록시 미경유)
- `OuoBypasser.resolve()`는 async — sync context에서는 `cli.run_async()` 호출. Playwright sync 세션(`BrowserFetcher` with 블록) 안에서는 main thread에 running loop가 남아 `asyncio.run()` 직접 호출 시 RuntimeError
- misskon.com은 한국 이중 차단(ISP SNI + Cloudflare 451) — httpx/번들 Chromium 모두 실패. `BrowserFetcher`는 `channel="chrome"`(실제 Chrome) + ECH + secure DoH launch args 필수
- ouo.io는 Cloudflare challenge를 앞에 뒀다(2026-09 실측) — 번들/headless Chromium은 "Just a moment..."에서 막히고 **real Chrome headed(`channel="chrome", headless=False`)만 통과**. UA 스푸핑 금지: 가짜 UA와 실제 바이너리 지문 불일치가 challenge 유발
- ouo 우회는 2단계("I'M A HUMAN" → `/go/` "Get Link", countdown 후 활성화)이며 **다중 체인(3중 shortener, 6스테이지)까지 존재** — 스테이지 한계 12
- ouo bypass는 간헐 실패 시 입력 URL을 그대로 반환한다 — `resolve_post`가 결과에 ouo 잔존 시 재시도 후 skip
- ouo `/st/` 형식 링크(`ouo.io/st/<id>?s=<target>`)는 목적지가 파라미터에 평문 노출된다 — 도착 판정은 hostname 기준(`_is_target_url`)이며 부분문자열 검사 금지. `/st/` 링크는 goto 시 plain `ouo.io/<id>`로 redirect된다
- gofile은 익명 API를 차단한다(error-notPremium) — `GofileResolver`는 웹 UI의 contents XHR을 Playwright로 캡처해 직링크(`download/web/{id}/{name}`) + `accountToken` Cookie로 조립한다. 폴더 링크는 파일 수만큼 metadata로 확장. mega는 여전히 pass-through
- **mediafire 직링크는 resolve한 IP에 묶인다** — 프록시(SG)로 resolve하면 heritage가 홈페이지 HTML(36KB)을 받는다(2026-09-07 실측). mediafire 페이지 fetch는 반드시 직접 경로(`proxy=None`)
- **misskon 멀티페이지 포스트**는 다운로드 링크가 `/N/` 뒷 페이지에만 있기도 하다(baegjm06 실측) — `resolve_post`가 `a.post-page-numbers` 전 페이지를 병합해 파싱한다
- **dispatch_log**(cosplay.db) — crawl이 이미 전송한 post URL을 skip한다("신작만" 재크롤). 과거 이력이 없어 첫 크롤은 전량 받는다; 보유 분류가 필요한 신작만은 extract-only → heritage 보유 diff → delta dispatch
- **수집/다운로드 2-phase**: `crawl --collect`가 resolve 결과를 dispatch_log 큐(`status='collected'`)에만 저장하고, `vesper dispatch`가 별도로 재 resolve+전송한다. 큐 url 키는 파일 단위 불변 식별자(mediafire file_page_url) — 포스트당 part1/part2 분할도 별도 행. mediafire 직링크는 resolve IP 바인딩+만료라 dispatch 직전 재 resolve 필수, mega는 저장된 direct_url pass-through. `dispatched` 행은 재수집이 덮어쓰지 않고 `failed`는 재수집으로 재시도 가능
- aria2 host는 `ws://`로 설정해도 `Aria2Dispatcher`가 http(s)로 변환한다
- aria2 dispatch는 `[aria2] download_dir`(daemon-side 경로, `/downloads` = host `/mnt/data2/torrent/downloads/aria`) 아래 사이트 서브디렉토리(`misskon/`, `cosplaytele/`, `H/`)로 전송한다 — heritage `extract_organize.sh`가 이 디렉토리로 압축 비번을 분기함 (misskon: `misskon.com`→`mrcong.com`, cosplaytele: `cosplaytele`). Hegre는 filename에 `모델/앨범/파일` 상대경로를 실어 `H/{모델명}/{앨범}/` 계층 형성
- **Hegre(H) 인증 다운로드** (2026-09-25 실측): `login` 쿠키만으로 CDN(content/cc.hegre.com) 200 — Referer 불필요, IP 바인딩 없음(직접/프록시 모두 200). members-only 링크는 비인증 HTML에도 노출되나 다운로드는 login 쿠키 필요(401). 쿠키는 수일 TTL — persistent profile(`~/.config/url-resolver/hegre_profile`)에 저장, 만료 시 재로그인
- **Hegre URL/selector** (2026-09-25 실측): video=`/films/<slug>`(content.hegre.com `-2160p.mp4?d=attachment`), photo=`/photos/<slug>`(cc.hegre.com `zips/<slug>-<px>px.zip`, 6000px 우선/spec 3.2), trailer(pp.hegre.com)와 정본은 CDN host로 구분. 모델명은 `a.record-model`의 `title` 속성. 로그인 폼은 `#username`/`#password`/`input.submit`(Rails CSRF — Playwright form submit으로 자동 처리)
- **Hegre 파이프라인 분담**: 이력/skip은 `~/.config/url-resolver/premium.db` 단일 소스(cosplay.db dispatch_log 미참조). CDN resolve는 dispatch 직전(spec 4.3) — 실측상 TTL/IP 바인딩 없어 완화 여지 있으나 유지
- `data/cosplay.db`는 gitignore 재생산물(`uv run python scripts/build_models_db.py`로 생성) — 부재 시 `ModelRegistry`는 조용히 비활성이므로 신규 클론에서 metadata.models가 캐노니컬명이 아닌 사이트 표기로 기록되는 것은 정상 동작이다. 변형 매칭에서 `cosplayer` 등 일반명사 토큰은 제외(stopword)된다
