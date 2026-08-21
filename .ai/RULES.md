# Vesper-X Common Rules

모든 AI agent 공통 rule. Vendor 별 rule은 각 root file에 둔다.

## Commands

| 작업 | Command |
| :--- | :--- |
| 의존성 설치 | `uv sync` |
| Test | `uv run pytest` |
| CLI 실행 | `uv run vesper parse "<url>" --extract-only` |
| Browser 설치 | `uv run playwright install chromium` — ouo 실우회 시 1회 |

Lint 도구는 미설정. 도입 시 이 표를 갱신한다.

## Architecture

- `src/vesper_x/cli.py` — Typer entry. parse / crawl / clip / batch
- `src/vesper_x/extractors/` — Parser(misskon, cosplaytele) · Crawler(crawler) · Bypasser(ouo) · Resolver(mediafire)
- `src/vesper_x/fetchers.py` — `BrowserFetcher` (Chrome ECH page fetch, `crawl`이 사용)
- `src/vesper_x/dispatchers/aria2.py` — aria2p RPC 전송
- `src/vesper_x/models.py` — `DownloadMetadata` 전송 단위
- `src/vesper_x/config.py` — `~/.config/url-resolver/config.toml` 로드 (`[network] proxy` 선택)

Pipeline: CLI → BrowserFetcher(Chrome ECH) → Crawler → Parser → Bypasser(ouo) → Resolver(mediafire) → DownloadMetadata → Dispatcher(aria2)

## Conventions

- 새 host 지원: `extractors/`에 Parser/Resolver 추가 + `cli.py:resolve_post`에 domain 분기
- Test는 실 network 없이 mock으로 작성 (전 test suite가 mock 기반)
- Python >= 3.12 표준 library 우선

## Gotchas

- pytest `asyncio_mode = "strict"` — async test에 `@pytest.mark.asyncio` 필수
- `OuoBypasser.resolve()`는 async — sync context에서는 `cli.run_async()` 호출. Playwright sync 세션(`BrowserFetcher` with 블록) 안에서는 main thread에 running loop가 남아 `asyncio.run()` 직접 호출 시 RuntimeError
- misskon.com은 한국 이중 차단(ISP SNI + Cloudflare 451) — httpx/번들 Chromium 모두 실패. `BrowserFetcher`는 `channel="chrome"`(실제 Chrome) + ECH + secure DoH launch args 필수
- ouo.io는 2단계 우회다: "I'M A HUMAN" 클릭 → `/go/` 페이지 "Get Link" 버튼(countdown 후 `disabled` 해제) 클릭 → 목적지. 버튼 활성화 대기 필수
- ouo bypass는 간헐 실패 시 입력 URL을 그대로 반환한다 — `resolve_post`가 결과에 ouo 잔존 시 재시도 후 skip
- aria2 host는 `ws://`로 설정해도 `Aria2Dispatcher`가 http(s)로 변환한다
- aria2 dispatch는 `[aria2] download_dir`(daemon-side 경로, `/downloads` = host `/mnt/data2/torrent/downloads/aria`) 아래 사이트 서브디렉토리(`misskon/`, `cosplaytele/`)로 전송한다 — heritage `extract_organize.sh`가 이 디렉토리로 압축 비번을 분기함 (misskon: `misskon.com`→`mrcong.com`, cosplaytele: `cosplaytele`)
