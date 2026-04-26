#!/usr/bin/env python3
"""ingest_pref_programs_47.py — 47 都道府県 公式サイト 補助金 BFS ingest.

User directive 2026-04-25: TOS 一旦無視で獲得優先。Launch 2026-05-06.

Strategy:
  - Per-prefecture seed URLs (top page + 補助金/keieishien sub-portal candidates).
  - BFS depth=2 from each seed, intra-domain only (pref.{slug}.lg.jp / pref.{slug}.jp / metro.tokyo.lg.jp).
  - Extract <a> with text/href containing 補助金/助成金/支援金/hojo/josei/shien/hojokin/joseikin.
  - Reject obvious junk URL fragments (#section, javascript:, .css/.js, image, anchor-only, soft-404 nav links repeated).
  - Each program row: primary_name = anchor text (truncated to 200), source_url = absolute.
  - Per-domain rate limit: 1 req/sec (separate per host). Global concurrency: 5 hosts in parallel.
  - SQLite: BEGIN IMMEDIATE + busy_timeout=300000.
  - Idempotent dedup by (source_url, primary_name).
  - UNI-ext-<10hex> namespace via SHA-1 of (name, source_url).
  - Tier:
      S = 200 + open now (no window data, treat as 'currently listed' = S if URL-text has 募集中/開催中)
      A = 200 + window-future or recent (default for newly fetched)
      B = otherwise (200 generic, or 404 etc.)

NO Anthropic API. urllib + requests + BeautifulSoup only.

Usage:
    .venv/bin/python scripts/ingest/ingest_pref_programs_47.py
    .venv/bin/python scripts/ingest/ingest_pref_programs_47.py --dry-run --max-per-pref 30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as exc:
    print(f"missing dep: {exc}. pip install requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)

_LOG = logging.getLogger("ingest_pref_programs_47")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
HTTP_TIMEOUT = 25
PER_HOST_RATE = 1.0  # 1 req/sec/domain
MAX_PARALLEL_HOSTS = 5
BFS_DEPTH = 2
MAX_LINKS_PER_PAGE = 800
DEFAULT_MAX_PER_PREF = 25  # cap programs harvested per prefecture

# 47 prefectures: (name, primary host(s), seed URLs)
# Seeds were probed live 2026-04-25 — all return 200.
PREFECTURES: list[dict] = [
    {"pref": "北海道", "slug": "hokkaido", "seeds": [
        "https://www.pref.hokkaido.lg.jp/kz/csk/index.html",
        "https://www.pref.hokkaido.lg.jp/kz/index.html",
    ]},
    {"pref": "青森県", "slug": "aomori", "seeds": [
        "https://www.pref.aomori.lg.jp/",
    ]},
    {"pref": "岩手県", "slug": "iwate", "seeds": [
        "https://www.pref.iwate.jp/",
    ]},
    {"pref": "宮城県", "slug": "miyagi", "seeds": [
        "https://www.pref.miyagi.jp/",
    ]},
    {"pref": "秋田県", "slug": "akita", "seeds": [
        "https://www.pref.akita.lg.jp/pages/genre/34580",  # 補助金 関連ジャンル
        "https://www.pref.akita.lg.jp/pages/genre/11678",  # 中小企業支援
        "https://www.pref.akita.lg.jp/pages/genre/11700",  # 電子手続き・入札・補助金等
    ]},
    {"pref": "山形県", "slug": "yamagata", "seeds": [
        "https://www.pref.yamagata.jp/",
    ]},
    {"pref": "福島県", "slug": "fukushima", "seeds": [
        "https://www.pref.fukushima.lg.jp/",
    ]},
    {"pref": "茨城県", "slug": "ibaraki", "seeds": [
        "https://www.pref.ibaraki.jp/",
    ]},
    {"pref": "栃木県", "slug": "tochigi", "seeds": [
        "https://www.pref.tochigi.lg.jp/",
    ]},
    {"pref": "群馬県", "slug": "gunma", "seeds": [
        "https://www.pref.gunma.jp/page/3001.html",
    ]},
    {"pref": "埼玉県", "slug": "saitama", "seeds": [
        "https://www.pref.saitama.lg.jp/soshiki/a0801/index.html",
    ]},
    {"pref": "千葉県", "slug": "chiba", "seeds": [
        "https://www.pref.chiba.lg.jp/keishi/index.html",
    ]},
    {"pref": "東京都", "slug": "tokyo", "seeds": [
        "https://www.metro.tokyo.lg.jp/purpose/grant",
        "https://www.zaimu.metro.tokyo.lg.jp/zaisei/zaisei/hojokin",
        "https://www.sangyo-rodo.metro.tokyo.lg.jp/chushou/",
    ]},
    {"pref": "神奈川県", "slug": "kanagawa", "seeds": [
        "https://www.pref.kanagawa.jp/",
    ]},
    {"pref": "新潟県", "slug": "niigata", "seeds": [
        "https://www.pref.niigata.lg.jp/",
    ]},
    {"pref": "富山県", "slug": "toyama", "seeds": [
        "https://www.pref.toyama.jp/",
    ]},
    {"pref": "石川県", "slug": "ishikawa", "seeds": [
        "https://www.pref.ishikawa.lg.jp/",
        "https://www.pref.ishikawa.lg.jp/index.html",
    ], "depth": 3},
    {"pref": "福井県", "slug": "fukui", "seeds": [
        "https://www.pref.fukui.lg.jp/",
    ]},
    {"pref": "山梨県", "slug": "yamanashi", "seeds": [
        "https://www.pref.yamanashi.jp/",
    ]},
    {"pref": "長野県", "slug": "nagano", "seeds": [
        "https://www.pref.nagano.lg.jp/",
    ]},
    {"pref": "岐阜県", "slug": "gifu", "seeds": [
        "https://www.pref.gifu.lg.jp/",
    ]},
    {"pref": "静岡県", "slug": "shizuoka", "seeds": [
        "https://www.pref.shizuoka.jp/sangyoshigoto/index.html",
    ]},
    {"pref": "愛知県", "slug": "aichi", "seeds": [
        "https://www.pref.aichi.jp/soshiki/sangyoshinko/",
        "https://www.pref.aichi.jp/",
    ]},
    {"pref": "三重県", "slug": "mie", "seeds": [
        "https://www.pref.mie.lg.jp/",
    ], "depth": 3},
    {"pref": "滋賀県", "slug": "shiga", "seeds": [
        "https://www.pref.shiga.lg.jp/",
    ]},
    {"pref": "京都府", "slug": "kyoto", "seeds": [
        "https://www.pref.kyoto.jp/sangyo/index.html",
        "https://www.pref.kyoto.jp/",
    ]},
    {"pref": "大阪府", "slug": "osaka", "seeds": [
        "https://www.pref.osaka.lg.jp/",
    ]},
    {"pref": "兵庫県", "slug": "hyogo", "seeds": [
        "https://web.pref.hyogo.lg.jp/",
        "https://web.pref.hyogo.lg.jp/index.html",
    ], "depth": 3},
    {"pref": "奈良県", "slug": "nara", "seeds": [
        "https://www.pref.nara.lg.jp/",
    ]},
    {"pref": "和歌山県", "slug": "wakayama", "seeds": [
        "https://www.pref.wakayama.lg.jp/",
    ]},
    {"pref": "鳥取県", "slug": "tottori", "seeds": [
        "https://www.pref.tottori.lg.jp/keieishien/",
        "https://www.pref.tottori.lg.jp/9100.htm",
        "https://www.pref.tottori.lg.jp/9087.htm",
    ], "depth": 3},
    {"pref": "島根県", "slug": "shimane", "seeds": [
        "https://www.pref.shimane.lg.jp/",
        "https://www.pref.shimane.lg.jp/industry/",
    ], "depth": 3},
    {"pref": "岡山県", "slug": "okayama", "seeds": [
        "https://www.pref.okayama.jp/",
    ], "depth": 3},
    {"pref": "広島県", "slug": "hiroshima", "seeds": [
        "https://www.pref.hiroshima.lg.jp/",
    ]},
    {"pref": "山口県", "slug": "yamaguchi", "seeds": [
        "https://www.pref.yamaguchi.lg.jp/soshiki/91/",
        "https://www.pref.yamaguchi.lg.jp/soshiki/93/",
        "https://www.pref.yamaguchi.lg.jp/",
    ], "depth": 3},
    {"pref": "徳島県", "slug": "tokushima", "seeds": [
        "https://www.pref.tokushima.lg.jp/",
    ]},
    {"pref": "香川県", "slug": "kagawa", "seeds": [
        "https://www.pref.kagawa.lg.jp/",
    ]},
    {"pref": "愛媛県", "slug": "ehime", "seeds": [
        "https://www.pref.ehime.jp/",
    ], "depth": 3},
    {"pref": "高知県", "slug": "kochi", "seeds": [
        "https://www.pref.kochi.lg.jp/",
    ]},
    {"pref": "福岡県", "slug": "fukuoka", "seeds": [
        "https://www.pref.fukuoka.lg.jp/",
    ]},
    {"pref": "佐賀県", "slug": "saga", "seeds": [
        "https://www.pref.saga.lg.jp/",
    ]},
    {"pref": "長崎県", "slug": "nagasaki", "seeds": [
        "https://www.pref.nagasaki.jp/",
    ]},
    {"pref": "熊本県", "slug": "kumamoto", "seeds": [
        "https://www.pref.kumamoto.jp/",
    ], "depth": 3},
    {"pref": "大分県", "slug": "oita", "seeds": [
        "https://www.pref.oita.jp/",
    ]},
    {"pref": "宮崎県", "slug": "miyazaki", "seeds": [
        "https://www.pref.miyazaki.lg.jp/",
    ]},
    {"pref": "鹿児島県", "slug": "kagoshima", "seeds": [
        "https://www.pref.kagoshima.jp/",
    ]},
    {"pref": "沖縄県", "slug": "okinawa", "seeds": [
        "https://www.pref.okinawa.lg.jp/",
        "https://www.pref.okinawa.jp/",
    ], "depth": 3},
]

# Filter heuristics
SUBSIDY_KEYWORDS_TEXT = ("補助金", "助成金", "支援金", "交付金", "奨励金", "事業費補助")
SUBSIDY_KEYWORDS_URL = ("hojo", "josei", "joseikin", "hojokin", "shien", "subsidy")
NAV_NOISE = (
    "閲覧補助", "サイトマップ", "プライバシー", "アクセシビリティ", "問い合わせ",
    "お問合せ", "お問い合わせ", "ホーム", "前のページ", "次のページ", "トップへ",
    "ページの先頭", "戻る", "ログイン", "RSS", "Twitter", "Facebook", "Instagram",
    "YouTube", "メニュー", "検索", "翻訳", "Language", "English", "やさしい日本語",
    "高齢者", "外国人", "妊産婦",
    "中小企業支援", "犯罪被害者等支援", "雇用・労働・定住支援",
    "コンテンツにスキップ", "本文へスキップ", "ページの先頭へ戻る",
    "ほかの助成・補助金に関する記事を探す", "ほかの",
    "新着記事", "お知らせ",
)
NOISE_HOST_BLACKLIST = ("noukaweb", "hojyokin-portal", "stayway", "j-net21")  # never harvest


_host_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_host_last: dict[str, float] = {}


def _polite_get(url: str, *, session: requests.Session, timeout: int = HTTP_TIMEOUT) -> requests.Response | None:
    host = urlparse(url).netloc
    with _host_locks[host]:
        last = _host_last.get(host, 0.0)
        delta = time.monotonic() - last
        if delta < PER_HOST_RATE:
            time.sleep(PER_HOST_RATE - delta)
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
            _host_last[host] = time.monotonic()
            return resp
        except requests.RequestException as exc:
            _LOG.debug("get_fail url=%s err=%s", url, exc)
            _host_last[host] = time.monotonic()
            return None


def _decode(resp: requests.Response) -> str:
    raw = resp.content
    # Try meta charset declared in body first (more reliable than HTTP header for JP gov sites)
    head = raw[:4096]
    meta_enc = None
    m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', head, re.IGNORECASE)
    if m:
        meta_enc = m.group(1).decode("ascii", errors="ignore").lower()
    # Skip ISO-8859-1 (gov server default mis-tagging); prefer apparent or meta
    declared = (resp.encoding or "").lower()
    if declared in ("iso-8859-1", "latin-1", "ascii", ""):
        declared = ""
    candidates = []
    if meta_enc:
        candidates.append(meta_enc)
    if declared:
        candidates.append(declared)
    candidates += ["utf-8", "shift_jis", "cp932", "euc_jp"]
    seen = set()
    for enc in candidates:
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            return raw.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_anchor_text(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    return t[:240]


def _is_program_link(text: str, href: str) -> bool:
    blob_text = text or ""
    blob_url = (href or "").lower()
    if any(b in blob_url for b in NOISE_HOST_BLACKLIST):
        return False
    has_jp_kw = any(k in blob_text for k in SUBSIDY_KEYWORDS_TEXT)
    has_url_kw = any(k in blob_url for k in SUBSIDY_KEYWORDS_URL)
    if not (has_jp_kw or has_url_kw):
        return False
    if any(n in blob_text for n in NAV_NOISE):
        return False
    if len(blob_text) < 4 or len(blob_text) > 200:
        return False
    # reject pure short navigational headers (just a category like "補助金")
    if blob_text in ("補助金", "助成金", "支援金", "補助金等", "助成・補助金", "交付金"):
        return False
    return True


def _is_intra_pref(href: str, allowed_hosts: set[str], allowed_root_suffixes: set[str]) -> bool:
    p = urlparse(href)
    if p.scheme not in ("http", "https"):
        return False
    if p.netloc in allowed_hosts:
        return True
    # match by root domain suffix (e.g. metro.tokyo.lg.jp covers www. / sangyo-rodo. / zaimu. etc.)
    for suf in allowed_root_suffixes:
        if p.netloc.endswith("." + suf) or p.netloc == suf:
            return True
    return False


def _domain_root_suffix(netloc: str) -> str:
    """metro.tokyo.lg.jp / pref.akita.lg.jp / pref.aichi.jp / sangyo-rodo.metro.tokyo.lg.jp / web.pref.hyogo.lg.jp"""
    parts = netloc.split(".")
    # take last 4 parts if .lg.jp / .ne.jp; else last 3
    if len(parts) >= 4 and parts[-2] == "lg" and parts[-1] == "jp":
        return ".".join(parts[-4:])
    return ".".join(parts[-3:]) if len(parts) >= 3 else netloc


def harvest_pref(
    pref_def: dict,
    *,
    max_links: int,
    bfs_depth: int = BFS_DEPTH,
) -> list[dict]:
    """BFS one prefecture and return list of program dicts."""
    pref = pref_def["pref"]
    slug = pref_def["slug"]
    seeds = pref_def["seeds"]
    # honor per-pref depth override
    bfs_depth = pref_def.get("depth", bfs_depth)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Determine allowed hosts + domain-root suffixes (seed netlocs + their roots)
    allowed_hosts = {urlparse(s).netloc for s in seeds}
    allowed_root_suffixes = {_domain_root_suffix(h) for h in allowed_hosts}

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(s, 0) for s in seeds]
    found: dict[tuple[str, str], dict] = {}  # (url, name) -> dict

    while queue:
        if len(found) >= max_links:
            break
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        resp = _polite_get(url, session=session)
        if resp is None or resp.status_code != 200:
            continue
        try:
            html = _decode(resp)
        except Exception:
            continue
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            continue

        # extract anchors
        anchors = soup.find_all("a", href=True)[:MAX_LINKS_PER_PAGE]
        for a in anchors:
            text = _normalize_anchor_text(a.get_text(" ", strip=True))
            href_raw = a["href"]
            href = urljoin(resp.url, href_raw)
            href = href.split("#", 1)[0]
            if not href:
                continue
            if not _is_intra_pref(href, allowed_hosts, allowed_root_suffixes):
                continue
            # skip non-page URL endings
            low = href.lower()
            if low.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".zip")):
                continue
            if _is_program_link(text, href):
                key = (href, text)
                if key not in found:
                    found[key] = {
                        "primary_name": text,
                        "source_url": href,
                        "prefecture": pref,
                        "authority_level": "prefecture",
                        "authority_name": pref,
                        "program_kind": _infer_kind(text, href),
                    }
                    if len(found) >= max_links:
                        break
            # enqueue for BFS if depth allows + URL/text keyword match (broad)
            if depth + 1 < bfs_depth:
                low_u = href.lower()
                low_t = text or ""
                if (any(k in low_u for k in SUBSIDY_KEYWORDS_URL) or
                    any(k in low_t for k in SUBSIDY_KEYWORDS_TEXT) or
                    any(k in low_u for k in ("sangyo", "keiei", "shoko", "shokorodo", "soshiki",
                                               "chusho", "chuusho", "nourin", "nogyo", "nougyou",
                                               "kanko", "kankou", "kankyo", "kankyou", "fukushi",
                                               "kosodate", "iryo", "iryou", "shinko", "shinkou",
                                               "rodo", "roudou", "kigyou", "kigyo", "shien")) or
                    any(k in low_t for k in ("中小企業", "産業", "経営", "商工", "農林",
                                               "観光", "環境", "福祉", "雇用", "労働",
                                               "事業者", "起業", "創業", "DX", "脱炭素"))):
                    if href not in visited:
                        queue.append((href, depth + 1))

        if len(found) >= max_links:
            break

    _LOG.info("pref=%s slug=%s harvested=%d (visited=%d)", pref, slug, len(found), len(visited))
    return list(found.values())


def _infer_kind(text: str, url: str) -> str:
    blob = (text or "") + " " + (url or "").lower()
    if "融資" in blob or "loan" in blob or "資金" in blob:
        return "loan"
    if "認定" in blob or "登録" in blob:
        return "certification"
    if "助成" in blob or "josei" in blob:
        return "subsidy"
    if "補助" in blob or "hojo" in blob:
        return "subsidy"
    if "支援" in blob or "shien" in blob:
        return "support"
    return "subsidy"


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------


def ext_unified_id(name: str, source_url: str) -> str:
    blob = f"pref47|{name}|{source_url}".encode("utf-8")
    digest = hashlib.sha1(blob).hexdigest()[:10]
    return f"UNI-ext-{digest}"


def open_db(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=300.0)
    con.execute("PRAGMA busy_timeout = 300000")
    con.execute("PRAGMA journal_mode = WAL")
    con.row_factory = sqlite3.Row
    return con


def upsert_program(
    con: sqlite3.Connection,
    prog: dict,
    fetched_at: str,
    now_iso: str,
) -> str:
    name = prog["primary_name"]
    src = prog["source_url"]
    uid = ext_unified_id(name, src)
    # default tier B; promote to S if 募集中/受付中 in name; else A if newly listed
    tier = "B"
    if any(k in name for k in ("募集中", "受付中", "公募中")):
        tier = "S"
    elif any(k in name for k in ("予定", "予告")):
        tier = "A"
    else:
        tier = "A"  # newly fetched live page = A by default

    enriched = {
        "_meta": {
            "ingest": "ingest_pref_programs_47.py",
            "wave": "p_pref47",
            "fetched_at": fetched_at,
            "attribution": f"出典: {prog.get('authority_name')} 公式サイト",
        },
    }
    enriched_json = json.dumps(enriched, ensure_ascii=False)
    checksum = hashlib.sha1(f"{name}|{src}".encode("utf-8")).hexdigest()[:16]

    con.execute("BEGIN IMMEDIATE")
    try:
        prev = con.execute(
            "SELECT excluded FROM programs WHERE unified_id = ?", (uid,)
        ).fetchone()
        if prev is None:
            con.execute(
                """INSERT INTO programs (
                    unified_id, primary_name, aliases_json,
                    authority_level, authority_name, prefecture, municipality,
                    program_kind, official_url,
                    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                    trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                    excluded, exclusion_reason,
                    crop_categories_json, equipment_category,
                    target_types_json, funding_purpose_json,
                    amount_band, application_window_json,
                    enriched_json, source_mentions_json,
                    source_url, source_fetched_at, source_checksum,
                    source_last_check_status, source_fail_count,
                    updated_at
                ) VALUES (
                    ?,?,?, ?,?,?,?, ?,?, ?,?,?,
                    ?,?,?,?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,?,
                    ?,?,
                    ?
                )""",
                (
                    uid,
                    name,
                    None,
                    prog.get("authority_level"),
                    prog.get("authority_name"),
                    prog.get("prefecture"),
                    prog.get("municipality"),
                    prog.get("program_kind"),
                    src,
                    None, None, None,
                    None, tier, None, None, None,
                    0, None,
                    None, None,
                    None, None,
                    None, None,
                    enriched_json, None,
                    src, fetched_at, checksum,
                    200, 0,
                    now_iso,
                ),
            )
            try:
                con.execute(
                    "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) VALUES (?,?,?,?)",
                    (uid, name, "", name),
                )
            except sqlite3.OperationalError:
                pass
            con.execute("COMMIT")
            return "insert"
        if prev["excluded"]:
            con.execute("ROLLBACK")
            return "skip"
        con.execute(
            """UPDATE programs SET
                source_fetched_at = ?, source_checksum = ?,
                source_last_check_status = ?,
                tier = ?, enriched_json = ?,
                updated_at = ?
                WHERE unified_id = ?""",
            (fetched_at, checksum, 200, tier, enriched_json, now_iso, uid),
        )
        con.execute("COMMIT")
        return "update"
    except Exception:
        con.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-per-pref", type=int, default=DEFAULT_MAX_PER_PREF)
    parser.add_argument("--depth", type=int, default=BFS_DEPTH)
    parser.add_argument("--parallel", type=int, default=MAX_PARALLEL_HOSTS)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--prefs", help="comma-separated list of prefecture slugs (debug)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    targets = PREFECTURES
    if args.prefs:
        wanted = set(args.prefs.split(","))
        targets = [p for p in PREFECTURES if p["slug"] in wanted]
        _LOG.info("filtered to %d prefectures: %s", len(targets), [p["slug"] for p in targets])

    all_progs: list[dict] = []
    pref_counts: dict[str, int] = {}

    # Parallel BFS — each pref runs in a thread (different host = no rate-limit interference)
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {
            ex.submit(harvest_pref, p, max_links=args.max_per_pref, bfs_depth=args.depth): p
            for p in targets
        }
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                progs = fut.result()
            except Exception as exc:
                _LOG.exception("pref=%s harvest_fail err=%s", p["pref"], exc)
                progs = []
            all_progs.extend(progs)
            pref_counts[p["pref"]] = len(progs)

    # Dedup
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for p in all_progs:
        k = (p["source_url"], p["primary_name"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(p)
    _LOG.info("harvested=%d unique=%d prefectures=%d",
              len(all_progs), len(unique), len({p["prefecture"] for p in unique}))

    if args.dry_run:
        for p in unique[:50]:
            print(p["prefecture"], "|", p["primary_name"][:80], "|", p["source_url"][:120])
        print(json.dumps({"unique_total": len(unique),
                          "by_pref": pref_counts}, ensure_ascii=False))
        return 0

    db_path = Path(args.db)
    if not db_path.exists():
        _LOG.error("db not found: %s", db_path)
        return 1

    now_iso = datetime.now(UTC).isoformat()
    fetched_at = now_iso
    con = open_db(db_path)
    counts = {"insert": 0, "update": 0, "skip": 0, "error": 0}

    for prog in unique:
        try:
            outcome = upsert_program(con, prog, fetched_at, now_iso)
            counts[outcome] = counts.get(outcome, 0) + 1
        except Exception as exc:
            _LOG.exception("upsert_fail name=%s err=%s", prog["primary_name"], exc)
            counts["error"] += 1
    con.close()

    _LOG.info("done counts=%s by_pref=%s", counts, pref_counts)
    print(json.dumps({
        "counts": counts,
        "by_pref": pref_counts,
        "unique_total": len(unique),
        "prefectures_covered": len({p["prefecture"] for p in unique}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
