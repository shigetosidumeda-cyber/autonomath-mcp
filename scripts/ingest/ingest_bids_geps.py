#!/usr/bin/env python3
"""Ingest 政府電子調達 (GEPS) / 調達ポータル bids into migration-017 `bids` table.

Scope (per docs/POST_DEPLOY expansion plan, 2026-04-24):
    GEPS is the national e-procurement portal run by デジタル庁. It publishes
    bulk CSV dumps under CC-BY 4.0 — attribution required
    ("出典: 調達ポータル（デジタル庁）"). No API; downloads only.

Source layout (調達ポータル bulk-download section):
    * Monthly full dump (current + 2 prior fiscal years) — ZIP of Shift_JIS CSVs.
    * Daily diff file — yesterday's adds/updates only.
    * Fiscal-year backfill archives — one ZIP per fiscal year, FY2013 onward.

This script:
    1. Downloads the ZIP for the selected mode
       (full / diff / backfill per --fiscal-year).
    2. Streams rows (Shift_JIS, cp932 errors='replace') — no whole-file
       decode in memory.
    3. Maps each row → migration-017 `bids` column set and UPSERTs.
    4. Mirrors to `bids_fts` (trigram FTS).
    5. Respects polite rate limit (1 req / 3 sec) for any discover /
       secondary fetches.

What this script does NOT do:
    * Scrape NJSS or other aggregators — CLAUDE.md 詐欺-risk rule.
    * Hammer GEPS beyond 1 req/3 sec — risk of IP block.
    * Touch the DB when `--dry-run` is set (just print counts).

CLI:
    python scripts/ingest/ingest_bids_geps.py --db data/jpintel.db \\
        [--mode full|diff|backfill]   (default: diff)
        [--fiscal-year YYYY]          (required for backfill; e.g. 2024)
        [--since YYYY-MM-DD]          (skip rows with 公告日 older than this)
        [--limit N]                   (stop after N successful UPSERTs)
        [--dry-run]

Exit codes:
    0  success
    1  unrecoverable fetch / ZIP error
    2  CSV column drift beyond the column map (>20% rows unmapped)
    3  output quality gate: 0 rows inserted on a non-empty source

Source URL pattern (per p-portal.go.jp observed layout — see SOURCE_URL_TODO):
    https://www.p-portal.go.jp/pps-web-biz/UZT001Kensaku?case_no=<案件番号>
    The query-string permalink is used when the 案件番号 is present; otherwise
    we fall back to the ZIP URL with a ``#<案件番号>`` fragment and log WARN.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import sqlite3
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import requests  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("jpintel.ingest_bids_geps")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
CACHE_DIR = Path("/tmp/jpintel_geps_cache")
LOG_DIR = REPO_ROOT / "data"

USER_AGENT = (
    "AutonoMath/jpintel-mcp bulk ingest (contact: info@bookyou.net) "
    "+https://autonomath.bookyou.net/"
)
HTTP_TIMEOUT = 180
MAX_RETRIES = 3
RATE_LIMIT_SECONDS = 3.0  # spec: 1 req / 3 sec

# ---------------------------------------------------------------------------
# Source URL templates
#
# NOTE (SOURCE_URL_TODO): the exact permalink pattern for individual bid
# case records on 調達ポータル is documented only inside the portal UI.
# From direct observation 2026-04 the search-result link format appears to
# be ``/pps-web-biz/UZT001Kensaku?case_no=<案件番号>``. We use that when
# 案件番号 is populated; when it's blank or the pattern is wrong we fall
# back to the ZIP URL with a `#<案件番号>` fragment and log a WARN so the
# lineage-audit catches it. The ZIP URL itself is always a valid primary
# citation under CC-BY 4.0 — the fragment is additive, not a substitute.
# ---------------------------------------------------------------------------
P_PORTAL_ROOT = "https://www.p-portal.go.jp/"
CASE_PERMALINK_TEMPLATE = "https://www.p-portal.go.jp/pps-web-biz/UZT001Kensaku?case_no={case_no}"

# GEPS bulk-download URLs. These are documented inside the portal and
# observed on 2026-04. If the deployment moves them, update here — the
# rest of the script is URL-agnostic.
BULK_URL_FULL_MONTHLY = "https://www.p-portal.go.jp/pps-web-biz/opendata/monthly_full_latest.zip"
BULK_URL_DIFF_DAILY = "https://www.p-portal.go.jp/pps-web-biz/opendata/daily_diff_latest.zip"
BULK_URL_FY_TEMPLATE = "https://www.p-portal.go.jp/pps-web-biz/opendata/fy{fiscal_year}_full.zip"


# ---------------------------------------------------------------------------
# CSV column mapping (GEPS 調達ポータル bulk-download schema)
#
# The CSV header names below are drawn from the column list 調達ポータル
# publishes under the open-data bulk-download section. Several columns have
# near-synonyms (`件名` vs `調達案件名称`, `発注機関` vs `発注機関名`) and
# the portal has shipped two layouts since 2019. We accept all known
# synonyms and map them to a single canonical key; the mapper is driven by
# membership in a set, not positional indexing, so column-order drift is
# tolerated as long as the header names are present.
#
# Un-verified / TODO columns are marked inline. If any of these prove
# absent at run time the row loses that single field (non-fatal); the log
# counts `col_missing` so quality can be monitored.
# ---------------------------------------------------------------------------
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "case_number": ("案件番号", "調達案件番号", "公告番号"),
    "bid_title": ("件名", "調達案件名称", "案件名", "調達件名"),
    "bid_kind_jp": ("入札方式", "調達方式", "契約方式"),
    "procuring_entity": ("発注機関", "発注機関名", "調達機関", "調達機関名"),
    "procuring_houjin_bangou": ("発注者法人番号", "発注機関法人番号", "法人番号"),
    "ministry": ("所管府省", "府省", "省庁"),
    "announcement_date": ("公告日", "公示日", "公告発出日"),
    "question_deadline": ("質問受付期限", "質問期限", "質問書提出期限"),
    "bid_deadline": ("締切日", "入札書提出期限", "入札期限", "開札日"),
    # TODO: 決定日 label varies — "落札日" and "契約日" are both observed.
    # We treat either as decision_date; if both present, 落札日 wins.
    "decision_date": ("落札日", "契約日", "開札日"),
    # 予定価格 is 税込 when disclosed; some rows redact it (non-disclosure).
    "budget_ceiling_yen": ("予定価格", "予定価格（税込）", "契約予定価格"),
    "awarded_amount_yen": (
        "落札金額",
        "契約金額",
        "落札価格",
        "契約金額（税込）",
    ),
    "winner_name": ("落札者", "受注者名", "契約相手方", "落札者名"),
    "winner_houjin_bangou": (
        "落札者法人番号",
        "受注者法人番号",
        "契約相手方法人番号",
    ),
    "participant_count": ("参加者数", "入札参加者数", "応札者数"),
    "bid_description": ("概要", "調達概要", "仕様概要", "調達内容"),
    "eligibility_conditions": ("参加資格", "参加資格要件", "入札参加資格"),
    # TODO: classification code. 調達ポータル has shipped both a 3-class
    # label (物品/役務/工事) and a more granular 8-digit JGS code. We prefer
    # the granular one if present, otherwise the 3-class label.
    "classification_code": ("調達区分", "調達種別", "分類", "JGS"),
}


# 入札方式 → migration-017 enum. See 017_bids.sql line 68 for the canonical
# enum list. `kobo_subsidy` is the catch-all for proposal-style procurements
# where what's being procured is a subsidy-adjacent proposal rather than a
# straight 物品 / 役務 / 工事 order — 公募型指名競争入札 / 企画競争 /
# プロポーザル方式 all land here.
BID_KIND_MAP: dict[str, str] = {
    "一般競争": "open",
    "一般競争入札": "open",
    "指名競争": "selective",
    "指名競争入札": "selective",
    "随意契約": "negotiated",
    "随契": "negotiated",
    "公募型指名競争入札": "kobo_subsidy",
    "公募型": "kobo_subsidy",
    "公募": "kobo_subsidy",
    "企画競争": "kobo_subsidy",
    "プロポーザル": "kobo_subsidy",
    "プロポーザル方式": "kobo_subsidy",
}


# Canonical 47-都道府県 list inlined from src/jpintel_mcp/api/vocab.py so the
# ingest script stays self-contained (runs without the package installed).
_PREFECTURES_CANONICAL: tuple[str, ...] = (
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
)


# Aggregator domains banned from source_url (CLAUDE.md rule; mirrors
# scripts/ingest_external_data.py BANNED_SOURCE_HOSTS). GEPS itself is
# a primary origin so this exists only as a guard against future mistakes.
BANNED_SOURCE_HOSTS: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
    "njss",
    "nyusatsu-navi",
)


# ---------------------------------------------------------------------------
# Dataclass mirroring `bids` columns (migration 017)
# ---------------------------------------------------------------------------


@dataclass
class BidRecord:
    unified_id: str
    bid_title: str
    bid_kind: str
    procuring_entity: str
    procuring_houjin_bangou: str | None
    ministry: str | None
    prefecture: str | None
    program_id_hint: str | None
    announcement_date: str | None
    question_deadline: str | None
    bid_deadline: str | None
    decision_date: str | None
    budget_ceiling_yen: int | None
    awarded_amount_yen: int | None
    winner_name: str | None
    winner_houjin_bangou: str | None
    participant_count: int | None
    bid_description: str | None
    eligibility_conditions: str | None
    classification_code: str | None
    source_url: str
    source_excerpt: str | None
    source_checksum: str | None
    confidence: float
    fetched_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strip(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    # GEPS sometimes fills blanks with "-" or "－" (全角) as a placeholder.
    if s in ("", "-", "－", "なし", "該当なし"):
        return None
    return s


def _normalize_date(v: Any) -> str | None:
    """Accept YYYY/MM/DD, YYYY-MM-DD, YYYYMMDD, 和暦 variants — emit ISO YYYY-MM-DD.

    和暦 parsing is best-effort (covers 令和 / 平成); anything else is returned
    as-is. Downstream queries tolerate free-form text since the column is
    TEXT in the schema.
    """
    s = _strip(v)
    if not s:
        return None
    # YYYY/MM/DD or YYYY-MM-DD
    for sep in ("/", "-", "."):
        if sep in s and len(s.split(sep)[0]) == 4:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    y = int(parts[0])
                    m = int(parts[1])
                    d = int(parts[2])
                    return f"{y:04d}-{m:02d}-{d:02d}"
                except ValueError:
                    pass
    # YYYYMMDD
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    # 和暦: 令和6年4月1日 / 平成31年3月1日
    for era, base in (("令和", 2018), ("平成", 1988), ("昭和", 1925)):
        if s.startswith(era):
            try:
                rest = s[len(era) :]
                y_str, _, rest = rest.partition("年")
                m_str, _, rest = rest.partition("月")
                d_str, _, _ = rest.partition("日")
                # 令和元年 → 令和1年
                if y_str in ("元", "元年"):
                    y_str = "1"
                y = base + int(y_str)
                m = int(m_str)
                d = int(d_str)
                return f"{y:04d}-{m:02d}-{d:02d}"
            except (ValueError, IndexError):
                pass
    return s  # fallthrough: keep original string


def _normalize_amount_yen(v: Any) -> int | None:
    """Parse 金額 to integer 円. Drops commas / 全角カンマ / 円 suffix.

    Returns None for anything that isn't parseable — GEPS commonly redacts
    amounts on 随契 rows by writing 非公表 / 秘密 / empty.
    """
    s = _strip(v)
    if not s:
        return None
    if s in ("非公表", "秘密", "不明", "未定"):
        return None
    # strip 円 / commas / spaces / thin space / fullwidth comma
    cleaned = s.replace(",", "").replace(",", "").replace(" ", "").replace("　", "")
    cleaned = cleaned.rstrip("円").rstrip("￥").lstrip("¥").lstrip("￥")
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _normalize_int(v: Any) -> int | None:
    s = _strip(v)
    if not s:
        return None
    try:
        return int(s.replace(",", "").replace(",", ""))
    except ValueError:
        return None


def _normalize_bid_kind(jp: Any) -> str:
    """Map JP label → enum. Unknown defaults to 'open' with a WARN log.

    Defaulting (rather than raising) because the CHECK constraint only
    allows the four listed values — an unknown label from column drift
    would crash the whole ZIP. Logging lets us catch drift without losing
    the row.
    """
    s = _strip(jp)
    if not s:
        return "open"
    # Exact match first.
    if s in BID_KIND_MAP:
        return BID_KIND_MAP[s]
    # Substring match (handles decorated labels like "一般競争入札（総合評価）").
    for key, mapped in BID_KIND_MAP.items():
        if key in s:
            return mapped
    _LOG.warning("bid_kind_unknown raw=%r defaulted=open", s)
    return "open"


def _infer_prefecture(procuring_entity: str | None) -> str | None:
    """Find 47都道府県 substring in procuring_entity; None for ministry-level.

    Returns the canonical form ("東京都", not "東京"). Ministry-level bids
    (農林水産省, 国土交通省 etc.) have no prefecture → None. Regional bureau
    names ("国土交通省関東地方整備局") also yield None intentionally — we
    don't guess from 関東 / 近畿 (no single pref).
    """
    if not procuring_entity:
        return None
    for pref in _PREFECTURES_CANONICAL:
        if pref in procuring_entity:
            return pref
    # Try short form ("東京" without "都") — rare but observed.
    for pref in _PREFECTURES_CANONICAL:
        short = pref.rstrip("都道府県") if pref != "北海道" else "北海道"
        if short and short in procuring_entity and len(short) >= 2:
            return pref
    return None


def _source_url_for(case_number: str | None, zip_url: str) -> tuple[str, bool]:
    """Build the primary-citation URL. Returns (url, used_fallback).

    used_fallback=True means we couldn't construct a permalink and fell
    back to the ZIP URL + `#case_no` fragment. The caller logs a WARN in
    that path so lineage-audit dashboards catch it.
    """
    if case_number:
        return CASE_PERMALINK_TEMPLATE.format(case_no=quote(case_number, safe="")), False
    return f"{zip_url}#unknown_case_no", True


def _unified_id(case_number: str, procuring_entity: str, announcement_date: str) -> str:
    """BID-<10 hex> keyed on (case_number, procuring_entity, announcement_date).

    Case number alone is not unique — ministries reuse the same number
    across fiscal years. The triple key is stable across portal revisions.
    """
    blob = f"{case_number}|{procuring_entity}|{announcement_date}".encode()
    digest = hashlib.sha256(blob).hexdigest()[:10]
    return f"BID-{digest}"


def _row_checksum(row: dict[str, Any]) -> str:
    """SHA-256 over the sorted canonical keys — detects upstream mutation."""
    canonical = "|".join(f"{k}={row.get(k) or ''}" for k in sorted(row))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _excerpt(row: dict[str, Any]) -> str:
    """Small, auditable excerpt — the fields a human needs to verify lineage."""
    parts = [
        f"件名: {row.get('bid_title') or ''}",
        f"発注: {row.get('procuring_entity') or ''}",
        f"落札者: {row.get('winner_name') or ''}",
        f"落札金額: {row.get('awarded_amount_yen') or ''}",
    ]
    return " / ".join(p for p in parts if p)


def _source_url_is_banned(url: str | None) -> bool:
    if not url:
        return False
    low = url.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


def _column_picker(header: list[str]) -> dict[str, int | None]:
    """Return {canonical_key: column_index_or_None} per COLUMN_ALIASES."""
    normalized = [h.strip().lstrip("﻿") for h in header]
    idx_of: dict[str, int | None] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        idx: int | None = None
        for alias in aliases:
            if alias in normalized:
                idx = normalized.index(alias)
                break
        idx_of[canonical] = idx
    return idx_of


# ---------------------------------------------------------------------------
# HTTP (rate-limited with retries; streaming for ZIP body)
# ---------------------------------------------------------------------------


def polite_get_bytes(url: str, tries: int = MAX_RETRIES) -> bytes:
    """Rate-limited GET returning the body. Streaming under the hood.

    Rate limit is enforced *after* the request finishes so a slow response
    doesn't double-count against the 1-req/3-sec budget.
    """
    headers = {"User-Agent": USER_AGENT}
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            with requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=HTTP_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                resp.raise_for_status()
                buf = io.BytesIO()
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        buf.write(chunk)
                body = buf.getvalue()
            time.sleep(RATE_LIMIT_SECONDS)
            return body
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait = 2**attempt
            _LOG.warning(
                "retry attempt=%d/%d url=%s err=%s sleep=%ds",
                attempt,
                tries,
                url,
                exc,
                wait,
            )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def fetch_zip_to_cache(url: str) -> Path:
    """Download ZIP (or reuse cached copy) and return local path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fname = url.rsplit("/", 1)[-1] or "geps_bulk.zip"
    local = CACHE_DIR / fname
    if local.exists() and local.stat().st_size > 10_000:
        _LOG.info("zip_cached path=%s size=%d", local, local.stat().st_size)
        return local
    body = polite_get_bytes(url)
    local.write_bytes(body)
    _LOG.info("zip_fetched url=%s size=%d", url, len(body))
    return local


# ---------------------------------------------------------------------------
# CSV → BidRecord
# ---------------------------------------------------------------------------


def iter_csv_rows_from_zip(zip_path: Path) -> Any:
    """Yield (csv_member_name, list[str] row) tuples without materialising.

    CP932 (Shift_JIS superset) with errors='replace' to survive the handful
    of rows upstream miscodes. Each CSV file in the ZIP is streamed: we do
    NOT call .read() on the whole file, we wrap the member file object in
    a TextIOWrapper so the csv module pulls lazily.
    """
    with zipfile.ZipFile(zip_path) as zf:
        csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_members:
            raise RuntimeError(f"no CSV members in {zip_path}")
        for member in csv_members:
            with zf.open(member, "r") as raw:
                text = io.TextIOWrapper(raw, encoding="cp932", errors="replace", newline="")
                reader = csv.reader(text)
                try:
                    header = next(reader)
                except StopIteration:
                    continue
                yield member, header, reader


def map_row_to_record(
    member: str,
    header_idx: dict[str, int | None],
    row: list[str],
    zip_url: str,
    fetched_at: str,
    *,
    unmapped_counter: dict[str, int],
) -> BidRecord | None:
    """Translate one CSV row into a BidRecord. Returns None if required fields missing.

    Required: case_number, procuring_entity, announcement_date, bid_title.
    If any are missing the row is dropped and unmapped_counter['skip_missing']
    is incremented so the quality gate can fire (>20% drop).
    """

    def get(key: str) -> str | None:
        i = header_idx.get(key)
        if i is None or i >= len(row):
            return None
        return _strip(row[i])

    case_number = get("case_number") or ""
    procuring_entity = get("procuring_entity") or ""
    announcement_date = _normalize_date(get("announcement_date")) or ""
    bid_title = get("bid_title") or ""

    if not (case_number and procuring_entity and announcement_date and bid_title):
        unmapped_counter["skip_missing"] = unmapped_counter.get("skip_missing", 0) + 1
        return None

    uid = _unified_id(case_number, procuring_entity, announcement_date)
    source_url, used_fallback = _source_url_for(case_number, zip_url)
    if used_fallback:
        _LOG.warning(
            "source_url_fallback case_number=%r zip=%s",
            case_number,
            zip_url,
        )

    # Attribution / lineage guard: should never trigger for GEPS, kept for
    # defence against future source additions.
    if _source_url_is_banned(source_url):
        unmapped_counter["skip_banned"] = unmapped_counter.get("skip_banned", 0) + 1
        return None

    raw_excerpt_fields: dict[str, Any] = {
        "bid_title": bid_title,
        "procuring_entity": procuring_entity,
        "winner_name": get("winner_name"),
        "awarded_amount_yen": get("awarded_amount_yen"),
    }

    rec = BidRecord(
        unified_id=uid,
        bid_title=bid_title,
        bid_kind=_normalize_bid_kind(get("bid_kind_jp")),
        procuring_entity=procuring_entity,
        procuring_houjin_bangou=get("procuring_houjin_bangou"),
        ministry=get("ministry"),
        prefecture=_infer_prefecture(procuring_entity),
        program_id_hint=None,  # populated by a separate matcher pass
        announcement_date=announcement_date,
        question_deadline=_normalize_date(get("question_deadline")),
        bid_deadline=_normalize_date(get("bid_deadline")),
        decision_date=_normalize_date(get("decision_date")),
        budget_ceiling_yen=_normalize_amount_yen(get("budget_ceiling_yen")),
        awarded_amount_yen=_normalize_amount_yen(get("awarded_amount_yen")),
        winner_name=get("winner_name"),
        winner_houjin_bangou=get("winner_houjin_bangou"),
        participant_count=_normalize_int(get("participant_count")),
        bid_description=get("bid_description"),
        eligibility_conditions=get("eligibility_conditions"),
        classification_code=get("classification_code"),
        source_url=source_url,
        source_excerpt=_excerpt(raw_excerpt_fields),
        source_checksum=_row_checksum(
            {k: (get(k) if header_idx.get(k) is not None else None) for k in COLUMN_ALIASES}
        ),
        confidence=0.95,  # bulk primary source with attribution
        fetched_at=fetched_at,
        updated_at=fetched_at,
    )
    return rec


# ---------------------------------------------------------------------------
# DB UPSERT
# ---------------------------------------------------------------------------


_UPSERT_SQL = """
INSERT INTO bids (
    unified_id, bid_title, bid_kind, procuring_entity, procuring_houjin_bangou,
    ministry, prefecture, program_id_hint,
    announcement_date, question_deadline, bid_deadline, decision_date,
    budget_ceiling_yen, awarded_amount_yen,
    winner_name, winner_houjin_bangou, participant_count,
    bid_description, eligibility_conditions, classification_code,
    source_url, source_excerpt, source_checksum,
    confidence, fetched_at, updated_at
) VALUES (
    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
)
ON CONFLICT(unified_id) DO UPDATE SET
    bid_title = excluded.bid_title,
    bid_kind = excluded.bid_kind,
    procuring_entity = excluded.procuring_entity,
    procuring_houjin_bangou = COALESCE(excluded.procuring_houjin_bangou, bids.procuring_houjin_bangou),
    ministry = COALESCE(excluded.ministry, bids.ministry),
    prefecture = COALESCE(excluded.prefecture, bids.prefecture),
    program_id_hint = COALESCE(bids.program_id_hint, excluded.program_id_hint),
    announcement_date = COALESCE(excluded.announcement_date, bids.announcement_date),
    question_deadline = COALESCE(excluded.question_deadline, bids.question_deadline),
    bid_deadline = COALESCE(excluded.bid_deadline, bids.bid_deadline),
    decision_date = COALESCE(excluded.decision_date, bids.decision_date),
    budget_ceiling_yen = COALESCE(excluded.budget_ceiling_yen, bids.budget_ceiling_yen),
    awarded_amount_yen = COALESCE(excluded.awarded_amount_yen, bids.awarded_amount_yen),
    winner_name = COALESCE(excluded.winner_name, bids.winner_name),
    winner_houjin_bangou = COALESCE(excluded.winner_houjin_bangou, bids.winner_houjin_bangou),
    participant_count = COALESCE(excluded.participant_count, bids.participant_count),
    bid_description = COALESCE(excluded.bid_description, bids.bid_description),
    eligibility_conditions = COALESCE(excluded.eligibility_conditions, bids.eligibility_conditions),
    classification_code = COALESCE(excluded.classification_code, bids.classification_code),
    source_url = excluded.source_url,
    source_excerpt = excluded.source_excerpt,
    source_checksum = excluded.source_checksum,
    confidence = MAX(bids.confidence, excluded.confidence),
    fetched_at = excluded.fetched_at,
    updated_at = excluded.updated_at
"""


def upsert_record(conn: sqlite3.Connection, rec: BidRecord) -> str:
    """UPSERT a single BidRecord; mirror to bids_fts; return 'insert'/'update'."""
    existed = (
        conn.execute("SELECT 1 FROM bids WHERE unified_id = ?", (rec.unified_id,)).fetchone()
        is not None
    )
    conn.execute(
        _UPSERT_SQL,
        (
            rec.unified_id,
            rec.bid_title,
            rec.bid_kind,
            rec.procuring_entity,
            rec.procuring_houjin_bangou,
            rec.ministry,
            rec.prefecture,
            rec.program_id_hint,
            rec.announcement_date,
            rec.question_deadline,
            rec.bid_deadline,
            rec.decision_date,
            rec.budget_ceiling_yen,
            rec.awarded_amount_yen,
            rec.winner_name,
            rec.winner_houjin_bangou,
            rec.participant_count,
            rec.bid_description,
            rec.eligibility_conditions,
            rec.classification_code,
            rec.source_url,
            rec.source_excerpt,
            rec.source_checksum,
            rec.confidence,
            rec.fetched_at,
            rec.updated_at,
        ),
    )
    # FTS mirror: delete + insert keeps the row fresh on updates. The FTS
    # table has no UNIQUE on unified_id (it's UNINDEXED) so the manual
    # delete is required.
    conn.execute("DELETE FROM bids_fts WHERE unified_id = ?", (rec.unified_id,))
    conn.execute(
        "INSERT INTO bids_fts (unified_id, bid_title, bid_description, "
        "procuring_entity, winner_name) VALUES (?,?,?,?,?)",
        (
            rec.unified_id,
            rec.bid_title or "",
            rec.bid_description or "",
            rec.procuring_entity or "",
            rec.winner_name or "",
        ),
    )
    return "update" if existed else "insert"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def resolve_source_url(mode: str, fiscal_year: int | None) -> str:
    if mode == "full":
        return BULK_URL_FULL_MONTHLY
    if mode == "diff":
        return BULK_URL_DIFF_DAILY
    if mode == "backfill":
        if fiscal_year is None:
            raise SystemExit("--fiscal-year is required for --mode backfill")
        return BULK_URL_FY_TEMPLATE.format(fiscal_year=fiscal_year)
    raise SystemExit(f"unknown mode: {mode}")


def run(
    db_path: Path,
    mode: str,
    fiscal_year: int | None,
    since: str | None,
    limit: int | None,
    dry_run: bool,
) -> int:
    fetched_at = _now_iso()
    zip_url = resolve_source_url(mode, fiscal_year)

    _LOG.info("mode=%s fiscal_year=%s since=%s zip_url=%s", mode, fiscal_year, since, zip_url)
    try:
        zip_path = fetch_zip_to_cache(zip_url)
    except Exception as exc:  # noqa: BLE001
        _LOG.error("fetch_failed url=%s err=%s", zip_url, exc)
        return 1

    counts: dict[str, int] = {
        "read": 0,
        "insert": 0,
        "update": 0,
        "skip_since": 0,
        "skip_missing": 0,
        "skip_banned": 0,
        "skip_check": 0,
    }

    conn: sqlite3.Connection | None = None
    if not dry_run:
        if not db_path.is_file():
            _LOG.error("db_missing path=%s (run scripts/migrate.py first)", db_path)
            return 1
        conn = sqlite3.connect(str(db_path), isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("BEGIN")

    try:
        for member, header, reader in iter_csv_rows_from_zip(zip_path):
            header_idx = _column_picker(header)
            missing = [k for k, v in header_idx.items() if v is None]
            _LOG.info(
                "csv_member name=%s cols=%d unmapped_keys=%s",
                member,
                len(header),
                missing,
            )

            for raw_row in reader:
                if not any((c or "").strip() for c in raw_row):
                    continue
                counts["read"] += 1

                rec = map_row_to_record(
                    member,
                    header_idx,
                    raw_row,
                    zip_url,
                    fetched_at,
                    unmapped_counter=counts,
                )
                if rec is None:
                    continue

                # --since filter on announcement_date (ISO lex-compare).
                if since and rec.announcement_date and rec.announcement_date < since:
                    counts["skip_since"] += 1
                    continue

                # CHECK constraint guard (defence in depth; schema also guards).
                if rec.bid_kind not in ("open", "selective", "negotiated", "kobo_subsidy"):
                    counts["skip_check"] += 1
                    continue

                if dry_run:
                    counts["insert"] += 1
                else:
                    assert conn is not None
                    verdict = upsert_record(conn, rec)
                    counts[verdict] += 1

                if limit is not None and (counts["insert"] + counts["update"]) >= limit:
                    _LOG.info("limit_reached n=%d", limit)
                    break
            else:
                continue  # inner loop did not break
            break  # limit break propagates out

        if conn is not None:
            conn.execute("COMMIT")
    except Exception:
        if conn is not None:
            conn.execute("ROLLBACK")
        raise
    finally:
        if conn is not None:
            conn.close()

    # Quality gates
    read = counts["read"] or 1
    missing_ratio = counts.get("skip_missing", 0) / read
    _LOG.info("counts=%s missing_ratio=%.2f", counts, missing_ratio)
    if missing_ratio > 0.20 and counts["read"] > 50:
        _LOG.error(
            "column_drift_gate missing_ratio=%.2f >0.20 — CSV column map needs refresh",
            missing_ratio,
        )
        return 2
    if counts["read"] > 0 and (counts["insert"] + counts["update"]) == 0 and not dry_run:
        _LOG.error("zero_rows_gate read=%d but nothing written", counts["read"])
        return 3
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"SQLite DB path (default: {DEFAULT_DB})"
    )
    ap.add_argument(
        "--mode",
        choices=("full", "diff", "backfill"),
        default="diff",
        help="full = monthly full dump; diff = yesterday's diff; "
        "backfill = full fiscal-year archive (requires --fiscal-year)",
    )
    ap.add_argument(
        "--fiscal-year",
        type=int,
        default=None,
        help="FY for --mode backfill (e.g. 2024). Ignored otherwise.",
    )
    ap.add_argument(
        "--since",
        type=str,
        default=None,
        help="Skip rows with announcement_date older than YYYY-MM-DD",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N successful UPSERTs (smoke-test shortcut)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Parse + count only; never write to DB")
    ap.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"ingest_bids_geps_{stamp}.log"
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    _LOG.info(
        "start db=%s mode=%s fiscal_year=%s since=%s limit=%s dry_run=%s log=%s",
        args.db,
        args.mode,
        args.fiscal_year,
        args.since,
        args.limit,
        args.dry_run,
        log_path,
    )
    return run(
        db_path=args.db,
        mode=args.mode,
        fiscal_year=args.fiscal_year,
        since=args.since,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
