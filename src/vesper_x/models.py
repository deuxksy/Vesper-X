from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DownloadMetadata:
    direct_url: str
    referer: str
    user_agent: str
    filename: Optional[str]
    source_page: str
    tags: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    cookies: Optional[str] = None
    # 파일호스트 페이지 URL(불변 식별자: mediafire.com/file/<id>) -
    # direct_url은 만료되는 CDN 서명이라 dispatch_log는 이쪽을 기록한다
    file_page_url: Optional[str] = None
