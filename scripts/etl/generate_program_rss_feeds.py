#!/usr/bin/env python3
"""Generate program-feed RSS files for organic SEO discovery surfaces.

Three feed families on top of the existing /rss.xml (release notes) and
/audit-log.rss (am_amendment_diff stream):

  A. ``site/rss/programs-tier-s.xml``      — Tier S programs (114 rows)
  B. ``site/rss/amendments.xml``           — am_amendment_diff month-scoped
  C. ``site/rss/prefecture/{slug}.xml``    — 47 prefectural slices (S+A+B+C)

Why three feeds (not one)?
--------------------------

* Feedly / Inoreader / Google Discover all reward narrow topical feeds.
  A single mega-feed of 11k programs would be auto-throttled.
* Each feed is capped at ``_MAX_ITEMS = 100`` (per CLAUDE.md "no over-stuffing"
  rule and the SEO honesty rule — Feedly visibly drops feeds over 200 items).
* The prefectural slice exists because regional 商工会 / 信金 readers are
  the cohort #7 organic-only audience; subscribing to a single ``東京都``
  feed beats scanning the global stream.

Constraints (CLAUDE.md, project_jpcite_rename, feedback_no_trademark…):

* read-only against ``data/jpintel.db`` and ``autonomath.db``
* NO LLM calls — pure SQL + jinja2 string formatting
* brand: jpcite on user-facing surfaces
* atom self-link uses ``https://jpcite.com/rss/...``
* idempotent: re-running on the same DB snapshot produces byte-identical
  output (modulo lastBuildDate; see ``--lastmod`` override for tests)

Usage::

    .venv/bin/python scripts/etl/generate_program_rss_feeds.py
    .venv/bin/python scripts/etl/generate_program_rss_feeds.py --dry-run
    .venv/bin/python scripts/etl/generate_program_rss_feeds.py \
        --jpintel-db data/jpintel.db \
        --autonomath-db autonomath.db \
        --out-dir site/rss \
        --domain jpcite.com

Exit codes
----------
0 success
1 fatal (DB missing, unwritable out-dir, jinja2 missing)
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("jpcite.etl.generate_program_rss_feeds")

REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp._jpcite_env_bridge import get_flag  # noqa: E402
from scripts.static_bad_urls import load_static_bad_urls  # noqa: E402

DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = Path(
    get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH", str(REPO_ROOT / "autonomath.db"))
)
DEFAULT_OUT_DIR = REPO_ROOT / "site" / "rss"
DEFAULT_SITE_DIR = REPO_ROOT / "site"
DEFAULT_DOMAIN = "jpcite.com"
_STATIC_BAD_URLS = load_static_bad_urls()

# Per-feed item cap. CLAUDE-md / user-spec: 100 max per feed (Feedly
# auto-trims long feeds and noticeably penalizes feeds > ~150 items).
_MAX_ITEMS = 100
_PUBLIC_ID_PREFIX_RE = re.compile(r"^(?:MUN-\d{2,6}-\d{3}|PREF-\d{2,6}-\d{3})[_\s]+")

_BANNED_SOURCE_HOSTS = frozenset(
    {
        "smart-hojokin.jp",
        "noukaweb.jp",
        "noukaweb.com",
        "hojyokin-portal.jp",
        "hojokin-portal.jp",
        "biz.stayway.jp",
        "biz-stayway.jp",
        "stayway.jp",
        "subsidymap.jp",
        "navit-j.com",
        "hojyokin.jp",
        "hojokin.jp",
        "creabiz.co.jp",
        "yorisoi.jp",
        "aichihojokin.com",
        "activation-service.jp",
        "jsearch.jp",
        "judgit.net",
        "news.mynavi.jp",
        "news.yahoo.co.jp",
        "shien-39.jp",
        "tamemap.net",
        "tokyo-np.co.jp",
        "yayoi-kk.co.jp",
        "jiji.com",
    }
)
_BANNED_AUTHORITY_TOKENS = frozenset(
    {
        "noukaweb",
        "hojyokin-portal",
        "hojokin-portal",
        "biz.stayway",
        "stayway",
        "smart-hojokin",
        "収集",
    }
)

# 47 都道府県 ASCII slug map. Mirrors the prefecture page generator in
# scripts/_pref_slugs.py — duplicated here for self-containment because the
# generator is not always on sys.path (e.g. CI runs it as a one-shot).
PREFECTURE_SLUG: dict[str, str] = {
    "北海道": "hokkaido",
    "青森県": "aomori",
    "岩手県": "iwate",
    "宮城県": "miyagi",
    "秋田県": "akita",
    "山形県": "yamagata",
    "福島県": "fukushima",
    "茨城県": "ibaraki",
    "栃木県": "tochigi",
    "群馬県": "gunma",
    "埼玉県": "saitama",
    "千葉県": "chiba",
    "東京都": "tokyo",
    "神奈川県": "kanagawa",
    "新潟県": "niigata",
    "富山県": "toyama",
    "石川県": "ishikawa",
    "福井県": "fukui",
    "山梨県": "yamanashi",
    "長野県": "nagano",
    "岐阜県": "gifu",
    "静岡県": "shizuoka",
    "愛知県": "aichi",
    "三重県": "mie",
    "滋賀県": "shiga",
    "京都府": "kyoto",
    "大阪府": "osaka",
    "兵庫県": "hyogo",
    "奈良県": "nara",
    "和歌山県": "wakayama",
    "鳥取県": "tottori",
    "島根県": "shimane",
    "岡山県": "okayama",
    "広島県": "hiroshima",
    "山口県": "yamaguchi",
    "徳島県": "tokushima",
    "香川県": "kagawa",
    "愛媛県": "ehime",
    "高知県": "kochi",
    "福岡県": "fukuoka",
    "佐賀県": "saga",
    "長崎県": "nagasaki",
    "熊本県": "kumamoto",
    "大分県": "oita",
    "宮崎県": "miyazaki",
    "鹿児島県": "kagoshima",
    "沖縄県": "okinawa",
}

# Mirrors api/audit_log.py::_TRACKED_FIELDS_JA — keep in sync.
_AMENDMENT_FIELDS_JA: dict[str, str] = {
    "amount_max_yen": "補助上限額",
    "subsidy_rate_max": "補助率上限",
    "target_set_json": "対象セット",
    "source_url": "出典URL",
    "source_fetched_at": "出典取得時刻",
    "eligibility_text": "適格要件 (合成)",
    "projection_regression_candidate": "再投影候補",
}


def _source_host_allowed(source_url: str | None) -> bool:
    if not source_url:
        return True
    if str(source_url).strip() in _STATIC_BAD_URLS:
        return False
    try:
        hostname = urlparse(str(source_url).strip()).hostname
    except ValueError:
        return True
    if not hostname:
        return True
    host = hostname.lower().rstrip(".")
    return not any(host == banned or host.endswith(f".{banned}") for banned in _BANNED_SOURCE_HOSTS)


def _public_program_name(name: str | None) -> str:
    return _PUBLIC_ID_PREFIX_RE.sub("", (name or "").strip()) or "(無題)"


def _public_authority_name(name: str | None) -> str:
    cleaned = (name or "").strip()
    lowered = cleaned.lower()
    if not cleaned or any(token in lowered for token in _BANNED_AUTHORITY_TOKENS):
        return ""
    return cleaned


@dataclass(frozen=True)
class ProgramItem:
    unified_id: str
    primary_name: str
    tier: str
    prefecture: str | None
    authority_name: str | None
    program_kind: str | None
    amount_max_man_yen: float | None
    source_url: str | None
    source_fetched_at: str  # ISO-8601 (used for pubDate ordering)
    slug: str  # site/programs/{slug}.html


@dataclass(frozen=True)
class AmendmentItem:
    diff_id: int
    entity_id: str
    field_name: str
    prev_value: str | None
    new_value: str | None
    detected_at: str  # ISO-8601


# ---------------------------------------------------------------------------
# slug — mirrors src/jpintel_mcp/utils/slug.py::program_static_slug exactly
# (we cannot import it cleanly because [site] extras may not be installed in
# every cron environment; we shim a fallback path that drops to sha1-6 only)
# ---------------------------------------------------------------------------
def _program_slug(primary_name: str | None, unified_id: str) -> str:
    try:
        from jpintel_mcp.utils.slug import program_static_slug  # type: ignore[import-not-found]

        return program_static_slug(primary_name, unified_id)
    except Exception:
        # Fallback: sha1-6 only. The site-served page filename is generated
        # by scripts/generate_program_pages.py with pykakasi, so the static
        # HTML may live at a different path. We accept this drift for
        # operator-only fallback runs; real site builds always have pykakasi.
        return sha1(unified_id.encode("utf-8")).hexdigest()[:6]


def _program_page_exists(site_dir: Path, slug: str) -> bool:
    return (site_dir / "programs" / f"{slug}.html").is_file()


# ---------------------------------------------------------------------------
# RSS rendering. We use jinja2 for spec-clarity even though hand-built
# string concat would be 30 lines shorter — jinja2 makes the template readable
# and matches the user spec ("jinja2 で <rss> template").
# ---------------------------------------------------------------------------
_RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>{{ title | e }}</title>
  <link>{{ home_url | e }}</link>
  <atom:link href="{{ feed_url | e }}" rel="self" type="application/rss+xml" />
  <description>{{ description | e }}</description>
  <language>ja</language>
  <copyright>(C) 2026 jpcite</copyright>
  <generator>jpcite site</generator>
  <lastBuildDate>{{ last_build }}</lastBuildDate>
{% for it in items %}
  <item>
    <title>{{ it.title | e }}</title>
    <link>{{ it.link | e }}</link>
    <description>{{ it.description | e }}</description>
    <category>{{ it.category | e }}</category>
    <guid isPermaLink="false">{{ it.guid | e }}</guid>
    <pubDate>{{ it.pub_date }}</pubDate>
  </item>
{% endfor %}
</channel>
</rss>
"""


def _render_rss(
    *,
    title: str,
    description: str,
    feed_url: str,
    home_url: str,
    items: Iterable[dict],
    last_build: datetime,
) -> str:
    try:
        from jinja2 import Environment
    except ImportError as exc:  # pragma: no cover — jinja2 is in [docs] extras
        raise SystemExit(f"jinja2 missing: pip install jinja2 — {exc}") from exc
    # nosec B701 - RSS XML template applies explicit `| e` escaping on every
    # variable expansion (see _RSS_TEMPLATE above). Autoescape would double-encode
    # angle brackets in the static RSS skeleton.
    env = Environment(autoescape=False, trim_blocks=False, lstrip_blocks=False)  # nosec B701
    tpl = env.from_string(_RSS_TEMPLATE)
    return tpl.render(
        title=title,
        description=description,
        feed_url=feed_url,
        home_url=home_url,
        items=list(items),
        last_build=format_datetime(last_build),
    )


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def _load_tier_s_programs(jpintel_conn: sqlite3.Connection, *, site_dir: Path) -> list[ProgramItem]:
    cur = jpintel_conn.execute(
        """
        SELECT unified_id, primary_name, tier, prefecture, authority_name,
               program_kind, amount_max_man_yen, source_url, source_fetched_at
        FROM programs
        WHERE excluded = 0
          AND tier = 'S'
          AND source_fetched_at IS NOT NULL
        ORDER BY source_fetched_at DESC, unified_id ASC
        """
    )
    rows = cur.fetchall()
    out: list[ProgramItem] = []
    for r in rows:
        (
            unified_id,
            primary_name,
            tier,
            prefecture,
            authority_name,
            program_kind,
            amount_max_man_yen,
            source_url,
            source_fetched_at,
        ) = r
        if not _source_host_allowed(source_url):
            continue
        slug = _program_slug(primary_name, unified_id)
        if not _program_page_exists(site_dir, slug):
            continue
        out.append(
            ProgramItem(
                unified_id=unified_id,
                primary_name=primary_name or "(無題)",
                tier=tier,
                prefecture=prefecture,
                authority_name=authority_name,
                program_kind=program_kind,
                amount_max_man_yen=amount_max_man_yen,
                source_url=source_url,
                source_fetched_at=source_fetched_at,
                slug=slug,
            )
        )
        if len(out) >= _MAX_ITEMS:
            break
    return out


def _load_prefecture_programs(
    jpintel_conn: sqlite3.Connection,
    *,
    site_dir: Path,
) -> dict[str, list[ProgramItem]]:
    """Return ``{prefecture_ja: [programs newest first, capped at MAX]}``."""
    by_pref: dict[str, list[ProgramItem]] = defaultdict(list)
    cur = jpintel_conn.execute(
        """
        SELECT unified_id, primary_name, tier, prefecture, authority_name,
               program_kind, amount_max_man_yen, source_url, source_fetched_at
        FROM programs
        WHERE excluded = 0
          AND tier IN ('S','A','B','C')
          AND prefecture IN ({pref_in})
          AND source_fetched_at IS NOT NULL
        ORDER BY prefecture ASC, source_fetched_at DESC, unified_id ASC
        """.format(
            pref_in=",".join("?" * len(PREFECTURE_SLUG)),
        ),
        tuple(PREFECTURE_SLUG.keys()),
    )
    for row in cur:
        (
            unified_id,
            primary_name,
            tier,
            prefecture,
            authority_name,
            program_kind,
            amount_max_man_yen,
            source_url,
            source_fetched_at,
        ) = row
        if not _source_host_allowed(source_url):
            continue
        slug = _program_slug(primary_name, unified_id)
        if not _program_page_exists(site_dir, slug):
            continue
        if len(by_pref[prefecture]) >= _MAX_ITEMS:
            continue
        by_pref[prefecture].append(
            ProgramItem(
                unified_id=unified_id,
                primary_name=primary_name or "(無題)",
                tier=tier,
                prefecture=prefecture,
                authority_name=authority_name,
                program_kind=program_kind,
                amount_max_man_yen=amount_max_man_yen,
                source_url=source_url,
                source_fetched_at=source_fetched_at,
                slug=slug,
            )
        )
    return by_pref


def _load_amendments(autonomath_conn: sqlite3.Connection) -> list[AmendmentItem]:
    try:
        cur = autonomath_conn.execute(
            """
            SELECT diff_id, entity_id, field_name, prev_value, new_value, detected_at
            FROM am_amendment_diff
            WHERE field_name IN
                  ('amount_max_yen','subsidy_rate_max','target_set_json',
                   'source_url','source_fetched_at','eligibility_text',
                   'projection_regression_candidate')
            ORDER BY detected_at DESC, diff_id DESC
            LIMIT ?
            """,
            (_MAX_ITEMS,),
        )
    except sqlite3.OperationalError as exc:
        if "am_amendment_diff" not in str(exc):
            raise
        logger.warning("am_amendment_diff missing — skipping amendments feed")
        return []
    out: list[AmendmentItem] = []
    for r in cur:
        diff_id, entity_id, field_name, prev_value, new_value, detected_at = r
        out.append(
            AmendmentItem(
                diff_id=int(diff_id),
                entity_id=entity_id,
                field_name=field_name,
                prev_value=prev_value,
                new_value=new_value,
                detected_at=detected_at,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Item assembly
# ---------------------------------------------------------------------------
def _parse_iso(ts: str) -> datetime:
    """Parse SQLite timestamp into UTC datetime, defensively.

    Inputs vary: ``YYYY-MM-DD HH:MM:SS`` (CURRENT_TIMESTAMP) and
    ``YYYY-MM-DDTHH:MM:SS+00:00`` (jpi_* mirrors). Both are normalized to
    tz-aware UTC.
    """
    s = ts.replace("Z", "+00:00").replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.fromisoformat(s[:19])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _truncate(s: str | None, n: int) -> str:
    if s is None:
        return "(null)"
    s = str(s).strip()
    return s if len(s) <= n else s[:n] + "…"


def _program_to_item(p: ProgramItem, *, domain: str) -> dict:
    page_url = f"https://{domain}/programs/{p.slug}.html"
    pub_dt = _parse_iso(p.source_fetched_at)
    parts: list[str] = []
    if p.tier:
        parts.append(f"Tier {p.tier}")
    if p.prefecture:
        parts.append(p.prefecture)
    authority_name = _public_authority_name(p.authority_name)
    if authority_name:
        parts.append(authority_name)
    if p.program_kind:
        parts.append(p.program_kind)
    if p.amount_max_man_yen:
        parts.append(f"上限 {int(p.amount_max_man_yen):,}万円")
    desc_lead = " / ".join(parts) if parts else "制度概要"
    src_label = f" 出典: {p.source_url}" if p.source_url else ""
    return {
        "title": _public_program_name(p.primary_name),
        "link": page_url,
        "description": f"{desc_lead}{src_label}",
        "category": p.program_kind or "制度",
        "guid": f"jpcite:program:{p.unified_id}",
        "pub_date": format_datetime(pub_dt),
    }


def _amendment_to_item(a: AmendmentItem, *, domain: str) -> dict:
    field_label = _AMENDMENT_FIELDS_JA.get(a.field_name, a.field_name)
    prev_s = _truncate(a.prev_value, 60)
    new_s = _truncate(a.new_value, 60)
    title = f"[{field_label}] {a.entity_id}"
    desc = f"prev: {prev_s} → new: {new_s}"
    pub_dt = _parse_iso(a.detected_at)
    return {
        "title": title,
        # Audit log surface — links to the data-freshness page since
        # individual am_entities canonical IDs aren't routed in the static
        # site (the entity-fact graph is API-only).
        "link": f"https://{domain}/audit-log.html#diff-{a.diff_id}",
        "description": desc,
        "category": field_label,
        "guid": f"jpcite:amendment:{a.diff_id}",
        "pub_date": format_datetime(pub_dt),
    }


# ---------------------------------------------------------------------------
# Build & write
# ---------------------------------------------------------------------------
def build_tier_s_feed(programs: list[ProgramItem], *, domain: str, lastmod: datetime) -> str:
    items = [_program_to_item(p, domain=domain) for p in programs]
    return _render_rss(
        title="jpcite — Tier S 制度 (補助金/融資/税制/認定 高信頼)",
        description=(
            "jpcite Tier S 制度 (出典リンク + 高信頼バッジ) の最新 100 件。"
            "定期再生成、ID/鮮度安定。"
        ),
        feed_url=f"https://{domain}/rss/programs-tier-s.xml",
        home_url=f"https://{domain}/",
        items=items,
        last_build=lastmod,
    )


def build_amendment_feed(amendments: list[AmendmentItem], *, domain: str, lastmod: datetime) -> str:
    items = [_amendment_to_item(a, domain=domain) for a in amendments]
    return _render_rss(
        title="jpcite — 制度改正検出ログ",
        description=(
            "jpcite が一次出典の差分追跡で検出した制度改正イベント。"
            "金額・補助率・対象・出典 URL の差分を時系列で配信。"
            "制度情報の更新確認に使えます。"
        ),
        feed_url=f"https://{domain}/rss/amendments.xml",
        home_url=f"https://{domain}/",
        items=items,
        last_build=lastmod,
    )


def build_prefecture_feed(
    prefecture_ja: str,
    programs: list[ProgramItem],
    *,
    domain: str,
    lastmod: datetime,
) -> str:
    items = [_program_to_item(p, domain=domain) for p in programs]
    slug = PREFECTURE_SLUG[prefecture_ja]
    return _render_rss(
        title=f"jpcite — {prefecture_ja} 制度フィード",
        description=(
            f"{prefecture_ja} 内で検索可能な制度 (補助金/融資/税制/認定、Tier S+A+B+C、最大 100 件)。"
            "公式出典 URL を優先し、地域別に講読できます。"
        ),
        feed_url=f"https://{domain}/rss/prefecture/{slug}.xml",
        home_url=f"https://{domain}/",
        items=items,
        last_build=lastmod,
    )


def _write_if_changed(path: Path, content: str, *, dry_run: bool) -> bool:
    if dry_run:
        logger.info("would_write path=%s bytes=%d", path, len(content.encode("utf-8")))
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing == content:
            return False
    path.write_text(content, encoding="utf-8")
    return True


def run(
    *,
    jpintel_db: Path,
    autonomath_db: Path,
    out_dir: Path,
    site_dir: Path,
    domain: str,
    dry_run: bool,
    lastmod: datetime,
) -> dict[str, int]:
    counters: dict[str, int] = {
        "tier_s_items": 0,
        "amendment_items": 0,
        "prefecture_files": 0,
        "prefecture_items_total": 0,
        "wrote": 0,
    }

    # ---- A. Tier S feed (jpintel.db) ----
    if not jpintel_db.exists():
        raise SystemExit(f"jpintel_db not found: {jpintel_db}")
    jpintel_uri = f"file:{jpintel_db}?mode=ro"
    j_conn = sqlite3.connect(jpintel_uri, uri=True)
    try:
        tier_s = _load_tier_s_programs(j_conn, site_dir=site_dir)
        counters["tier_s_items"] = len(tier_s)
        feed_a = build_tier_s_feed(tier_s, domain=domain, lastmod=lastmod)
        if _write_if_changed(out_dir / "programs-tier-s.xml", feed_a, dry_run=dry_run):
            counters["wrote"] += 1

        # ---- C. Prefecture feeds (jpintel.db) ----
        by_pref = _load_prefecture_programs(j_conn, site_dir=site_dir)
        for pref_ja, slug in PREFECTURE_SLUG.items():
            programs = by_pref.get(pref_ja, [])
            if not programs:
                # Skip empty prefectures — the static site already 404s on a
                # zero-program region. Emitting an empty feed would be a
                # negative-signal SEO surface (Google Discover penalizes
                # near-empty feeds).
                continue
            feed_c = build_prefecture_feed(pref_ja, programs, domain=domain, lastmod=lastmod)
            if _write_if_changed(out_dir / "prefecture" / f"{slug}.xml", feed_c, dry_run=dry_run):
                counters["wrote"] += 1
            counters["prefecture_files"] += 1
            counters["prefecture_items_total"] += len(programs)
    finally:
        j_conn.close()

    # ---- B. Amendment feed (autonomath.db) ----
    if not autonomath_db.exists():
        logger.warning("autonomath_db missing path=%s — skipping amendments feed", autonomath_db)
    else:
        au_uri = f"file:{autonomath_db}?mode=ro"
        a_conn = sqlite3.connect(au_uri, uri=True)
        try:
            amendments = _load_amendments(a_conn)
            counters["amendment_items"] = len(amendments)
            feed_b = build_amendment_feed(amendments, domain=domain, lastmod=lastmod)
            if _write_if_changed(out_dir / "amendments.xml", feed_b, dry_run=dry_run):
                counters["wrote"] += 1
        finally:
            a_conn.close()

    logger.info(
        "rss_feeds_done tier_s=%d amendments=%d prefectures=%d (%d items) wrote=%d",
        counters["tier_s_items"],
        counters["amendment_items"],
        counters["prefecture_files"],
        counters["prefecture_items_total"],
        counters["wrote"],
    )
    return counters


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    p.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument("--dry-run", action="store_true")
    # Test-only override so byte-identical idempotency can be asserted
    # without a live clock.
    p.add_argument(
        "--lastmod",
        type=str,
        default=None,
        help="ISO-8601 datetime override for <lastBuildDate> (test only)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)
    lastmod = _parse_iso(args.lastmod) if args.lastmod else datetime.now(UTC).replace(microsecond=0)
    try:
        counters = run(
            jpintel_db=args.jpintel_db,
            autonomath_db=args.autonomath_db,
            out_dir=args.out_dir,
            site_dir=args.site_dir,
            domain=args.domain,
            dry_run=bool(args.dry_run),
            lastmod=lastmod,
        )
    except Exception:
        logger.exception("rss_feeds_generate_failed")
        return 1
    if counters["tier_s_items"] == 0:
        logger.warning("no tier S programs found — Tier S feed will be empty")
    return 0


if __name__ == "__main__":
    sys.exit(main())
