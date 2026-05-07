#!/usr/bin/env python3
"""Idempotent ingest pipeline for the 2026-04-23 external data-collection drop.

Reads per-directory ``records.jsonl`` files under the configured data-dir
(default ``/tmp/autonomath_data_collection_2026-04-23/``) and UPSERTs each
row into the appropriate table:

    03_exclusion_rules        -> exclusion_rules   (legacy table + new cols)
    04_program_documents      -> program_documents (new)
    06_prefecture_programs    -> programs          (UPSERT new external rows)
    07_new_program_candidates -> new_program_candidates (new)
    08_loan_programs          -> loan_programs     (new) + mirror to programs
    13_enforcement_cases      -> enforcement_cases (new)
    22_mirasapo_cases         -> case_studies      (new)
    49_case_law_judgments     -> case_law          (new, migration 012)
    09/11/12/14/15/16/17/20/21/23/25/26/27/29/33
                              -> programs          (UPSERT new external rows)
    01/02/05/10/18/19/32      -> skipped (stats/master/FAQ, out of scope)

Design guarantees:

* **Idempotent.** Every write uses SQLite's UPSERT form
  (``ON CONFLICT(...) DO UPDATE SET ...``) keyed on the table's natural
  PK or UNIQUE constraint. Re-running the script after ``records.jsonl``
  grew does not double-count rows already ingested on a previous pass.
* **Preserves existing data.** For ``programs`` UPSERTs, rows with
  ``excluded = 1`` are never overwritten (the existing 509-row
  excluded cohort carries operator-blessed state). Non-excluded
  existing rows are updated only on columns that arrive non-null —
  we never clobber a populated canonical field with an external NULL.
* **Safe under concurrent writes.** The input directory is still being
  filled by a parallel data-collection agent. We open each JSONL with
  streaming reads, skip partially-written lines (JSON parse failure
  logged + counted as ``skip_parse_error``), and every DB write is
  transacted so a killed run leaves no half-applied state.
* **Prefix-isolated unified_ids.** Program rows created from external
  data use a ``UNI-ext-<10hex>`` namespace so they cannot collide with
  the canonical ``UNI-<10hex>`` ingested from unified_registry.json.

CLI:

    python scripts/ingest_external_data.py \\
        --data-dir /tmp/autonomath_data_collection_2026-04-23/ \\
        [--dry-run] [--only 13_enforcement_cases] [--since 2026-04-23T12:00:00Z]

See ``tests/test_ingest_external_data.py`` for the fixture-driven
behaviour contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

try:
    import orjson  # fastest JSONL parser; matches project convention
except ImportError:  # pragma: no cover - orjson is a hard dep in pyproject.toml
    orjson = None  # type: ignore[assignment]


_LOG = logging.getLogger("jpintel.ingest_external")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_DATA_DIR = Path("/tmp/autonomath_data_collection_2026-04-23/")  # nosec B108 - one-shot historical data dir; --data-dir overrides
LOG_DIR = REPO_ROOT / "data"

# Directories we skip — these carry aggregate stats / distributions / FAQs
# and belong to a different schema stream. Not an error, just out of scope
# for migration 011.
SKIP_DIRS: frozenset[str] = frozenset(
    {
        "01_meti_acceptance_stats",  # per-round acceptance ratios
        "02_maff_acceptance_stats",  # per-round acceptance ratios
        "05_adoption_additional",  # 100k+ adoption award rows
        "18_estat_industry_distribution",  # 73k estat industry rows
        "19_ministry_qa_faq",  # ministry FAQ Q&A
        "10_municipality_master",  # master.json / historical_raw.json (master schema, not program records)
        "32_houjin_master",  # master.jsonl (houjin master, 数百万件クラス)
    }
)


# Aggregator domains we refuse to store as `source_url`. CLAUDE.md rule:
# "Aggregators like noukaweb, hojyokin-portal, biz.stayway are banned from
# source_url — past incidents created 詐欺 risk." The collector agent can
# still surface these URLs during discovery but the ingest must never
# write them as a primary citation. Match on host substring — cheap and
# robust to subdomain drift.
BANNED_SOURCE_HOSTS: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
)


def _first_str(val: Any) -> str | None:
    """Normalise list/tuple to first non-empty string; passthrough str/None.

    Some collector dirs emit plural URL keys (``primary_source_urls``,
    ``source_urls``) holding a list. Downstream code expects str, so
    collapse to the first element here.
    """
    if val is None:
        return None
    if isinstance(val, str):
        return val or None
    if isinstance(val, (list, tuple)):
        for item in val:
            if isinstance(item, str) and item:
                return item
        return None
    return None


def _source_url_is_banned(url: Any) -> bool:
    s = _first_str(url)
    if not s:
        return False
    low = s.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


# ---------------------------------------------------------------------------
# JSONL streaming
# ---------------------------------------------------------------------------


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load records.jsonl defensively.

    The upstream writer is still running; a final line may be partial.
    We parse line-by-line and log parse errors rather than aborting the
    whole ingest.
    """
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("rb") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = orjson.loads(raw) if orjson is not None else json.loads(raw.decode("utf-8"))
            except (ValueError, json.JSONDecodeError) as e:
                _LOG.warning("skip_parse_error file=%s line=%d err=%s", path.name, lineno, e)
                continue
            if not isinstance(row, dict):
                continue
            rows.append(row)
    return rows


def _json_dump(v: Any) -> str | None:
    """Serialize a list/dict to compact JSON; return None for empties."""
    if v is None:
        return None
    if isinstance(v, (list, dict)) and not v:
        return None
    if orjson is not None:
        return orjson.dumps(v).decode("utf-8")
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _bool_to_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    # occasionally represented as strings "true"/"false" upstream
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes"):
            return 1
        if s in ("false", "0", "no"):
            return 0
    if isinstance(v, (int, float)):
        return 1 if v else 0
    return None


def _passes_since(fetched_at: Any, since: str | None) -> bool:
    """True if `fetched_at` is later than `since` (or no filter)."""
    if not since:
        return True
    if not isinstance(fetched_at, str) or not fetched_at:
        # Unknown timestamp → include. Upstream usually populates this.
        return True
    # Lex comparison on ISO-8601 works for same-offset strings. We don't
    # promise tz normalisation here — the upstream writer is consistent.
    return fetched_at >= since


# ---------------------------------------------------------------------------
# Unified ID derivation
# ---------------------------------------------------------------------------


def _ext_unified_id(name: str, *extra: Any) -> str:
    """Deterministic UNI-ext-<10hex> from (name, *extra).

    The `ext` prefix is deliberate — it keeps the external namespace
    separate from the canonical ``UNI-xxxx`` rows that unified_registry.json
    produces. Even if two independent directories name the same program
    the same way, the deterministic hash means a re-ingest is
    idempotent (UPSERT on unified_id).
    """

    def _stringify(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, (list, tuple)):
            return "/".join(_stringify(x) for x in v)
        if isinstance(v, dict):
            return json.dumps(v, sort_keys=True, ensure_ascii=False)
        return str(v)

    parts = [name or ""] + [_stringify(e) for e in extra]
    blob = "|".join(parts).encode("utf-8")
    digest = hashlib.sha1(blob).hexdigest()[:10]
    return f"UNI-ext-{digest}"


def _ext_rule_id(program_a: str, source_url: str | None, program_b: Any) -> str:
    """Deterministic rule_id for external exclusion rules.

    Includes program_b in the hash so distinct (program_a -> program_b)
    pairs from different source rows produce distinct rule_ids, avoiding
    spurious UPDATE-on-UPSERT when the same program_a shows up in
    multiple source rows with different excluded_programs lists.
    """
    key = f"{program_a}|{source_url or ''}|{program_b or ''}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"excl-ext-{digest}"


# ---------------------------------------------------------------------------
# Programs UPSERT
# ---------------------------------------------------------------------------


_PROGRAM_FIELDS_UPDATABLE = (
    "primary_name",
    "aliases_json",
    "authority_level",
    "authority_name",
    "prefecture",
    "municipality",
    "program_kind",
    "official_url",
    "amount_max_man_yen",
    "amount_min_man_yen",
    "subsidy_rate",
    "target_types_json",
    "funding_purpose_json",
    "source_url",
    "source_fetched_at",
    "source_checksum",
    "enriched_json",
)


def _upsert_program(conn: sqlite3.Connection, row: dict[str, Any], now: str) -> str:
    """UPSERT a program row and return one of {"insert","update","skip"}.

    Contract:
      * `row` must already be normalised to the programs-table column
        set (caller translates directory-specific keys).
      * `row['unified_id']` must be set — we always use the external
        namespace (`UNI-ext-*`) from the caller.
      * Existing rows with `excluded = 1` are NEVER overwritten.
      * For non-excluded existing rows, non-null columns in `row` win;
        existing non-null columns stay put when `row` has null — we
        never clobber populated canonical fields with an external null.
    """
    uid = row["unified_id"]
    prev = conn.execute(
        "SELECT excluded, "
        + ", ".join(_PROGRAM_FIELDS_UPDATABLE)
        + " FROM programs WHERE unified_id = ?",
        (uid,),
    ).fetchone()

    if prev is None:
        # Default tier for ext rows: C when we have both a primary-source
        # URL and an authority_name (meets CLAUDE.md "every row must cite
        # a primary source"). X otherwise — stays in quarantine so the
        # user-facing search never surfaces unattributed rows.
        ext_tier: str | None = None
        if uid.startswith("UNI-ext-"):
            has_url = bool(_first_str(row.get("source_url")))
            has_auth = bool(_first_str(row.get("authority_name")))
            ext_tier = "C" if (has_url and has_auth) else "X"

        # INSERT. Seed lineage on new rows so source_fetched_at is honest.
        conn.execute(
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
                updated_at
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )""",
            (
                uid,
                row.get("primary_name") or "",
                row.get("aliases_json"),
                row.get("authority_level"),
                row.get("authority_name"),
                row.get("prefecture"),
                row.get("municipality"),
                row.get("program_kind"),
                row.get("official_url"),
                row.get("amount_max_man_yen"),
                row.get("amount_min_man_yen"),
                row.get("subsidy_rate"),
                None,  # trust_level
                ext_tier,  # tier — C for ext w/ primary source, X else
                None,  # coverage_score
                None,  # gap_to_tier_s_json
                None,  # a_to_j_coverage_json
                0,  # excluded
                None,  # exclusion_reason
                None,  # crop_categories_json
                None,  # equipment_category
                row.get("target_types_json"),
                row.get("funding_purpose_json"),
                None,  # amount_band
                None,  # application_window_json
                row.get("enriched_json"),
                None,  # source_mentions_json
                row.get("source_url"),
                row.get("source_fetched_at") or now,
                row.get("source_checksum"),
                now,
            ),
        )
        # FTS row for discoverability. We keep it simple — name only.
        conn.execute(
            "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
            "VALUES (?,?,?,?)",
            (
                uid,
                row.get("primary_name") or "",
                "",
                row.get("primary_name") or "",
            ),
        )
        return "insert"

    # Existing row. Operator-excluded rows are frozen.
    if prev["excluded"]:
        return "skip"

    # UPDATE only when existing column is NULL and incoming is non-null
    # (spec: "既存値で非 null のものは維持"). This protects curator-owned
    # fields like primary_name/tier/amount from external overwrite.
    # Two narrow exceptions:
    #   * `source_url` / `source_fetched_at` / `enriched_json` refresh
    #     even when non-null, so we always have the most recent lineage
    #     + full external payload for the FE to inspect.
    #   * `updated_at` always stamps so downstream freshness UIs reflect
    #     the re-ingest.
    refresh_always = {"source_url", "source_fetched_at", "enriched_json"}

    sets: list[str] = []
    vals: list[Any] = []
    for col in _PROGRAM_FIELDS_UPDATABLE:
        incoming = row.get(col)
        if incoming is None:
            continue
        if col in refresh_always:
            if prev[col] == incoming:
                continue
            sets.append(f"{col} = ?")
            vals.append(incoming)
            continue
        # Preserve-existing semantics: only fill when the current value is NULL.
        if prev[col] is not None:
            continue
        sets.append(f"{col} = ?")
        vals.append(incoming)
    if not sets:
        return "skip"
    sets.append("updated_at = ?")
    vals.append(now)
    vals.append(uid)
    conn.execute(
        f"UPDATE programs SET {', '.join(sets)} WHERE unified_id = ?",
        vals,
    )
    return "update"


# ---------------------------------------------------------------------------
# Handlers (one per directory schema)
# ---------------------------------------------------------------------------


def _handle_exclusion_rules(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    """03_exclusion_rules -> exclusion_rules (existing table + new cols).

    Each source row carries `excluded_programs: list[str]`. We fan out
    one DB row per (program_a, program_b) pair so the consumer side can
    query "what does program_a exclude?" with a simple WHERE.
    """
    counts = {"insert": 0, "update": 0, "skip": 0, "skip_since": 0, "skip_banned": 0}
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("source_url")):
            counts["skip_banned"] += 1
            continue
        program_a = src.get("program_name_a")
        if not program_a:
            counts["skip"] += 1
            continue
        excluded_list = src.get("excluded_programs") or []
        if not isinstance(excluded_list, list) or not excluded_list:
            # Fan-out degenerate: one row with program_b = None.
            excluded_list = [None]
        source_urls = [src.get("source_url")] if src.get("source_url") else []
        for program_b in excluded_list:
            rule_id = _ext_rule_id(program_a, src.get("source_url"), program_b)
            existing = conn.execute(
                "SELECT rule_id FROM exclusion_rules WHERE rule_id = ?",
                (rule_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO exclusion_rules (
                        rule_id, kind, severity, program_a, program_b,
                        program_b_group_json, description, source_notes,
                        source_urls_json, extra_json,
                        source_excerpt, condition
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        rule_id,
                        src.get("rule_type") or "exclude",
                        None,
                        program_a,
                        program_b,
                        _json_dump(excluded_list),
                        None,
                        None,
                        _json_dump(source_urls),
                        _json_dump(
                            {
                                "confidence": src.get("confidence"),
                                "fetched_at": src.get("fetched_at"),
                            }
                        ),
                        src.get("source_excerpt"),
                        src.get("condition"),
                    ),
                )
                counts["insert"] += 1
            else:
                # UPDATE only the two new-migration-011 columns if they
                # differ. Leave legacy columns (description, source_notes)
                # alone — those are curator-owned.
                conn.execute(
                    """UPDATE exclusion_rules SET
                        source_excerpt = COALESCE(?, source_excerpt),
                        condition = COALESCE(?, condition)
                       WHERE rule_id = ?""",
                    (src.get("source_excerpt"), src.get("condition"), rule_id),
                )
                counts["update"] += 1
    return counts


def _upsert_and_classify(
    conn: sqlite3.Connection,
    check_sql: str,
    check_params: tuple[Any, ...],
    upsert_sql: str,
    upsert_params: tuple[Any, ...],
) -> str:
    """Run a "does this row already exist?" check, then the UPSERT, and
    return one of {"insert", "update"} based on the pre-state.

    SQLite's ``changes()`` reports 1 for both INSERT and DO UPDATE paths
    of an UPSERT, so the only reliable way to distinguish the two for
    accurate reporting is the pre-check. Worth the extra SELECT for
    tables ingested at our scale (< 5k rows per run).
    """
    existed = conn.execute(check_sql, check_params).fetchone() is not None
    conn.execute(upsert_sql, upsert_params)
    return "update" if existed else "insert"


def _handle_program_documents(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    counts = {"insert": 0, "update": 0, "skip_since": 0, "skip_banned": 0}
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("source_url")) or _source_url_is_banned(
            src.get("form_url_direct")
        ):
            counts["skip_banned"] += 1
            continue
        verdict = _upsert_and_classify(
            conn,
            "SELECT 1 FROM program_documents WHERE program_name = ? AND "
            "(form_url_direct IS ? OR form_url_direct = ?)",
            (
                src.get("program_name"),
                src.get("form_url_direct"),
                src.get("form_url_direct"),
            ),
            """INSERT INTO program_documents (
                program_name, form_name, form_type, form_format, form_url_direct,
                pages, signature_required, support_org_needed, completion_example_url,
                source_url, source_excerpt, fetched_at, confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(program_name, form_url_direct) DO UPDATE SET
                form_name = COALESCE(excluded.form_name, form_name),
                form_type = COALESCE(excluded.form_type, form_type),
                form_format = COALESCE(excluded.form_format, form_format),
                pages = COALESCE(excluded.pages, pages),
                signature_required = COALESCE(excluded.signature_required, signature_required),
                support_org_needed = COALESCE(excluded.support_org_needed, support_org_needed),
                completion_example_url = COALESCE(excluded.completion_example_url, completion_example_url),
                source_url = COALESCE(excluded.source_url, source_url),
                source_excerpt = COALESCE(excluded.source_excerpt, source_excerpt),
                fetched_at = COALESCE(excluded.fetched_at, fetched_at),
                confidence = COALESCE(excluded.confidence, confidence)
            """,
            (
                src.get("program_name"),
                src.get("form_name"),
                src.get("form_type"),
                src.get("form_format"),
                src.get("form_url_direct"),
                src.get("pages"),
                _bool_to_int(src.get("signature_required")),
                _bool_to_int(src.get("support_org_needed")),
                src.get("completion_example_url"),
                src.get("source_url"),
                src.get("source_excerpt"),
                src.get("fetched_at"),
                src.get("confidence"),
            ),
        )
        counts[verdict] += 1
    return counts


def _handle_prefecture_programs(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    """06_prefecture_programs -> programs (UPSERT)."""
    counts = {"insert": 0, "update": 0, "skip": 0, "skip_since": 0, "skip_banned": 0}
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("official_url")):
            counts["skip_banned"] += 1
            continue
        name = src.get("program_name")
        if not name:
            counts["skip"] += 1
            continue
        uid = _ext_unified_id(name, src.get("authority_name"), src.get("prefecture"))
        row = {
            "unified_id": uid,
            "primary_name": name,
            "authority_level": src.get("authority_level"),
            "authority_name": src.get("authority_name"),
            "prefecture": src.get("prefecture"),
            "municipality": src.get("municipality"),
            "program_kind": src.get("program_kind"),
            "official_url": src.get("official_url"),
            "amount_max_man_yen": src.get("amount_max_man_yen"),
            "subsidy_rate": src.get("subsidy_rate"),
            "target_types_json": _json_dump(src.get("target_types") or []),
            "source_url": src.get("official_url") or src.get("source_url"),
            "source_fetched_at": src.get("fetched_at"),
            "enriched_json": _json_dump(
                {
                    "source_excerpt": src.get("source_excerpt"),
                    "confidence": src.get("confidence"),
                }
            ),
        }
        result = _upsert_program(conn, row, now)
        counts[result] = counts.get(result, 0) + 1
    return counts


def _handle_new_program_candidates(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    counts = {"insert": 0, "update": 0, "skip_since": 0, "skip_banned": 0}
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("source_url")):
            counts["skip_banned"] += 1
            continue
        verdict = _upsert_and_classify(
            conn,
            "SELECT 1 FROM new_program_candidates WHERE candidate_name = ? AND "
            "(source_url IS ? OR source_url = ?)",
            (
                src.get("candidate_name"),
                src.get("source_url"),
                src.get("source_url"),
            ),
            """INSERT INTO new_program_candidates (
                candidate_name, mentioned_in, ministry, budget_yen,
                program_kind_hint, expected_start, policy_background_excerpt,
                source_url, source_pdf_page, fetched_at, confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(candidate_name, source_url) DO UPDATE SET
                mentioned_in = COALESCE(excluded.mentioned_in, mentioned_in),
                ministry = COALESCE(excluded.ministry, ministry),
                budget_yen = COALESCE(excluded.budget_yen, budget_yen),
                program_kind_hint = COALESCE(excluded.program_kind_hint, program_kind_hint),
                expected_start = COALESCE(excluded.expected_start, expected_start),
                policy_background_excerpt = COALESCE(excluded.policy_background_excerpt, policy_background_excerpt),
                source_pdf_page = COALESCE(excluded.source_pdf_page, source_pdf_page),
                fetched_at = COALESCE(excluded.fetched_at, fetched_at),
                confidence = COALESCE(excluded.confidence, confidence)
            """,
            (
                src.get("candidate_name"),
                src.get("mentioned_in"),
                src.get("ministry"),
                src.get("budget_yen"),
                src.get("program_kind_hint"),
                src.get("expected_start"),
                src.get("policy_background_excerpt"),
                src.get("source_url"),
                # source_pdf_page can be str ("56-58 (line ...)") or int
                str(src["source_pdf_page"]) if src.get("source_pdf_page") is not None else None,
                src.get("fetched_at"),
                src.get("confidence"),
            ),
        )
        counts[verdict] += 1
    return counts


def _classify_loan_security(raw: str | None, excerpt: str | None) -> dict[str, str | None]:
    """Split Japanese 担保・保証人 phrasing into three orthogonal axes.

    Returns a dict with keys collateral_required / personal_guarantor_required /
    third_party_guarantor_required / security_notes. Each axis takes one of
    ``required`` / ``not_required`` / ``negotiable`` / ``unknown``.

    Rules are conservative — when in doubt, emit ``unknown`` rather than a
    wrong classification. 無担保無保証 JFC products (マル経, 新創業融資)
    are the highest-value positive match because consumers actively filter
    for them; we handle that combo explicitly before the weaker signals.
    """
    text = " ".join(s for s in (raw or "", excerpt or "") if s)
    notes = raw

    collateral: str = "unknown"
    personal: str = "unknown"
    third_party: str = "unknown"

    # Explicit combined negation (most common compact phrasing). Covers
    # 「無担保・無保証」「無担保、無保証」「無担保無保証」.
    combined_none = any(p in text for p in ("無担保・無保証", "無担保、無保証", "無担保無保証"))

    if combined_none:
        collateral = "not_required"
        # 無保証 here is typically 無保証人 — no third-party guarantor. The
        # personal (代表者) guarantor treatment differs by product, so only
        # mark it not_required if the source says so elsewhere.
        third_party = "not_required"
    else:
        if "無担保" in text:
            collateral = "not_required"
        if "無保証人" in text or "無保証" in text:
            third_party = "not_required"

    # 代表者保証 / 経営者保証 免除 — the GL on 経営者保証 (金融庁) and the
    # 事業承継特別保証 product explicitly waive personal guarantees.
    if any(
        k in text for k in ("経営者保証免除", "代表者保証免除", "経営者保証不要", "代表者保証不要")
    ):
        personal = "not_required"

    # "要相談（担保・保証）" or bare "要相談" in the security field means
    # both axes are on the negotiation table. Only escalate still-unknown
    # axes — don't downgrade a confident not_required to negotiable.
    if raw and "要相談" in raw:
        if collateral == "unknown":
            collateral = "negotiable"
        if personal == "unknown":
            personal = "negotiable"
        if third_party == "unknown":
            third_party = "negotiable"

    return {
        "collateral_required": collateral,
        "personal_guarantor_required": personal,
        "third_party_guarantor_required": third_party,
        "security_notes": notes,
    }


def _handle_loan_programs(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    """08_loan_programs -> loan_programs (specialised) AND programs (mirror).

    Loans are programs too. We write the rich fields to loan_programs
    and mirror a minimal program row so search surfaces still find them.
    """
    counts = {
        "insert": 0,
        "update": 0,
        "skip_since": 0,
        "skip_banned": 0,
        "programs_insert": 0,
        "programs_update": 0,
        "programs_skip": 0,
    }
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("official_url")):
            counts["skip_banned"] += 1
            continue
        # amount_max_yen could be int or None; rate_names can be list or str.
        rate_names = src.get("rate_names")
        if isinstance(rate_names, list):
            rate_names = ",".join(str(x) for x in rate_names)
        # Split 担保 / 個人保証人 / 第三者保証人 on ingest — keeps downstream
        # queries simple and lets a user filter by risk axis directly.
        risk = _classify_loan_security(src.get("security_required"), src.get("source_excerpt"))
        verdict = _upsert_and_classify(
            conn,
            "SELECT 1 FROM loan_programs WHERE program_name = ? AND "
            "(provider IS ? OR provider = ?)",
            (
                src.get("program_name"),
                src.get("provider"),
                src.get("provider"),
            ),
            """INSERT INTO loan_programs (
                program_name, provider, loan_type,
                amount_max_yen, loan_period_years_max, grace_period_years_max,
                interest_rate_base_annual, interest_rate_special_annual, rate_names,
                security_required, target_conditions,
                official_url, source_excerpt, fetched_at, confidence,
                collateral_required, personal_guarantor_required,
                third_party_guarantor_required, security_notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(program_name, provider) DO UPDATE SET
                loan_type = COALESCE(excluded.loan_type, loan_type),
                amount_max_yen = COALESCE(excluded.amount_max_yen, amount_max_yen),
                loan_period_years_max = COALESCE(excluded.loan_period_years_max, loan_period_years_max),
                grace_period_years_max = COALESCE(excluded.grace_period_years_max, grace_period_years_max),
                interest_rate_base_annual = COALESCE(excluded.interest_rate_base_annual, interest_rate_base_annual),
                interest_rate_special_annual = COALESCE(excluded.interest_rate_special_annual, interest_rate_special_annual),
                rate_names = COALESCE(excluded.rate_names, rate_names),
                security_required = COALESCE(excluded.security_required, security_required),
                target_conditions = COALESCE(excluded.target_conditions, target_conditions),
                official_url = COALESCE(excluded.official_url, official_url),
                source_excerpt = COALESCE(excluded.source_excerpt, source_excerpt),
                fetched_at = COALESCE(excluded.fetched_at, fetched_at),
                confidence = COALESCE(excluded.confidence, confidence),
                -- Risk axes: a new classification is authoritative (we want
                -- upstream excerpt upgrades to flow through). Only keep the
                -- prior value if the new one is NULL, which _classify_loan_security
                -- never returns — still guard for safety.
                collateral_required = COALESCE(excluded.collateral_required, collateral_required),
                personal_guarantor_required = COALESCE(excluded.personal_guarantor_required, personal_guarantor_required),
                third_party_guarantor_required = COALESCE(excluded.third_party_guarantor_required, third_party_guarantor_required),
                security_notes = COALESCE(excluded.security_notes, security_notes)
            """,
            (
                src.get("program_name"),
                src.get("provider"),
                src.get("loan_type"),
                src.get("amount_max_yen"),
                src.get("loan_period_years_max"),
                src.get("grace_period_years_max"),
                src.get("interest_rate_base_annual"),
                src.get("interest_rate_special_annual"),
                rate_names,
                src.get("security_required"),
                src.get("target_conditions"),
                src.get("official_url"),
                src.get("source_excerpt"),
                src.get("fetched_at"),
                src.get("confidence"),
                risk["collateral_required"],
                risk["personal_guarantor_required"],
                risk["third_party_guarantor_required"],
                risk["security_notes"],
            ),
        )
        counts[verdict] += 1

        # Mirror to programs so /v1/programs/search can find loan offerings.
        name = src.get("program_name")
        if name:
            uid = _ext_unified_id(name, src.get("provider"))
            amount_max_man_yen = None
            if isinstance(src.get("amount_max_yen"), (int, float)):
                amount_max_man_yen = src["amount_max_yen"] / 10000.0
            prog_row = {
                "unified_id": uid,
                "primary_name": name,
                "authority_level": "国" if "公庫" in (src.get("provider") or "") else None,
                "authority_name": src.get("provider"),
                "program_kind": "loan",
                "official_url": src.get("official_url"),
                "amount_max_man_yen": amount_max_man_yen,
                "source_url": src.get("official_url"),
                "source_fetched_at": src.get("fetched_at"),
                "enriched_json": _json_dump(
                    {
                        "loan_type": src.get("loan_type"),
                        "interest_rate_base_annual": src.get("interest_rate_base_annual"),
                        "interest_rate_special_annual": src.get("interest_rate_special_annual"),
                        "loan_period_years_max": src.get("loan_period_years_max"),
                        "grace_period_years_max": src.get("grace_period_years_max"),
                        "source_excerpt": src.get("source_excerpt"),
                    }
                ),
            }
            result = _upsert_program(conn, prog_row, now)
            counts[f"programs_{result}"] = counts.get(f"programs_{result}", 0) + 1
    return counts


def _handle_enforcement_cases(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    counts = {"insert": 0, "update": 0, "skip": 0, "skip_since": 0, "skip_banned": 0}
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("source_url")):
            counts["skip_banned"] += 1
            continue
        case_id = src.get("case_id")
        if not case_id:
            counts["skip"] += 1
            continue
        verdict = _upsert_and_classify(
            conn,
            "SELECT 1 FROM enforcement_cases WHERE case_id = ?",
            (case_id,),
            """INSERT INTO enforcement_cases (
                case_id, event_type, program_name_hint,
                recipient_name, recipient_kind, recipient_houjin_bangou,
                is_sole_proprietor, bureau, intermediate_recipient,
                prefecture, ministry, occurred_fiscal_years_json,
                amount_yen, amount_project_cost_yen, amount_grant_paid_yen,
                amount_improper_grant_yen, amount_improper_project_cost_yen,
                reason_excerpt, legal_basis,
                source_url, source_section, source_title,
                disclosed_date, disclosed_until, fetched_at, confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(case_id) DO UPDATE SET
                event_type = COALESCE(excluded.event_type, event_type),
                program_name_hint = COALESCE(excluded.program_name_hint, program_name_hint),
                recipient_name = COALESCE(excluded.recipient_name, recipient_name),
                recipient_kind = COALESCE(excluded.recipient_kind, recipient_kind),
                recipient_houjin_bangou = COALESCE(excluded.recipient_houjin_bangou, recipient_houjin_bangou),
                is_sole_proprietor = COALESCE(excluded.is_sole_proprietor, is_sole_proprietor),
                bureau = COALESCE(excluded.bureau, bureau),
                intermediate_recipient = COALESCE(excluded.intermediate_recipient, intermediate_recipient),
                prefecture = COALESCE(excluded.prefecture, prefecture),
                ministry = COALESCE(excluded.ministry, ministry),
                occurred_fiscal_years_json = COALESCE(excluded.occurred_fiscal_years_json, occurred_fiscal_years_json),
                amount_yen = COALESCE(excluded.amount_yen, amount_yen),
                amount_project_cost_yen = COALESCE(excluded.amount_project_cost_yen, amount_project_cost_yen),
                amount_grant_paid_yen = COALESCE(excluded.amount_grant_paid_yen, amount_grant_paid_yen),
                amount_improper_grant_yen = COALESCE(excluded.amount_improper_grant_yen, amount_improper_grant_yen),
                amount_improper_project_cost_yen = COALESCE(excluded.amount_improper_project_cost_yen, amount_improper_project_cost_yen),
                reason_excerpt = COALESCE(excluded.reason_excerpt, reason_excerpt),
                legal_basis = COALESCE(excluded.legal_basis, legal_basis),
                source_url = COALESCE(excluded.source_url, source_url),
                source_section = COALESCE(excluded.source_section, source_section),
                source_title = COALESCE(excluded.source_title, source_title),
                disclosed_date = COALESCE(excluded.disclosed_date, disclosed_date),
                disclosed_until = COALESCE(excluded.disclosed_until, disclosed_until),
                fetched_at = COALESCE(excluded.fetched_at, fetched_at),
                confidence = COALESCE(excluded.confidence, confidence)
            """,
            (
                case_id,
                src.get("event_type"),
                src.get("program_name_hint"),
                src.get("recipient_name"),
                src.get("recipient_kind"),
                src.get("recipient_houjin_bangou"),
                _bool_to_int(src.get("is_sole_proprietor")),
                src.get("bureau"),
                src.get("intermediate_recipient"),
                src.get("prefecture"),
                src.get("ministry"),
                _json_dump(src.get("occurred_fiscal_years") or []),
                src.get("amount_yen"),
                src.get("amount_project_cost_yen"),
                src.get("amount_grant_paid_yen"),
                src.get("amount_improper_grant_yen"),
                src.get("amount_improper_project_cost_yen"),
                src.get("reason_excerpt"),
                src.get("legal_basis"),
                src.get("source_url"),
                src.get("source_section"),
                src.get("source_title"),
                src.get("disclosed_date"),
                src.get("disclosed_until"),
                src.get("fetched_at"),
                src.get("confidence"),
            ),
        )
        counts[verdict] += 1
    return counts


def _handle_mirasapo_cases(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    counts = {"insert": 0, "update": 0, "skip": 0, "skip_since": 0, "skip_banned": 0}
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("source_url")):
            counts["skip_banned"] += 1
            continue
        case_id = src.get("case_id")
        if not case_id:
            counts["skip"] += 1
            continue
        verdict = _upsert_and_classify(
            conn,
            "SELECT 1 FROM case_studies WHERE case_id = ?",
            (case_id,),
            """INSERT INTO case_studies (
                case_id, company_name, houjin_bangou, is_sole_proprietor,
                prefecture, municipality, industry_jsic, industry_name,
                employees, founded_year, capital_yen,
                case_title, case_summary,
                programs_used_json, total_subsidy_received_yen,
                outcomes_json, patterns_json,
                publication_date, source_url, source_excerpt,
                fetched_at, confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(case_id) DO UPDATE SET
                company_name = COALESCE(excluded.company_name, company_name),
                houjin_bangou = COALESCE(excluded.houjin_bangou, houjin_bangou),
                is_sole_proprietor = COALESCE(excluded.is_sole_proprietor, is_sole_proprietor),
                prefecture = COALESCE(excluded.prefecture, prefecture),
                municipality = COALESCE(excluded.municipality, municipality),
                industry_jsic = COALESCE(excluded.industry_jsic, industry_jsic),
                industry_name = COALESCE(excluded.industry_name, industry_name),
                employees = COALESCE(excluded.employees, employees),
                founded_year = COALESCE(excluded.founded_year, founded_year),
                capital_yen = COALESCE(excluded.capital_yen, capital_yen),
                case_title = COALESCE(excluded.case_title, case_title),
                case_summary = COALESCE(excluded.case_summary, case_summary),
                programs_used_json = COALESCE(excluded.programs_used_json, programs_used_json),
                total_subsidy_received_yen = COALESCE(excluded.total_subsidy_received_yen, total_subsidy_received_yen),
                outcomes_json = COALESCE(excluded.outcomes_json, outcomes_json),
                patterns_json = COALESCE(excluded.patterns_json, patterns_json),
                publication_date = COALESCE(excluded.publication_date, publication_date),
                source_url = COALESCE(excluded.source_url, source_url),
                source_excerpt = COALESCE(excluded.source_excerpt, source_excerpt),
                fetched_at = COALESCE(excluded.fetched_at, fetched_at),
                confidence = COALESCE(excluded.confidence, confidence)
            """,
            (
                case_id,
                src.get("company_name"),
                src.get("houjin_bangou"),
                _bool_to_int(src.get("is_sole_proprietor")),
                src.get("prefecture"),
                src.get("municipality"),
                src.get("industry_jsic"),
                src.get("industry_name"),
                src.get("employees"),
                src.get("founded_year"),
                src.get("capital_yen"),
                src.get("case_title"),
                src.get("case_summary"),
                _json_dump(src.get("programs_used") or []),
                src.get("total_subsidy_received_yen"),
                _json_dump(src.get("outcomes") or []),
                _json_dump(src.get("patterns") or []),
                src.get("publication_date"),
                src.get("source_url"),
                src.get("source_excerpt"),
                src.get("fetched_at"),
                src.get("confidence"),
            ),
        )
        counts[verdict] += 1
    return counts


def _handle_case_law(
    conn: sqlite3.Connection, rows: list[dict[str, Any]], now: str, since: str | None
) -> dict[str, int]:
    """49_case_law_judgments -> case_law (courts.go.jp 判例).

    Idempotency key: (case_number, court). Rows missing case_number are
    dropped — without it we cannot dedupe re-hearings of the same case
    across higher/lower courts.
    """
    counts = {"insert": 0, "update": 0, "skip": 0, "skip_since": 0, "skip_banned": 0}
    for src in rows:
        if not _passes_since(src.get("fetched_at"), since):
            counts["skip_since"] += 1
            continue
        if _source_url_is_banned(src.get("source_url")) or _source_url_is_banned(
            src.get("pdf_url")
        ):
            counts["skip_banned"] += 1
            continue
        case_number = src.get("case_number")
        case_name = src.get("case_name")
        if not case_number or not case_name:
            counts["skip"] += 1
            continue
        court = src.get("court")
        verdict = _upsert_and_classify(
            conn,
            "SELECT 1 FROM case_law WHERE case_number = ? AND (court IS ? OR court = ?)",
            (case_number, court, court),
            """INSERT INTO case_law (
                case_name, court, decision_date, case_number,
                subject_area, key_ruling, parties_involved, impact_on_business,
                source_url, source_excerpt, confidence, pdf_url, category,
                fetched_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(case_number, court) DO UPDATE SET
                case_name = COALESCE(excluded.case_name, case_name),
                decision_date = COALESCE(excluded.decision_date, decision_date),
                subject_area = COALESCE(excluded.subject_area, subject_area),
                key_ruling = COALESCE(excluded.key_ruling, key_ruling),
                parties_involved = COALESCE(excluded.parties_involved, parties_involved),
                impact_on_business = COALESCE(excluded.impact_on_business, impact_on_business),
                source_url = COALESCE(excluded.source_url, source_url),
                source_excerpt = COALESCE(excluded.source_excerpt, source_excerpt),
                confidence = COALESCE(excluded.confidence, confidence),
                pdf_url = COALESCE(excluded.pdf_url, pdf_url),
                category = COALESCE(excluded.category, category),
                fetched_at = COALESCE(excluded.fetched_at, fetched_at)
            """,
            (
                case_name,
                court,
                src.get("decision_date"),
                case_number,
                src.get("subject_area"),
                src.get("key_ruling"),
                src.get("parties_involved"),
                src.get("impact_on_business"),
                src.get("source_url"),
                src.get("source_excerpt"),
                src.get("confidence"),
                src.get("pdf_url"),
                src.get("category"),
                src.get("fetched_at"),
            ),
        )
        counts[verdict] += 1
    return counts


def _make_program_handler(
    *,
    name_key: str = "program_name",
    url_key: str = "official_url",
    authority_key: str = "authority",
    amount_yen_key: str | None = None,
    amount_man_yen_key: str | None = None,
    program_kind_key: str | None = "program_kind",
    default_kind: str | None = None,
    prefecture_key: str | None = None,
    municipality_key: str | None = None,
    target_types_key: str | None = None,
    authority_level_key: str | None = None,
) -> Callable[[sqlite3.Connection, list[dict[str, Any]], str, str | None], dict[str, int]]:
    """Factory for generic "program record" handlers.

    The 20-ish remaining directories are all variants of "a program with
    name/authority/url/optional amount". We close over the per-dir key
    mapping and return a handler that upserts into `programs`.
    """

    def handler(
        conn: sqlite3.Connection,
        rows: list[dict[str, Any]],
        now: str,
        since: str | None,
    ) -> dict[str, int]:
        counts = {"insert": 0, "update": 0, "skip": 0, "skip_since": 0, "skip_banned": 0}
        for src in rows:
            if not _passes_since(src.get("fetched_at"), since):
                counts["skip_since"] += 1
                continue
            if _source_url_is_banned(src.get(url_key) if url_key else None):
                counts["skip_banned"] += 1
                continue
            name = src.get(name_key)
            if not name:
                counts["skip"] += 1
                continue
            # Resolve optional amount.
            amount_max_man_yen: float | None = None
            if amount_man_yen_key and src.get(amount_man_yen_key) is not None:
                try:
                    amount_max_man_yen = float(src[amount_man_yen_key])
                except (TypeError, ValueError):
                    amount_max_man_yen = None
            elif amount_yen_key and src.get(amount_yen_key) is not None:
                try:
                    amount_max_man_yen = float(src[amount_yen_key]) / 10000.0
                except (TypeError, ValueError):
                    amount_max_man_yen = None
            # program_kind dispatch.
            kind = src.get(program_kind_key) if program_kind_key else None
            if kind is None and default_kind:
                kind = default_kind
            # Extract enriched payload: stash the whole source record so
            # downstream queries can introspect without a schema change.
            # Drop `fetched_at` / `confidence` since those get hoisted.
            enriched = {k: v for k, v in src.items() if k not in ("fetched_at", "confidence")}
            uid = _ext_unified_id(
                name,
                src.get(authority_key) if authority_key else None,
                src.get(prefecture_key) if prefecture_key else None,
            )
            resolved_url = _first_str(src.get(url_key)) if url_key else None
            row = {
                "unified_id": uid,
                "primary_name": name,
                "authority_level": (src.get(authority_level_key) if authority_level_key else None),
                "authority_name": _first_str(src.get(authority_key)) if authority_key else None,
                "prefecture": src.get(prefecture_key) if prefecture_key else None,
                "municipality": (src.get(municipality_key) if municipality_key else None),
                "program_kind": kind,
                "official_url": resolved_url,
                "amount_max_man_yen": amount_max_man_yen,
                "target_types_json": (
                    _json_dump(src.get(target_types_key) or []) if target_types_key else None
                ),
                "source_url": resolved_url,
                "source_fetched_at": src.get("fetched_at"),
                "enriched_json": _json_dump(enriched) if enriched else None,
            }
            result = _upsert_program(conn, row, now)
            counts[result] = counts.get(result, 0) + 1
        return counts

    return handler


# ---------------------------------------------------------------------------
# Auto-detect fallback
# ---------------------------------------------------------------------------

# Heuristic key probes for dirs the collection agent adds faster than we can
# register explicit handlers. Order = probe order; first hit wins.
_AUTO_NAME_KEYS: tuple[str, ...] = (
    "program_name",
    "grant_name",
    "item_name",
    "name",
    "name_ja",
    "title",
)
_AUTO_AUTHORITY_KEYS: tuple[str, ...] = (
    "authority",
    "authority_name",
    "competent_authority",
    "competent_ministry",
    "competent_agency",
    "responsible_ministry",
    "organization",
    "ministry",
    "government_level",
    "administrator",
    "operator",
    "agency",
    "issuer",
    "enforcement_body",
    "implementing_bodies",
    "supervision",
    "所管",
    "jurisdiction_ministry",
    "regulator",
    "issuing_agency",
    "implementing_body",
    "governing_body",
    "issuing_body",
    "overseeing_body",
    "owner",
)
_AUTO_AMOUNT_YEN_KEYS: tuple[str, ...] = (
    "amount_max_yen",
    "loan_amount_max_yen",
    "grant_amount_max_yen",
    "max_amount_yen",
)
_AUTO_AMOUNT_MANYEN_KEYS: tuple[str, ...] = (
    "amount_max_man_yen",
    "max_amount_man_yen",
)
_AUTO_URL_KEYS: tuple[str, ...] = (
    "official_url",
    "source_url",
    "url",
    "primary_source_url",
    "primary_source",
    "primary_source_pdf",
    "primary_source_urls",
    "source_urls",
    "source_primary",
    "portal_url",
    "law_url",
    "egov_url",
    "url_official",
    "url_youkou_pdf",
    "ppc_legal_page",
)


def _auto_detect_handler(
    first_row: dict[str, Any],
) -> Callable[[sqlite3.Connection, list[dict[str, Any]], str, str | None], dict[str, int]] | None:
    """Fallback handler picker for directories without an explicit entry.

    Inspects the first record's keys. Returns None if the shape does not
    look like a program (no name-like column or no authority-like column).
    The data-collection agent adds new domain dirs faster than we can
    register them — the auto-detector lets them flow into `programs` with
    sensible defaults instead of sitting as dead files under /tmp.
    """
    keys = set(first_row.keys())
    name_key = next((k for k in _AUTO_NAME_KEYS if k in keys), None)
    if not name_key:
        return None
    # Require *some* authority anchor. Without it the row is almost
    # certainly background statistics / reference data, not a program.
    auth_key = next((k for k in _AUTO_AUTHORITY_KEYS if k in keys), None)
    if not auth_key:
        return None
    amount_yen_key = next((k for k in _AUTO_AMOUNT_YEN_KEYS if k in keys), None)
    amount_man_yen_key = next((k for k in _AUTO_AMOUNT_MANYEN_KEYS if k in keys), None)
    url_key = next((k for k in _AUTO_URL_KEYS if k in keys), "official_url")
    return _make_program_handler(
        name_key=name_key,
        authority_key=auth_key,
        amount_yen_key=amount_yen_key,
        amount_man_yen_key=amount_man_yen_key,
        url_key=url_key,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


HANDLERS: dict[
    str,
    Callable[[sqlite3.Connection, list[dict[str, Any]], str, str | None], dict[str, int]],
] = {
    # Specialised schemas.
    "03_exclusion_rules": _handle_exclusion_rules,
    "04_program_documents": _handle_program_documents,
    "06_prefecture_programs": _handle_prefecture_programs,
    "07_new_program_candidates": _handle_new_program_candidates,
    "08_loan_programs": _handle_loan_programs,
    "13_enforcement_cases": _handle_enforcement_cases,
    "22_mirasapo_cases": _handle_mirasapo_cases,
    "49_case_law_judgments": _handle_case_law,
    # Program-record schemas — all route through _upsert_program via the
    # factory. The per-dir kwargs encode the key mapping.
    "09_certification_programs": _make_program_handler(
        authority_key="authority", default_kind="certification"
    ),
    "11_mhlw_employment_grants": _make_program_handler(
        authority_key="authority", default_kind="subsidy"
    ),
    "12_tax_incentives": _make_program_handler(
        name_key="name",
        authority_key="government_level",
        url_key="official_url",
        default_kind="tax_credit",
    ),
    "14_retirement_mutual_aid": _make_program_handler(
        authority_key="authority",
        default_kind="mutual_aid",
    ),
    "15_environment_energy_programs": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "16_trade_export_programs": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "17_tourism_mlit_chisou_programs": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "20_designated_city_programs": _make_program_handler(
        authority_key="authority_name",
        authority_level_key="authority_level",
        amount_yen_key="amount_max_yen",
        prefecture_key="prefecture",
        municipality_key="municipality",
        target_types_key="target_types",
    ),
    "21_startup_support": _make_program_handler(
        authority_key="authority",
    ),
    "23_medical_care_grants": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "25_foreign_workforce": _make_program_handler(
        authority_key="authority",
        default_kind="visa_residence_status",
    ),
    "26_agri_tax_deep": _make_program_handler(
        authority_key="authority",
        default_kind="tax_deduction",
    ),
    "27_chamber_commerce": _make_program_handler(
        authority_key="authority",
        amount_yen_key="loan_amount_max_yen",
        default_kind="loan",
    ),
    "29_jeed_disability": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "33_prefecture_programs_part2": _make_program_handler(
        authority_key="authority_name",
        authority_level_key="authority_level",
        amount_yen_key="amount_max_yen",
        prefecture_key="prefecture",
        municipality_key="municipality",
        target_types_key="target_types",
    ),
    "36_women_childcare_support": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "37_fisheries_aquaculture": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "38_agri_welfare_linkage": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "39_bcp_disaster_prevention": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
        default_kind="bcp",
    ),
    "40_private_foundations": _make_program_handler(
        name_key="grant_name",
        authority_key="organization",
        amount_yen_key="amount_max_yen",
        default_kind="private_grant",
    ),
    "41_cybersecurity_programs": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "43_transport_construction_2024": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    # Previously listed as "if/when it appears" in SKIP_DIRS — data has arrived.
    "24_ip_support": _make_program_handler(
        authority_key="authority",
        default_kind="ip_fee_reduction",
    ),
    "28_research_grants": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
        default_kind="research_grant",
    ),
    "30_culture_media_grants": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    "31_nonprofit_support": _make_program_handler(
        authority_key="authority",
        default_kind="nonprofit_certification",
    ),
    "34_disaster_recovery_remote_area": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
    # 44, 50 are regulation/rule schemas (item_name instead of program_name).
    # We store them as programs with a distinctive kind so consumers can
    # filter them out of "subsidies" queries.
    "44_compliance_fair_trade": _make_program_handler(
        name_key="item_name",
        authority_key="authority",
        default_kind="regulation",
    ),
    "45_public_procurement": _make_program_handler(
        authority_key="authority",
        default_kind="qualification",
    ),
    "46_functional_food_regulation": _make_program_handler(
        authority_key="authority",
        default_kind="notification",
    ),
    "47_local_ordinance_benefits": _make_program_handler(
        authority_key="authority_name",
        authority_level_key="authority_level",
        prefecture_key="prefecture",
        municipality_key="municipality",
    ),
    "48_crowdfunding_matching_funds": _make_program_handler(
        authority_key="authority",
        default_kind="tax_credit",
    ),
    "50_crypto_web3_regulation": _make_program_handler(
        name_key="item_name",
        authority_key="authority",
        default_kind="regulation",
    ),
    "51_telecom_5g_6g": _make_program_handler(
        authority_key="authority",
        amount_yen_key="amount_max_yen",
    ),
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _configure_logging(log_path: Path) -> None:
    root = logging.getLogger("jpintel.ingest_external")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


def run_ingest(
    *,
    data_dir: Path,
    db_path: Path,
    only: str | None = None,
    since: str | None = None,
    dry_run: bool = False,
) -> dict[str, dict[str, int]]:
    """Main ingest loop.

    Returns a per-directory count dict for caller reporting.
    """
    if not data_dir.is_dir():
        raise FileNotFoundError(f"data-dir does not exist: {data_dir}")

    now = datetime.now(UTC).isoformat()
    results: dict[str, dict[str, int]] = {}

    # Discover directory handlers in sorted order — lexicographic matches the
    # 01_/02_/... prefix so logs read in the same order as the filesystem.
    dirs = sorted(p for p in data_dir.iterdir() if p.is_dir())

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        # Enable WAL + FK just like session.py does for runtime consistency.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")

        for d in dirs:
            name = d.name
            if only and name != only:
                continue
            if name in SKIP_DIRS:
                _LOG.info("skip_out_of_scope dir=%s", name)
                continue
            handler = HANDLERS.get(name)
            jsonl = d / "records.jsonl"
            if not jsonl.is_file():
                _LOG.info("no_records_yet dir=%s", name)
                continue

            rows = _iter_jsonl(jsonl)
            if handler is None:
                # Auto-detect fallback for dirs the collection agent
                # created without a matching explicit handler. Safe
                # because _upsert_program uses the `UNI-ext-` prefix
                # namespace and never clobbers canonical rows.
                if rows:
                    handler = _auto_detect_handler(rows[0])
                if handler is None:
                    _LOG.warning(
                        "no_handler_for_dir dir=%s lines=%d auto_detect=miss",
                        name,
                        len(rows),
                    )
                    continue
                _LOG.info("auto_detected_handler dir=%s rows=%d", name, len(rows))
            _LOG.info("ingesting dir=%s rows=%d since=%s", name, len(rows), since)
            if dry_run:
                results[name] = {"dry_run_rows": len(rows)}
                continue

            conn.execute("BEGIN")
            try:
                counts = handler(conn, rows, now, since)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            results[name] = counts
            _LOG.info("dir=%s counts=%s", name, counts)
        if not dry_run and results:
            # Freshness ping. `get_meta` MCP tool reads this; if we don't
            # bump it the surface says "last ingested 2026-04-22" even when
            # we just wrote +3k new rows.
            conn.execute(
                """INSERT INTO meta(key, value, updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                ("last_ingested_at", now, now),
            )
            conn.commit()
    finally:
        conn.close()
    return results


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Root of the external collection drop (contains NN_name/records.jsonl).",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("JPINTEL_DB_PATH") or DEFAULT_DB),
        help="SQLite DB path (default: data/jpintel.db).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count but do not write to DB.",
    )
    p.add_argument(
        "--only",
        default=None,
        help="Restrict to a single directory name (e.g. 13_enforcement_cases).",
    )
    p.add_argument(
        "--since",
        default=None,
        help="ISO-8601 fetched_at lower bound; rows older than this are skipped.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"ingest_external_{ts}.log"
    _configure_logging(log_path)

    _LOG.info(
        "start data_dir=%s db=%s dry_run=%s only=%s since=%s",
        args.data_dir,
        args.db,
        args.dry_run,
        args.only,
        args.since,
    )

    try:
        results = run_ingest(
            data_dir=args.data_dir,
            db_path=args.db,
            only=args.only,
            since=args.since,
            dry_run=args.dry_run,
        )
    except Exception as e:
        _LOG.error("ingest_failed err=%s", e, exc_info=True)
        return 1

    # Summary table for the console.
    print(f"\ningest summary (log: {log_path})\n")
    total = {"insert": 0, "update": 0, "skip": 0}
    for d, counts in results.items():
        pretty = ", ".join(f"{k}={v}" for k, v in counts.items())
        print(f"  {d}: {pretty}")
        for k, v in counts.items():
            if k in total:
                total[k] += v
    print(f"\n  TOTAL: insert={total['insert']} update={total['update']} skip={total['skip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
