# W4B 다운로더 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** W4B(watch4beauty.com)의 세트 자산(사진 ZIP + 4K mp4)을 Hegre와 공용인 `run_premium_crawl` 루프로 수집·aria2 dispatch 한다.

**Architecture:** `src/vesper_x/extractors/w4b.py`의 W4BParser(순수) + W4BCrawler(Playwright persistent profile)가 세트당 ZIP+최고해상도 mp4를 resolve하고, `cli.run_premium_crawl` 공용 루프가 skip 판정·dispatch·premium.db 기록을 담당한다. `[sites]` 등록만으로 aria2 subdir `W4B` 자동 라우팅.

**Tech Stack:** Python 3.12+, Playwright(`channel="chrome"`), BeautifulSoup, typer, pytest(mock 기반)

**Spec:** `docs/superpowers/specs/2026-09-27-w4b-downloader-design.md`

## Global Constraints

- Python >= 3.12, 표준 라이브러리 우선
- 테스트는 실 network 없이 mock/fixture 기반. Playwright 브라우저 경로(login/fetch/collect/resolve)는 미테스트 — hegre.py 패턴 동일
- pytest `asyncio_mode = "strict"` — async 테스트에 `@pytest.mark.asyncio` 필수
- Commit: Conventional Commits — 말머리 영어, 본문 한국어, `Co-Authored-By: Claude Code <noreply@anthropic.com>` 트레일러
- credentials는 로컬 `~/.config/url-resolver/config.toml`의 `[credentials.w4b]`에만. repo 평문 금지

## Review Focus

1. ZIP+mp4 공존 세트 → 2개 metadata, basename 상이로 충돌 없음 — Task 1 `test_pick_downloads_returns_zip_and_4k`
2. `/updates/popular` 등 비세트 경로 → collect 제외 — Task 1 `test_extract_model_content_refs_excludes_popular`
3. 쿠키 헤더 형식 `k=v; k=v`(httponly `session` 포함) — Task 2 `test_build_cookie_header`
4. extract-only는 premium.db를 오염시키지 않음 — Task 4 `test_run_premium_crawl_extract_only_does_not_record`
5. mp4 서명 URL TTL — resolve가 dispatch 직전에만 호출되는 루프 구조로 방어(네트워크 테스트 불가, 최종 review 확인)

---
### Task 1: W4BParser 순수 로직

**Files:**
- Create: `src/vesper_x/extractors/w4b.py` (상수 + W4BParser)
- Test: `tests/test_w4b.py` (신설)

**Interfaces (Produces):**
- 상수 `URLS` — 키 home/login/model/updates, 값: `https://www.watch4beauty.com`, `https://www.watch4beauty.com/login`, `https://www.watch4beauty.com/models/{slug}`, `https://www.watch4beauty.com/updates`
- 상수 `SELECTORS` — `login_user`=`#username-field`, `login_pass`=`#password-field`, `model_content_links`=`a.grid-item`, `download_links`=`a.button[href*='.zip'], a.button[href*='.mp4']`
- `W4BParser.pick_downloads(links: list[dict], base_url: str) -> list[dict]` — links 입력 `[{"href", "text"}]`, 반환 `[{"url", "type": "photo"|"video", "basename"}]`, 순서 [zip, mp4]
- `W4BParser.extract_model_name(html: str) -> Optional[str]` — verbatim, 부재 시 None
- `W4BCrawler.extract_model_content_refs(html: str, base_url: str) -> list[dict]` — 반환 `[{"url", "title"}]`, url dedupe

- [ ] **Step 1: 실패 테스트 작성** — tests/test_w4b.py에 다음 테스트를 작성한다. fixture 상수: BASE=`https://www.watch4beauty.com/updates/quickie-by-the-pool`, ZIP_HREF=`/api/media/20220227-max.zip`, MP4_2160=백스테이지 서명 mp4 URL 예시(ttl/token 쿼리 포함, 경로 끝이 `/backstage/2160.mp4`), MP4_1080=동일 패턴 `/1080.mp4`.

- `test_pick_downloads_returns_zip_and_4k` — links=[zip 상대경로, mp4 2160] 입력 시 반환 정확히 2개, 첫 원소 url이 urljoin 결과 `https://www.watch4beauty.com/api/media/20220227-max.zip`이고 type=`photo`, basename=`20220227-max.zip`, 둘째 원소 url은 MP4_2160 그대로, type=`video`, basename=`2160.mp4`
- `test_pick_downloads_prefers_2160_over_1080` — 1080과 2160이 모두 있으면 mp4 pick은 1개뿐이고 basename=`2160.mp4`
- `test_pick_downloads_falls_back_to_1080` — 1080만 있으면 basename=`1080.mp4`
- `test_pick_downloads_video_only_set` — mp4만 있으면 type은 video뿐
- `test_pick_downloads_photo_only_set` — zip만 있으면 type은 photo뿐
- `test_pick_downloads_empty` — 빈 links → 빈 리스트
- `test_extract_model_name_verbatim` — starring 앵커(href=`/models/christy-white`, 텍스트 CHRISTY WHITE)와 footer 노이즈 앵커(href=`/models`, 텍스트 Popular models)가 함께 있어도 반환은 `CHRISTY WHITE`; 앵커 부재 페이지에서는 None
- `test_extract_model_content_refs_updates_only` — grid-item 4종(updates 2, stories 1, non-grid noise 1) fixture에서 stories와 non-grid 제외, updates 2건만 반환, url은 urljoin 절대경로
- `test_extract_model_content_refs_excludes_popular` — `/updates/popular` 단독 fixture → 빈 리스트
- `test_extract_model_content_refs_dedupes` — 동일 href grid-item 2개 → 1건

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_w4b.py -v` → FAIL (module 없음)

- [ ] **Step 3: 구현** — src/vesper_x/extractors/w4b.py

- 모듈 docstring: `W4B 크롤러/파서 — 다운로드 링크는 Download 클릭 후 JS가 채운다 (2026-09-27 실측). 상수 갱신 방식은 hegre.py 패턴.`
- 상수 URLS/SELECTORS — 위 Interfaces 값 그대로
- `_UPDATES_PATH_RE = re.compile(r"/updates/[\w-]+/?")`
- `W4BParser.pick_downloads`: href에 `.zip` 포함 → photo pick (url은 urljoin, basename은 경로 마지막 세그먼트). href가 `.mp4`로 끝나는 것 → 경로에서 정규식 `/(\d{3,4})\.mp4` 해상도 추출, 2160 우선 없으면 최대 1개만 video pick (url은 그대로, basename은 마지막 세그먼트). 반환 순서 [zip, mp4]
- `W4BParser.extract_model_name`: selector `a[href*='/models/']` 첫 앵커 텍스트 strip — `/models`(슬래시 없는 footer 노이즈)는 substring 미매칭
- `W4BCrawler.extract_model_content_refs` (staticmethod): `a.grid-item`의 href 중 path fullmatch + slug가 popular 아님 → `{"url": urljoin, "title": a.get("title")}`, seen-set dedupe — hegre의 _content_ref 패턴과 동일

- [ ] **Step 4: 테스트 통과** — `uv run pytest tests/test_w4b.py -v` → PASS

- [ ] **Step 5: Commit** — `git add src/vesper_x/extractors/w4b.py tests/test_w4b.py` 후 `feat: W4B 파서 순수 로직 - pick_downloads/extract_model_name/extract_model_content_refs`

---

### Task 2: W4BCrawler — 쿠키 헤더·credentials·launch 옵션

**Files:**
- Modify: `src/vesper_x/extractors/w4b.py` (W4BCrawler 추가)
- Test: `tests/test_w4b.py` (추가)

**Interfaces (Produces):**
- `W4B_PROFILE_DIR = Path.home() / ".config" / "url-resolver" / "w4b_profile"`
- `W4BCrawler.build_cookie_header(cookies: list[dict]) -> str` (staticmethod) — playwright cookies에서 session과 cf_clearance만 골라 `k=v; k=v` 형식으로. 해당 이름 부재 시 그 이름은 생략, 입력 빈 리스트 → 빈 문자열
- `W4BCrawler(config: AppConfig)` — attr: `config`, `parser`, `_cookie_header: Optional[str]`, `_user_agent: Optional[str]`
- `W4BCrawler.ensure_credentials() -> CredentialConfig` — `config.credentials.get("w4b")`, 부재 시 ValueError 메시지에 `credentials.w4b` 포함
- `W4BCrawler._launch_kwargs() -> dict` — `channel="chrome"`, `headless=False`, `config.proxy` 존재 시 `proxy={"server": ...}`
- Playwright 경로(아래 브라우저 메서드들은 미테스트, hegre.py 패턴):
  - `async login() -> bool` — URLS.login 오픈, SELECTORS.login_user/login_pass fill, `form button[type=submit]` click, 네비게이션 대기. 클릭 후에도 URL에 `/login`이 남아 있으면 `page.evaluate`로 `document.querySelector('form').requestSubmit()` 재시도 후 재확인. 반환: 성공 시 True
  - `async fetch(url: str, scrolls: int = 0) -> str` — persistent context 매 launch(ouo/hegre 패턴), goto domcontentloaded, scrolls 만큼 바닥 스크롤 후 1초 대기 반복, 쿠키와 `navigator.userAgent`를 각각 `_cookie_header`/`_user_agent`에 stash, page.content() 반환
  - `async collect(model_slug: str | None = None) -> list[dict]` — model_slug 있으면 fetch(URLS.model.format(slug)) 후 extract_model_content_refs, 없으면 fetch(URLS.updates, scrolls=5) 후 동일 추출
  - `async resolve(url: str) -> list[DownloadMetadata]` — 세션 오픈 → url goto → Download 트리거 클릭(page.get_by_role(link, name=Download, exact=True).first) → selector `a.button[href*='.zip'], a.button[href*='.mp4']` 대기(타임아웃 10초, TimeoutError면 links 빈 리스트로 계속) → 쿠키/UA stash → page.content()로 html 확보 → extract_model_name + pick_downloads → metadata 생성. filename은 `{모델명 or Unknown}/{URL 경로 마지막 세그먼트}/{pick basename}` — 모델명 정제는 hegre와 동일한 `re.sub(r"[^\w\- .()]+", "_", name)`. DownloadMetadata 필드: direct_url=pick url, referer=url, user_agent=stash한 UA, filename 위 조합, source_page=url, models=[모델명] or [], file_page_url=url, cookies=stash한 쿠키 헤더

- [ ] **Step 1: 실패 테스트** — tests/test_w4b.py에 추가:

- `test_build_cookie_header_filters_and_formats` — playwright cookies 예시 `[{"name": "other", "value": "1"}, {"name": "session", "value": "abc"}, {"name": "cf_clearance", "value": "xyz"}]` 입력 → 반환 `session=abc; cf_clearance=xyz`. 빈 리스트 → 빈 문자열
- `test_ensure_credentials_missing_raises` — AppConfig() 기본(credential 없음)으로 W4BCrawler 생성, pytest.raises(ValueError, match="credentials.w4b")
- `test_launch_kwargs_uses_chrome_channel_and_proxy` — AppConfig(proxy="http://x:1")로 생성, kwargs의 channel=`chrome`, headless False, proxy server 값 확인

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_w4b.py -v` → 신규 3건 FAIL
- [ ] **Step 3: 구현** — Interfaces에 명시된 대로. 브라우저 메서드는 hegre.py의 대응 메서드와 동일 구조(매 launch persistent context, finally close)
- [ ] **Step 4: 테스트 통과** — `uv run pytest tests/test_w4b.py -v` → PASS
- [ ] **Step 5: Commit** — `feat: W4BCrawler - 쿠키 헤더 빌더/credentials/launch 옵션/collect-resolve 골격`

---

### Task 3: HegreCrawler.resolve 래퍼

**Files:**
- Modify: `src/vesper_x/extractors/hegre.py` (HegreCrawler에 메서드 추가)
- Test: `tests/test_hegre.py` (추가)

**Interfaces (Produces):**
- `HegreCrawler.resolve(url: str) -> list[DownloadMetadata]` — 본문은 `html = await self.fetch(url)` 후 `return self.resolve_content(html, url)`. 기존 fetch/resolve_content/collect는 무변경

- [ ] **Step 1: 실패 테스트** — tests/test_hegre.py에 추가. asyncio strict이므로 `@pytest.mark.asyncio` 데코레이터 필수:

  - `test_resolve_wrapper_fetches_and_parses` — crawler 인스턴스의 fetch를 monkeypatch(fake async 함수가 VIDEO_PAGE 반환)하고, `await crawler.resolve("https://hegre.com/films/massage-x")` 결과 metas[0].direct_url이 VIDEO_PAGE의 4K URL과 동일함을 단언
  - 기존 FakeCrawler(CLI 통합 더블)에 `async def resolve(self, url)` 추가 — fetch+resolve_content 조합. 이 더블은 Task 4의 루프 테스트에서 resolve(url) 인터페이스로 호출된다

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_hegre.py -v` → 신규 테스트 FAIL (AttributeError: resolve)
- [ ] **Step 3: 구현** — 3줄 래퍼: fetch 후 resolve_content 반환
- [ ] **Step 4: 테스트 통과** — `uv run pytest tests/test_hegre.py -v` → PASS
- [ ] **Step 5: Commit** — `feat: HegreCrawler.resolve 래퍼 - 프리미엄 공용 resolve(url) 인터페이스 충족`

---

### Task 4: run_premium_crawl 일반화

**Files:**
- Modify: `src/vesper_x/cli.py` — run_hegre_crawl을 run_premium_crawl로 교체
- Modify: `tests/test_hegre.py` — run_hegre_crawl 테스트 7건 갱신
- Import 추가: cli.py 상단에 `from vesper_x.extractors.w4b import W4BCrawler`

**Interfaces (Produces):**
- `PREMIUM_SITES = {"hegre": (HegreCrawler, "H"), "w4b": (W4BCrawler, "W4B")}` — cli.py 모듈 레벨. 값은 (crawler 클래스, premium.db site 코드)
- `run_premium_crawl(site: str, url=None, model=None, new_only=False, extract_only=False, limit=0, config=None, db=None, crawler=None) -> None` — 기존 run_hegre_crawl 본체에서 달라지는 것 3가지뿐: crawler 생성 `PREMIUM_SITES[site][0](config)`, creds 게이트 `config.credentials.get(site)`(메시지에 `credentials.{site}`), site 코드 전부 `PREMIUM_SITES[site][1]`(upsert_model/upsert_gallery/checkpoint). 루프 내 resolve 호출은 `run_async(crawler.resolve(ref["url"]))` 로 변경

- [ ] **Step 1: 실패 테스트** — 기존 run_hegre_crawl 테스트 7건을 run_premium_crawl(site="hegre", ...) call-shape으로 갱신(FakeCrawler는 Task 3에서 resolve(url)를 이미 갖는다):

  - dispatch+기록 테스트 — monkeypatch Aria2Dispatcher, dispatch 후 db.is_downloaded True, downloads 행 direct_url 단언
  - `test_run_premium_crawl_extract_only_does_not_record` — extract_only=True에서 dispatch 없음, db 미오염 단언
  - skip 테스트, no-links 계속 테스트, checkpoint 테스트(키 "H"), creds 부재 Exit 테스트, 1건 실패 연속 테스트 — call-shape만 변경

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_hegre.py -v` → FAIL (run_premium_crawl 미정의)
- [ ] **Step 3: 구현** — Step 시그니처대로 run_hegre_crawl을 교체. 구조는 기존 루프 유지
- [ ] **Step 4: 테스트 통과** — `uv run pytest tests/test_hegre.py -v` → PASS
- [ ] **Step 5: Commit** — `feat: run_premium_crawl 일반화 - site 파라미터로 crawler/site 코드/creds 키 주입`

---

### Task 5: w4b CLI 연결 + 설정 등록

**Files:**
- Modify: `src/vesper_x/cli.py` (crawl 분기, _select_crawler registry, --site help)
- Modify: `config/default.toml` + `src/vesper_x/config.py` (DEFAULT_SITES)
- Test: `tests/test_w4b.py` (추가)

**Interfaces (Produces):**
- `_is_w4b_url(url: str) -> bool` — hostname이 watch4beauty.com이거나 그 서브도메인. hegre 판정과 동일 hostname 기준
- crawl 분기: `site == "w4b" or (url and _is_w4b_url(url))` → run_premium_crawl(site="w4b", url=url, model=model, new_only=new, extract_only=extract_only, limit=limit)
- `_select_crawler` registry에 `"w4b": lambda: W4BCrawler(config)` 추가
- 설정 이중 등록: config/default.toml [sites]와 config.py의 DEFAULT_SITES 양쪽에 `watch4beauty.com` → crawler w4b, subdir W4B (현재 3개 도메인이 양쪽에 미러링되는 관행 유지)
- `--site` 옵션 help를 `사이트 명시 선택 (hegre, w4b)`로 갱신

- [ ] **Step 1: 실패 테스트** — tests/test_w4b.py에 추가:

  - `test_is_w4b_url_hostname_based` — 도메인 순수 대문자, www 서브도메인은 True. `https://watch4beauty.com.evil.example/x`와 쿼리 문자열 위장은 False
  - `test_select_crawler_registry_has_w4b` — _select_crawler가 watch4beauty.com URL에 W4BCrawler 반환
  - `test_default_sites_contain_w4b` — AppConfig().sites에 watch4beauty.com 키 존재, subdir이 W4B

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_w4b.py -v` → 신규 3건 FAIL
- [ ] **Step 3: 구현** — 위 Interfaces 대로 cli.py/config.py/config/default.toml 수정
- [ ] **Step 4: 테스트 통과** — `uv run pytest tests/test_w4b.py -v` → PASS
- [ ] **Step 5: Commit** — `feat: w4b CLI 연결 - site 옵션/hostname 분기/사이트 설정 등록`

---

### Task 6: premium.db site 컬럼 + models 출력

**Files:**
- Modify: `src/vesper_x/premium_db.py` (holding_by_model)
- Modify: `src/vesper_x/cli.py` (models 커맨드 출력)
- Test: `tests/test_w4b.py` (추가)

**Interfaces (Produces):**
- `PremiumDB.holding_by_model(name_like: str) -> list[dict]` — 반환 dict에 site 키 추가(name, site, videos, photos, last_at), SELECT에 m.site 추가 및 GROUP BY m.name, m.site
- models 커맨드: premium 보유 라벨을 `premium 보유`로, 각 행에 site 표시 추가 (예: `Christy White  W4B  영상 3 / 사진 12`)

- [ ] **Step 1: 실패 테스트** — tests/test_w4b.py에 추가:

  - `test_holding_by_model_includes_site` — tmp_path PremiumDB에 모델 Christy White site W4B로 upsert_model+upsert_gallery+record_download 후 holding_by_model("christy") 결과[0]의 site이 W4B, videos/photos 카운트 단언
  - `test_holding_by_model_hegre_regression` — site H로 기록된 데이터가 기존과 같이 집계되는지 단언

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_w4b.py -v` → 신규 2건 FAIL
- [ ] **Step 3: 구현** — premium_db.py holding_by_model SELECT/GROUP BY 변경 + cli.py models 출력 라벨과 행 포맷 변경
- [ ] **Step 4: 테스트 통과** — `uv run pytest` → 전체 PASS (회귀 포함)
- [ ] **Step 5: Commit** — `feat: premium.db 보유 조회에 site 컬럼 추가 - W4B/H 구분 표시`

---

## 실행 참고

- 전체 완료 후 `uv run pytest` 전수 통과가 완료 조건이다.
- E2E(실접속)는 본 계획 밖 — 구현 완료 후 사용자 승인을 받아 `uv run vesper crawl --site w4b --model christy-white --extract-only` 실행으로 검증한다.
- Playwright 브라우저 경로의 실측 보강 포인트(스펙 7장 오픈 아이템): updates 무한스크롤 동작, Download 트리거 동작, aria2에 cf_clearance 필요성.
