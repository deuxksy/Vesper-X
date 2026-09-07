"""ModelRegistry — models.db 이름 사전 접근 계층 (A/B의 공통 기반)."""
import sqlite3
from pathlib import Path

import pytest

from vesper_x.models_db import ModelRegistry

SCHEMA = """
CREATE TABLE sites (id INTEGER PRIMARY KEY, domain TEXT UNIQUE, census_date TEXT, note TEXT);
CREATE TABLE models (id INTEGER PRIMARY KEY, canonical_name TEXT UNIQUE, slug TEXT UNIQUE, grade TEXT, is_aggregator INTEGER DEFAULT 0);
CREATE TABLE model_names (site_id INT, model_id INT, variant TEXT, post_count INT, slug_url TEXT,
    PRIMARY KEY (site_id, variant));
CREATE TABLE archive_artists (model_id INT, region TEXT, folder_name TEXT, album_count INT, size_kb INT);
"""


@pytest.fixture
def db_path(tmp_path) -> Path:
    db = sqlite3.connect(tmp_path / "models.db")
    db.executescript(SCHEMA)
    db.execute("INSERT INTO sites VALUES (1, 'misskon.com', '2026-09-07', '')")
    db.execute("INSERT INTO sites VALUES (2, 'cosplaytele.com', '2026-09-07', '')")
    # 캐노니컬 Byoru: misskon 61 + cosplaytele 변형 2개(196+24) + heritage 보유
    db.execute("INSERT INTO models VALUES (10, 'Byoru', 'byoru', NULL, 0)")
    db.execute("INSERT INTO model_names VALUES (1, 10, 'Byoru', 61, 'https://misskon.com/tag/byoru/')")
    db.execute("INSERT INTO model_names VALUES (2, 10, 'Byoru (ビョル)', 196, NULL)")
    db.execute("INSERT INTO model_names VALUES (2, 10, 'Byoru', 24, NULL)")
    db.execute("INSERT INTO archive_artists VALUES (10, 'SEA', 'Byoru (ビョル)', 57, 113000)")
    # 캐노니컬 日奈娇: roman 변형 포함
    db.execute("INSERT INTO models VALUES (11, '日奈娇', 'rinaijiao', NULL, 0)")
    db.execute("INSERT INTO model_names VALUES (1, 11, '日奈娇', 49, 'https://misskon.com/tag/rinaijiao/')")
    db.execute("INSERT INTO model_names VALUES (2, 11, 'Rinaijiao-(日奈娇)', 35, NULL)")
    db.commit()
    db.close()
    return tmp_path / "models.db"


def test_canonicalize_exact_variant(db_path):
    reg = ModelRegistry(db_path)
    assert reg.canonicalize("Byoru") == "Byoru"
    assert reg.canonicalize("Byoru (ビョル)") == "Byoru"


def test_canonicalize_fuzzy_roman_token(db_path):
    """'Umeko J' 같은 공백 변형도 토큰 매칭으로 캐노니컬을 찾는다."""
    reg = ModelRegistry(db_path)
    # DB에는 日奈娇 CJK + Rinaijiao-(日奈娇) 혼합 변형만 있다
    assert reg.canonicalize("Rinaijiao") == "日奈娇"


def test_canonicalize_unknown_returns_none(db_path):
    reg = ModelRegistry(db_path)
    assert reg.canonicalize("존재하지않는모델") is None


def test_canonicalize_empty_registry_returns_none(tmp_path):
    """DB 파일 자체가 없으면 조용히 비활성 - 기존 동작 fallback."""
    reg = ModelRegistry(tmp_path / "nope.db")
    assert reg.canonicalize("Byoru") is None


def test_lookup_returns_counts_and_slug_and_archive(db_path):
    reg = ModelRegistry(db_path)
    info = reg.lookup("byoru")
    assert info["canonical"] == "Byoru"
    assert info["slug"] == "byoru"
    assert info["misskon_slug"] == "https://misskon.com/tag/byoru/"
    assert info["snapshot"]["misskon"] == 61
    assert info["snapshot"]["cosplaytele"] == 220  # 변형 합산
    assert info["archive"]["albums"] == 57
    assert info["archive"]["region"] == "SEA"


def test_lookup_by_slug_finds_cjk_canonical(db_path):
    """slug rinaijiao로 日奈娇 캐노니컬을 찾는다 - 동기화 키 경로."""
    reg = ModelRegistry(db_path)
    info = reg.lookup("rinaijiao")
    assert info["canonical"] == "日奈娇"


def test_lookup_unknown_model_returns_none(db_path):
    reg = ModelRegistry(db_path)
    assert reg.lookup("no-such-model") is None


def test_generic_words_do_not_bridge_models(db_path):
    """"cosplayer" 같은 일반 단어가 다른 모델과 매칭을 만들면 안 된다."""
    db = sqlite3.connect(db_path)
    # ZinieQ 변형 추가: "ZinieQ (ジニCosplayer)" - roman 토큰에 cosplayer 포함
    db.execute("INSERT INTO models VALUES (12, 'ZinieQ', 'zinieq', NULL, 0)")
    db.execute("INSERT INTO model_names VALUES (2, 12, 'ZinieQ (ジニCosplayer)', 80, NULL)")
    db.commit()
    db.close()
    reg = ModelRegistry(db_path)
    assert reg.canonicalize("ZinieQ (ジニCosplayer)") == "ZinieQ"
    assert reg.canonicalize("Unknown Cosplayer") is None


def test_dispatch_log_records_and_queries(db_path):
    """dispatch_log: URL 등록 후 is_dispatched True, 미등록 False."""
    reg = ModelRegistry(db_path)
    assert reg.is_dispatched("https://misskon.com/post-1/") is False
    reg.record_dispatch("https://misskon.com/post-1/", note="machi set")
    assert reg.is_dispatched("https://misskon.com/post-1/") is True


def test_dispatch_log_without_db_is_noop(tmp_path):
    reg = ModelRegistry(tmp_path / "nope.db")
    assert reg.is_dispatched("https://misskon.com/x/") is False
    reg.record_dispatch("https://misskon.com/x/")  # 예외 없이 no-op


def test_set_grade_and_lookup(db_path):
    reg = ModelRegistry(db_path)
    reg.set_grade("byoru", "A")
    assert reg.lookup("byoru")["grade"] == "A"


def test_set_grade_without_db_noop(tmp_path):
    reg = ModelRegistry(tmp_path / "nope.db")
    reg.set_grade("byoru", "A")  # 예외 없이


def test_dispatch_log_records_model_id(db_path):
    reg = ModelRegistry(db_path)
    reg.set_grade("byoru", "A")
    reg.record_dispatch("https://misskon.com/post-x/", note="set.rar",
                        direct_url="https://www.mediafire.com/file/abc",
                        model_name="Byoru")
    row = reg._connect().execute(
        "SELECT model_id FROM dispatch_log WHERE url='https://misskon.com/post-x/'").fetchone()
    expected = reg._connect().execute(
        "SELECT id FROM models WHERE canonical_name='Byoru'").fetchone()[0]
    assert row[0] == expected
