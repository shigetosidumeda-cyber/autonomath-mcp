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
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

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
    return body


def _cache_put(key: str, body: dict[str, Any]) -> None:
    _CACHE[key] = (time.monotonic() + _CACHE_TTL_SEC, body)


def _reset_cache_for_tests() -> None:
    """Test helper. Drops the process-local packet cache."""
    _CACHE.clear()


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
            row = am_conn.execute(
                "SELECT MAX(detected_at) FROM am_amendment_diff"
            ).fetchone()
            if row is not None and row[0]:
                return f"corpus-{str(row[0])[:10]}"
        except sqlite3.OperationalError:
            pass
        try:
            row = am_conn.execute(
                "SELECT MAX(last_verified) FROM am_source"
            ).fetchone()
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
                rules.append(
                    {
                        "rule_id": (
                            chain_entry.get("rule_id")
                            or f"compat:{canonical_id or primary_id}:{partner}"
                        ),
                        "verdict": verdict_label,
                        "evidence_url": (
                            chain_entry.get("source_url")
                            or (chain_entry.get("source_urls") or [None])[0]
                            or ""
                        ),
                        "note": chain_entry.get("rule_text", "")[:300],
                        "_partner_program": partner,
                        "_confidence": verdict.confidence,
                    }
                )
            if len(rules) >= cap:
                break
        return rules, gaps

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

    # ------------------------------------------------------------------
    # Quality scoring.
    # ------------------------------------------------------------------

    @staticmethod
    def _freshness_bucket(snapshot_id: str) -> str:
        """Map ``corpus-YYYY-MM-DD`` to a freshness bucket."""
        if not snapshot_id.startswith("corpus-"):
            return "unknown"
        date_part = snapshot_id[len("corpus-"):]
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
    def _human_review_required(
        records: list[dict[str, Any]], coverage_score: float
    ) -> bool:
        for rec in records:
            for rule in rec.get("rules") or []:
                if rule.get("verdict") in {"defer", "block", "unknown"}:
                    return True
        return coverage_score < 0.5

    # ------------------------------------------------------------------
    # Cache key + envelope build.
    # ------------------------------------------------------------------

    @staticmethod
    def _make_cache_key(
        subject_kind: str,
        subject_id: str,
        *,
        include_facts: bool,
        include_rules: bool,
        include_compression: bool,
        fields: str,
        input_token_price_jpy_per_1m: float | None,
        corpus_snapshot_id: str,
    ) -> str:
        return "|".join(
            [
                subject_kind,
                subject_id,
                str(include_facts),
                str(include_rules),
                str(include_compression),
                fields,
                str(input_token_price_jpy_per_1m or ""),
                corpus_snapshot_id,
            ]
        )

    @staticmethod
    def _new_packet_id() -> str:
        return f"evp_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _now_jst_iso() -> str:
        return datetime.now(_JST).isoformat(timespec="seconds")

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
    ) -> dict[str, Any] | None:
        """Compose a single-record packet for one program.

        Returns ``None`` when the program_id resolves to nothing
        (callers translate to 404).
        """
        return self._compose_single_subject(
            subject_kind="program",
            subject_id=program_id,
            include_facts=include_facts,
            include_rules=include_rules,
            include_compression=include_compression,
            fields=fields,
            input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
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
            corpus_snapshot_id=snapshot_id,
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        # Discover subject ids via jpi_programs (autonomath mirror).
        subject_ids: list[str] = []
        am = None
        try:
            am = self._open_ro(self.autonomath_db)
            sql_clauses: list[str] = []
            params: list[Any] = []
            if query_text:
                sql_clauses.append("primary_name LIKE ?")
                params.append(f"%{query_text}%")
            pref = filters.get("prefecture")
            if pref:
                sql_clauses.append("prefecture = ?")
                params.append(pref)
            tier = filters.get("tier")
            if tier:
                sql_clauses.append("tier = ?")
                params.append(tier)
            where = (" WHERE " + " AND ".join(sql_clauses)) if sql_clauses else ""
            sql = (
                "SELECT unified_id FROM jpi_programs"
                f"{where} ORDER BY tier ASC LIMIT ?"
            )
            params.append(min(limit, MAX_RECORDS_PER_PACKET) + 1)
            try:
                rows = am.execute(sql, params).fetchall()
                subject_ids = [r["unified_id"] for r in rows if r["unified_id"]]
            except sqlite3.OperationalError:
                subject_ids = []
        except FileNotFoundError:
            subject_ids = []
        finally:
            if am is not None:
                am.close()

        truncated = len(subject_ids) > min(limit, MAX_RECORDS_PER_PACKET)
        subject_ids = subject_ids[:min(limit, MAX_RECORDS_PER_PACKET)]

        records: list[dict[str, Any]] = []
        gaps: list[str] = []
        for sid in subject_ids:
            inner = self._compose_single_subject(
                subject_kind="program",
                subject_id=sid,
                include_facts=include_facts,
                include_rules=include_rules,
                include_compression=include_compression,
                fields=fields,
                input_token_price_jpy_per_1m=input_token_price_jpy_per_1m,
            )
            if inner is None:
                continue
            # Lift inner.records[0] up.
            for rec in inner.get("records", []):
                records.append(rec)
            for g in inner.get("quality", {}).get("known_gaps", []):
                if g not in gaps:
                    gaps.append(g)

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
                "coverage_score": coverage_score,
                "known_gaps": gaps,
                "human_review_required": self._human_review_required(
                    records, coverage_score
                ),
            },
            "verification": {
                "replay_endpoint": (
                    f"/v1/programs/search?q={query_text}"
                    if query_text else "/v1/programs/search"
                ),
                "provenance_endpoint": "",
                "freshness_endpoint": _FRESHNESS_ENDPOINT,
            },
            "_disclaimer": _DISCLAIMER,
        }
        if truncated:
            envelope["_warning"] = "truncated"

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
            corpus_snapshot_id=snapshot_id,
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
            logger.warning(
                "evidence_packet: autonomath.db missing at %s", self.autonomath_db
            )
            return None

        gaps: list[str] = []
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
            try:
                am.execute("SELECT 1 FROM am_amendment_diff LIMIT 1").fetchone()
            except sqlite3.OperationalError:
                gaps.append("amendment_diff_unavailable")
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
                "coverage_score": coverage_score,
                "known_gaps": gaps,
                "human_review_required": self._human_review_required(
                    [record], coverage_score
                ),
            },
            "verification": {
                "replay_endpoint": self._replay_endpoint(
                    subject_kind, subject_id
                ),
                "provenance_endpoint": (
                    f"/v1/am/provenance/{canonical_id}"
                    if canonical_id
                    else ""
                ),
                "freshness_endpoint": _FRESHNESS_ENDPOINT,
            },
            "_disclaimer": _DISCLAIMER,
        }

        if facts_truncated:
            envelope["_warning"] = "truncated"

        if input_token_price_jpy_per_1m is not None:
            envelope["_token_pricing_input_jpy_per_1m"] = (
                input_token_price_jpy_per_1m
            )
        if include_compression:
            envelope["_compression_hint"] = (
                "include_compression=True placeholder; the deterministic "
                "token estimator lives in services/token_compression.py "
                "(not yet shipped)."
            )

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
        lines.append(
            f"- corpus_snapshot_id: `{envelope.get('corpus_snapshot_id', '')}`"
        )
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
        lines.append(
            f"- human_review_required: "
            f"`{quality.get('human_review_required', False)}`"
        )
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
            lines.append(
                f"### `{rec.get('entity_id', '')}` — {rec.get('primary_name', '')}"
            )
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
