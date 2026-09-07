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

# 강기준(한자 완전일치/전체포함) 감사로 확정한 병합 쌍: (유지 canonical, 흡수 canonical)
MANUAL_MERGES = [
    ("yuuhui玉汇", "Kokuhui"),
    ("铃木美咲", "Misaki Sai"),
    ("咬一口兔娘ovo (Yaokoututu)", "咬一口兔娘ovo"),
    ("黏黏团子兔", "咬一口兔娘ovo (Yaokoututu)"),  # 동일인 - 2026-09-07 사용자 확정
    ("前羽_rr", "前羽rr"),
    ("Neko薇薇", "Neko-薇薇"),
    ("Zia (지아)", "Jia (지아)"),
    ("桃良阿宅 (taoliangazhai)", "Tao Liang"),
    ("Qianchuan Yixiao (笑芳香沁)", "Fragrant Qin (笑芳香沁)"),
    ("Jeong Jenny (정제니)", "Jenny"),
    ("Jena (제나)", "제나 (June)"),
    ("Vina Silbee", "VINA"),
    ("抖娘-利世", "Li Shi"),
    ("抱走莫子aa", "Mozi"),
    ("Carol周妍希", "Zhou Yan Xi (周妍希)"),
    ("Chiu_mini (mini肉包)", "肉包 (Rou bao)"),
]

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
    # cosplaytele: WP REST 카테고리(공식 모델 분류) - 이름/정확한 카운트/URL
    # (/category 인덱스 페이지는 404이나 API는 개방, 2026-09-07 실측)
    ct_rows = []
    genre_prefixes = ('cosplay', 'free style', 'game', 'anime', 'video',
                      'nude', 'ero', 'uncensored', 'photo', 'ai ')
    for line in open(DATA_DIR / 'cosplaytele_categories.tsv'):
        name, cnt, url = line.rstrip('\n').split('\t')
        if name.lower().startswith(genre_prefixes) or name.lower() in NOISE:
            continue
        ct_rows.append((name, int(cnt), url))
    return mk_rows, ct_rows


def _existing_model_prefs(db_path) -> dict:
    """재빌드 전 기존 DB에서 수동 지정(등급/국적)을 백업한다."""
    prefs = {}
    if db_path.exists():
        old = sqlite3.connect(db_path)
        try:
            for slug, grade, region in old.execute(
                    "SELECT slug, grade, region FROM models "
                    "WHERE grade IS NOT NULL OR region IS NOT NULL"):
                prefs[slug] = (grade, region)
        except sqlite3.OperationalError:
            try:
                for slug, grade in old.execute("SELECT slug, grade FROM models WHERE grade IS NOT NULL"):
                    prefs[slug] = (grade, None)
            except sqlite3.OperationalError:
                pass
        old.close()
    return prefs


def infer_region(name: str):
    """이름 문자로 국적 추론 - 한글 KOR, 가나 JPN, 한자 CHN, 로마자 미정."""
    import re
    if re.search(r"[가-힯]", name):
        return "KOR"
    if re.search(r"[ぁ-ヿ]", name):
        return "JPN"
    if re.search(r"[一-鿿]", name):
        return "CHN"
    return None


def derive_grade(misskon: int, cosplaytele: int, owned: int, region: str = None) -> str:
    """보유(행동) 기반 초기 등급 - 수동 조정은 preserved로 덮어쓴다.
    정책: 한국 국적 모델은 최소 C (2026-09-07 사용자 확정)."""
    available = misskon + cosplaytele
    if owned >= 30:
        grade = "A"
    elif owned >= 10:
        grade = "B"
    elif owned >= 3:
        grade = "C"
    elif owned >= 1:
        grade = "D"
    elif available >= 10:
        grade = "E"
    else:
        grade = "F"
    if region == "KOR" and grade > "C":
        grade = "C"
    return grade


def build():
    mk_rows, ct_rows = load()
    preserved = _existing_model_prefs(DATA_DIR / "models.db")
    db = sqlite3.connect(DATA_DIR / 'models.db')
    db.executescript("""
DROP VIEW IF EXISTS v_model_summary;
DROP TABLE IF EXISTS model_counts;
DROP TABLE IF EXISTS archive_artists;
DROP TABLE IF EXISTS model_names;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS sites;
CREATE TABLE sites (id INTEGER PRIMARY KEY, domain TEXT UNIQUE, census_date TEXT, note TEXT);
CREATE TABLE models (id INTEGER PRIMARY KEY, canonical_name TEXT UNIQUE, slug TEXT UNIQUE, grade TEXT, region TEXT, is_aggregator INTEGER DEFAULT 0);
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

    # 수동 slug 지정 (문자 추론이 못하는 것)
    MANUAL_SLUGS = {"서安": "seoan", "서안": "seoan"}

    def derive_slug(name):
        """표시명에서 roman slug 도출: roman 토큰 > 병음(한자) > flat."""
        if name in MANUAL_SLUGS:
            return MANUAL_SLUGS[name]
        romans = re.findall(r'[a-z0-9_.]{3,}', name.lower())
        if romans:
            return re.sub(r'[^a-z0-9]+', '-', ' '.join(romans)).strip('-')
        # 한자는 병음으로 (pypinyin) - slug는 발음이 아니라 식별자다
        from pypinyin import lazy_pinyin
        pinyin = "".join(lazy_pinyin(name, errors="ignore"))
        pinyin = re.sub(r'[^a-zA-Z0-9]+', '-', pinyin).strip('-').lower()
        if pinyin:
            return pinyin
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
    ct_urls = {}  # model_id -> 카테고리 URL (crawl_url 자동 도출용)
    for cname, cnt, curl in ct_rows:
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
                    # roman 교집합은 2토큰 이상일 때만 병합 - "momo"/"sama" 같은
                    # 단일 단어가 다른 사람을 이어붙이는 사고 방지 (Sayo Momo 실측)
                    roman_ok = len(cr & mr) >= 2
                    if ((mc and cc and (mc & cc)) or roman_ok or
                            (len(mf) >= 4 and len(cf) >= 4 and (mf in cf or cf in mf))):
                        target = mk_name
                        break
        mid = model_id(target if target else cname, is_agg)
        db.execute("INSERT OR REPLACE INTO model_names VALUES (?,?,?,?,?)", (2, mid, cname, cnt, curl))
        if curl and not is_agg:
            ct_urls[mid] = curl

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

    # 4.5. 확정 병합: variant/보유를 유지 캐노니컬로 이동 후 흡수 캐노니컬 삭제
    for keep_name, drop_name in MANUAL_MERGES:
        keep = db.execute("SELECT id FROM models WHERE canonical_name=?", (keep_name,)).fetchone()
        drop = db.execute("SELECT id FROM models WHERE canonical_name=?", (drop_name,)).fetchone()
        if not keep or not drop or keep[0] == drop[0]:
            continue
        for site_id, variant, post_count, slug_url in db.execute(
                "SELECT site_id, variant, post_count, slug_url FROM model_names WHERE model_id=?",
                (drop[0],)).fetchall():
            db.execute("INSERT OR REPLACE INTO model_names VALUES (?,?,?,?,?)",
                       (site_id, keep[0], variant, post_count, slug_url))
        db.execute("DELETE FROM model_names WHERE model_id=?", (drop[0],))
        db.execute("UPDATE archive_artists SET model_id=? WHERE model_id=?", (keep[0], drop[0]))
        db.execute("DELETE FROM models WHERE id=?", (drop[0],))

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

    # 6. 등급/크롤URL/국적: 기존 수동 지정 보존, 신규는 규칙 부여
    # 국적 1순위 heritage 권역(다수결), 2순위 이름 문자 추론
    heritage_regions = {}
    for mid, region in db.execute("SELECT model_id, region FROM archive_artists"):
        heritage_regions.setdefault(mid, []).append(region)
    for model_id, slug, misskon, cosplaytele, owned, name in db.execute("""
            SELECT m.id, m.slug, v.misskon, v.cosplaytele, v.owned_albums, m.canonical_name
            FROM v_model_summary v JOIN models m ON m.id = v.id""").fetchall():
        grade, region = preserved.get(slug, (None, None))
        if region is None and model_id in heritage_regions:
            regions = heritage_regions[model_id]
            region = max(set(regions), key=regions.count)
        if region is None:
            region = infer_region(name)
        grade = grade or derive_grade(misskon, cosplaytele, owned, region)
        db.execute("UPDATE models SET grade = ?, region = ? WHERE id = ?",
                   (grade, region, model_id))

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
