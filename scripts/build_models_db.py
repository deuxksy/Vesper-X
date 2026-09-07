#!/usr/bin/env python3
"""data/*.tsv 전수조사 스냅샷에서 data/models.db를 재생성한다.

스키마: sites / models(캐노니컬) / model_names(사이트별 변형) + v_model_summary 뷰.
변형 매칭: 로마·CJK 토큰 교집합 + 공백 제거 flat containment.
"""
import re
import sqlite3
from pathlib import Path

from vesper_x.models_db import tokens, flat

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

NOISE = {'ai art', 'unknown cosplayer', 'xiuren秀人网', 'pure media', 'fantasy factory',
         'djawa photo', 'photochips', 'artgravia', 'sweetbox', 'leehee express',
         'moon night snap', 'bimilstory', 'atfm', 'heroine k'}

# 간체/번체, roman-only/CJK-only 등 토큰 매칭이 못 묶는 알려진 쌍:
# (misskon 캐노니컬, cosplaytele 변형들)
MANUAL_MATCHES = {
    "白银81": ("白銀81 (81silver811)",),
    "日奈娇": ("Rinaijiao", "Rinaijiao-(日奈娇)"),
}


def load():
    mk_rows = []
    for line in open(DATA_DIR / 'misskon_census_full.tsv'):
        name, cnt, slug = line.rstrip('\n').split('\t')
        mk_rows.append((name, int(cnt), slug))
    ct_rows = []
    for line in open(DATA_DIR / 'cosplaytele_census_full.tsv'):
        name, cnt = line.rstrip('\n').split('\t')
        ct_rows.append((name, int(cnt)))
    return mk_rows, ct_rows


def build():
    mk_rows, ct_rows = load()
    db = sqlite3.connect(DATA_DIR / 'models.db')
    db.executescript("""
DROP VIEW IF EXISTS v_model_summary;
DROP TABLE IF EXISTS archive_artists;
DROP TABLE IF EXISTS model_names;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS sites;
CREATE TABLE sites (id INTEGER PRIMARY KEY, domain TEXT UNIQUE, census_date TEXT, note TEXT);
CREATE TABLE models (id INTEGER PRIMARY KEY, canonical_name TEXT UNIQUE, slug TEXT UNIQUE, is_aggregator INTEGER DEFAULT 0);
CREATE TABLE model_names (
    site_id INT, model_id INT, variant TEXT, post_count INT, slug_url TEXT,
    PRIMARY KEY (site_id, variant),
    FOREIGN KEY (site_id) REFERENCES sites(id),
    FOREIGN KEY (model_id) REFERENCES models(id));
CREATE TABLE archive_artists (
    model_id INT, region TEXT, folder_name TEXT, album_count INT, size_kb INT,
    PRIMARY KEY (folder_name),
    FOREIGN KEY (model_id) REFERENCES models(id));
CREATE VIEW v_model_summary AS
SELECT m.id, m.canonical_name, m.is_aggregator,
       COALESCE(SUM(CASE WHEN mn.site_id=1 THEN mn.post_count END), 0) AS misskon,
       COALESCE(SUM(CASE WHEN mn.site_id=2 THEN mn.post_count END), 0) AS cosplaytele,
       COUNT(DISTINCT mn.site_id) AS sites_present,
       COALESCE(ar.albums, 0) AS owned_albums,
       ROUND(COALESCE(ar.size_kb, 0) / 1048576.0, 1) AS owned_gb,
       ar.regions
FROM models m
LEFT JOIN model_names mn ON mn.model_id = m.id
LEFT JOIN (SELECT model_id, SUM(album_count) AS albums, SUM(size_kb) AS size_kb,
                  GROUP_CONCAT(DISTINCT region) AS regions
           FROM archive_artists GROUP BY model_id) ar ON ar.model_id = m.id
GROUP BY m.id;
""")
    db.execute("INSERT INTO sites VALUES (1, 'misskon.com', ?, '/tag/cosplay/ 전수 워크')",
               (census_date := _tsv_date('misskon_census_full.tsv'),))
    db.execute("INSERT INTO sites VALUES (2, 'cosplaytele.com', ?, 'WP REST API 전수 열거')",
               (_tsv_date('cosplaytele_census_full.tsv'),))

    def derive_slug(name):
        """표시명에서 roman slug 도출: 등장순 roman 토큰 하이픈 연결, 없으면 flat 전체."""
        romans = re.findall(r'[a-z0-9_.]{3,}', name.lower())
        if romans:
            return re.sub(r'[^a-z0-9]+', '-', ' '.join(romans)).strip('-')
        return flat(name)

    def model_id(name, is_agg=0):
        row = db.execute("SELECT id FROM models WHERE canonical_name=?", (name,)).fetchone()
        if row:
            return row[0]
        slug = derive_slug(name)
        # slug 충돌 시 접미사
        n = 2
        while db.execute("SELECT 1 FROM models WHERE slug=?", (slug,)).fetchone():
            slug = f"{derive_slug(name)}-{n}"
            n += 1
        return db.execute("INSERT INTO models (canonical_name, slug, is_aggregator) VALUES (?,?,?)",
                          (name, slug, is_agg)).lastrowid

    for name, cnt, slug in mk_rows:
        is_agg = 1 if name.lower() in NOISE else 0
        mid = model_id(name, is_agg)
        db.execute("INSERT OR REPLACE INTO model_names VALUES (?,?,?,?,?)", (1, mid, name, cnt, slug))

    mk_tok = {name: (tokens(name), flat(name)) for name, _, _ in mk_rows}
    for cname, cnt in ct_rows:
        is_agg = 1 if (cname.lower() in NOISE or cname.startswith('[')) else 0
        target = None
        if not is_agg:
            # 수동 보정 쌍 우선
            for mk_name, cts in MANUAL_MATCHES.items():
                if cname in cts:
                    target = mk_name
                    break
            if target is None:
                (cr, cc), cf = tokens(cname), flat(cname)
                for mk_name, ((mr, mc), mf) in mk_tok.items():
                    if ((mc and cc and (mc & cc)) or (mr and cr and (mr & cr)) or
                            (len(mf) >= 4 and len(cf) >= 4 and (mf in cf or cf in mf))):
                        target = mk_name
                        break
        mid = model_id(target if target else cname, is_agg)
        db.execute("INSERT OR REPLACE INTO model_names VALUES (?,?,?,?,?)", (2, mid, cname, cnt, None))

    # 4. heritage 아카이브: 폴더명(roman (native))을 기존 변형에 매칭, 미매칭은 새 캐노니컬
    ar_path = DATA_DIR / 'heritage_archive_census.tsv'
    if ar_path.exists():
        all_variants = db.execute(
            "SELECT mn.variant, mn.model_id FROM model_names mn "
            "JOIN models m ON m.id = mn.model_id WHERE m.is_aggregator = 0"
        ).fetchall()
        var_tok = [(v, mid, tokens(v), flat(v)) for v, mid in all_variants]
        # 수동 쌍 미리 매핑 (heritage 폴더명이 아니라 변형 매칭에도 반영되도록
        # cosplaytele 변형 삽입 시 이미 MANUAL_MATCHES가 적용된 상태다)
        for line in open(ar_path):
            region, folder, albums, kb = line.rstrip('\n').split('\t')
            (fr, fc), ff = tokens(folder), flat(folder)
            target_mid = None
            for _v, mid, (vr, vc), vf in var_tok:
                if ((fc and vc and (fc & vc)) or (fr and vr and (fr & vr)) or
                        (len(ff) >= 4 and len(vf) >= 4 and (ff in vf or vf in ff))):
                    target_mid = mid
                    break
            if target_mid is None:
                target_mid = model_id(folder)
            db.execute("INSERT OR REPLACE INTO archive_artists VALUES (?,?,?,?,?)",
                       (target_mid, region, folder, int(albums), int(kb)))

    # 5. CJK slug 보강: 캐노니컬에 roman이 없어도 변형에 있으면 roman slug로 승격
    for mid, slug in db.execute("SELECT id, slug FROM models").fetchall():
        if re.search(r"[a-z0-9]", slug):
            continue
        for (variant,) in db.execute(
                "SELECT variant FROM model_names WHERE model_id = ?", (mid,)):
            cand = derive_slug(variant)
            if re.search(r"[a-z0-9]", cand) and not db.execute(
                    "SELECT 1 FROM models WHERE slug = ? AND id != ?", (cand, mid)).fetchone():
                db.execute("UPDATE models SET slug = ? WHERE id = ?", (cand, mid))
                break

    db.commit()
    n = db.execute("SELECT COUNT(*) FROM model_names").fetchone()[0]
    db.close()
    print(f"data/models.db 재생성 완료 - model_names {n}행 (census: {census_date})")


def _tsv_date(fname: str) -> str:
    import datetime
    ts = (DATA_DIR / fname).stat().st_mtime
    return datetime.date.fromtimestamp(ts).isoformat()


if __name__ == "__main__":
    build()
