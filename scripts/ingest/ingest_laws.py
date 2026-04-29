#!/usr/bin/env python3
"""Ingest 法令 (Japanese statute corpus) from e-Gov 法令 API V2 into `laws`.

Target schema: scripts/migrations/015_laws.sql (`laws` + `laws_fts` + the
join table `program_law_refs`; this script populates the first two — the
join table is out of scope, authored separately from program-side 要綱
parsing).

Coverage target (per 015 header): ~3,400 rows spanning 憲法 + 法律 +
政令 + 勅令 + 府省令 + 規則. License is CC-BY 4.0; attribution
`出典: e-Gov法令検索 (デジタル庁)` is embedded in the `summary` column
for any row whose original API payload does not already carry its own
attribution string.

Endpoints (V2):
    GET {BASE}/laws                 - list/search, returns index entries
    GET {BASE}/law_data/{law_id}    - full text + metadata (JSON)
    GET {BASE}/law_revisions/{id}   - revision chain (currently unused;
                                      `revision_status` is inferred from
                                      the list endpoint's `status` field)

No auth. No published rate limit; we self-throttle to 1 req/sec.

Design guarantees (mirrors scripts/ingest_external_data.py + session.py):
    * Idempotent.   ON CONFLICT(unified_id) DO UPDATE; re-runs skip rows
                    whose checksum matches the stored value.
    * Deterministic unified_id.  LAW-<10hex> = sha256(law_number|law_id).
                    The same (number,id) always produces the same id, so
                    a re-fetch after revision produces the SAME unified_id
                    (the row is UPDATED, not duplicated). A new law gets
                    a new unified_id.
    * FTS mirror.   After every INSERT/UPDATE we DELETE-then-INSERT into
                    `laws_fts` to keep the trigram index current. Same
                    pattern docs/_internal/ingest_automation.md §122.
    * Polite fetch. 1 req/sec via time.sleep; 3-retry exponential back-off
                    on 5xx; 404 logged and skipped; JSON-parse errors
                    logged and skipped (single bad row does not abort).

CLI:
    python scripts/ingest/ingest_laws.py --db data/jpintel.db
    python scripts/ingest/ingest_laws.py --db data/jpintel.db --limit 100
    python scripts/ingest/ingest_laws.py --db data/jpintel.db --law-type act
    python scripts/ingest/ingest_laws.py --db data/jpintel.db --dry-run
    python scripts/ingest/ingest_laws.py --db data/jpintel.db --since 2026-01-01

NOTE: migration 015 must be applied before this script runs.
      `python scripts/migrate.py --db data/jpintel.db` is a separate step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError as exc:  # pragma: no cover - requests is a soft dep
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("jpintel.ingest_laws")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

BASE_URL = "https://laws.e-gov.go.jp/api/2"
PERMALINK_TEMPLATE = "https://laws.e-gov.go.jp/law/{law_id}"
USER_AGENT = "AutonoMath/0.1.0 (+https://zeimu-kaikei.ai)"
RATE_LIMIT_SEC = 1.0
HTTP_TIMEOUT = 30
MAX_RETRIES = 3

ATTRIBUTION_NOTICE = "出典: e-Gov法令検索 (デジタル庁)"

# ---------------------------------------------------------------------------
# Law-type mapping  (API string  ->  015_laws enum)
# ---------------------------------------------------------------------------
# Order matters: we match the longest prefix first so "府省令" beats "省令".
LAW_TYPE_MAP: tuple[tuple[str, str], ...] = (
    ("憲法", "constitution"),
    ("Constitution", "constitution"),
    ("法律", "act"),
    ("Act", "act"),
    ("政令", "cabinet_order"),
    ("CabinetOrder", "cabinet_order"),
    ("勅令", "imperial_order"),
    ("ImperialOrder", "imperial_order"),
    ("府省令", "ministerial_ordinance"),
    ("省令", "ministerial_ordinance"),
    ("府令", "ministerial_ordinance"),
    ("MinisterialOrdinance", "ministerial_ordinance"),
    ("MinisterialOrder", "ministerial_ordinance"),
    ("規則", "rule"),
    ("Rule", "rule"),
    ("告示", "notice"),
    ("Notice", "notice"),
    ("訓令", "guideline"),
    ("通達", "guideline"),
    ("Guideline", "guideline"),
)

VALID_LAW_TYPES: frozenset[str] = frozenset(v for _, v in LAW_TYPE_MAP)

# Reverse lookup for the --law-type filter (enum -> API category codes).
# e-Gov V2 exposes a `law_type` query parameter whose accepted values are
# the Japanese category strings. We send all JP aliases that map to the
# enum so "ministerial_ordinance" filter covers 府省令/省令/府令 alike.
LAW_TYPE_REVERSE: dict[str, list[str]] = {}
for jp, en in LAW_TYPE_MAP:
    LAW_TYPE_REVERSE.setdefault(en, []).append(jp)


# ---------------------------------------------------------------------------
# HTTP client (polite, retrying)
# ---------------------------------------------------------------------------


class EGovClient:
    """Thin wrapper over requests.Session with 1 req/sec + exponential back-off.

    NOT thread-safe; this script is single-threaded on purpose.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "ja,en;q=0.5",
        })
        self._last_call_monotonic: float = 0.0

    def _pace(self) -> None:
        now = time.monotonic()
        wait = RATE_LIMIT_SEC - (now - self._last_call_monotonic)
        if wait > 0:
            time.sleep(wait)
        self._last_call_monotonic = time.monotonic()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, bytes | None, int]:
        """Fetch JSON with retry on 5xx.

        Returns (parsed_body | None, raw_bytes | None, status_code).
        On 404: returns (None, None, 404). On repeated 5xx / network
        failure: returns (None, None, 0).

        Raw bytes are returned alongside the parsed dict so callers can
        compute source_checksum on the exact payload the server sent.
        """
        last_status = 0
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                resp = self._session.get(url, params=params, timeout=HTTP_TIMEOUT)
            except requests.RequestException as exc:
                _LOG.warning("fetch_error url=%s attempt=%d err=%s", url, attempt, exc)
                if attempt == MAX_RETRIES:
                    return None, None, 0
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue

            last_status = resp.status_code
            if resp.status_code == 404:
                return None, None, 404
            if 500 <= resp.status_code < 600:
                _LOG.warning(
                    "fetch_5xx url=%s attempt=%d status=%d", url, attempt, resp.status_code
                )
                if attempt == MAX_RETRIES:
                    return None, None, resp.status_code
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue
            if resp.status_code >= 400:
                _LOG.warning(
                    "fetch_client_error url=%s status=%d body=%s",
                    url, resp.status_code, resp.text[:200],
                )
                return None, None, resp.status_code

            raw = resp.content
            try:
                body = resp.json()
            except ValueError as exc:
                _LOG.warning("json_parse_error url=%s err=%s", url, exc)
                return None, raw, resp.status_code
            return body, raw, resp.status_code

        return None, None, last_status


# ---------------------------------------------------------------------------
# API response adapters
# ---------------------------------------------------------------------------
#
# The e-Gov V2 payload shape is documented at
#     https://laws.e-gov.go.jp/apitop/
# but the exact JSON key names the service ships can drift across
# endpoint/version. To keep the script robust we extract via a small set
# of candidate keys per field. If the key set the live API uses is
# different from any candidate below, the getter returns None and the
# row is ingested with partial metadata (never crashes). TODO: once the
# API payload has been sampled in production, prune the candidate lists
# down to the one true key name.


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None and d[k] != "":
            return d[k]
    return None


def _extract_law_id(entry: dict[str, Any]) -> str | None:
    val = _first(entry, "law_id", "lawId", "LawId", "law_num_id", "id")
    return str(val) if val is not None else None


def _extract_law_number(entry: dict[str, Any]) -> str | None:
    val = _first(entry, "law_num", "lawNum", "LawNum", "law_number")
    return str(val) if val is not None else None


def _extract_law_title(entry: dict[str, Any]) -> str | None:
    val = _first(entry, "law_title", "lawName", "LawName", "law_name", "title")
    return str(val) if val is not None else None


def _extract_law_short_title(entry: dict[str, Any]) -> str | None:
    val = _first(entry, "abbrev", "law_title_kana", "lawAbbreviation", "law_short_title", "abbreviation")
    return str(val) if val is not None else None


def _extract_ministry(entry: dict[str, Any]) -> str | None:
    val = _first(entry, "ministry", "competent_ministry", "Ministry", "responsible_ministry")
    return str(val) if val is not None else None


def _extract_law_type_jp(entry: dict[str, Any]) -> str | None:
    """Return the RAW Japanese/English category string, pre-normalisation.

    V2 returns English CamelCase enums like "Act", "CabinetOrder",
    "ImperialOrder", "MinisterialOrdinance", "Rule" (see law_type field).
    Fallback to `category` (e.g. "刑事", "文化") only if law_type missing.
    """
    val = _first(entry, "law_type", "LawType", "lawType", "law_num_type", "category", "law_category")
    return str(val) if val is not None else None


def _extract_promulgated_date(entry: dict[str, Any]) -> str | None:
    val = _first(entry, "promulgation_date", "PromulgationDate", "promulgated_date")
    return _normalize_iso_date(val)


def _extract_enforced_date(entry: dict[str, Any]) -> str | None:
    val = _first(
        entry,
        "amendment_enforcement_date",
        "enforcement_date",
        "EnforcementDate",
        "enforced_date",
        "effective_date",
    )
    return _normalize_iso_date(val)


def _extract_last_amended_date(entry: dict[str, Any]) -> str | None:
    val = _first(
        entry,
        "amendment_promulgate_date",
        "last_amendment_date",
        "LastAmendmentDate",
        "last_amended_date",
        "last_revision_date",
        "revision_date",
        "updated",
        "updated_at",
    )
    return _normalize_iso_date(val)


def _extract_revision_status(entry: dict[str, Any]) -> str:
    raw = _first(
        entry,
        "repeal_status",
        "current_revision_status",
        "status",
        "revision_status",
        "RevisionStatus",
        "law_status",
    )
    if not raw:
        return "current"
    s = str(raw).lower()
    # V2 uses "None" (no repeal), "Repealed", "CurrentEnforced", "Superseded" (PascalCase)
    # plus Japanese fallbacks in older payloads.
    if "repeal" in s or "廃止" in s:
        return "repealed"
    if "supersed" in s or "改正" in s or "amend" in s:
        return "superseded"
    return "current"


def _extract_superseded_by_api_id(entry: dict[str, Any]) -> str | None:
    """The *API-side* id of the replacing law, pre-unified_id mapping."""
    val = _first(
        entry,
        "superseded_by_law_id",
        "succeeding_law_id",
        "successor_law_id",
        "replaced_by",
    )
    return str(val) if val is not None else None


def _extract_article_count(entry: dict[str, Any]) -> int | None:
    val = _first(entry, "article_count", "ArticleCount", "articles_count")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _extract_summary(entry: dict[str, Any]) -> str | None:
    val = _first(entry, "summary", "abstract", "description", "overview")
    if val is None:
        return None
    return str(val).strip() or None


def _extract_subject_areas(entry: dict[str, Any]) -> list[str] | None:
    val = _first(entry, "subject_areas", "categories", "tags", "keywords")
    if val is None:
        return None
    if isinstance(val, list):
        return [str(x) for x in val if x]
    if isinstance(val, str):
        return [val]
    return None


def _normalize_iso_date(raw: Any) -> str | None:
    """Best-effort: coerce API date strings to ISO 8601 'YYYY-MM-DD'.

    Accepts:
      - 'YYYY-MM-DD'         (pass through)
      - 'YYYYMMDD'           (common in 元号-free 法令 payloads)
      - 'YYYY/MM/DD'         (occasional)
    Any other format returns the raw string unchanged (the schema is
    permissive TEXT, so downstream consumers can still read it, but
    searches on enforced_date should tolerate the drift).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Already ISO.
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    # YYYYMMDD -> YYYY-MM-DD.
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # YYYY/MM/DD -> YYYY-MM-DD.
    if len(s) == 10 and s[4] == "/" and s[7] == "/":
        return s.replace("/", "-")
    return s  # unknown shape; preserve verbatim


def normalize_law_type(raw_jp: str | None) -> str | None:
    """Map an e-Gov category string to a 015 enum value."""
    if not raw_jp:
        return None
    text = raw_jp.strip()
    for jp, en in LAW_TYPE_MAP:
        if jp in text:
            return en
    return None


# ---------------------------------------------------------------------------
# Unified ID + checksum
# ---------------------------------------------------------------------------


def compute_unified_id(law_number: str, law_id_from_api: str) -> str:
    """LAW-<10hex> = sha256(law_number|law_id_from_api)[:10].

    Deterministic so re-runs are idempotent. The 10-char length matches
    the UNI-xxxxxxxxxx / LAW-xxxxxxxxxx convention across migrations
    001-018 (total unified_id length = 14).
    """
    blob = law_number.encode("utf-8") + b"|" + law_id_from_api.encode("utf-8")
    return "LAW-" + hashlib.sha256(blob).hexdigest()[:10]


def compute_source_checksum(raw_body: bytes | None) -> str | None:
    if not raw_body:
        return None
    return hashlib.sha256(raw_body).hexdigest()


# ---------------------------------------------------------------------------
# Fetch orchestration
# ---------------------------------------------------------------------------


def iter_law_index(
    client: EGovClient,
    *,
    law_type_filter: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch the index of laws from GET {BASE}/laws.

    V2 supports pagination via `limit` + `offset` (if the server exposes
    it) OR `page` + `per_page`. We try the modern cursor params first
    and fall back to offset-based. If the response is a flat list we
    treat it as a single page.

    TODO: confirm pagination shape once we see live traffic. The current
    behaviour errs on the safe side — we stop as soon as a page returns
    empty or fewer items than requested.
    """
    per_page = 200
    offset = 0
    collected: list[dict[str, Any]] = []

    while True:
        params: dict[str, Any] = {"limit": per_page, "offset": offset}
        if law_type_filter:
            # Send all Japanese aliases that map to this enum. e-Gov
            # accepts either a single value or comma-joined list depending
            # on endpoint version; we send the first and TODO if server
            # returns 400 we'll need to loop instead.
            jp_aliases = LAW_TYPE_REVERSE.get(law_type_filter, [])
            if jp_aliases:
                params["law_type"] = jp_aliases[0]

        url = f"{BASE_URL}/laws"
        body, _raw, status = client.get_json(url, params=params)
        if body is None:
            _LOG.error("index_fetch_failed offset=%d status=%d", offset, status)
            break

        # Accept several top-level shapes:
        #   {"laws": [...], "total_count": N, "next_offset": M}  — actual V2 shape (verified 2026-04-24)
        #   {"items": [...]}              — occasional alt
        #   [ ... ]                       — flat array fallback
        # V2 entries are nested: {"law_info": {...}, "revision_info": {...}, "current_revision_info": {...}}
        # We flatten revision_info first (older authoritative), then law_info (newer wins), so that
        # top-level keys like law_id / law_num / law_title are accessible to the extractors.
        page: list[dict[str, Any]]
        if isinstance(body, list):
            raw_page = [x for x in body if isinstance(x, dict)]
        elif isinstance(body, dict):
            raw_page = body.get("laws") or body.get("items") or body.get("data") or []
            raw_page = [x for x in raw_page if isinstance(x, dict)]
        else:
            raw_page = []
        page = []
        for entry in raw_page:
            flat = dict(entry)
            for nest_key in ("current_revision_info", "revision_info", "law_info"):
                sub = entry.get(nest_key)
                if isinstance(sub, dict):
                    for k, v in sub.items():
                        if k not in flat or flat[k] is None or flat[k] == "":
                            flat[k] = v
            page.append(flat)

        if not page:
            break
        collected.extend(page)

        if limit is not None and len(collected) >= limit:
            return collected[:limit]

        if len(page) < per_page:
            break
        offset += per_page

    return collected


def fetch_law_detail(client: EGovClient, law_id_from_api: str) -> tuple[dict[str, Any] | None, bytes | None]:
    """GET {BASE}/law_data/{law_id} — full text + metadata.

    Returns (parsed_body | None, raw_bytes | None). The raw bytes feed
    source_checksum; the parsed body is merged with the index entry
    (index for lineage/status, detail for title/dates/article_count).
    """
    url = f"{BASE_URL}/law_data/{law_id_from_api}"
    body, raw, status = client.get_json(url)
    if body is None:
        if status == 404:
            _LOG.info("law_detail_404 law_id=%s", law_id_from_api)
        return None, raw
    # Detail payloads often nest the law under a top-level key.
    if isinstance(body, dict):
        for k in ("law_full_text", "law_data", "law", "data"):
            inner = body.get(k)
            if isinstance(inner, dict):
                return inner, raw
    return body, raw


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------


_UPSERT_SQL = """
INSERT INTO laws (
    unified_id, law_number, law_title, law_short_title, law_type,
    ministry, promulgated_date, enforced_date, last_amended_date,
    revision_status, superseded_by_law_id, article_count,
    full_text_url, summary, subject_areas_json,
    source_url, source_checksum, confidence, fetched_at, updated_at
) VALUES (
    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
)
ON CONFLICT(unified_id) DO UPDATE SET
    law_number         = excluded.law_number,
    law_title          = excluded.law_title,
    law_short_title    = COALESCE(excluded.law_short_title, law_short_title),
    law_type           = excluded.law_type,
    ministry           = COALESCE(excluded.ministry, ministry),
    promulgated_date   = COALESCE(excluded.promulgated_date, promulgated_date),
    enforced_date      = COALESCE(excluded.enforced_date, enforced_date),
    last_amended_date  = COALESCE(excluded.last_amended_date, last_amended_date),
    revision_status    = excluded.revision_status,
    superseded_by_law_id = COALESCE(excluded.superseded_by_law_id, superseded_by_law_id),
    article_count      = COALESCE(excluded.article_count, article_count),
    full_text_url      = COALESCE(excluded.full_text_url, full_text_url),
    summary            = COALESCE(excluded.summary, summary),
    subject_areas_json = COALESCE(excluded.subject_areas_json, subject_areas_json),
    source_url         = excluded.source_url,
    source_checksum    = excluded.source_checksum,
    fetched_at         = excluded.fetched_at,
    updated_at         = excluded.updated_at
"""


def upsert_law(
    conn: sqlite3.Connection,
    *,
    unified_id: str,
    law_number: str,
    law_title: str,
    law_short_title: str | None,
    law_type: str,
    ministry: str | None,
    promulgated_date: str | None,
    enforced_date: str | None,
    last_amended_date: str | None,
    revision_status: str,
    superseded_by_law_id: str | None,
    article_count: int | None,
    full_text_url: str | None,
    summary: str | None,
    subject_areas: list[str] | None,
    source_url: str,
    source_checksum: str | None,
    fetched_at: str,
) -> str:
    """UPSERT into `laws`, sync `laws_fts`, return 'insert' | 'update' | 'skip'.

    SKIP semantics: a row is skipped when the incoming source_checksum
    equals the stored one AND the existing fetched_at is >= the incoming
    fetched_at (avoids rewriting a more-recent pass). The FTS row is not
    rewritten on skip.
    """
    prev = conn.execute(
        "SELECT source_checksum, fetched_at FROM laws WHERE unified_id = ?",
        (unified_id,),
    ).fetchone()

    now = datetime.now(UTC).isoformat()

    if prev is not None:
        prev_cs, prev_fetched = prev["source_checksum"], prev["fetched_at"]
        # Skip if content is byte-identical and the stored row is at
        # least as fresh as the incoming one.
        if (
            source_checksum
            and prev_cs == source_checksum
            and prev_fetched
            and prev_fetched >= fetched_at
        ):
            return "skip"

    subject_areas_json = (
        json.dumps(subject_areas, ensure_ascii=False, separators=(",", ":"))
        if subject_areas else None
    )

    conn.execute(
        _UPSERT_SQL,
        (
            unified_id,
            law_number,
            law_title,
            law_short_title,
            law_type,
            ministry,
            promulgated_date,
            enforced_date,
            last_amended_date,
            revision_status,
            superseded_by_law_id,
            article_count,
            full_text_url,
            summary,
            subject_areas_json,
            source_url,
            source_checksum,
            0.95,  # confidence — matches schema default; e-Gov is a primary source
            fetched_at,
            now,
        ),
    )

    # FTS: DELETE-then-INSERT. laws_fts has no UNIQUE on unified_id so
    # INSERT OR REPLACE does not apply; the explicit DELETE is the
    # documented pattern (docs/_internal/ingest_automation.md §122).
    conn.execute("DELETE FROM laws_fts WHERE unified_id = ?", (unified_id,))
    conn.execute(
        "INSERT INTO laws_fts(unified_id, law_title, law_short_title, law_number, summary) "
        "VALUES (?,?,?,?,?)",
        (
            unified_id,
            law_title,
            law_short_title or "",
            law_number,
            summary or "",
        ),
    )

    return "update" if prev is not None else "insert"


# ---------------------------------------------------------------------------
# Row assembly
# ---------------------------------------------------------------------------


def build_row_from_api(
    *,
    index_entry: dict[str, Any],
    detail_entry: dict[str, Any] | None,
    raw_detail_bytes: bytes | None,
    api_id_to_unified: dict[str, str],
) -> dict[str, Any] | None:
    """Merge index + detail payloads into the 015 `laws` row shape.

    Returns None (and logs) when a mandatory field (law_id / law_number /
    law_title / law_type) cannot be recovered from either payload.
    """
    merged: dict[str, Any] = {}
    # Detail payload wins on overlapping keys (fresher, fuller).
    if detail_entry:
        merged.update(detail_entry)
    for k, v in index_entry.items():
        merged.setdefault(k, v)

    law_id_api = _extract_law_id(merged)
    law_number = _extract_law_number(merged)
    law_title = _extract_law_title(merged)
    law_type_jp = _extract_law_type_jp(merged)
    law_type = normalize_law_type(law_type_jp)

    if not law_id_api or not law_number or not law_title:
        _LOG.warning(
            "skip_missing_core law_id=%s law_number=%s law_title=%s",
            law_id_api, law_number, (law_title or "")[:40],
        )
        return None

    if not law_type:
        _LOG.warning(
            "skip_unmapped_law_type law_id=%s raw_jp=%s", law_id_api, law_type_jp
        )
        return None

    summary = _extract_summary(merged)
    # CC-BY attribution — embed in summary only if the source didn't
    # ship its own. We never overwrite a non-empty summary, so this is
    # additive (a later richer summary stays).
    if summary:
        if ATTRIBUTION_NOTICE not in summary:
            summary = f"{summary}\n\n{ATTRIBUTION_NOTICE}"
    else:
        summary = ATTRIBUTION_NOTICE

    superseded_api_id = _extract_superseded_by_api_id(merged)
    superseded_unified: str | None = None
    if superseded_api_id and superseded_api_id in api_id_to_unified:
        superseded_unified = api_id_to_unified[superseded_api_id]
    elif superseded_api_id:
        # Per spec: leave NULL + log; reconciliation pass later fills it.
        _LOG.info(
            "superseded_forward_ref_unresolved law_id=%s succ=%s",
            law_id_api, superseded_api_id,
        )

    fetched_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    source_url = PERMALINK_TEMPLATE.format(law_id=law_id_api)
    source_checksum = compute_source_checksum(raw_detail_bytes)

    return {
        "unified_id": compute_unified_id(law_number, law_id_api),
        "law_id_api": law_id_api,
        "law_number": law_number,
        "law_title": law_title,
        "law_short_title": _extract_law_short_title(merged),
        "law_type": law_type,
        "ministry": _extract_ministry(merged),
        "promulgated_date": _extract_promulgated_date(merged),
        "enforced_date": _extract_enforced_date(merged),
        "last_amended_date": _extract_last_amended_date(merged),
        "revision_status": _extract_revision_status(merged),
        "superseded_by_law_id": superseded_unified,
        "article_count": _extract_article_count(merged),
        "full_text_url": source_url,
        "summary": summary,
        "subject_areas": _extract_subject_areas(merged),
        "source_url": source_url,
        "source_checksum": source_checksum,
        "fetched_at": fetched_at,
    }


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    root = logging.getLogger("jpintel.ingest_laws")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _passes_since(last_amended_date: str | None, since: str | None) -> bool:
    if not since:
        return True
    if not last_amended_date:
        # No amendment date known → always refetch (safer than silently skipping).
        return True
    return last_amended_date > since


def run(
    *,
    db_path: Path,
    limit: int | None,
    law_type: str | None,
    since: str | None,
    dry_run: bool,
) -> dict[str, int]:
    """Main ingest loop. Returns counts dict."""
    t_start = time.monotonic()
    client = EGovClient()

    _LOG.info(
        "ingest_start db=%s limit=%s law_type=%s since=%s dry_run=%s",
        db_path, limit, law_type, since, dry_run,
    )

    # 1) Index.
    _LOG.info("fetching law index from %s/laws", BASE_URL)
    index = iter_law_index(client, law_type_filter=law_type, limit=limit)
    total = len(index)
    _LOG.info("index_ready total=%d", total)
    if total == 0:
        return {"fetched": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

    # Pre-compute api_id -> unified_id map so we can resolve forward refs
    # in the same pass (best-effort; any truly forward ref is logged and
    # left NULL for a later reconciliation pass).
    api_id_to_unified: dict[str, str] = {}
    for e in index:
        lid = _extract_law_id(e)
        lnum = _extract_law_number(e)
        if lid and lnum:
            api_id_to_unified[lid] = compute_unified_id(lnum, lid)

    # 2) DB handle.
    conn: sqlite3.Connection | None = None
    if not dry_run:
        conn = sqlite3.connect(str(db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")

    counts = {"fetched": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

    try:
        for idx, index_entry in enumerate(index, start=1):
            law_id_api = _extract_law_id(index_entry) or "?"
            law_title_preview = (_extract_law_title(index_entry) or "?")[:40]

            # --since gate: skip laws whose last-amendment predates --since.
            # Applied against the *index* entry so we can avoid a detail
            # fetch entirely when the index carries enough metadata.
            idx_amended = _extract_last_amended_date(index_entry)
            if since and idx_amended and not _passes_since(idx_amended, since):
                _LOG.info(
                    "[%d/%d] %s %s... -> SKIP (since=%s, amended=%s)",
                    idx, total, law_id_api, law_title_preview, since, idx_amended,
                )
                counts["skipped"] += 1
                continue

            # 3) Detail fetch.
            try:
                detail, raw_detail = fetch_law_detail(client, law_id_api)
            except Exception as exc:  # noqa: BLE001 - defensive; log & keep going
                _LOG.warning(
                    "[%d/%d] %s %s... -> ERR (%s)",
                    idx, total, law_id_api, law_title_preview, exc,
                )
                counts["errors"] += 1
                continue

            row = build_row_from_api(
                index_entry=index_entry,
                detail_entry=detail,
                raw_detail_bytes=raw_detail,
                api_id_to_unified=api_id_to_unified,
            )
            if row is None:
                counts["errors"] += 1
                continue
            counts["fetched"] += 1

            if dry_run:
                _LOG.info(
                    "[%d/%d] %s %s... -> %s DRY",
                    idx, total, law_id_api, law_title_preview, row["unified_id"],
                )
                continue

            assert conn is not None
            try:
                conn.execute("BEGIN")
                verdict = upsert_law(
                    conn,
                    unified_id=row["unified_id"],
                    law_number=row["law_number"],
                    law_title=row["law_title"],
                    law_short_title=row["law_short_title"],
                    law_type=row["law_type"],
                    ministry=row["ministry"],
                    promulgated_date=row["promulgated_date"],
                    enforced_date=row["enforced_date"],
                    last_amended_date=row["last_amended_date"],
                    revision_status=row["revision_status"],
                    superseded_by_law_id=row["superseded_by_law_id"],
                    article_count=row["article_count"],
                    full_text_url=row["full_text_url"],
                    summary=row["summary"],
                    subject_areas=row["subject_areas"],
                    source_url=row["source_url"],
                    source_checksum=row["source_checksum"],
                    fetched_at=row["fetched_at"],
                )
                conn.execute("COMMIT")
            except sqlite3.Error as exc:
                conn.execute("ROLLBACK")
                _LOG.warning(
                    "[%d/%d] %s %s... -> ERR (db: %s)",
                    idx, total, law_id_api, law_title_preview, exc,
                )
                counts["errors"] += 1
                continue

            if verdict == "insert":
                counts["inserted"] += 1
                tag = "OK"
            elif verdict == "update":
                counts["updated"] += 1
                tag = "OK"
            else:
                counts["skipped"] += 1
                tag = "SKIP"

            _LOG.info(
                "[%d/%d] %s %s... -> %s %s",
                idx, total, law_id_api, law_title_preview, row["unified_id"], tag,
            )
    finally:
        if conn is not None:
            conn.close()

    elapsed = time.monotonic() - t_start
    _LOG.info(
        "Ingested %d, skipped %d, errors %d in %.1f seconds",
        counts["inserted"] + counts["updated"],
        counts["skipped"],
        counts["errors"],
        elapsed,
    )
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite DB path (default: {DEFAULT_DB})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max laws to ingest (for testing; omit = all)",
    )
    p.add_argument(
        "--law-type",
        type=str,
        default=None,
        choices=sorted(VALID_LAW_TYPES),
        help="filter by law_type enum",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch + parse but do not INSERT",
    )
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help="only re-fetch laws with last_amended_date > since (ISO date, e.g. 2026-01-01)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    if not args.dry_run and not args.db.parent.exists():
        _LOG.error("db parent does not exist: %s", args.db.parent)
        return 2
    try:
        counts = run(
            db_path=args.db,
            limit=args.limit,
            law_type=args.law_type,
            since=args.since,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.error("ingest_failed err=%s", exc, exc_info=True)
        return 1

    print(
        f"Ingested {counts['inserted'] + counts['updated']}, "
        f"skipped {counts['skipped']}, "
        f"errors {counts['errors']} "
        f"(inserts={counts['inserted']} updates={counts['updated']} fetched={counts['fetched']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
