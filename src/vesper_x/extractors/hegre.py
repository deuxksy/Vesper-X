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
