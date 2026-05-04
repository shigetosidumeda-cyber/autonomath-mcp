"""Evidence Packet composer.

Spec source: ``docs/_internal/llm_resilient_business_plan_2026-04-30.md`` §6.

The Evidence Packet is **NOT** a new datastore. It is a composer that
bundles already-shipped services into one envelope so customer LLMs /
agents see one stable wire shape for "give me everything jpcite knows
about this subject, with primary-source citations attached".

Composed from:

  * ``api.source_manifest._resolve_program``      — primary metadata + canonical_id resolution.
  * ``api.source_manifest._build_manifest``       — per-fact provenance + entity rollup (autonomath.db).
  * ``services.funding_stack_checker``            — partner-program verdicts (compat_matrix + exclusion_rules).
  * ``am_amendment_diff``                         — corpus snapshot + change-watch substrate.
  * ``am_source.last_verified``                   — corpus_snapshot_id derivation.

NO LLM imports. NO live HTTP fetches. NO writes — both DB connections
are opened ``mode=ro`` so a misconfigured deploy never mutates the 9.4 GB
autonomath.db through this surface. Citation_verifier (live URL fetch)
is intentionally NOT called here: that would burst the 30s budget per
program; customers call ``POST /v1/citations/verify`` separately on the
citations they actually need to upgrade.

Cache key (spec §6):

    subject_kind | subject_id | include_facts | include_rules |
    include_compression | fields | input_token_price_jpy_per_1m |
    corpus_snapshot_id

In-memory dict, 600s TTL, mirrors ``api/_corpus_snapshot._CACHE`` posture.

Fail-open: every upstream call is wrapped in try/except. On failure the
composer appends a code to ``quality.known_gaps`` and continues.

500-record cap per packet (spec). Anything beyond pages via the
``cursor`` argument; truncation surfaces ``_warning="truncated"``.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import unicodedata
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from jpintel_mcp.api._license_gate import REDISTRIBUTABLE_LICENSES

logger = logging.getLogger("jpintel.services.evidence_packet")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Wire shape version. Bump on backwards-incompatible change.
PACKET_API_VERSION: str = "v1"

#: Cap on records[] per packet. Spec §6.
MAX_RECORDS_PER_PACKET: int = 500

#: Cap on facts surfaced inline per record. Mirrors source_manifest.
MAX_FACTS_PER_RECORD: int = 500

#: Cap on rules surfaced inline per record. Heuristic — enough to show the
#: top blockers without bloating the wire.
MAX_RULES_PER_RECORD: int = 50

#: Subject kinds — closed enum.
SubjectKind = Literal["program", "houjin", "query"]

#: Caller-supplied baselines accepted by the compression estimator.
CompressionSourceBasis = Literal["unknown", "pdf_pages", "token_count"]

#: Packet projection profiles (§4.3 deliverable). The 4 profiles ship one
#: stable wire shape; the difference is which optional sub-blocks survive
#: the projection. Default ``full`` is the unfiltered envelope.
#:
#:   full           — every block the composer produced (no projection).
#:   brief          — drops facts/rules/precomputed/aliases to give callers
#:                    the smallest envelope that still cites primary URLs.
#:   verified_only  — keeps only the citations whose latest
#:                    verification_status == 'verified', and drops facts/
#:                    rules whose source_url is not in that allow-list.
#:                    Use when the caller cannot tolerate inferred/stale
#:                    citations.
#:   changes_only   — keeps records[].recent_changes + their citations,
#:                    drops facts/rules/precomputed/short_summary. Used by
#:                    M&A / 顧問先 watch-list flows.
PacketProfile = Literal["full", "brief", "verified_only", "changes_only"]

#: Closed enum. The 4 valid `verification_status` values mirror
#: ``services.citation_verifier.VerificationResult`` and the
#: ``citation_verification.verification_status`` CHECK constraint
#: (migration 126_citation_verification). Anything else is rewritten
#: to ``'unknown'`` by the composer to preserve the wire contract.
VALID_CITATION_STATUSES: frozenset[str] = frozenset(
    {"verified", "inferred", "unknown", "stale"}
)

#: Default verdict when the citation_verification join returns no row.
#: Matches §28.9 No-Go #1: never default to ``'verified'`` without proof.
_DEFAULT_CITATION_STATUS: str = "unknown"

#: User-facing amendment fields that are safe to expose as compact recent
#: changes. Internal audit/projection fields stay hidden from Evidence Packet
#: callers.
_RECENT_CHANGE_FIELDS: frozenset[str] = frozenset(
    {
        "amount_max_yen",
        "amount_min_yen",
        "deadline",
        "primary_name",
        "source_fetched_at",
        "source_url",
        "status",
        "subsidy_rate",
        "subsidy_rate_max",
    }
)

_RECENT_CHANGE_FIELD_LABELS: dict[str, str] = {
    "amount_max_yen": "上限額",
    "amount_min_yen": "下限額",
    "deadline": "締切",
    "primary_name": "制度名",
    "source_fetched_at": "出典取得日",
    "source_url": "出典URL",
    "status": "募集状態",
    "subsidy_rate": "補助率",
    "subsidy_rate_max": "最大補助率",
}

_RECENT_CHANGE_CAP: int = 5

_ALIAS_CAP: int = 10
_ALIAS_KIND_PRIORITY: dict[str, int] = {
    "canonical": 0,
    "abbreviation": 1,
    "kana": 2,
    "partial": 3,
    "legacy": 4,
    "english": 5,
    "listed": 6,
}

_PDF_FACT_REF_CAP: int = 5
_PDF_FACT_REF_FIELDS: frozenset[str] = frozenset(
    {
        "amount_max_yen",
        "amount_min_yen",
        "deadline",
        "required_documents",
        "source_excerpt",
        "subsidy_rate",
        "subsidy_rate_max",
    }
)

#: Cache TTL — same posture as _corpus_snapshot._CACHE.
_CACHE_TTL_SEC: float = 600.0

#: JST timezone (CLAUDE.md anonymous quota resets at JST midnight; the
#: packet's `generated_at` should likewise carry a JST offset for parity).
_JST = timezone(timedelta(hours=9))

#: Fence text for the `_disclaimer` block. Matches the funding_stack_checker
#: 景表法 / 消費者契約法 posture.
_DISCLAIMER: dict[str, Any] = {
    "type": "information_only",
    "not_legal_or_tax_advice": True,
    "note": (
        "Evidence Packet bundles primary-source citations and rule "
        "verdicts; it is not legal, tax, or grant-application advice. "
        "Final decisions require 専門家 (税理士 / 行政書士 / 中小企業 "
        "診断士 / 認定支援機関) review."
    ),
}

#: Always-populated freshness endpoint reference.
_FRESHNESS_ENDPOINT: str = "/v1/meta/freshness"

_PREFECTURE_ALIASES: tuple[tuple[str, str], ...] = (
    ("北海道", "北海道"),
    ("青森県", "青森県"),
    ("岩手県", "岩手県"),
    ("宮城県", "宮城県"),
    ("秋田県", "秋田県"),
    ("山形県", "山形県"),
    ("福島県", "福島県"),
    ("茨城県", "茨城県"),
    ("栃木県", "栃木県"),
    ("群馬県", "群馬県"),
    ("埼玉県", "埼玉県"),
    ("千葉県", "千葉県"),
    ("東京都", "東京都"),
    ("東京", "東京都"),
    ("神奈川県", "神奈川県"),
    ("新潟県", "新潟県"),
    ("富山県", "富山県"),
    ("石川県", "石川県"),
    ("福井県", "福井県"),
    ("山梨県", "山梨県"),
    ("長野県", "長野県"),
    ("岐阜県", "岐阜県"),
    ("静岡県", "静岡県"),
    ("愛知県", "愛知県"),
    ("三重県", "三重県"),
    ("滋賀県", "滋賀県"),
    ("京都府", "京都府"),
    ("京都", "京都府"),
    ("大阪府", "大阪府"),
    ("大阪", "大阪府"),
    ("兵庫県", "兵庫県"),
    ("奈良県", "奈良県"),
    ("和歌山県", "和歌山県"),
    ("鳥取県", "鳥取県"),
    ("島根県", "島根県"),
    ("岡山県", "岡山県"),
    ("広島県", "広島県"),
    ("山口県", "山口県"),
    ("徳島県", "徳島県"),
    ("香川県", "香川県"),
    ("愛媛県", "愛媛県"),
    ("高知県", "高知県"),
    ("福岡県", "福岡県"),
    ("佐賀県", "佐賀県"),
    ("長崎県", "長崎県"),
    ("熊本県", "熊本県"),
    ("大分県", "大分県"),
    ("宮崎県", "宮崎県"),
    ("鹿児島県", "鹿児島県"),
    ("沖縄県", "沖縄県"),
)

_QUERY_KEYWORDS: tuple[str, ...] = tuple(
    sorted(
        {
            "IT導入",
            "DX",
            "GX",
            "ものづくり",
            "省力化",
            "省エネ",
            "脱炭素",
            "設備投資",
            "設備",
            "投資",
            "補助金",
            "助成金",
            "交付金",
            "融資",
            "税制",
            "税額控除",
            "特別償却",
            "認定",
            "創業",
            "事業承継",
            "小規模",
            "中小企業",
            "スタートアップ",
            "農業",
            "観光",
            "人材",
            "雇用",
            "賃上げ",
            "研究開発",
            "インボイス",
            "電子帳簿",
        },
        key=len,
        reverse=True,
    )
)

_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9]{2,}")
_CORPORATE_NUMBER_RE = re.compile(r"T?([0-9０-９]{13})")
_FALLBACK_SPLIT_RE = re.compile(r"[\s、。,.?？!！/／・:：（）()「」『』【】\[\]]+")
_FALLBACK_PARTICLE_RE = re.compile(
    r"^(?:の|は|を|に|で|と|が|から|まで)+|"
    r"(?:について|教えてください|ください|ですか)+$"
)
_NON_PROGRAM_INTENT_RE = re.compile(
    r"法人番号|適格請求書|行政処分|業務停止|営業停止|免許取消|業務改善命令|"
    r"漏洩|報告義務|個人情報保護法|電子帳簿|インボイス|消費税|簡易課税|"
    r"仕入率|固定資産税|税制|税額控除"
)
_ENFORCEMENT_INTENT_RE = re.compile(r"行政処分|業務停止|営業停止|免許取消|業務改善命令")
_TAX_INTENT_RE = re.compile(r"消費税|簡易課税|仕入率|固定資産税|税制|税額控除|インボイス|電子帳簿")


# ---------------------------------------------------------------------------
# In-memory cache (process-local).
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_get(key: str) -> dict[str, Any] | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expiry, body = entry
    if expiry < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return deepcopy(body)


def _cache_put(key: str, body: dict[str, Any]) -> None:
    _CACHE[key] = (time.monotonic() + _CACHE_TTL_SEC, deepcopy(body))


def _reset_cache_for_tests() -> None:
    """Test helper. Drops the process-local packet cache."""
    _CACHE.clear()


def _attach_known_gaps_inventory(envelope: dict[str, Any]) -> None:
    """Attach packet-shape gap detection (A8) to the envelope.

    Reads ``services.known_gaps.detect_gaps`` lazily so the import
    stays cheap and the composer module's no-LLM contract is unaffected.
    The legacy ``quality.known_gaps`` (``list[str]``) is preserved as-is;
    the new richer report lives in ``quality.known_gaps_inventory``
    (``list[dict]`` of ``{kind, message, affected_records}``).
    """
    try:
        from jpintel_mcp.services.known_gaps import detect_gaps

        inventory = detect_gaps(envelope)
    except Exception:  # pragma: no cover - defensive fail-open surface
        return
    quality = envelope.setdefault("quality", {})
    quality["known_gaps_inventory"] = inventory


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


class EvidencePacketComposer:
    """Bundles existing services into the Evidence Packet envelope.

    Both DB connections are opened ``mode=ro``. The composer does NOT
    rebuild any of the upstream logic — it imports the resolver +
    manifest builder from ``api.source_manifest`` and invokes
    ``services.funding_stack_checker`` for the rules surface.
    """

    # In-memory partner-pair index for the program-record rules surface.
    # Lazy-built on first call so import is cheap.
    _checker_cls: Any = None

    def __init__(
        self,
        jpintel_db: Path | str,
        autonomath_db: Path | str,
    ) -> None:
        self.jpintel_db = Path(jpintel_db)
        self.autonomath_db = Path(autonomath_db)
        self._funding_stack_checker: Any = None  # lazy

    # ------------------------------------------------------------------
    # DB helpers (read-only)
    # ------------------------------------------------------------------

    def _open_ro(self, path: Path) -> sqlite3.Connection:
        import contextlib

        if not path.exists():
            raise FileNotFoundError(f"sqlite file not found: {path}")
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
        return conn

    # ------------------------------------------------------------------
    # corpus_snapshot_id derivation (autonomath.db side).
    # ------------------------------------------------------------------

    def _corpus_snapshot_id(self, am_conn: sqlite3.Connection | None) -> str:
        """Derive ``corpus_snapshot_id`` per spec.

        Preference order:
          1. ``MAX(am_amendment_diff.detected_at)`` — strongest mutation signal.
          2. ``MAX(am_source.last_verified)`` — corpus-wide refresh signal.
          3. Fallback ``corpus-YYYY-MM-DD`` (deterministic per-day stamp).
        """
        today_stamp = "corpus-" + datetime.now(UTC).strftime("%Y-%m-%d")
        if am_conn is None:
            return today_stamp
        try:
            row = am_conn.execute("SELECT MAX(detected_at) FROM am_amendment_diff").fetchone()
            if row is not None and row[0]:
                return f"corpus-{str(row[0])[:10]}"
        except sqlite3.OperationalError:
            pass
        try:
            row = am_conn.execute("SELECT MAX(last_verified) FROM am_source").fetchone()
            if row is not None and row[0]:
                return f"corpus-{str(row[0])[:10]}"
        except sqlite3.OperationalError:
            pass
        return today_stamp

    # ------------------------------------------------------------------
    # Field-value extractor (am_entity_facts EAV).
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_fact_value(
        field_kind: str | None,
        text_val: Any,
        json_val: Any,
        numeric_val: Any,
    ) -> Any:
        """Pick the populated EAV column based on field_kind."""
        kind = (field_kind or "text").lower()
        if kind == "numeric" and numeric_val is not None:
            return numeric_val
        if kind == "json" and json_val is not None:
            try:
                import json as _json

                return _json.loads(json_val)
            except (TypeError, ValueError):
                return json_val
        if text_val is not None:
            return text_val
        if numeric_val is not None:
            return numeric_val
        if json_val is not None:
            return json_val
        return None

    # ------------------------------------------------------------------
    # Per-record fact + rule fetchers.
    # ------------------------------------------------------------------

    def _fetch_facts_for_entity(
        self,
        am_conn: sqlite3.Connection,
        canonical_id: str,
        cap: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Return (facts[], total_facts, facts_with_source)."""
        if not canonical_id:
            return [], 0, 0
        try:
            rows = am_conn.execute(
                """SELECT f.id            AS fact_id,
                          f.field_name    AS field_name,
                          f.field_kind    AS field_kind,
                          f.field_value_text    AS text_val,
                          f.field_value_json    AS json_val,
                          f.field_value_numeric AS num_val,
                          f.confirming_source_count AS conf_count,
                          f.source_id     AS source_id,
                          s.source_url    AS source_url,
                          s.domain        AS publisher,
                          s.first_seen    AS fetched_at,
                          s.license       AS license,
                          s.content_hash  AS checksum
                     FROM am_entity_facts f
                LEFT JOIN am_source s ON s.id = f.source_id
                    WHERE f.entity_id = ?
                 ORDER BY f.field_name ASC, f.id ASC
                    LIMIT ?""",
                (canonical_id, cap + 1),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.warning(
                "evidence_packet: am_entity_facts read failed for %s",
                canonical_id,
            )
            return [], 0, 0
        truncated = len(rows) > cap
        if truncated:
            rows = rows[:cap]
        facts: list[dict[str, Any]] = []
        with_source = 0
        for r in rows:
            value = self._coerce_fact_value(
                r["field_kind"], r["text_val"], r["json_val"], r["num_val"]
            )
            try:
                conf_count = int(r["conf_count"] or 1)
            except (TypeError, ValueError):
                conf_count = 1
            confidence = min(1.0, max(0.1, conf_count / 3.0))
            entry: dict[str, Any] = {
                "fact_id": int(r["fact_id"]),
                "field": r["field_name"],
                "value": value,
                "confidence": round(confidence, 3),
            }
            if r["source_id"] is not None:
                with_source += 1
                entry["source"] = {
                    "url": r["source_url"],
                    "publisher": r["publisher"] or "unknown",
                    "fetched_at": r["fetched_at"],
                    "checksum": r["checksum"],
                    "license": r["license"] or "unknown",
                }
            facts.append(entry)
        # Total facts on the entity (separate count for coverage_pct).
        try:
            total_row = am_conn.execute(
                "SELECT COUNT(*) FROM am_entity_facts WHERE entity_id = ?",
                (canonical_id,),
            ).fetchone()
            total_facts = int(total_row[0]) if total_row else len(facts)
        except sqlite3.OperationalError:
            total_facts = len(facts)
        return facts, total_facts, with_source

    @staticmethod
    def _compact_pdf_fact_value(value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()[:500]
        return value

    def _fetch_pdf_fact_refs(
        self,
        am_conn: sqlite3.Connection,
        canonical_id: str,
        cap: int = _PDF_FACT_REF_CAP,
    ) -> list[dict[str, Any]]:
        """Return compact references to high-value facts sourced from PDFs.

        This is deliberately a local catalog lookup. It does not fetch PDFs;
        it gives downstream LLMs a short list of PDF-backed fields worth
        citing before they spend tokens on a whole application guide.
        """
        if not canonical_id or cap <= 0:
            return []

        fact_cols = self._table_columns(am_conn, "am_entity_facts")
        source_cols = self._table_columns(am_conn, "am_source")
        required_fact_cols = {
            "entity_id",
            "field_name",
            "field_kind",
            "field_value_text",
            "field_value_json",
            "field_value_numeric",
            "source_id",
        }
        required_source_cols = {"id", "source_url"}
        if not required_fact_cols.issubset(fact_cols) or not required_source_cols.issubset(
            source_cols
        ):
            return []

        select_cols = [
            "f.field_name AS field_name",
            "f.field_kind AS field_kind",
            "f.field_value_text AS text_val",
            "f.field_value_json AS json_val",
            "f.field_value_numeric AS num_val",
            "s.source_url AS source_url",
        ]
        optional_source_cols = {
            "content_hash": "checksum",
            "last_verified": "last_verified",
            "license": "license",
            "domain": "domain",
            "source_type": "source_type",
        }
        for col, alias in optional_source_cols.items():
            if col in source_cols:
                select_cols.append(f"s.{col} AS {alias}")

        pdf_clause = "LOWER(COALESCE(s.source_url, '')) LIKE '%.pdf%'"
        if "is_pdf" in source_cols:
            pdf_clause = f"(s.is_pdf = 1 OR {pdf_clause})"

        visible_fields = sorted(_PDF_FACT_REF_FIELDS)
        placeholders = ",".join("?" for _ in visible_fields)
        sql = (
            f"SELECT {', '.join(select_cols)} "
            "FROM am_entity_facts f "
            "JOIN am_source s ON s.id = f.source_id "
            f"WHERE f.entity_id = ? AND f.field_name IN ({placeholders}) "
            f"AND {pdf_clause} "
            "ORDER BY f.field_name ASC, f.id ASC "
            "LIMIT ?"
        )
        try:
            rows = am_conn.execute(sql, (canonical_id, *visible_fields, int(cap))).fetchall()
        except sqlite3.OperationalError:
            return []

        refs: list[dict[str, Any]] = []
        for row in rows:
            value = self._coerce_fact_value(
                row["field_kind"], row["text_val"], row["json_val"], row["num_val"]
            )
            if value is None:
                continue
            row_keys = set(row.keys())
            ref: dict[str, Any] = {
                "field_name": str(row["field_name"]),
                "value": self._compact_pdf_fact_value(value),
                "source_url": row["source_url"],
            }
            for key in ("checksum", "last_verified", "license", "domain", "source_type"):
                if key in row_keys and row[key]:
                    ref[key] = row[key]
            refs.append(ref)
        return refs

    def _fetch_program_summary(
        self,
        am_conn: sqlite3.Connection,
        canonical_id: str,
    ) -> dict[str, Any] | None:
        """Return compact am_program_summary data when present.

        This is optional precomputed data. Missing table / older schema /
        sparse rows all fail open and simply omit the field.
        """
        if not canonical_id:
            return None
        try:
            row = am_conn.execute(
                "SELECT * FROM am_program_summary WHERE entity_id = ? LIMIT 1",
                (canonical_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None

        cols = set(row.keys())

        def _get(name: str) -> Any:
            if name not in cols:
                return None
            return row[name]

        precomputed: dict[str, Any] = {"basis": "am_program_summary"}
        summaries: dict[str, str] = {}
        for size in ("50", "200", "800"):
            value = _get(f"summary_{size}")
            if isinstance(value, str) and value.strip():
                summaries[size] = value
        if summaries:
            precomputed["summaries"] = summaries

        token_estimates: dict[str, int] = {}
        for size in ("50", "200", "800"):
            value = _get(f"token_{size}_est")
            if value is None:
                continue
            try:
                token_estimates[size] = int(value)
            except (TypeError, ValueError):
                continue
        if token_estimates:
            precomputed["token_estimates"] = token_estimates

        generated_at = _get("generated_at")
        if generated_at:
            precomputed["generated_at"] = generated_at

        source_quality = _get("source_quality")
        if source_quality is not None:
            import contextlib

            with contextlib.suppress(TypeError, ValueError):
                precomputed["source_quality"] = float(source_quality)

        return precomputed if len(precomputed) > 1 else None

    def _fetch_citation_verifications(
        self,
        entity_ids: list[str],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Return latest citation_verification verdict per (entity_id, source_url).

        Reads from jpintel.db (migration 126_citation_verification — table is
        addressed there because it is request-side state, NOT corpus state on
        autonomath.db). The composer joins by ``entity_id`` so the same value
        the Evidence Packet records carry can look itself up here.

        Selection rule: most recent ``verified_at`` per (entity_id, source_url)
        wins; older rows are ignored. The composite
        (entity_id, source_url, verified_at DESC, id DESC) index added by the
        migration carries the read in one BTree walk.

        Returns ``{}`` on any error so the composer falls open to the default
        ``unknown`` status. The composer must NEVER raise from a missing
        verification join — request-side absence is the expected steady state
        until the §4.3 backfill task has populated the table.

        ``entity_ids`` of length 0 short-circuits to ``{}`` (saves a query
        round-trip on empty record sets).
        """
        if not entity_ids:
            return {}
        clean_ids = [eid for eid in entity_ids if isinstance(eid, str) and eid]
        if not clean_ids:
            return {}
        try:
            conn = self._open_ro(self.jpintel_db)
        except FileNotFoundError:
            logger.info(
                "evidence_packet: jpintel.db missing at %s — defaulting citations to unknown",
                self.jpintel_db,
            )
            return {}
        try:
            placeholders = ",".join("?" for _ in clean_ids)
            # Window function picks the latest verdict per
            # (entity_id, source_url) without a self-join. The composite
            # entity/source/verified_at index drives the partition scan.
            sql = (
                "SELECT entity_id, source_url, verification_status, "
                "matched_form, source_checksum, verified_at, "
                "verification_basis FROM ( "
                "    SELECT *, ROW_NUMBER() OVER ( "
                "        PARTITION BY entity_id, source_url "
                "        ORDER BY verified_at DESC, id DESC "
                "    ) AS rn "
                "    FROM citation_verification "
                f"    WHERE entity_id IN ({placeholders}) "
                ") WHERE rn = 1"
            )
            try:
                rows = conn.execute(sql, clean_ids).fetchall()
            except sqlite3.OperationalError:
                # Table missing (migration 126 not applied) — fail open.
                return {}
        finally:
            conn.close()

        out: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            entity_id = str(row["entity_id"])
            source_url = str(row["source_url"])
            status = row["verification_status"]
            if status not in VALID_CITATION_STATUSES:
                # Defensive — the CHECK constraint should already prevent
                # this, but a manual INSERT could bypass it. Coerce to
                # the safe default rather than emit an unrecognised string.
                status = _DEFAULT_CITATION_STATUS
            out[(entity_id, source_url)] = {
                "verification_status": status,
                "matched_form": row["matched_form"],
                "source_checksum": row["source_checksum"],
                "verified_at": row["verified_at"],
                "verification_basis": row["verification_basis"],
            }
        return out

    def _fetch_recent_changes(
        self,
        am_conn: sqlite3.Connection,
        canonical_id: str,
        cap: int = _RECENT_CHANGE_CAP,
    ) -> list[dict[str, Any]]:
        """Return compact, user-facing recent changes for a program.

        The append-only ``am_amendment_diff`` table also contains internal
        projection/debug fields. Evidence Packets only expose fields that a
        user can act on directly, and omit raw before/after payloads to keep
        the packet short and non-operational.
        """
        if not canonical_id or cap <= 0:
            return []
        cols = self._table_columns(am_conn, "am_amendment_diff")
        required = {"entity_id", "field_name", "detected_at"}
        if not required.issubset(cols):
            return []

        select_cols = ["field_name", "detected_at"]
        if "source_url" in cols:
            select_cols.append("source_url")

        visible_fields = sorted(_RECENT_CHANGE_FIELDS)
        placeholders = ",".join("?" for _ in visible_fields)
        sql = (
            f"SELECT {', '.join(select_cols)} "
            "FROM am_amendment_diff "
            f"WHERE entity_id = ? AND field_name IN ({placeholders}) "
            "ORDER BY detected_at DESC "
            "LIMIT ?"
        )
        try:
            rows = am_conn.execute(sql, (canonical_id, *visible_fields, int(cap))).fetchall()
        except sqlite3.OperationalError:
            return []

        changes: list[dict[str, Any]] = []
        for row in rows:
            row_keys = set(row.keys())
            field_name = str(row["field_name"] or "")
            if field_name not in _RECENT_CHANGE_FIELDS:
                continue
            detected_at = row["detected_at"]
            if not detected_at:
                continue
            change: dict[str, Any] = {
                "field_name": field_name,
                "label": _RECENT_CHANGE_FIELD_LABELS.get(field_name, field_name),
                "detected_at": str(detected_at),
            }
            if "source_url" in row_keys and row["source_url"]:
                change["source_url"] = row["source_url"]
            changes.append(change)
        return changes

    def _fetch_source_health(
        self,
        am_conn: sqlite3.Connection,
        source_url: str | None,
        *,
        source_fetched_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Return read-only source freshness/licensing metadata.

        This never verifies URLs live. It only reflects the local source
        catalog so agents can decide whether the packet is cite-ready or
        should be followed by a citation-verification call.
        """
        if not source_url:
            return None

        health: dict[str, Any] = {"source_url": source_url}
        if source_fetched_at:
            health["source_fetched_at"] = source_fetched_at

        cols = self._table_columns(am_conn, "am_source")
        if "source_url" not in cols:
            if source_fetched_at:
                health["verification_status"] = "metadata_only"
                return health
            return None

        requested_cols = [
            "source_type",
            "domain",
            "content_hash",
            "last_verified",
            "license",
            "canonical_status",
            "is_pdf",
        ]
        select_cols = ["source_url", *(col for col in requested_cols if col in cols)]
        try:
            row = am_conn.execute(
                f"SELECT {', '.join(select_cols)} FROM am_source WHERE source_url = ? LIMIT 1",
                (source_url,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None

        if row is None:
            health["verification_status"] = "metadata_only"
            return health

        row_keys = set(row.keys())
        if "source_type" in row_keys and row["source_type"]:
            health["source_type"] = row["source_type"]
        if "domain" in row_keys and row["domain"]:
            health["domain"] = row["domain"]
        if "content_hash" in row_keys and row["content_hash"]:
            health["checksum"] = row["content_hash"]
        if "last_verified" in row_keys and row["last_verified"]:
            health["last_verified"] = row["last_verified"]
        if "license" in row_keys and row["license"]:
            health["license"] = row["license"]
        if "canonical_status" in row_keys and row["canonical_status"]:
            health["canonical_status"] = row["canonical_status"]
        if "is_pdf" in row_keys and row["is_pdf"] is not None:
            health["is_pdf"] = bool(row["is_pdf"])
        health["verification_status"] = (
            "catalog_last_verified" if health.get("last_verified") else "cataloged_unverified"
        )
        health["verification_basis"] = "local_source_catalog"
        health["live_verified_at_request"] = False
        return health

    @staticmethod
    def _build_short_summary(precomputed: dict[str, Any] | None) -> dict[str, Any] | None:
        """Lift the smallest deterministic summary into an easy-to-use field."""
        if not precomputed:
            return None
        summaries = precomputed.get("summaries")
        if not isinstance(summaries, dict):
            return None
        token_estimates = precomputed.get("token_estimates")
        if not isinstance(token_estimates, dict):
            token_estimates = {}
        for size in ("50", "200", "800"):
            text = summaries.get(size)
            if not isinstance(text, str) or not text.strip():
                continue
            summary: dict[str, Any] = {
                "text": text.strip(),
                "basis": precomputed.get("basis", "am_program_summary"),
                "size": size,
            }
            token_estimate = token_estimates.get(size)
            if token_estimate is not None:
                summary["token_estimate"] = token_estimate
            if precomputed.get("source_quality") is not None:
                summary["source_quality"] = precomputed["source_quality"]
            if precomputed.get("generated_at"):
                summary["generated_at"] = precomputed["generated_at"]
            return summary
        return None

    @staticmethod
    def _clean_alias_text(alias: Any, primary_name: str | None) -> str | None:
        if not isinstance(alias, str):
            return None
        text = unicodedata.normalize("NFKC", alias).strip()
        if not text or len(text) > 80:
            return None
        if text == (primary_name or "").strip():
            return None
        lowered = text.lower()
        if lowered.startswith(("program:", "http://", "https://")):
            return None
        return text

    @staticmethod
    def _guess_alias_language(text: str) -> str:
        return "en" if text.isascii() else "ja"

    def _fetch_aliases(
        self,
        am_conn: sqlite3.Connection,
        canonical_id: str,
        unified_id: str | None,
        primary_name: str | None,
        cap: int = _ALIAS_CAP,
    ) -> list[dict[str, Any]]:
        """Return compact, user-facing aliases/old names for the program."""
        aliases: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_alias(
            alias: Any,
            *,
            kind: str,
            language: str | None = None,
            source: str,
        ) -> None:
            text = self._clean_alias_text(alias, primary_name)
            if text is None or text in seen or len(aliases) >= cap:
                return
            seen.add(text)
            aliases.append(
                {
                    "text": text,
                    "kind": kind,
                    "language": language or self._guess_alias_language(text),
                    "source": source,
                }
            )

        jpi_cols = self._table_columns(am_conn, "jpi_programs")
        if unified_id and {"unified_id", "aliases_json"}.issubset(jpi_cols):
            try:
                row = am_conn.execute(
                    "SELECT aliases_json FROM jpi_programs WHERE unified_id = ? LIMIT 1",
                    (unified_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
            if row is not None and row["aliases_json"]:
                try:
                    import json as _json

                    parsed = _json.loads(row["aliases_json"])
                except (TypeError, ValueError):
                    parsed = []
                if isinstance(parsed, list):
                    for alias in parsed:
                        add_alias(
                            alias,
                            kind="listed",
                            source="jpi_programs.aliases_json",
                        )

        alias_cols = self._table_columns(am_conn, "am_alias")
        required = {"canonical_id", "alias", "alias_kind"}
        if canonical_id and required.issubset(alias_cols):
            language_expr = "language" if "language" in alias_cols else "NULL AS language"
            entity_filter = (
                "AND (entity_table = 'am_entities' OR entity_table IS NULL)"
                if "entity_table" in alias_cols
                else ""
            )
            order_col = "id" if "id" in alias_cols else "rowid"
            try:
                rows = am_conn.execute(
                    f"""SELECT alias, alias_kind, {language_expr}
                          FROM am_alias
                         WHERE canonical_id = ?
                           {entity_filter}
                      ORDER BY CASE alias_kind
                                 WHEN 'canonical' THEN 0
                                 WHEN 'abbreviation' THEN 1
                                 WHEN 'kana' THEN 2
                                 WHEN 'partial' THEN 3
                                 WHEN 'legacy' THEN 4
                                 WHEN 'english' THEN 5
                                 ELSE 9
                               END,
                               {order_col} ASC
                         LIMIT 50""",
                    (canonical_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                kind = row["alias_kind"] or "alias"
                if kind not in _ALIAS_KIND_PRIORITY:
                    kind = "alias"
                add_alias(
                    row["alias"],
                    kind=kind,
                    language=row["language"],
                    source="am_alias",
                )
        return aliases

    def _fetch_rules_for_program(
        self,
        canonical_id: str,
        primary_id: str,
        cap: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Build the records[].rules[] surface from funding_stack_checker.

        For a single subject program we look up partner programs in
        ``am_compat_matrix`` and emit verdicts. Returns (rules[], gaps[]).
        """
        gaps: list[str] = []
        partner_ids: list[str] = []
        # Step 1: discover partner programs via am_compat_matrix.
        am = None
        try:
            am = self._open_ro(self.autonomath_db)
        except FileNotFoundError:
            gaps.append("compat_matrix_unavailable")
            return [], gaps
        try:
            try:
                rows = am.execute(
                    """SELECT program_a_id, program_b_id, compat_status,
                              inferred_only
                         FROM am_compat_matrix
                        WHERE program_a_id = ? OR program_b_id = ?
                     ORDER BY inferred_only ASC, confidence DESC
                        LIMIT 50""",
                    (canonical_id or primary_id, canonical_id or primary_id),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            seen: set[str] = set()
            for r in rows:
                a = r["program_a_id"]
                b = r["program_b_id"]
                other = b if a == (canonical_id or primary_id) else a
                if not other or other in seen:
                    continue
                seen.add(other)
                partner_ids.append(other)
                if len(partner_ids) >= 5:
                    break
        finally:
            am.close()
        if not partner_ids:
            gaps.append("compat_matrix_no_partner")
            return [], gaps

        # Step 2: ask the funding_stack_checker for verdicts. Cached
        # singleton — built once per composer instance.
        if self._funding_stack_checker is None:
            try:
                from jpintel_mcp.services.funding_stack_checker import (
                    FundingStackChecker,
                )

                self._funding_stack_checker = FundingStackChecker(
                    jpintel_db=self.jpintel_db,
                    autonomath_db=self.autonomath_db,
                )
            except (FileNotFoundError, ImportError):
                gaps.append("funding_stack_unavailable")
                return [], gaps
        rules: list[dict[str, Any]] = []
        for partner in partner_ids:
            verdict = self._funding_stack_checker.check_pair(
                program_a=canonical_id or primary_id,
                program_b=partner,
            )
            for chain_entry in verdict.rule_chain:
                if len(rules) >= cap:
                    break
                # Map verdict → spec vocab.
                verdict_label = self._map_verdict(verdict.verdict)
                evidence_url, license_name, allowed_urls = self._rule_evidence_source(
                    chain_entry
                )
                rule = {
                    "rule_id": (
                        chain_entry.get("rule_id")
                        or f"compat:{canonical_id or primary_id}:{partner}"
                    ),
                    "verdict": verdict_label,
                    "evidence_url": evidence_url,
                    "note": chain_entry.get("rule_text", "")[:300],
                    "_partner_program": partner,
                    "_confidence": verdict.confidence,
                }
                if license_name:
                    rule["license"] = license_name
                if len(allowed_urls) > 1:
                    rule["source_urls"] = allowed_urls
                rules.append(
                    rule
                )
            if len(rules) >= cap:
                break
        return rules, gaps

    def _rule_evidence_source(
        self,
        chain_entry: dict[str, Any],
    ) -> tuple[str, str | None, list[str]]:
        raw_urls: list[Any] = [chain_entry.get("source_url")]
        source_urls = chain_entry.get("source_urls")
        if isinstance(source_urls, list):
            raw_urls.extend(source_urls)
        urls: list[str] = []
        seen: set[str] = set()
        for raw_url in raw_urls:
            if not isinstance(raw_url, str):
                continue
            url = raw_url.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
        if not urls:
            return "", None, []
        licensed = [(url, self._source_license_for_url(url)) for url in urls]
        allowed = [
            (url, license_name)
            for url, license_name in licensed
            if license_name in REDISTRIBUTABLE_LICENSES
        ]
        if allowed:
            return allowed[0][0], allowed[0][1], [url for url, _license in allowed]
        first_url, first_license = licensed[0]
        return first_url, first_license, []

    def _source_license_for_url(self, source_url: str | None) -> str | None:
        if not source_url:
            return None
        try:
            conn = self._open_ro(self.autonomath_db)
        except FileNotFoundError:
            return None
        try:
            cols = self._table_columns(conn, "am_source")
            if "source_url" not in cols or "license" not in cols:
                return None
            row = conn.execute(
                "SELECT license FROM am_source WHERE source_url = ? LIMIT 1",
                (source_url,),
            ).fetchone()
            if row is None:
                return None
            value = row["license"]
            return value if isinstance(value, str) and value else None
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

    @staticmethod
    def _map_verdict(verdict: str) -> str:
        """Map funding_stack_checker verdict → Packet rule.verdict vocab.

        Plan §6 example uses ``defer`` (≈ requires_review). Map:
          requires_review → defer
          incompatible    → block
          compatible      → allow
          unknown         → unknown
        """
        return {
            "requires_review": "defer",
            "incompatible": "block",
            "compatible": "allow",
            "unknown": "unknown",
        }.get(verdict, verdict)

    @staticmethod
    def _attach_compression_block(
        envelope: dict[str, Any],
        *,
        source_url: str | None,
        input_token_price_jpy_per_1m: float | None,
        source_tokens_basis: CompressionSourceBasis = "unknown",
        source_pdf_pages: int | None = None,
        source_token_count: int | None = None,
    ) -> None:
        """Attach a deterministic TokenCompressionEstimator block fail-open."""
        try:
            from jpintel_mcp.services.token_compression import (
                TokenCompressionEstimator,
            )

            packet_for_estimate = {
                k: v for k, v in envelope.items() if k not in {"compression", "_compression_hint"}
            }
            envelope["compression"] = TokenCompressionEstimator().compose(
                packet_for_estimate,
                source_url=source_url,
                source_basis=source_tokens_basis,
                pdf_pages=source_pdf_pages,
                source_token_count=source_token_count,
                input_price_jpy_per_1m=input_token_price_jpy_per_1m,
            )
        except Exception:  # pragma: no cover - defensive fail-open surface
            logger.exception("evidence_packet: compression estimator failed")
            quality = envelope.setdefault("quality", {})
            gaps = quality.setdefault("known_gaps", [])
            if isinstance(gaps, list) and "compression_unavailable" not in gaps:
                gaps.append("compression_unavailable")

    @staticmethod
    def _context_savings_summary(compression: Any) -> dict[str, Any] | None:
        if not isinstance(compression, dict):
            return None
        savings = compression.get("cost_savings_estimate")
        summary: dict[str, Any] = {
            "evaluated": compression.get("source_tokens_estimate") is not None,
            "source_tokens_basis": compression.get("source_tokens_basis"),
            "source_tokens_input_source": compression.get("source_tokens_input_source"),
            "packet_tokens_estimate": compression.get("packet_tokens_estimate"),
            "source_tokens_estimate": compression.get("source_tokens_estimate"),
            "avoided_tokens_estimate": compression.get("avoided_tokens_estimate"),
            "compression_ratio": compression.get("compression_ratio"),
            "input_context_reduction_rate": compression.get("input_context_reduction_rate"),
            "provider_billing_not_guaranteed": compression.get(
                "provider_billing_not_guaranteed", True
            ),
            "savings_claim": compression.get("savings_claim"),
        }
        if isinstance(savings, dict):
            summary.update(
                {
                    "input_token_price_jpy_per_1m": savings.get("input_token_price_jpy_per_1m"),
                    "break_even_avoided_tokens": savings.get("break_even_avoided_tokens"),
                    "break_even_source_tokens_estimate": savings.get(
                        "break_even_source_tokens_estimate"
                    ),
                    "break_even_met": savings.get("break_even_met"),
                    "net_savings_jpy_ex_tax": savings.get("net_savings_jpy_ex_tax"),
                    "billing_savings_claim": savings.get("billing_savings_claim"),
                }
            )
        return summary

    @staticmethod
    def _cost_savings_decision(context_savings: dict[str, Any] | None) -> dict[str, Any]:
        """Tell agents whether a cost-savings recommendation is justified."""
        if not context_savings or context_savings.get("evaluated") is not True:
            return {
                "recommend_for_cost_savings": False,
                "cost_savings_decision": "needs_caller_baseline",
                "missing_for_cost_claim": [
                    "source_tokens_basis",
                    "source_pdf_pages_or_source_token_count",
                    "input_token_price_jpy_per_1m",
                ],
            }

        if context_savings.get("break_even_met") is True:
            return {
                "recommend_for_cost_savings": True,
                "cost_savings_decision": "supported_by_caller_baseline",
                "missing_for_cost_claim": [],
            }

        if context_savings.get("break_even_met") is False:
            return {
                "recommend_for_cost_savings": False,
                "cost_savings_decision": "not_supported_by_caller_baseline",
                "missing_for_cost_claim": [],
            }

        return {
            "recommend_for_cost_savings": False,
            "cost_savings_decision": "needs_input_token_price",
            "missing_for_cost_claim": ["input_token_price_jpy_per_1m"],
        }

    @staticmethod
    def _source_linked_record_count(records: list[dict[str, Any]]) -> int:
        count = 0
        for rec in records:
            if rec.get("source_url"):
                count += 1
                continue
            facts = rec.get("facts") or []
            if any(isinstance(fact, dict) and fact.get("source") for fact in facts):
                count += 1
        return count

    @staticmethod
    def _collect_record_citations(
        records: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """Return de-duplicated (entity_id, source_url) pairs from records[].

        Sources scanned, in priority order:
          1. record.source_url
          2. record.facts[*].source.url
          3. record.recent_changes[*].source_url
          4. record.pdf_fact_refs[*].source_url
          5. record.rules[*].evidence_url

        Pairs are emitted in first-seen order (dict-preserving) so the
        downstream citations[] array is deterministic per packet.
        """
        seen: dict[tuple[str, str], None] = {}
        for rec in records:
            entity_id = rec.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                continue
            primary = rec.get("source_url")
            if isinstance(primary, str) and primary:
                seen.setdefault((entity_id, primary), None)
            for fact in rec.get("facts") or []:
                src = fact.get("source") if isinstance(fact, dict) else None
                if isinstance(src, dict):
                    url = src.get("url")
                    if isinstance(url, str) and url:
                        seen.setdefault((entity_id, url), None)
            for chg in rec.get("recent_changes") or []:
                if isinstance(chg, dict):
                    url = chg.get("source_url")
                    if isinstance(url, str) and url:
                        seen.setdefault((entity_id, url), None)
            for ref in rec.get("pdf_fact_refs") or []:
                if isinstance(ref, dict):
                    url = ref.get("source_url")
                    if isinstance(url, str) and url:
                        seen.setdefault((entity_id, url), None)
            for rule in rec.get("rules") or []:
                if isinstance(rule, dict):
                    url = rule.get("evidence_url")
                    if isinstance(url, str) and url:
                        seen.setdefault((entity_id, url), None)
        return list(seen.keys())

    @staticmethod
    def _build_citations_block(
        records: list[dict[str, Any]],
        verifications: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Project per-record citations into ``evidence_value.citations[]``.

        Each entry surfaces the latest known verdict for the (entity_id,
        source_url) pair. When the citation_verification join returns no row,
        the entry defaults to ``verification_status='unknown'`` with all
        verdict-derived fields ``None`` — never silently emit ``'verified'``
        without a stored proof.
        """
        out: list[dict[str, Any]] = []
        pairs = EvidencePacketComposer._collect_record_citations(records)
        for entity_id, source_url in pairs:
            verdict = verifications.get((entity_id, source_url))
            if verdict is None:
                out.append(
                    {
                        "entity_id": entity_id,
                        "source_url": source_url,
                        "verification_status": _DEFAULT_CITATION_STATUS,
                        "matched_form": None,
                        "source_checksum": None,
                        "verified_at": None,
                        "verification_basis": None,
                    }
                )
                continue
            status = verdict.get("verification_status", _DEFAULT_CITATION_STATUS)
            if status not in VALID_CITATION_STATUSES:
                status = _DEFAULT_CITATION_STATUS
            out.append(
                {
                    "entity_id": entity_id,
                    "source_url": source_url,
                    "verification_status": status,
                    "matched_form": verdict.get("matched_form"),
                    "source_checksum": verdict.get("source_checksum"),
                    "verified_at": verdict.get("verified_at"),
                    "verification_basis": verdict.get("verification_basis"),
                }
            )
        return out

    @staticmethod
    def _build_evidence_value(
        envelope: dict[str, Any],
        records: list[dict[str, Any]],
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Plan §4-A + §4.3 `evidence_value` block.

        AI-side counters that explain *why* this packet may be worth
        recommending — independent of any caller-supplied price baseline.
        Pure record/quality-derived; no LLM call, no live web fetch.

        ``citations`` (§4.3 deliverable): per-citation verification verdict
        joined from ``citation_verification`` (migration 126). When omitted,
        defaults to an empty list rather than ``None`` so the wire shape is
        stable for AI agents that read ``evidence_value.citations[]``.
        """
        records_returned = len(records)
        source_linked = EvidencePacketComposer._source_linked_record_count(records)
        precomputed_records = sum(1 for rec in records if rec.get("precomputed"))
        pdf_fact_refs = sum(len(rec.get("pdf_fact_refs") or []) for rec in records)

        coverage_values: list[float] = []
        for rec in records:
            cov = rec.get("fact_provenance_coverage_pct")
            if isinstance(cov, (int, float)):
                coverage_values.append(float(cov))
        if coverage_values:
            coverage_avg: float | None = round(
                sum(coverage_values) / len(coverage_values), 4
            )
        else:
            coverage_avg = None

        quality = envelope.get("quality") or {}
        gaps = quality.get("known_gaps") or []
        known_gap_count = len(gaps) if isinstance(gaps, list) else 0

        cits = citations or []
        verified_count = sum(
            1 for c in cits if c.get("verification_status") == "verified"
        )
        inferred_count = sum(
            1 for c in cits if c.get("verification_status") == "inferred"
        )
        stale_count = sum(
            1 for c in cits if c.get("verification_status") == "stale"
        )
        unknown_count = sum(
            1 for c in cits if c.get("verification_status") == "unknown"
        )

        return {
            "records_returned": records_returned,
            "source_linked_records": source_linked,
            "precomputed_records": precomputed_records,
            "pdf_fact_refs": pdf_fact_refs,
            "known_gap_count": known_gap_count,
            "fact_provenance_coverage_pct_avg": coverage_avg,
            "citations": cits,
            "citation_count": len(cits),
            "citation_verified_count": verified_count,
            "citation_inferred_count": inferred_count,
            "citation_stale_count": stale_count,
            "citation_unknown_count": unknown_count,
            # NO live web search — composer is read-only against local SQLite.
            "web_search_performed_by_jpcite": False,
            # NO request-time LLM — plan §4-A safety contract.
            "request_time_llm_call_performed": False,
        }

    @staticmethod
    def _build_evidence_decision(
        records_returned: int,
        source_linked_records: int,
    ) -> tuple[bool, str]:
        """Return (recommend_for_evidence, evidence_decision) per plan §4-A."""
        if records_returned <= 0:
            return False, "no_records_returned"
        if source_linked_records <= 0:
            return False, "records_returned_without_source_links"
        return True, "supported_by_source_linked_records"

    @classmethod
    def _build_agent_recommendation(cls, envelope: dict[str, Any]) -> dict[str, Any]:
        """Return machine-readable guidance for LLM/tool agents.

        The recommendation is intentionally conditional. It exposes why an
        agent may suggest jpcite, but it does not claim guaranteed provider
        billing savings.

        Plan §4-A two-axis decision:
            * `recommend_for_evidence` / `evidence_decision`
              — based purely on source-linked record presence; baseline-free.
            * `recommend_for_cost_savings` / `cost_savings_decision`
              — requires caller-supplied source-token baseline + price.
        """
        raw_records = envelope.get("records") or []
        records = [rec for rec in raw_records if isinstance(rec, dict)]
        records_returned = len(records)
        source_linked_records = cls._source_linked_record_count(records)
        precomputed_count = sum(1 for rec in records if rec.get("precomputed"))
        pdf_ref_count = sum(len(rec.get("pdf_fact_refs") or []) for rec in records)
        context_savings = cls._context_savings_summary(envelope.get("compression"))
        recommend_for_evidence, evidence_decision = cls._build_evidence_decision(
            records_returned, source_linked_records
        )

        route = envelope.get("verification", {}).get("replay_endpoint")
        if not isinstance(route, str) or not route:
            route = "/v1/evidence/packets/query"

        if records_returned <= 0:
            base = {
                "recommendation": "broaden_query_or_skip",
                "recommend_to_user": False,
                "recommend_for_evidence": False,
                "evidence_decision": evidence_decision,
                "route": route,
                "records_returned": 0,
                "source_linked_records_returned": 0,
                "reason_codes": [
                    "no_records_returned",
                    "query_needs_broader_terms_or_different_endpoint",
                ],
                "value_reasons": [],
                "message": (
                    "Do not recommend jpcite for this exact query yet; broaden "
                    "the query or use a more specific endpoint."
                ),
                "context_savings": context_savings,
                **cls._cost_savings_decision(context_savings),
            }
            return base

        reason_codes = ["source_linked_records_returned"]
        if precomputed_count > 0:
            reason_codes.extend(
                [
                    "precomputed_summary_available",
                    "no_request_time_llm",
                    "no_live_web_search",
                ]
            )
        else:
            reason_codes.append("precomputed_summary_unavailable")
        if pdf_ref_count > 0:
            reason_codes.append("pdf_fact_refs_available")
        if context_savings and context_savings.get("break_even_met") is True:
            reason_codes.append("caller_baseline_break_even_met")
        elif context_savings and context_savings.get("evaluated") is True:
            reason_codes.append("caller_baseline_evaluated")
        else:
            reason_codes.append("context_savings_baseline_needed")

        # value_reasons mirrors plan §4-A's example list: the positive
        # signals the agent can quote when justifying a jpcite recommendation.
        # Always derived from the same record/compression facts as reason_codes,
        # so the two never diverge silently.
        gaps = envelope.get("quality", {}).get("known_gaps") or []
        gaps_list = gaps if isinstance(gaps, list) else []
        value_reasons: list[str] = []
        if source_linked_records > 0:
            value_reasons.append("source_linked_records_returned")
        if precomputed_count > 0:
            value_reasons.append("precomputed_summary_available")
        if pdf_ref_count > 0:
            value_reasons.append("pdf_fact_refs_available")
        if gaps_list:
            value_reasons.append("known_gaps_exposed")
        # Composer never calls an LLM at request time, never live-fetches.
        value_reasons.extend(["no_request_time_llm", "no_live_web_search"])
        if context_savings and context_savings.get("break_even_met") is True:
            value_reasons.append("caller_baseline_break_even_met")

        if source_linked_records <= 0:
            return {
                "recommendation": "broaden_query_or_skip",
                "recommend_to_user": False,
                "recommend_for_evidence": False,
                "evidence_decision": evidence_decision,
                "route": route,
                "records_returned": records_returned,
                "source_linked_records_returned": source_linked_records,
                "reason_codes": [
                    "records_returned_without_source_links",
                    "query_needs_broader_terms_or_different_endpoint",
                ],
                "value_reasons": [],
                "message": (
                    "Do not recommend jpcite for this exact query yet; the "
                    "packet lacks source-linked evidence."
                ),
                "context_savings": context_savings,
                **cls._cost_savings_decision(context_savings),
            }

        if precomputed_count > 0:
            return {
                "recommendation": "use_jpcite_prefetch",
                "recommend_to_user": True,
                "recommend_for_evidence": recommend_for_evidence,
                "evidence_decision": evidence_decision,
                "route": "/v1/intelligence/precomputed/query",
                "records_returned": records_returned,
                "source_linked_records_returned": source_linked_records,
                "reason_codes": reason_codes,
                "value_reasons": value_reasons,
                "message": (
                    "Use jpcite before sending long Japanese public-program "
                    "sources to an LLM; this packet includes compact, "
                    "source-linked context without a request-time LLM call."
                ),
                "context_savings": context_savings,
                **cls._cost_savings_decision(context_savings),
            }

        return {
            "recommendation": "use_evidence_packet",
            "recommend_to_user": True,
            "recommend_for_evidence": recommend_for_evidence,
            "evidence_decision": evidence_decision,
            "route": route,
            "records_returned": records_returned,
            "source_linked_records_returned": source_linked_records,
            "reason_codes": reason_codes,
            "value_reasons": value_reasons,
            "message": (
                "Recommend jpcite for source-linked evidence prefetch. Treat context "
                "savings as unproven until a comparable baseline is supplied."
            ),
            "context_savings": context_savings,
            **cls._cost_savings_decision(context_savings),
        }

    @classmethod
    def _attach_agent_recommendation(cls, envelope: dict[str, Any]) -> None:
        recommendation = cls._build_agent_recommendation(envelope)
        envelope["agent_recommendation"] = recommendation
        if "no_records_returned" in recommendation.get("reason_codes", []):
            gaps = envelope.setdefault("quality", {}).setdefault("known_gaps", [])
            if isinstance(gaps, list) and "no_records_returned" not in gaps:
                gaps.append("no_records_returned")

    @staticmethod
    def _apply_profile(
        envelope: dict[str, Any],
        profile: str,
    ) -> dict[str, Any]:
        """Project ``envelope`` through the requested ``profile`` filter.

        Default ``full`` is the identity projection. Other profiles drop
        record-level sub-blocks per the §4.3 contract:

          * ``brief``         drops facts / rules / precomputed / pdf_fact_refs
                              / aliases / short_summary on every record. The
                              envelope keeps verification + quality + citations.
          * ``verified_only`` drops facts whose ``source.url`` is not in the
                              ``verification_status='verified'`` allow-list,
                              and drops records that end up with no facts AND
                              no verified primary ``source_url``.
          * ``changes_only``  drops facts / rules / precomputed / pdf_fact_refs
                              / aliases / short_summary on every record;
                              records without ``recent_changes`` are dropped.

        ``evidence_value.citations[]`` is NEVER dropped — it is the §4.3
        deliverable and AI agents read it to decide trust.

        Mutates ``envelope`` in place AND returns it (caller can chain).
        Unknown ``profile`` values fall through to ``full`` to keep the
        wire stable when a stale client passes a future-tense value.
        """
        if profile not in {"brief", "verified_only", "changes_only"}:
            envelope.setdefault("packet_profile", profile if profile == "full" else "full")
            return envelope

        envelope["packet_profile"] = profile
        records = envelope.get("records") or []

        if profile == "brief":
            for rec in records:
                for key in (
                    "facts",
                    "rules",
                    "precomputed",
                    "pdf_fact_refs",
                    "aliases",
                    "short_summary",
                    "fact_provenance_coverage_pct",
                ):
                    rec.pop(key, None)
            return envelope

        if profile == "changes_only":
            kept: list[dict[str, Any]] = []
            for rec in records:
                if not rec.get("recent_changes"):
                    continue
                for key in (
                    "facts",
                    "rules",
                    "precomputed",
                    "pdf_fact_refs",
                    "aliases",
                    "short_summary",
                    "fact_provenance_coverage_pct",
                ):
                    rec.pop(key, None)
                kept.append(rec)
            envelope["records"] = kept
            return envelope

        # verified_only. Use the full (entity_id, source_url) pair, not URL
        # alone: two different entities can cite the same government page but
        # only one pair may have been explicitly verified.
        cits = envelope.get("evidence_value", {}).get("citations") or []
        verified_pairs: set[tuple[str, str]] = {
            (str(c.get("entity_id")), str(c.get("source_url")))
            for c in cits
            if c.get("verification_status") == "verified"
            and isinstance(c.get("entity_id"), str)
            and isinstance(c.get("source_url"), str)
        }
        kept = []
        for rec in records:
            entity_id = rec.get("entity_id")
            primary_verified = (
                isinstance(entity_id, str)
                and isinstance(rec.get("source_url"), str)
                and (entity_id, rec["source_url"]) in verified_pairs
            )
            facts = rec.get("facts") or []
            kept_facts = []
            for f in facts:
                src = f.get("source") if isinstance(f, dict) else None
                url = src.get("url") if isinstance(src, dict) else None
                if isinstance(entity_id, str) and isinstance(url, str) and (
                    entity_id,
                    url,
                ) in verified_pairs:
                    kept_facts.append(f)
            if facts:
                rec["facts"] = kept_facts
                # Recompute coverage on the verified-only fact subset so the
                # downstream `fact_provenance_coverage_pct_avg` stays honest.
                with_source = sum(
                    1 for f in kept_facts if isinstance(f, dict) and f.get("source")
                )
                rec["fact_provenance_coverage_pct"] = (
                    round(with_source / len(kept_facts), 4) if kept_facts else 0.0
                )
            # Drop rules whose evidence_url is not verified.
            rules = rec.get("rules") or []
            kept_rules = [
                r
                for r in rules
                if isinstance(r, dict)
                and isinstance(r.get("evidence_url"), str)
                and isinstance(entity_id, str)
                and (entity_id, r["evidence_url"]) in verified_pairs
            ]
            if rules:
                rec["rules"] = kept_rules
            # Drop pdf_fact_refs whose source_url is not verified.
            pdf_refs = rec.get("pdf_fact_refs") or []
            kept_pdf = [
                p
                for p in pdf_refs
                if isinstance(p, dict)
                and isinstance(p.get("source_url"), str)
                and isinstance(entity_id, str)
                and (entity_id, p["source_url"]) in verified_pairs
            ]
            if pdf_refs:
                rec["pdf_fact_refs"] = kept_pdf
            # Drop recent change source URLs that do not have a verified
            # citation verdict for this entity. Otherwise verified_only can
            # reintroduce unknown citations when evidence_value is rebuilt.
            changes = rec.get("recent_changes") or []
            kept_changes = [
                c
                for c in changes
                if isinstance(c, dict)
                and isinstance(c.get("source_url"), str)
                and isinstance(entity_id, str)
                and (entity_id, c["source_url"]) in verified_pairs
            ]
            if changes:
                rec["recent_changes"] = kept_changes
            # Keep the record if anything verified survives, OR if the
            # primary source_url was verified.
            if primary_verified or kept_facts or kept_rules or kept_pdf or kept_changes:
                kept.append(rec)
        envelope["records"] = kept
        return envelope

    @classmethod
    def _attach_evidence_value(
        cls,
        envelope: dict[str, Any],
        composer: EvidencePacketComposer | None = None,
    ) -> None:
        """Plan §4-A + §4.3: surface AI-readable evidence value counters.

        When ``composer`` is supplied, the citation_verification join is
        executed against jpintel.db so each citation in
        ``evidence_value.citations[]`` carries its latest verdict. With
        ``composer=None``, existing citation verdicts already attached to the
        envelope are preserved; new/unseen pairs default to
        ``verification_status='unknown'``.
        """
        records = [
            rec for rec in (envelope.get("records") or []) if isinstance(rec, dict)
        ]
        if composer is not None:
            entity_ids = [
                rec.get("entity_id")
                for rec in records
                if isinstance(rec.get("entity_id"), str)
            ]
            verifications = composer._fetch_citation_verifications(entity_ids)
        else:
            existing = envelope.get("evidence_value", {}).get("citations") or []
            verifications = {}
            for cit in existing:
                if not isinstance(cit, dict):
                    continue
                entity_id = cit.get("entity_id")
                source_url = cit.get("source_url")
                status = cit.get("verification_status")
                if (
                    isinstance(entity_id, str)
                    and isinstance(source_url, str)
                    and status in VALID_CITATION_STATUSES
                ):
                    verifications[(entity_id, source_url)] = dict(cit)
        citations = cls._build_citations_block(records, verifications)
        envelope["evidence_value"] = cls._build_evidence_value(
            envelope, records, citations
        )

    @classmethod
    def _refresh_projection_metadata(
        cls,
        envelope: dict[str, Any],
        composer: EvidencePacketComposer | None = None,
    ) -> None:
        """Recompute quality, recommendation, and citations after projection."""
        records = [
            rec for rec in (envelope.get("records") or []) if isinstance(rec, dict)
        ]
        quality = envelope.get("quality")
        if isinstance(quality, dict):
            coverage_score = cls._coverage_score(records)
            quality["coverage_score"] = coverage_score
            quality["human_review_required"] = cls._human_review_required(
                records,
                coverage_score,
            )
        cls._attach_agent_recommendation(envelope)
        cls._attach_evidence_value(envelope, composer=composer)

    # ------------------------------------------------------------------
    # Quality scoring.
    # ------------------------------------------------------------------

    @staticmethod
    def _freshness_bucket(snapshot_id: str) -> str:
        """Map ``corpus-YYYY-MM-DD`` to a freshness bucket."""
        if not snapshot_id.startswith("corpus-"):
            return "unknown"
        date_part = snapshot_id[len("corpus-") :]
        try:
            ts = datetime.fromisoformat(date_part).replace(tzinfo=UTC)
        except ValueError:
            return "unknown"
        age_days = (datetime.now(UTC) - ts).days
        if age_days <= 7:
            return "within_7d"
        if age_days <= 30:
            return "within_30d"
        if age_days <= 90:
            return "within_90d"
        return "stale"

    @staticmethod
    def _coverage_score(records: list[dict[str, Any]]) -> float:
        """Mean fact_provenance coverage across records."""
        if not records:
            return 0.0
        scores: list[float] = []
        for rec in records:
            facts = rec.get("facts") or []
            if not facts:
                scores.append(0.0)
                continue
            with_src = sum(1 for f in facts if f.get("source"))
            scores.append(with_src / len(facts))
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 3)

    @staticmethod
    def _human_review_required(records: list[dict[str, Any]], coverage_score: float) -> bool:
        for rec in records:
            for rule in rec.get("rules") or []:
                if rule.get("verdict") in {"defer", "block", "unknown"}:
                    return True
        return coverage_score < 0.5

    # ------------------------------------------------------------------
    # Cache key + envelope build.
    # ------------------------------------------------------------------

    def _make_cache_key(
        self,
        subject_kind: str,
        subject_id: str,
        *,
        include_facts: bool,
        include_rules: bool,
        include_compression: bool,
        fields: str,
        input_token_price_jpy_per_1m: float | None,
        source_tokens_basis: CompressionSourceBasis,
        source_pdf_pages: int | None,
        source_token_count: int | None,
        corpus_snapshot_id: str,
        profile: str = "full",
    ) -> str:
        return "|".join(
            [
                str(self.jpintel_db),
                str(self.autonomath_db),
                subject_kind,
                subject_id,
                str(include_facts),
                str(include_rules),
                str(include_compression),
                fields,
                str(input_token_price_jpy_per_1m or ""),
                source_tokens_basis,
                str(source_pdf_pages or ""),
                str(source_token_count or ""),
                corpus_snapshot_id,
                profile,
            ]
        )

    @staticmethod
    def _new_packet_id() -> str:
        return f"evp_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _now_jst_iso() -> str:
        return datetime.now(_JST).isoformat(timespec="seconds")

    @staticmethod
    def _normalise_free_text_query(query_text: str) -> str:
        return unicodedata.normalize("NFKC", query_text or "").strip()

    @staticmethod
    def _detect_prefecture(query_text: str) -> str | None:
        text = EvidencePacketComposer._normalise_free_text_query(query_text)
        for needle, prefecture in _PREFECTURE_ALIASES:
            if needle in text:
                return prefecture
        return None

    @staticmethod
    def _query_terms(query_text: str) -> list[str]:
        """Extract coarse Japanese search terms without tokenizer deps.

        Evidence packets should handle natural LLM/user questions like
        "東京都の設備投資補助金は?" rather than requiring exact title
        substrings. This deliberately stays dictionary-light and
        deterministic: no MeCab, no LLM, no network.
        """
        text = EvidencePacketComposer._normalise_free_text_query(query_text)
        if not text:
            return []

        terms: list[str] = []
        seen: set[str] = set()

        def add(term: str) -> None:
            term = term.strip()
            if len(term) < 2 or term in seen:
                return
            seen.add(term)
            terms.append(term)

        for keyword in _QUERY_KEYWORDS:
            if keyword in text:
                add(keyword)
        for match in _ASCII_TERM_RE.finditer(text):
            add(match.group(0))

        if not terms:
            for chunk in _FALLBACK_SPLIT_RE.split(text):
                chunk = _FALLBACK_PARTICLE_RE.sub("", chunk)
                if 2 <= len(chunk) <= 20:
                    add(chunk)

        # Keep the SQL compact and predictable.
        return terms[:8]

    @staticmethod
    def _prefers_non_program_context(query_text: str) -> bool:
        text = EvidencePacketComposer._normalise_free_text_query(query_text)
        return _NON_PROGRAM_INTENT_RE.search(text) is not None

    @staticmethod
    def _extract_corporate_number(query_text: str) -> str | None:
        text = EvidencePacketComposer._normalise_free_text_query(query_text)
        match = _CORPORATE_NUMBER_RE.search(text)
        return match.group(1) if match else None

    @staticmethod
    def _non_program_context_order(query_text: str) -> tuple[str, ...]:
        text = EvidencePacketComposer._normalise_free_text_query(query_text)
        if _ENFORCEMENT_INTENT_RE.search(text):
            return ("enforcement", "law", "tax")
        if _TAX_INTENT_RE.search(text):
            return ("tax", "law", "enforcement")
        return ("law", "tax", "enforcement")

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        except sqlite3.OperationalError:
            return set()
        return {str(row["name"]) for row in rows}

    def _discover_program_ids_for_query(
        self,
        am_conn: sqlite3.Connection,
        query_text: str,
        filters: dict[str, Any],
        *,
        limit: int,
    ) -> list[str]:
        """Return candidate program ids for exact or natural-language query."""
        cap = min(limit, MAX_RECORDS_PER_PACKET) + 1
        clauses: list[str] = []
        params: list[Any] = []
        q = self._normalise_free_text_query(query_text)
        if q:
            clauses.append("primary_name LIKE ?")
            params.append(f"%{q}%")
        pref = filters.get("prefecture")
        if pref:
            clauses.append("prefecture = ?")
            params.append(pref)
        tier = filters.get("tier")
        if tier:
            clauses.append("tier = ?")
            params.append(tier)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT unified_id FROM jpi_programs{where} ORDER BY tier ASC LIMIT ?"
        try:
            rows = am_conn.execute(sql, [*params, cap]).fetchall()
        except sqlite3.OperationalError:
            rows = []
        subject_ids = [r["unified_id"] for r in rows if r["unified_id"]]
        if len(subject_ids) >= cap or not q:
            return subject_ids

        terms = self._query_terms(q)
        if not terms:
            return subject_ids

        cols = self._table_columns(am_conn, "jpi_programs")
        search_cols = [
            col
            for col in (
                "primary_name",
                "aliases_json",
                "program_kind",
                "funding_purpose_json",
                "target_types_json",
                "equipment_category",
                "authority_name",
            )
            if col in cols
        ]
        if not search_cols:
            return subject_ids

        detected_prefecture = None if pref else self._detect_prefecture(q)
        fallback_clauses: list[str] = []
        fallback_params: list[Any] = []
        term_clauses: list[str] = []
        for term in terms:
            term_clause = " OR ".join(f"{col} LIKE ?" for col in search_cols)
            term_clauses.append(f"({term_clause})")
            fallback_params.extend([f"%{term}%"] * len(search_cols))
        if term_clauses:
            fallback_clauses.append(f"({' OR '.join(term_clauses)})")
        if tier:
            fallback_clauses.append("tier = ?")
            fallback_params.append(tier)
        if pref:
            fallback_clauses.append("prefecture = ?")
            fallback_params.append(pref)
        elif detected_prefecture:
            fallback_clauses.append("(prefecture = ? OR prefecture IS NULL OR prefecture = '')")
            fallback_params.append(detected_prefecture)

        score_parts: list[str] = []
        score_params: list[Any] = []
        for term in terms:
            score_parts.append("CASE WHEN primary_name LIKE ? THEN 10 ELSE 0 END")
            score_params.append(f"%{term}%")
            if "program_kind" in cols:
                score_parts.append("CASE WHEN program_kind LIKE ? THEN 2 ELSE 0 END")
                score_params.append(f"%{term}%")
            if "funding_purpose_json" in cols:
                score_parts.append("CASE WHEN funding_purpose_json LIKE ? THEN 2 ELSE 0 END")
                score_params.append(f"%{term}%")
        if detected_prefecture or pref:
            score_parts.append("CASE WHEN prefecture = ? THEN 3 ELSE 0 END")
            score_params.append(pref or detected_prefecture)
        score_expr = " + ".join(score_parts) if score_parts else "0"
        fallback_sql = (
            "SELECT unified_id, "
            f"({score_expr}) AS _score "
            "FROM jpi_programs "
            f"WHERE {' AND '.join(fallback_clauses)} "
            "ORDER BY _score DESC, tier ASC, updated_at DESC "
            "LIMIT ?"
        )
        try:
            rows = am_conn.execute(
                fallback_sql,
                [*score_params, *fallback_params, cap],
            ).fetchall()
        except sqlite3.OperationalError:
            return subject_ids

        seen = set(subject_ids)
        for row in rows:
            uid = row["unified_id"]
            if uid and uid not in seen:
                seen.add(uid)
                subject_ids.append(uid)
        return subject_ids

    def _discover_non_program_records_for_query(
        self,
        am_conn: sqlite3.Connection,
        query_text: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return compact non-program records for law/tax/enforcement intents."""
        terms = self._query_terms(query_text)
        if not terms:
            return []
        remaining = max(0, min(limit, MAX_RECORDS_PER_PACKET))
        if remaining == 0:
            return []

        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add_record(record: dict[str, Any]) -> None:
            key = (str(record.get("record_kind")), str(record.get("entity_id")))
            if key in seen or len(records) >= remaining:
                return
            seen.add(key)
            records.append(record)

        text = self._normalise_free_text_query(query_text)
        bangou = self._extract_corporate_number(text)

        def add_structured_miss(
            *,
            entity_id: str,
            primary_name: str,
            source_url: str | None,
            lookup: dict[str, Any],
        ) -> None:
            add_record(
                {
                    "entity_id": entity_id,
                    "primary_name": primary_name,
                    "record_kind": "structured_miss",
                    "source_url": source_url,
                    "lookup": lookup,
                }
            )

        if bangou and _ENFORCEMENT_INTENT_RE.search(text):
            exact_match_found = False
            checked_tables: list[str] = []
            am_cols = self._table_columns(am_conn, "am_enforcement_detail")
            if {
                "enforcement_id",
                "houjin_bangou",
                "target_name",
            }.issubset(am_cols):
                checked_tables.append("am_enforcement_detail")
                try:
                    rows = am_conn.execute(
                        """SELECT enforcement_id, entity_id, houjin_bangou,
                                  target_name, enforcement_kind,
                                  issuing_authority, issuance_date,
                                  reason_summary, source_url
                             FROM am_enforcement_detail
                            WHERE houjin_bangou = ?
                         ORDER BY issuance_date DESC
                            LIMIT ?""",
                        (bangou, remaining - len(records)),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                for row in rows:
                    exact_match_found = True
                    add_record(
                        {
                            "entity_id": row["entity_id"] or row["enforcement_id"],
                            "primary_name": row["target_name"],
                            "record_kind": "enforcement",
                            "source_url": row["source_url"],
                            "houjin_bangou": row["houjin_bangou"],
                            "enforcement_kind": row["enforcement_kind"],
                            "issuing_authority": row["issuing_authority"],
                            "issuance_date": row["issuance_date"],
                            "reason_summary": row["reason_summary"],
                        }
                    )

            case_cols = self._table_columns(am_conn, "jpi_enforcement_cases")
            if {
                "case_id",
                "recipient_houjin_bangou",
                "recipient_name",
            }.issubset(case_cols):
                checked_tables.append("jpi_enforcement_cases")
                try:
                    rows = am_conn.execute(
                        """SELECT case_id, recipient_houjin_bangou,
                                  recipient_name, event_type, ministry,
                                  disclosed_date, legal_basis, reason_excerpt,
                                  source_url
                             FROM jpi_enforcement_cases
                            WHERE recipient_houjin_bangou = ?
                         ORDER BY disclosed_date DESC
                            LIMIT ?""",
                        (bangou, remaining - len(records)),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                for row in rows:
                    exact_match_found = True
                    add_record(
                        {
                            "entity_id": row["case_id"],
                            "primary_name": row["recipient_name"] or row["case_id"],
                            "record_kind": "enforcement_case",
                            "source_url": row["source_url"],
                            "houjin_bangou": row["recipient_houjin_bangou"],
                            "event_type": row["event_type"],
                            "ministry": row["ministry"],
                            "disclosed_date": row["disclosed_date"],
                            "legal_basis": row["legal_basis"],
                            "reason_excerpt": row["reason_excerpt"],
                        }
                    )

            if not exact_match_found:
                add_structured_miss(
                    entity_id=f"structured_miss:enforcement:{bangou}",
                    primary_name=f"法人番号 {bangou} 行政処分ローカル照合",
                    source_url=None,
                    lookup={
                        "kind": "enforcement_by_houjin_bangou",
                        "houjin_bangou": bangou,
                        "status": (
                            "not_found_in_local_mirror" if checked_tables else "mirror_unavailable"
                        ),
                        "checked_tables": checked_tables,
                        "official_absence_proven": False,
                        "note": (
                            "ローカルミラーで法人番号完全一致の行政処分を検出"
                            "できませんでした。これは公式に処分が存在しない"
                            "ことの証明ではありません。due diligence では一次"
                            "資料または公式検索で再確認してください。"
                        ),
                    },
                )

        if bangou and "採択" in text:
            try:
                rows = am_conn.execute(
                    """SELECT id, houjin_bangou, program_name_raw, company_name_raw,
                              round_label, announced_at, prefecture, source_url,
                              fetched_at
                         FROM jpi_adoption_records
                        WHERE houjin_bangou = ?
                     ORDER BY announced_at DESC
                        LIMIT ?""",
                    (bangou, remaining),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                title = " / ".join(
                    part
                    for part in (
                        row["company_name_raw"],
                        row["program_name_raw"],
                        row["round_label"],
                    )
                    if part
                )
                add_record(
                    {
                        "entity_id": f"adoption:{row['id']}",
                        "primary_name": title or row["houjin_bangou"],
                        "record_kind": "adoption_record",
                        "source_url": row["source_url"],
                        "houjin_bangou": row["houjin_bangou"],
                        "announced_at": row["announced_at"],
                        "prefecture": row["prefecture"],
                        "fetched_at": row["fetched_at"],
                    }
                )

        if bangou and "適格請求書" in text:
            checked_tables: list[str] = []
            exact_match_found = False
            try:
                if self._table_columns(am_conn, "jpi_invoice_registrants"):
                    checked_tables.append("jpi_invoice_registrants")
                rows = am_conn.execute(
                    """SELECT invoice_registration_number, houjin_bangou,
                              normalized_name, registered_date, prefecture,
                              source_url, fetched_at
                         FROM jpi_invoice_registrants
                        WHERE invoice_registration_number IN (?, ?)
                           OR houjin_bangou = ?
                        LIMIT ?""",
                    (f"T{bangou}", bangou, bangou, remaining - len(records)),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                exact_match_found = True
                add_record(
                    {
                        "entity_id": row["invoice_registration_number"],
                        "primary_name": row["normalized_name"],
                        "record_kind": "invoice_registrant",
                        "source_url": row["source_url"],
                        "houjin_bangou": row["houjin_bangou"],
                        "registered_date": row["registered_date"],
                        "prefecture": row["prefecture"],
                        "fetched_at": row["fetched_at"],
                    }
                )
            if not exact_match_found:
                add_structured_miss(
                    entity_id=f"structured_miss:invoice:T{bangou}",
                    primary_name=f"T{bangou} インボイス登録ローカル照合",
                    source_url="https://www.invoice-kohyo.nta.go.jp/",
                    lookup={
                        "kind": "invoice_registration_number",
                        "invoice_registration_number": f"T{bangou}",
                        "houjin_bangou": bangou,
                        "status": (
                            "not_found_in_local_mirror" if checked_tables else "mirror_unavailable"
                        ),
                        "checked_tables": checked_tables,
                        "official_absence_proven": False,
                        "note": (
                            "ローカルの国税庁インボイス公表ミラーでは完全一致"
                            "しませんでした。登録日の確定には国税庁の公式"
                            "公表サイトで再確認してください。"
                        ),
                    },
                )

        def run_like_query(
            *,
            table: str,
            id_col: str,
            name_col: str,
            source_col: str,
            record_kind: str,
            search_cols: tuple[str, ...],
            extra_select: tuple[str, ...] = (),
        ) -> None:
            if len(records) >= remaining:
                return
            cols = self._table_columns(am_conn, table)
            required = {id_col, name_col}
            if not required.issubset(cols):
                return
            usable_search_cols = [col for col in search_cols if col in cols]
            if not usable_search_cols:
                return
            selected = [id_col, name_col]
            if source_col in cols:
                selected.append(source_col)
            selected.extend(col for col in extra_select if col in cols)
            selected_sql = ", ".join(selected)

            term_clauses: list[str] = []
            where_params: list[Any] = []
            score_parts: list[str] = []
            score_params: list[Any] = []
            for term in terms:
                term_clauses.append(
                    "(" + " OR ".join(f"{col} LIKE ?" for col in usable_search_cols) + ")"
                )
                where_params.extend([f"%{term}%"] * len(usable_search_cols))
                score_parts.append(f"CASE WHEN {name_col} LIKE ? THEN 10 ELSE 0 END")
                score_params.append(f"%{term}%")
            sql = (
                f"SELECT {selected_sql}, ({' + '.join(score_parts)}) AS _score "
                f"FROM {table} "
                f"WHERE {' OR '.join(term_clauses)} "
                "ORDER BY _score DESC "
                "LIMIT ?"
            )
            try:
                rows = am_conn.execute(
                    sql, [*score_params, *where_params, remaining - len(records)]
                ).fetchall()
            except sqlite3.OperationalError:
                return
            for row in rows:
                row_keys = set(row.keys())
                record: dict[str, Any] = {
                    "entity_id": row[id_col],
                    "primary_name": row[name_col],
                    "record_kind": record_kind,
                    "source_url": row[source_col] if source_col in row_keys else None,
                }
                for col in extra_select:
                    if col in row_keys and row[col]:
                        record[col] = row[col]
                add_record(record)

        query_specs: dict[str, dict[str, Any]] = {
            "law": {
                "table": "jpi_laws",
                "id_col": "unified_id",
                "name_col": "law_title",
                "source_col": "source_url",
                "record_kind": "law",
                "search_cols": (
                    "law_title",
                    "law_short_title",
                    "summary",
                    "subject_areas_json",
                ),
                "extra_select": ("law_short_title", "ministry"),
            },
            "tax": {
                "table": "jpi_tax_rulesets",
                "id_col": "unified_id",
                "name_col": "ruleset_name",
                "source_col": "source_url",
                "record_kind": "tax_ruleset",
                "search_cols": (
                    "ruleset_name",
                    "tax_category",
                    "eligibility_conditions",
                    "filing_requirements",
                    "source_excerpt",
                ),
                "extra_select": ("tax_category", "authority", "rate_or_amount"),
            },
            "enforcement": {
                "table": "am_enforcement_detail",
                "id_col": "enforcement_id",
                "name_col": "target_name",
                "source_col": "source_url",
                "record_kind": "enforcement",
                "search_cols": (
                    "target_name",
                    "enforcement_kind",
                    "issuing_authority",
                    "reason_summary",
                    "related_law_ref",
                ),
                "extra_select": (
                    "enforcement_kind",
                    "issuing_authority",
                    "issuance_date",
                ),
            },
        }
        for kind in self._non_program_context_order(query_text):
            run_like_query(**query_specs[kind])
        return records

    # ------------------------------------------------------------------
    # Public composer entry points.
    # ------------------------------------------------------------------

    def compose_for_program(
        self,
        program_id: str,
        *,
        include_facts: bool = True,
        include_rules: bool = True,
        include_compression: bool = False,
        fields: str = "default",
        input_token_price_jpy_per_1m: float | None = None,
        source_tokens_basis: CompressionSourceBasis = "unknown",
        source_pdf_pages: int | None = None,
        source_token_count: int | None = None,
        profile: str = "full",
    ) -> dict[str, Any] | None:
        """Compose a single-record packet for one program.

        Returns ``None`` when the program_id resolves to nothing
        (callers translate to 404).

        ``profile`` (§4.3): one of ``full`` / ``brief`` / ``verified_only`` /
        ``changes_only``. Applied AFTER citation_verification join so the
        ``verified_only`` filter has access to the latest verdicts.
        """
        return self._compose_single_subject(
            subject_kind="program",
            subject_id=program_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            source_tokens_basis=source_tokens_basis,
            source_pdf_pages=source_pdf_pages,
            source_token_count=source_token_count,
            profile=profile,
        )

    def compose_for_houjin(
        self,
        bangou: str,
        *,
        include_facts: bool = True,
        include_rules: bool = False,
        include_compression: bool = False,
        fields: str = "default",
        input_token_price_jpy_per_1m: float | None = None,
        source_tokens_basis: CompressionSourceBasis = "unknown",
        source_pdf_pages: int | None = None,
        source_token_count: int | None = None,
        profile: str = "full",
    ) -> dict[str, Any] | None:
        """Compose a single-record packet for one 法人番号.

        ``rules`` defaults to False — corporate subjects don't have a
        direct compat_matrix surface today.
        """
        return self._compose_single_subject(
            subject_kind="houjin",
            subject_id=bangou,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            source_tokens_basis=source_tokens_basis,
            source_pdf_pages=source_pdf_pages,
            source_token_count=source_token_count,
            profile=profile,
        )

    def compose_for_query(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        *,
        limit: int = 10,
        include_facts: bool = True,
        include_rules: bool = False,
        include_compression: bool = False,
        fields: str = "default",
        input_token_price_jpy_per_1m: float | None = None,
        source_tokens_basis: CompressionSourceBasis = "unknown",
        source_pdf_pages: int | None = None,
        source_token_count: int | None = None,
        profile: str = "full",
    ) -> dict[str, Any]:
        """Compose a multi-record packet for a search query.

        Each record is composed via ``compose_for_program`` so the wire
        shape stays in lockstep. Truncation surfaces ``_warning="truncated"``.
        """
        filters = filters or {}
        snapshot_id = self._derive_snapshot_id_safe()
        cache_key = self._make_cache_key(
            "query",
            f"{query_text}|{sorted(filters.items())}|{limit}",
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            source_tokens_basis=source_tokens_basis,
            source_pdf_pages=source_pdf_pages,
            source_token_count=source_token_count,
            corpus_snapshot_id=snapshot_id,
            profile=profile,
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        # Discover subject ids via jpi_programs (autonomath mirror).
        subject_ids: list[str] = []
        am = None
        try:
            am = self._open_ro(self.autonomath_db)
            subject_ids = self._discover_program_ids_for_query(
                am,
                query_text,
                filters,
                limit=limit,
            )
        except FileNotFoundError:
            subject_ids = []
        finally:
            if am is not None:
                am.close()

        truncated = len(subject_ids) > min(limit, MAX_RECORDS_PER_PACKET)
        subject_ids = subject_ids[: min(limit, MAX_RECORDS_PER_PACKET)]

        records: list[dict[str, Any]] = []
        gaps: list[str] = []
        for sid in subject_ids:
            inner = self._compose_single_subject(
                subject_kind="program",
                subject_id=sid,
                include_facts=include_facts,
                include_rules=include_rules,
                include_compression=False,
                fields=fields,
                input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
                source_tokens_basis="unknown",
                source_pdf_pages=None,
                source_token_count=None,
            )
            if inner is None:
                continue
            # Lift inner.records[0] up.
            for rec in inner.get("records", []):
                records.append(deepcopy(rec))
            for g in inner.get("quality", {}).get("known_gaps", []):
                if g not in gaps:
                    gaps.append(g)

        preferred_non_program = self._prefers_non_program_context(query_text)
        remaining = min(limit, MAX_RECORDS_PER_PACKET) - len(records)
        non_program_limit = (
            min(limit, MAX_RECORDS_PER_PACKET) if preferred_non_program else remaining
        )
        if non_program_limit > 0 and query_text:
            am = None
            try:
                am = self._open_ro(self.autonomath_db)
                non_program_records = self._discover_non_program_records_for_query(
                    am,
                    query_text,
                    limit=non_program_limit,
                )
                if preferred_non_program and non_program_records:
                    merged: list[dict[str, Any]] = []
                    seen_records: set[tuple[str, str]] = set()
                    for rec in [*non_program_records, *records]:
                        key = (
                            str(rec.get("record_kind")),
                            str(rec.get("entity_id")),
                        )
                        if key in seen_records:
                            continue
                        seen_records.add(key)
                        merged.append(rec)
                        if len(merged) >= min(limit, MAX_RECORDS_PER_PACKET):
                            break
                    records = merged
                else:
                    records.extend(non_program_records)
            except FileNotFoundError:
                pass
            finally:
                if am is not None:
                    am.close()

        coverage_score = self._coverage_score(records)
        envelope: dict[str, Any] = {
            "packet_id": self._new_packet_id(),
            "generated_at": self._now_jst_iso(),
            "api_version": PACKET_API_VERSION,
            "corpus_snapshot_id": snapshot_id,
            "query": {
                "user_intent": query_text,
                "normalized_filters": dict(filters),
            },
            "answer_not_included": True,
            "records": records,
            "quality": {
                "freshness_bucket": self._freshness_bucket(snapshot_id),
                "freshness_scope": "corpus_wide_max_not_record_level",
                "freshness_basis": "corpus_snapshot_id",
                "coverage_score": coverage_score,
                "known_gaps": gaps,
                "human_review_required": self._human_review_required(records, coverage_score),
            },
            "verification": {
                "replay_endpoint": (
                    f"/v1/programs/search?q={query_text}" if query_text else "/v1/programs/search"
                ),
                "provenance_endpoint": "",
                "freshness_endpoint": _FRESHNESS_ENDPOINT,
            },
            "_disclaimer": _DISCLAIMER,
        }
        if truncated:
            envelope["_warning"] = "truncated"
        if any(rec.get("precomputed") for rec in records):
            envelope["answer_basis"] = "precomputed"
        if input_token_price_jpy_per_1m is not None:
            envelope["_token_pricing_input_jpy_per_1m"] = input_token_price_jpy_per_1m
        if include_compression:
            self._attach_compression_block(
                envelope,
                source_url=None,
                input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
                source_tokens_basis=source_tokens_basis,
                source_pdf_pages=source_pdf_pages,
                source_token_count=source_token_count,
            )

        self._attach_agent_recommendation(envelope)
        self._attach_evidence_value(envelope, composer=self)
        _attach_known_gaps_inventory(envelope)
        # Apply the §4.3 profile projection AFTER evidence_value attaches
        # citations[] so verified_only can read the latest verdicts.
        self._apply_profile(envelope, profile)
        self._refresh_projection_metadata(envelope, composer=self)
        _cache_put(cache_key, envelope)
        return envelope

    # ------------------------------------------------------------------
    # Single-subject worker.
    # ------------------------------------------------------------------

    def _derive_snapshot_id_safe(self) -> str:
        am = None
        try:
            am = self._open_ro(self.autonomath_db)
            return self._corpus_snapshot_id(am)
        except FileNotFoundError:
            return self._corpus_snapshot_id(None)
        finally:
            if am is not None:
                am.close()

    def _compose_single_subject(
        self,
        *,
        subject_kind: SubjectKind,
        subject_id: str,
        include_facts: bool,
        include_rules: bool,
        include_compression: bool,
        fields: str,
        input_token_price_jpy_per_1m: float | None,
        source_tokens_basis: CompressionSourceBasis,
        source_pdf_pages: int | None,
        source_token_count: int | None,
        profile: str = "full",
    ) -> dict[str, Any] | None:
        # 1. Cache check (snapshot_id is part of the key — re-derived per
        #    call, cheap because _corpus_snapshot has its own 5min cache).
        snapshot_id = self._derive_snapshot_id_safe()
        cache_key = self._make_cache_key(
            subject_kind,
            subject_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            source_tokens_basis=source_tokens_basis,
            source_pdf_pages=source_pdf_pages,
            source_token_count=source_token_count,
            corpus_snapshot_id=snapshot_id,
            profile=profile,
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        # 2. Resolve subject metadata. Deferred imports so the test guard
        #    can verify NO LLM modules are imported at composer load time.
        am = None
        try:
            am = self._open_ro(self.autonomath_db)
        except FileNotFoundError:
            logger.warning("evidence_packet: autonomath.db missing at %s", self.autonomath_db)
            return None

        gaps: list[str] = []
        precomputed_summary: dict[str, Any] | None = None
        recent_changes: list[dict[str, Any]] = []
        source_health: dict[str, Any] | None = None
        aliases: list[dict[str, Any]] = []
        pdf_fact_refs: list[dict[str, Any]] = []
        try:
            base: dict[str, Any]
            canonical_id = ""
            if subject_kind == "program":
                from jpintel_mcp.api.source_manifest import _resolve_program

                resolved = _resolve_program(am, subject_id)
                if resolved is None:
                    return None
                canonical_id, base = resolved
            elif subject_kind == "houjin":
                resolved = self._resolve_houjin(am, subject_id)
                if resolved is None:
                    return None
                canonical_id, base = resolved
            else:
                return None

            # 3. Per-record facts.
            facts: list[dict[str, Any]] = []
            total_facts = 0
            with_source = 0
            facts_truncated = False
            if include_facts and canonical_id:
                facts, total_facts, with_source = self._fetch_facts_for_entity(
                    am, canonical_id, MAX_FACTS_PER_RECORD
                )
                if len(facts) >= MAX_FACTS_PER_RECORD:
                    facts_truncated = True
            elif include_facts and not canonical_id:
                gaps.append("provenance_unavailable")

            # Verify am_amendment_diff is reachable for honesty signal.
            amendment_diff_available = True
            try:
                am.execute("SELECT 1 FROM am_amendment_diff LIMIT 1").fetchone()
            except sqlite3.OperationalError:
                amendment_diff_available = False
                gaps.append("amendment_diff_unavailable")

            if subject_kind == "program":
                precomputed_summary = self._fetch_program_summary(am, canonical_id)
                if amendment_diff_available:
                    recent_changes = self._fetch_recent_changes(am, canonical_id)
                source_health = self._fetch_source_health(
                    am,
                    base.get("primary_source_url"),
                    source_fetched_at=base.get("source_fetched_at"),
                )
                aliases = self._fetch_aliases(
                    am,
                    canonical_id,
                    base.get("program_id"),
                    base.get("primary_name"),
                )
                if include_facts:
                    pdf_fact_refs = self._fetch_pdf_fact_refs(am, canonical_id)
        finally:
            am.close()

        # 4. Per-record rules.
        rules: list[dict[str, Any]] = []
        if include_rules and subject_kind == "program":
            rules, rule_gaps = self._fetch_rules_for_program(
                canonical_id, subject_id, MAX_RULES_PER_RECORD
            )
            for g in rule_gaps:
                if g not in gaps:
                    gaps.append(g)

        # 5. Build the record.
        record: dict[str, Any] = {
            "entity_id": canonical_id or subject_id,
            "primary_name": base.get("primary_name"),
            "record_kind": subject_kind,
            "source_url": base.get("primary_source_url"),
        }
        if base.get("source_fetched_at"):
            record["source_fetched_at"] = base["source_fetched_at"]
        if base.get("authority_name"):
            record["authority_name"] = base["authority_name"]
        if base.get("prefecture"):
            record["prefecture"] = base["prefecture"]
        if base.get("tier"):
            record["tier"] = base["tier"]
        if include_facts:
            record["facts"] = facts
            record["fact_provenance_coverage_pct"] = (
                round(with_source / total_facts, 4) if total_facts > 0 else 0.0
            )
        if include_rules:
            record["rules"] = rules
        if precomputed_summary is not None:
            record["precomputed"] = precomputed_summary
            short_summary = self._build_short_summary(precomputed_summary)
            if short_summary is not None:
                record["short_summary"] = short_summary
        if recent_changes:
            record["recent_changes"] = recent_changes
        if source_health is not None:
            record["source_health"] = source_health
        if aliases:
            record["aliases"] = aliases
        if pdf_fact_refs:
            record["pdf_fact_refs"] = pdf_fact_refs

        coverage_score = self._coverage_score([record])

        envelope: dict[str, Any] = {
            "packet_id": self._new_packet_id(),
            "generated_at": self._now_jst_iso(),
            "api_version": PACKET_API_VERSION,
            "corpus_snapshot_id": snapshot_id,
            "query": {
                "user_intent": f"detail:{subject_kind}:{subject_id}",
                "normalized_filters": {},
            },
            "answer_not_included": True,
            "records": [record],
            "quality": {
                "freshness_bucket": self._freshness_bucket(snapshot_id),
                "freshness_scope": "corpus_wide_max_not_record_level",
                "freshness_basis": "corpus_snapshot_id",
                "coverage_score": coverage_score,
                "known_gaps": gaps,
                "human_review_required": self._human_review_required([record], coverage_score),
            },
            "verification": {
                "replay_endpoint": self._replay_endpoint(subject_kind, subject_id),
                "provenance_endpoint": (
                    f"/v1/am/provenance/{canonical_id}" if canonical_id else ""
                ),
                "freshness_endpoint": _FRESHNESS_ENDPOINT,
            },
            "_disclaimer": _DISCLAIMER,
        }

        if facts_truncated:
            envelope["_warning"] = "truncated"
        if precomputed_summary is not None:
            envelope["answer_basis"] = "precomputed"

        if input_token_price_jpy_per_1m is not None:
            envelope["_token_pricing_input_jpy_per_1m"] = input_token_price_jpy_per_1m
        if include_compression:
            self._attach_compression_block(
                envelope,
                source_url=record.get("source_url"),
                input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
                source_tokens_basis=source_tokens_basis,
                source_pdf_pages=source_pdf_pages,
                source_token_count=source_token_count,
            )

        self._attach_agent_recommendation(envelope)
        self._attach_evidence_value(envelope, composer=self)
        _attach_known_gaps_inventory(envelope)
        # Apply the §4.3 profile projection AFTER evidence_value attaches
        # citations[] so verified_only can read the latest verdicts.
        self._apply_profile(envelope, profile)
        self._refresh_projection_metadata(envelope, composer=self)
        _cache_put(cache_key, envelope)
        return envelope

    # ------------------------------------------------------------------
    # Houjin resolver (lightweight — am_entities + jpi_invoice_registrants).
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_houjin(
        am_conn: sqlite3.Connection, bangou: str
    ) -> tuple[str, dict[str, Any]] | None:
        b = (bangou or "").strip()
        if not b:
            return None
        # Match canonical_id first (corporate_entity:T<bangou>).
        candidates = [
            f"corporate_entity:T{b}",
            f"corporate_entity:{b}",
            b,
        ]
        for cid in candidates:
            try:
                row = am_conn.execute(
                    """SELECT canonical_id, primary_name, source_url, fetched_at
                         FROM am_entities
                        WHERE canonical_id = ?
                        LIMIT 1""",
                    (cid,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
            if row is not None:
                return row["canonical_id"], {
                    "program_id": b,
                    "primary_name": row["primary_name"],
                    "primary_source_url": row["source_url"],
                    "source_fetched_at": row["fetched_at"],
                    "authority_name": None,
                    "prefecture": None,
                    "tier": None,
                    "resolution_path": "am_canonical_id_houjin",
                }
        return None

    @staticmethod
    def _replay_endpoint(subject_kind: str, subject_id: str) -> str:
        if subject_kind == "program":
            return f"/v1/programs/{subject_id}?fields=full"
        if subject_kind == "houjin":
            return f"/v1/houjin/{subject_id}"
        return f"/v1/programs/search?q={subject_id}"

    # ------------------------------------------------------------------
    # Format dispatch helpers (used by REST layer).
    # ------------------------------------------------------------------

    @staticmethod
    def to_csv(envelope: dict[str, Any]) -> str:
        """Flatten records[] into CSV. Header row first.

        Columns: entity_id, primary_name, record_kind, source_url, tier,
        prefecture, fact_count, fact_provenance_coverage_pct, rule_count,
        corpus_snapshot_id.
        """
        import csv
        import io

        out = io.StringIO()
        w = csv.writer(out)
        header = [
            "entity_id",
            "primary_name",
            "record_kind",
            "source_url",
            "tier",
            "prefecture",
            "fact_count",
            "fact_provenance_coverage_pct",
            "rule_count",
            "corpus_snapshot_id",
        ]
        w.writerow(header)
        snap = envelope.get("corpus_snapshot_id", "")
        for rec in envelope.get("records", []):
            facts = rec.get("facts") or []
            rules = rec.get("rules") or []
            w.writerow(
                [
                    rec.get("entity_id", ""),
                    rec.get("primary_name", ""),
                    rec.get("record_kind", ""),
                    rec.get("source_url", ""),
                    rec.get("tier", ""),
                    rec.get("prefecture", ""),
                    len(facts),
                    rec.get("fact_provenance_coverage_pct", 0.0),
                    len(rules),
                    snap,
                ]
            )
        return out.getvalue()

    @staticmethod
    def to_markdown(envelope: dict[str, Any]) -> str:
        """Render a human-friendly markdown view."""
        lines: list[str] = []
        lines.append(f"# Evidence Packet `{envelope.get('packet_id', '')}`")
        lines.append("")
        lines.append(f"- generated_at: `{envelope.get('generated_at', '')}`")
        lines.append(f"- corpus_snapshot_id: `{envelope.get('corpus_snapshot_id', '')}`")
        lines.append(f"- api_version: `{envelope.get('api_version', '')}`")
        q = envelope.get("query", {}) or {}
        if q.get("user_intent"):
            lines.append(f"- user_intent: {q['user_intent']}")
        quality = envelope.get("quality", {}) or {}
        lines.append("")
        lines.append("## Quality")
        lines.append("")
        lines.append(f"- freshness_bucket: `{quality.get('freshness_bucket', '')}`")
        lines.append(f"- coverage_score: {quality.get('coverage_score', 0.0)}")
        lines.append(f"- human_review_required: `{quality.get('human_review_required', False)}`")
        gaps = quality.get("known_gaps") or []
        if gaps:
            lines.append("- known_gaps:")
            for g in gaps:
                lines.append(f"  - `{g}`")
        else:
            lines.append("- known_gaps: (none)")
        lines.append("")
        lines.append("## Records")
        lines.append("")
        for rec in envelope.get("records", []):
            lines.append(f"### `{rec.get('entity_id', '')}` — {rec.get('primary_name', '')}")
            lines.append("")
            lines.append(f"- record_kind: `{rec.get('record_kind', '')}`")
            if rec.get("source_url"):
                lines.append(f"- source_url: {rec['source_url']}")
            if rec.get("tier"):
                lines.append(f"- tier: `{rec['tier']}`")
            if rec.get("prefecture"):
                lines.append(f"- prefecture: {rec['prefecture']}")
            facts = rec.get("facts") or []
            if facts:
                lines.append(f"- facts: {len(facts)}")
                for f in facts[:10]:
                    src = f.get("source") or {}
                    src_str = src.get("url") or "(no source)"
                    lines.append(
                        f"  - **{f.get('field')}** = `{f.get('value')}` "
                        f"(conf={f.get('confidence', 0.0)}, src={src_str})"
                    )
                if len(facts) > 10:
                    lines.append(f"  - … and {len(facts) - 10} more facts")
            rules = rec.get("rules") or []
            if rules:
                lines.append(f"- rules: {len(rules)}")
                for r in rules[:10]:
                    lines.append(
                        f"  - **{r.get('verdict')}** — "
                        f"{r.get('note', '')[:120]} "
                        f"(rule_id=`{r.get('rule_id', '')}`)"
                    )
                if len(rules) > 10:
                    lines.append(f"  - … and {len(rules) - 10} more rules")
            lines.append("")
        ver = envelope.get("verification", {}) or {}
        lines.append("## Verification")
        lines.append("")
        lines.append(f"- replay: `{ver.get('replay_endpoint', '')}`")
        lines.append(f"- provenance: `{ver.get('provenance_endpoint', '')}`")
        lines.append(f"- freshness: `{ver.get('freshness_endpoint', '')}`")
        lines.append("")
        lines.append("---")
        d = envelope.get("_disclaimer") or {}
        lines.append(f"_Disclaimer:_ {d.get('note', '')}")
        return "\n".join(lines)


__all__ = [
    "EvidencePacketComposer",
    "MAX_RECORDS_PER_PACKET",
    "PACKET_API_VERSION",
    "_reset_cache_for_tests",
]
