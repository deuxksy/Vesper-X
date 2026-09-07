"""models.db 접근 계층 — 캐노니컬 모델 사전 (vesper models 조회 + 메타데이터 통일의 공통 기반).

동기화 키 설계:
  models.id    - DB 내부 조인 전용
  models.slug  - 외부 동기화 키 (폴더명/사이트 태그와 연결되는 안정 식별자)
  canonical_name - 표시명
DB 파일이 없으면 조용히 비활성(모든 조회 None) - 기존 파이프라인 동작 유지.
"""
import re
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "models.db"


# 일반명사 토큰은 모델 매칭에 쓰지 않는다 - "ZinieQ (ジニCosplayer)"와
# "Unknown Cosplayer"가 cosplayer 토큰으로 잘못 이어지는 사고 방지
STOP_TOKENS = {"cosplayer", "cosplay", "coser", "photos", "photo", "video", "hd"}


def tokens(name: str) -> tuple[set, set]:
    """로마 토큰(3자+, 일반명사 제외)과 CJK 토큰(2자+)으로 분해."""
    return (set(re.findall(r"[a-z0-9_.]{3,}", name.lower())) - STOP_TOKENS,
            set(re.findall(r"[一-鿿぀-ヿ가-힯]{2,}", name)))


def flat(name: str) -> str:
    """공백/구둣점 제거한 소문자 전체 문자열 - 공백 변형 매칭용."""
    return re.sub(r"[^a-z0-9一-鿿぀-ヿ가-힯]", "", name.lower())


def _token_match(a: str, b: str) -> bool:
    (ar, ac), (br, bc) = tokens(a), tokens(b)
    if (ac and bc and (ac & bc)) or (ar and br and (ar & br)):
        return True
    fa, fb = flat(a), flat(b)
    return len(fa) >= 4 and len(fb) >= 4 and (fa in fb or fb in fa)


class ModelRegistry:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._variants: Optional[list[tuple[str, int]]] = None  # (variant, model_id) 캐시

    def _connect(self) -> Optional[sqlite3.Connection]:
        if not self.db_path.exists():
            return None
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
        return self._conn

    def _load_variants(self) -> list[tuple[str, int]]:
        if self._variants is None:
            conn = self._connect()
            rows = conn.execute(
                "SELECT mn.variant, mn.model_id FROM model_names mn "
                "JOIN models m ON m.id = mn.model_id WHERE m.is_aggregator = 0"
            ).fetchall() if conn else []
            self._variants = rows
        return self._variants

    def _resolve_model_id(self, query: str) -> Optional[int]:
        conn = self._connect()
        if conn is None:
            return None
        row = conn.execute(
            "SELECT model_id FROM model_names WHERE variant = ? LIMIT 1", (query,)).fetchone()
        if row:
            return row[0]
        row = conn.execute(
            "SELECT id FROM models WHERE slug = ? LIMIT 1", (query.lower(),)).fetchone()
        if row:
            return row[0]
        for variant, model_id in self._load_variants():
            if _token_match(query, variant):
                return model_id
        return None

    def canonicalize(self, name: str) -> Optional[str]:
        """변형 이름 → 캐노니컬 이름. 미매칭/DB 없음 → None."""
        conn = self._connect()
        if conn is None:
            return None
        model_id = self._resolve_model_id(name)
        if model_id is None:
            return None
        row = conn.execute(
            "SELECT canonical_name FROM models WHERE id = ?", (model_id,)).fetchone()
        return row[0] if row else None

    def lookup(self, query: str) -> Optional[dict]:
        """조회용 종합 정보: 캐노니컬/slug/사이트 카운트/misskon 태그 URL/heritage 보유."""
        conn = self._connect()
        if conn is None:
            return None
        model_id = self._resolve_model_id(query)
        if model_id is None:
            return None

        canonical, slug = conn.execute(
            "SELECT canonical_name, COALESCE(slug, '') FROM models WHERE id = ?",
            (model_id,)).fetchone()

        snapshot = {"misskon": 0, "cosplaytele": 0}
        misskon_slug = None
        for site_id, cnt, slug_url in conn.execute(
                "SELECT site_id, post_count, slug_url FROM model_names WHERE model_id = ?",
                (model_id,)):
            if site_id == 1:
                snapshot["misskon"] += cnt
                misskon_slug = slug_url or misskon_slug
            elif site_id == 2:
                snapshot["cosplaytele"] += cnt

        archive = {"albums": 0, "size_kb": 0, "region": None, "folders": []}
        for region, folder, albums, size_kb in conn.execute(
                "SELECT region, folder_name, album_count, size_kb FROM archive_artists WHERE model_id = ?",
                (model_id,)):
            archive["albums"] += albums
            archive["size_kb"] += size_kb
            archive["region"] = region if archive["region"] is None else f"{archive['region']},{region}"
            archive["folders"].append(folder)

        return {
            "canonical": canonical,
            "slug": slug,
            "misskon_slug": misskon_slug,
            "snapshot": snapshot,
            "archive": archive,
        }
