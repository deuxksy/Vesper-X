# 🗺️ Vesper-X Roadmap

*Direct Link Extractor & Shortener Bypass Automation Suite*

본 문서는 **Vesper-X**의 우회 능력 강화, 파일 호스트 지원 확장, 성능 최적화 등을 위한 중장기 로드맵입니다.

---

## 🎯 핵심 장기 과제 (Long-Term Goals)

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Playwright Stealth & 봇 탐지 무력화 (Anti-Bot Engine)                     │
│ 2. 단축링크 바이패스 엔진 고도화 (Shortener Bypass Expansion)                 │
│ 3. DNS / SNI / ISP 차단 회피 고도화 (Anti-Censorship & Networking)          │
│ 4. 주요 파일호스트 직링크 리졸버 확장 (Host Resolvers Expansion)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 1. ⚡ Playwright Stealth 및 봇 탐지 무력화 (Anti-Bot & Fast-Bypass)
- [ ] **Stealth 엔진 도입**: `playwright-stealth` 등을 연동하여 `navigator.webdriver` 흔적을 제거, Cloudflare Turnstile / 봇 탐지를 사람 브라우저처럼 자연스럽게 통과
- [ ] **리소스 차단 최적화 (Fast-Bypass)**: 불필요한 광고 팝업, 트래커, 폰트, 미디어 리소스를 네트워크 레벨(`route.abort()`)에서 차단하여 단축링크 우회 속도 극대화(3~5배 단축)
- [ ] **헤드리스 탐지 우회**: Cloudflare 챌린지 및 캡차 발생 시 백그라운드 자동 해결 파이프라인 구축

---

### 2. 🔗 단축링크 바이패스 엔진 고도화 (Shortener Bypass Engine)
- [ ] **기존 `ouo.io` / `ouo.press` 안정화**: Cloudflare 챌린지 및 세션 토큰 파싱 에러 회복 로직 강화
- [ ] **신규 단축링크 패턴 확장**:
  - `shrinkme.io`, `exe.io`
  - `linkvertise.com`
  - `shorte.st`, `cuty.io`
- [ ] **단축링크 자동 감지 라우터**: 미확인 단축링크 유입 시 패턴 매칭을 통해 해당 우회 모듈로 자동 분기

---

### 3. 🌐 DNS / SNI / ISP 차단 회피 고도화 (Anti-Censorship & Networking)
- [ ] **Secure DoH 다중화 및 자동 폴백(Fallback)**:
  - Google DNS (`https://dns.google/dns-query`)
  - Cloudflare DNS (`https://cloudflare-dns.com/dns-query`)
  - Quad9 DNS (`https://dns.quad9.net/dns-query`)
- [ ] **프록시(Proxy) 체이닝 및 SOCKS5 지원**:
  - 전역/사이트별 SOCKS5/HTTP 프록시 설정 지원으로 VPN 없이도 특정 국가/지역 제한 사이트 파싱 가능화
- [ ] **Chrome ECH (Encrypted Client Hello) 프로파일 최적화**: TLS 핸드셰이크 차단 원천 무력화

---

### 4. 📦 주요 파일호스트 직링크 리졸버 확장 (Host Resolvers Expansion)
- [ ] **현재 지원**: `MediaFire` (직링크 변환), `Gofile`, `Mega` (경로 전달)
- [ ] **신규 파일호스트 직링크 추출기 추가**:
  - `Pixeldrain` (직접 다운로드 스트림 링크 변환)
  - `Workupload` (직링크 추출)
  - `Bunkr` / `CyberDrop` (미디어 직링크 파서)
  - `Rapidgator` / `Katfile` (무료 다운로드 타이머/링크 파서)
- [ ] **파일호스트 Referer / Cookie 전달 최적화**: Hotlink 방지 파일호스트에 대한 aria2 헤더 전달 체계 강화

---

## 📈 진행 단계 (Phases)

| Phase | 목표 | 중점 작업 | 상태 |
|---|---|---|---|
| **Phase 1** | 코어 파이프라인 구축 | MissKon/CosplayTele 크롤러, ouo 우회, MediaFire 추출, aria2 연동 | ✅ 완료 |
| **Phase 2** | 스텔스 & 차단 회피 강화 | Playwright Stealth, DoH 다중화, Fast-Bypass 리소스 필터링 | ⏳ 대기 |
| **Phase 3** | 단축링크 & 호스트 확장 | Shrinkme/Linkvertise 바이패스, Pixeldrain/Workupload 리졸버 추가 | ⏳ 대기 |
| **Phase 4** | 안정성 & 프록시 고도화 | SOCKS5 프록시 풀 연동, 자동 재시도 및 실패 복구 파이프라인 | ⏳ 대기 |
