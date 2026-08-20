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
- `src/vesper_x/dispatchers/aria2.py` — aria2p RPC 전송
- `src/vesper_x/models.py` — `DownloadMetadata` 전송 단위
- `src/vesper_x/config.py` — `~/.config/url-resolver/config.toml` 로드

Pipeline: CLI → Crawler → Parser → Bypasser(ouo) → Resolver(mediafire) → DownloadMetadata → Dispatcher(aria2)

## Conventions

- 새 host 지원: `extractors/`에 Parser/Resolver 추가 + `cli.py:resolve_post`에 domain 분기
- Test는 실 network 없이 mock으로 작성 (전 test suite가 mock 기반)
- Python >= 3.12 표준 library 우선

## Gotchas

- pytest `asyncio_mode = "strict"` — async test에 `@pytest.mark.asyncio` 필수
- `OuoBypasser.resolve()`는 async — sync context에서는 `asyncio.run()` 호출
- aria2 host는 `ws://`로 설정해도 `Aria2Dispatcher`가 http(s)로 변환한다
