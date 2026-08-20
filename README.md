# Vesper-X

*Direct Link Extractor & Shortener Bypass Automation Suite*

**Vesper-X**는 코스프레/화보 및 웹 미디어 게시글에서 단축 링크와 광고를 우회하고, 파일 호스트(MediaFire 등)의 직링크를 추출하여 다운로더로 연결하는 자동화 도구입니다.

---

## 🚀 주요 기능

- **Post Parsing**: MissKon, CosplayTele 게시글에서 호스트 다운로드 링크 자동 추출
- **Shortener Bypass**: `ouo.io`, `ouo.press` 등 단축링크 Playwright 기반 브라우저 우회
- **Direct Link Extraction**: MediaFire, Mega, Gofile 등 호스팅 사이트 직링크 변환
- **Aria2 Dispatch**: aria2 RPC 연동 전송

---

## 💻 사용법

```bash
# 단일 게시글 파싱 및 직링크 추출
uv run vesper parse "https://misskon.com/..."

# 카테고리/태그 순차 크롤링
uv run vesper crawl "https://cosplaytele.com/category/byoru/" --pages 2 --extract-only

# 클립보드 URL 파싱
uv run vesper clip --extract-only
```
