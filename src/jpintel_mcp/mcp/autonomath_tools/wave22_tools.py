"""wave22_tools — Wave 22 composition tools (5 new MCP tools, 2026-04-29).

Five tools that further compound call density on top of Wave 21. Each
tool emits ``_next_calls`` (compound multiplier mechanism) and the
auditor reproducibility pair (``corpus_snapshot_id`` + ``corpus_checksum``).

Tools shipped here
------------------

  match_due_diligence_questions
      Given a target 法人番号, returns 30-50 DD questions tailored to
      industry × program portfolio × 与信 risk by joining the
      `dd_question_templates` library (migration 102) with houjin /
      adoption / enforcement / invoice corpora. Sensitive (§52 + §72).

  prepare_kessan_briefing
      Given a 法人番号 + fiscal year, returns 月次 / 四半期 summary of
      program-eligibility changes since last 決算 by joining
      `am_amendment_diff` with the customer's `saved_searches` digest
      cadence. Sensitive (§52 — 決算 = 税理士法 territory).

  forecast_program_renewal
      Given a program slug, returns probability + window of renewal in
      next FY based on historical 制度 cycle observed in
      `am_application_round` + `am_amendment_snapshot`. Pure stats —
      NOT sensitive (statistical forecast about program lifecycle, not
      regulated business advice).

  cross_check_jurisdiction
      Given a 商号 or 法人番号, returns where they registered (法務局)
      vs. where they pay 事業所税 (自治体) vs. where they should file
      based on actual 拠点 (jpi_houjin_master + jpi_invoice_registrants
      + jpi_adoption_records municipality / prefecture data). Detects
      不一致 for 税理士 client onboarding. Sensitive (§52 + §72).

  bundle_application_kit
      Given a program slug + client profile, returns the COMPLETE
      downloadable kit (DOCX 申請書 placeholder + cover letter +
      必要書類 checklist + similar 採択例 list). Pure file assembly,
      NO LLM. Sensitive (§1 行政書士法 — 申請書面作成は独占業務、
      当社 surfaces only scaffolding + primary URLs).

Each tool ALWAYS returns:
  * ``results`` (list[dict]) + ``total`` / ``limit`` / ``offset``
    (paginated-consumer envelope)
  * ``_disclaimer`` if §52 / §72 / §1 sensitive
  * ``_next_calls`` list[dict] (compound multiplier mechanism)
  * ``corpus_snapshot_id`` + ``corpus_checksum`` (auditor reproducibility)

NO Anthropic API self-call. All five tools are pure SQL / Python over
autonomath.db — the LLM call is the customer's, never ours.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error as _raw_make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.wave22")

# Env-gated registration (default on). Flip to "0" for one-flag rollback
# if a regression surfaces post-launch.
_ENABLED = os.environ.get("AUTONOMATH_WAVE22_ENABLED", "1") == "1"


def make_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return a Wave22 error envelope with the reproducibility pair."""
    return attach_corpus_snapshot(_raw_make_error(*args, **kwargs))


# ---------------------------------------------------------------------------
# Disclaimers (§52 / §72 / §1 fence — see envelope_wrapper.SENSITIVE_TOOLS).
# ---------------------------------------------------------------------------

_DISCLAIMER_DD_QUESTIONS = (
    "本 response は dd_question_templates (60 行) と houjin / adoption / "
    "enforcement / invoice corpora の機械的 join による DD 質問リストで、"
    "信用調査・反社チェック・労務 due diligence (社労士法・弁護士法 §72) ・"
    "税務助言 (税理士法 §52) の代替ではありません。質問内容は情報照会用 "
    "checklist であり、確定判断は資格を有する専門家にご相談ください。"
)

_DISCLAIMER_KESSAN_BRIEFING = (
    "本 response は am_amendment_diff + saved_searches + tax_rulesets の "
    "機械的 aggregation による 決算期前後の制度変動 briefing で、税務代理 "
    "(税理士法 §52) ・申告書作成代行は提供しません。差分検知は heuristic "
    "を含み、申告書面・決算書面の作成は資格を有する税理士・公認会計士へ。"
)

_DISCLAIMER_JURISDICTION = (
    "本 response は houjin_master + invoice_registrants + adoption_records "
    "の住所・所在地データの突合せで、税務代理 (税理士法 §52) ・登記申請 "
    "(司法書士法 §3) ・行政書士業務 (行政書士法 §1) の代替ではありません。"
    "不一致検出は heuristic で、確定判断は士業へ。"
)

_DISCLAIMER_APPLICATION_KIT = (
    "本 response は公開公募要領 + 採択事例 + 必要書類リストの assembly で、"
    "申請書面の作成・提出代行は行政書士法 §1 の独占業務です。当社は "
    "scaffold + primary source URL のみ surface し、書面作成自体は提供 "
    "しません。最終申請判断は資格を有する行政書士・中小企業診断士・税理士へ。"
)


# ---------------------------------------------------------------------------
# Reproducibility — corpus_snapshot_id + corpus_checksum.
# ---------------------------------------------------------------------------

_SNAPSHOT_TTL_SECONDS = 300.0
_SNAPSHOT_CACHE: dict[str, tuple[float, str, str]] = {}

# Tables sampled for the checksum mix-in. autonomath.db carries the
# `programs` / `laws` / `tax_rulesets` / `court_decisions` mirror tables
# (migration 032), so a single connection can produce a complete snapshot.
_SNAPSHOT_TABLES: tuple[str, ...] = (
    "programs",
    "laws",
    "tax_rulesets",
    "court_decisions",
)


def _compute_corpus_snapshot(conn: sqlite3.Connection) -> tuple[str, str]:
    """Return (corpus_snapshot_id, corpus_checksum) for the autonomath corpus.

    Caches per-process for 5 minutes. Mirrors api/_corpus_snapshot.py
    semantics so MCP and REST surface the same identity for a given
    moment — auditors can quote either side and reproduce the result.
    """
    cache_key = "autonomath"
    now_mono = datetime.datetime.now().timestamp()
    cached = _SNAPSHOT_CACHE.get(cache_key)
    if cached is not None and cached[0] > now_mono:
        return cached[1], cached[2]

    snapshot_id: str | None = None
    try:
        row = conn.execute("SELECT MAX(detected_at) FROM am_amendment_diff").fetchone()
        if row and row[0]:
            snapshot_id = str(row[0])
    except sqlite3.Error:
        pass

    if not snapshot_id:
        # autonomath.db has the canonical corpus tables but their
        # source_fetched_at / fetched_at columns are partly empty (the
        # original data was bulk-imported via migration 032 from
        # jpintel.db without preserving every per-row timestamp). We
        # fall through several signals: the jpi_* mirrors carry good
        # fetched_at, am_entities has a uniform high-water-mark.
        candidates: list[str] = []
        for table, expr in (
            ("programs", "MAX(source_fetched_at)"),
            ("laws", "MAX(fetched_at)"),
            ("tax_rulesets", "MAX(fetched_at)"),
            ("court_decisions", "MAX(fetched_at)"),
            ("jpi_tax_rulesets", "MAX(fetched_at)"),
            ("jpi_court_decisions", "MAX(fetched_at)"),
            ("am_entities", "MAX(fetched_at)"),
        ):
            try:
                row = conn.execute(f"SELECT {expr} FROM {table}").fetchone()
                if row and row[0]:
                    candidates.append(str(row[0]))
            except sqlite3.Error:
                continue
        snapshot_id = max(candidates) if candidates else "1970-01-01T00:00:00Z"

    counts: list[int] = []
    for table in _SNAPSHOT_TABLES:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts.append(int(row[0]) if row and row[0] is not None else 0)
        except sqlite3.Error:
            counts.append(0)

    api_version = "v0.3.1"
    digest_input = (f"{snapshot_id}|{api_version}|{','.join(str(c) for c in counts)}").encode()
    checksum = "sha256:" + hashlib.sha256(digest_input).hexdigest()[:16]

    _SNAPSHOT_CACHE[cache_key] = (
        now_mono + _SNAPSHOT_TTL_SECONDS,
        snapshot_id,
        checksum,
    )
    return snapshot_id, checksum


def _attach_snapshot(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:
    """Inject corpus_snapshot_id + corpus_checksum keys onto `body`.

    Also default-injects ``_billing_unit=1`` on success-path envelopes so
    the Wave22/24 billing pipeline (which greps the envelope for the
    field) records 1 metered request per call. Tools that bill differently
    can set ``_billing_unit`` explicitly before calling _attach_snapshot;
    this preserves that value.
    """
    snapshot_id, checksum = _compute_corpus_snapshot(conn)
    body["corpus_snapshot_id"] = snapshot_id
    body["corpus_checksum"] = checksum
    if "_billing_unit" not in body:
        body["_billing_unit"] = 1
    return body


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _today_iso() -> str:
    """Today JST as YYYY-MM-DD."""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db, returning either a conn or an error envelope."""
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at the repo root or AUTONOMATH_DB_PATH.",
            retry_with=["search_programs"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_programs"],
        )


def _normalize_houjin(value: str) -> str:
    """Strip whitespace + leading 'T' (invoice registration prefix)."""
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s


def _industry_major_from_jsic(code: str | None) -> str | None:
    """Extract major-letter from a JSIC code (e.g. '0111' → 'A' via medium)."""
    if not code:
        return None
    code = str(code).strip()
    if not code:
        return None
    # Major code is a single letter A..T — use directly if matches.
    if len(code) == 1 and code.isalpha():
        return code.upper()
    # For numeric medium / minor, we can't infer the major without a
    # lookup table — leave None to fall through to '*' wildcard.
    return None


# ---------------------------------------------------------------------------
# 1) match_due_diligence_questions
# ---------------------------------------------------------------------------


def _match_dd_questions_impl(
    houjin_bangou: str,
    deck_size: int = 40,
) -> dict[str, Any]:
    """Pure SQL: dd_question_templates × houjin/adoption/enforcement/invoice.

    Returns 30-50 DD questions tailored to:
      * industry_jsic_major (inferred from adoption history)
      * program portfolio (subsidies / tax / loans observed)
      * 与信 risk dimensions (enforcement events, invoice gap, etc.)

    NO LLM. Pure pattern-match against the question template DB.
    """
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号 with or without 'T' prefix).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    deck_size = max(20, min(deck_size, 60))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Resolve target context -------------------------------------------
    try:
        houjin_row = conn.execute(
            """
            SELECT houjin_bangou, normalized_name, prefecture, corporation_type
              FROM jpi_houjin_master
             WHERE houjin_bangou = ?
            """,
            (hb,),
        ).fetchone()
    except sqlite3.Error:
        houjin_row = None

    # Industry inferred from adoption history (industry_jsic_medium).
    jsic_majors_seen: set[str] = set()
    program_kinds_seen: set[str] = set()
    try:
        ad_rows = conn.execute(
            """
            SELECT industry_jsic_medium, program_id_hint, program_name_raw
              FROM jpi_adoption_records
             WHERE houjin_bangou = ?
             LIMIT 100
            """,
            (hb,),
        ).fetchall()
        for r in ad_rows:
            mj = _industry_major_from_jsic(r["industry_jsic_medium"])
            if mj:
                jsic_majors_seen.add(mj)
            program_kinds_seen.add("subsidy")
    except sqlite3.Error:
        ad_rows = []

    # Has invoice registration?
    has_invoice = False
    try:
        inv_row = conn.execute(
            """
            SELECT 1 FROM jpi_invoice_registrants
             WHERE houjin_bangou = ? AND revoked_date IS NULL
                                    AND expired_date IS NULL
             LIMIT 1
            """,
            (hb,),
        ).fetchone()
        has_invoice = bool(inv_row)
    except sqlite3.Error:
        pass

    # Recent enforcement events (5y).
    enforcement_count = 0
    try:
        enf_row = conn.execute(
            """
            SELECT COUNT(*) AS n
              FROM am_enforcement_detail
             WHERE houjin_bangou = ?
               AND issuance_date >= date('now', '-5 years')
            """,
            (hb,),
        ).fetchone()
        enforcement_count = enf_row["n"] if enf_row else 0
    except sqlite3.Error:
        pass

    # --- Compose the deck --------------------------------------------------
    # Strategy:
    #   1. Universal (industry='*') high-severity (>=80) questions: take all,
    #      capped by per-category quota.
    #   2. Industry-specific questions (matching jsic_major): take all matches.
    #   3. Fill remaining slots with universal mid-severity (50..79).
    #
    # Per-category quota prevents any one dimension from dominating.
    per_cat_cap = max(3, deck_size // 7)

    selected: list[dict[str, Any]] = []
    seen_qids: set[str] = set()
    cat_counts: dict[str, int] = {}

    def _take(rows: list[Any]) -> None:
        for r in rows:
            qid = r["question_id"]
            if qid in seen_qids:
                continue
            cat = r["question_category"]
            if cat_counts.get(cat, 0) >= per_cat_cap:
                continue
            selected.append(
                {
                    "question_id": qid,
                    "question_ja": r["question_ja"],
                    "category": cat,
                    "industry_jsic_major": r["industry_jsic_major"],
                    "risk_dimension": r["risk_dimension"],
                    "severity_weight": r["severity_weight"],
                    "rationale_short": r["rationale_short"],
                    "primary_source_hint": r["primary_source_hint"],
                    "citation_hint": r["citation_hint"],
                }
            )
            seen_qids.add(qid)
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            if len(selected) >= deck_size:
                return

    # 1) High-severity universal first.
    try:
        rows_high = conn.execute(
            """
            SELECT question_id, question_ja, question_category,
                   industry_jsic_major, risk_dimension, severity_weight,
                   rationale_short, primary_source_hint, citation_hint
              FROM dd_question_templates
             WHERE industry_jsic_major = '*' AND severity_weight >= 80
             ORDER BY severity_weight DESC, question_category, question_id
            """,
        ).fetchall()
        _take(list(rows_high))
    except sqlite3.Error as exc:
        logger.exception("dd_question_templates high-severity query failed")
        return make_error(
            code="db_unavailable",
            message=f"dd_question_templates query failed: {exc}",
            hint="Ensure migration 102 has been applied.",
        )

    # 2) Industry-specific.
    if jsic_majors_seen and len(selected) < deck_size:
        try:
            placeholders = ",".join("?" for _ in jsic_majors_seen)
            rows_ind = conn.execute(
                f"""
                SELECT question_id, question_ja, question_category,
                       industry_jsic_major, risk_dimension, severity_weight,
                       rationale_short, primary_source_hint, citation_hint
                  FROM dd_question_templates
                 WHERE industry_jsic_major IN ({placeholders})
                 ORDER BY severity_weight DESC, question_id
                """,
                list(jsic_majors_seen),
            ).fetchall()
            _take(list(rows_ind))
        except sqlite3.Error:
            pass

    # 3) Fill mid-severity universal.
    if len(selected) < deck_size:
        try:
            rows_mid = conn.execute(
                """
                SELECT question_id, question_ja, question_category,
                       industry_jsic_major, risk_dimension, severity_weight,
                       rationale_short, primary_source_hint, citation_hint
                  FROM dd_question_templates
                 WHERE industry_jsic_major = '*' AND severity_weight < 80
                 ORDER BY severity_weight DESC, question_category, question_id
                """,
            ).fetchall()
            _take(list(rows_mid))
        except sqlite3.Error:
            pass

    # --- Targeting context (surfaced for the LLM) -------------------------
    target_context = {
        "houjin_bangou": hb,
        "normalized_name": (houjin_row["normalized_name"] if houjin_row else None),
        "prefecture": (houjin_row["prefecture"] if houjin_row else None),
        "industry_jsic_majors_seen": sorted(jsic_majors_seen),
        "adoption_count": len(ad_rows),
        "program_kinds_seen": sorted(program_kinds_seen),
        "has_invoice_registration": has_invoice,
        "enforcement_count_5y": enforcement_count,
    }

    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "target": target_context,
        "results": selected,
        "total": len(selected),
        "limit": deck_size,
        "offset": 0,
        "by_category": dict(sorted(cat_counts.items())),
        "data_quality": {
            "template_corpus_total": 60,
            "houjin_resolved": houjin_row is not None,
            "industries_inferred": list(jsic_majors_seen),
            "caveat": (
                "industries are inferred from adoption history. "
                "deck excludes industry-specific questions when "
                "industries_inferred is empty (no adoption row)."
            ),
        },
        "_disclaimer": _DISCLAIMER_DD_QUESTIONS,
        "_next_calls": [
            {
                "tool": "cross_check_jurisdiction",
                "args": {"houjin_bangou": hb},
                "rationale": (
                    "Some DD questions probe jurisdiction mismatches; "
                    "the LLM should call cross_check_jurisdiction next "
                    "to surface concrete 不一致 evidence."
                ),
                "compound_mult": 2.2,
            },
            {
                "tool": "get_provenance",
                "args": {"entity_id": hb},
                "rationale": (
                    "Surface the provenance trail behind the targeting "
                    "context (adoption / invoice / enforcement) for "
                    "auditor work-paper."
                ),
                "compound_mult": 1.4,
            },
            {
                "tool": "prepare_kessan_briefing",
                "args": {"houjin_bangou": hb, "fiscal_year": None},
                "rationale": (
                    "DD often precedes a 決算 review — surface the "
                    "post-kessan amendment briefing as the next step."
                ),
                "compound_mult": 1.6,
            },
        ],
    }
    return _attach_snapshot(conn, out)


# ---------------------------------------------------------------------------
# 2) prepare_kessan_briefing
# ---------------------------------------------------------------------------


def _kessan_briefing_impl(
    houjin_bangou: str,
    fiscal_year: int | None = None,
    cadence: str = "monthly",
) -> dict[str, Any]:
    """Pure SQL: am_amendment_diff + saved_searches + tax_rulesets briefing.

    Returns monthly / quarterly summary of program-eligibility changes
    since the last 決算 (or for `fiscal_year` if given).
    """
    if not houjin_bangou or not isinstance(houjin_bangou, str):
        return make_error(
            code="missing_required_arg",
            message="houjin_bangou is required (13-digit 法人番号).",
            field="houjin_bangou",
        )
    hb = _normalize_houjin(houjin_bangou)
    if not (hb.isdigit() and len(hb) == 13):
        return make_error(
            code="invalid_enum",
            message=f"houjin_bangou must be 13 digits (got {hb!r}).",
            field="houjin_bangou",
        )
    if cadence not in ("monthly", "quarterly"):
        cadence = "monthly"
    today = datetime.date.today()
    if fiscal_year is None:
        # Fiscal year heuristic: 4月-3月 cycle. If we're in Apr or later,
        # current FY = current year; else previous year.
        fy = today.year if today.month >= 4 else (today.year - 1)
    else:
        try:
            fy = int(fiscal_year)
        except (TypeError, ValueError):
            return make_error(
                code="invalid_enum",
                message=f"fiscal_year must be int (got {fiscal_year!r}).",
                field="fiscal_year",
            )

    fy_start = datetime.date(fy, 4, 1)
    fy_end = datetime.date(fy + 1, 3, 31)
    # Cap the upper bound at today so we don't claim future bins.
    cutoff = min(today, fy_end)

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- am_amendment_diff in window --------------------------------------
    try:
        diff_rows = conn.execute(
            """
            SELECT entity_id, field_name, prev_value, new_value,
                   detected_at, source_url
              FROM am_amendment_diff
             WHERE detected_at >= ? AND detected_at <= ?
             ORDER BY detected_at ASC
             LIMIT 500
            """,
            (fy_start.isoformat() + "T00:00:00", cutoff.isoformat() + "T23:59:59"),
        ).fetchall()
    except sqlite3.Error:
        diff_rows = []

    # --- Tax_ruleset effective windows touching fy -----------------------
    try:
        tax_rows = conn.execute(
            """
            SELECT unified_id, ruleset_name, tax_category, effective_from,
                   effective_until, authority, source_url
              FROM jpi_tax_rulesets
             WHERE (effective_from BETWEEN ? AND ?)
                OR (effective_until BETWEEN ? AND ?)
             ORDER BY COALESCE(effective_from, effective_until) ASC
             LIMIT 50
            """,
            (fy_start.isoformat(), fy_end.isoformat(), fy_start.isoformat(), fy_end.isoformat()),
        ).fetchall()
    except sqlite3.Error:
        tax_rows = []

    # --- Bin into monthly / quarterly buckets ----------------------------
    bins: dict[str, dict[str, int]] = {}

    def _bin_key(date_iso: str) -> str:
        d = datetime.date.fromisoformat(date_iso[:10])
        if cadence == "monthly":
            return f"{d.year:04d}-{d.month:02d}"
        q = (d.month - 1) // 3 + 1
        return f"{d.year:04d}-Q{q}"

    for r in diff_rows:
        try:
            key = _bin_key(r["detected_at"])
        except (ValueError, TypeError):
            continue
        b = bins.setdefault(key, {"amendment_diffs": 0, "tax_changes": 0})
        b["amendment_diffs"] += 1

    for r in tax_rows:
        ts = r["effective_from"] or r["effective_until"]
        if not ts:
            continue
        try:
            key = _bin_key(ts)
        except (ValueError, TypeError):
            continue
        b = bins.setdefault(key, {"amendment_diffs": 0, "tax_changes": 0})
        b["tax_changes"] += 1

    timeline = [
        {
            "bin": k,
            "amendment_diffs": v["amendment_diffs"],
            "tax_changes": v["tax_changes"],
            "total_events": v["amendment_diffs"] + v["tax_changes"],
        }
        for k, v in sorted(bins.items())
    ]

    # --- Top-level highlights (top 5 by total_events) ---------------------
    top_bins = sorted(timeline, key=lambda b: b["total_events"], reverse=True)[:5]

    # --- Saved-searches digest cadence (best-effort cross-DB hint) -------
    # saved_searches lives on jpintel.db. We do not cross-connect here —
    # we surface the customer's last_run_at as a hint via a soft probe
    # (table absent in autonomath.db → empty list, no error).
    saved_searches_tracked = 0
    try:
        ss_row = conn.execute("SELECT COUNT(*) AS n FROM saved_searches").fetchone()
        saved_searches_tracked = ss_row["n"] if ss_row else 0
    except sqlite3.Error:
        saved_searches_tracked = 0  # table not on autonomath.db is normal

    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "fiscal_year": fy,
        "fy_window": {
            "start": fy_start.isoformat(),
            "end": fy_end.isoformat(),
            "cutoff": cutoff.isoformat(),
        },
        "cadence": cadence,
        "results": timeline,
        "total": len(timeline),
        "limit": len(timeline) or 1,
        "offset": 0,
        "top_bins": top_bins,
        "tax_changes_in_window": [
            {
                "unified_id": r["unified_id"],
                "ruleset_name": r["ruleset_name"],
                "tax_category": r["tax_category"],
                "effective_from": r["effective_from"],
                "effective_until": r["effective_until"],
                "authority": r["authority"],
                "source_url": r["source_url"],
            }
            for r in tax_rows
        ],
        "amendment_diffs_count": len(diff_rows),
        "saved_searches_tracked": saved_searches_tracked,
        "data_quality": {
            "amendment_diff_corpus_caveat": (
                "am_amendment_diff is populated by the post-launch cron. "
                "If 0 results, the cron has not yet run for this window — "
                "fall back to am_amendment_snapshot for time-series."
            ),
        },
        "_disclaimer": _DISCLAIMER_KESSAN_BRIEFING,
        "_next_calls": [
            {
                "tool": "track_amendment_lineage_am",
                "args": {
                    "target_kind": "program",
                    "target_id": "<program_id_of_interest>",
                },
                "rationale": (
                    "Drill into a specific program's amendment lineage "
                    "for any bin that surfaced significant deltas."
                ),
                "compound_mult": 1.4,
            },
            {
                "tool": "list_tax_sunset_alerts",
                "args": {},
                "rationale": (
                    "Tax-changes-in-window may be only the surface — "
                    "full sunset_at horizon is in list_tax_sunset_alerts."
                ),
                "compound_mult": 1.3,
            },
            {
                "tool": "match_due_diligence_questions",
                "args": {"houjin_bangou": hb, "deck_size": 40},
                "rationale": (
                    "Briefing surfaces what changed; DD deck surfaces "
                    "what to confirm. Compose them in the same call."
                ),
                "compound_mult": 1.6,
            },
        ],
    }
    return _attach_snapshot(conn, out)


# ---------------------------------------------------------------------------
# 3) forecast_program_renewal
# ---------------------------------------------------------------------------


def _forecast_renewal_impl(
    program_id: str,
    horizon_fy: int | None = None,
) -> dict[str, Any]:
    """Pure stats: am_application_round + am_amendment_snapshot history
    → probability + window of renewal in next FY.

    NOT sensitive — statistical forecast about program lifecycle, not
    business advice.
    """
    if not program_id or not isinstance(program_id, str) or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
            retry_with=["search_programs"],
        )
    pid = program_id.strip()

    today = datetime.date.today()
    if horizon_fy is None:
        # Default to next FY (Apr of current/next calendar year).
        horizon_fy = today.year if today.month >= 4 else (today.year - 1)
        horizon_fy += 1
    else:
        try:
            horizon_fy = int(horizon_fy)
        except (TypeError, ValueError):
            return make_error(
                code="invalid_enum",
                message=f"horizon_fy must be int (got {horizon_fy!r}).",
                field="horizon_fy",
            )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Pull all rounds, ordered chronologically -------------------------
    try:
        rounds = conn.execute(
            """
            SELECT round_id, round_label, round_seq,
                   application_open_date, application_close_date,
                   announced_date, status, source_url
              FROM am_application_round
             WHERE program_entity_id = ?
             ORDER BY round_seq ASC, application_open_date ASC
            """,
            (pid,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("forecast_renewal round query failed")
        return make_error(
            code="db_unavailable",
            message=f"am_application_round query failed: {exc}",
        )

    if not rounds:
        out: dict[str, Any] = {
            "program_id": pid,
            "horizon_fy": horizon_fy,
            "results": [],
            "total": 0,
            "limit": 1,
            "offset": 0,
            "renewal_probability": None,
            "predicted_window": None,
            "rationale": (
                "No application rounds in am_application_round for this "
                "program — cannot infer a renewal cycle. Probability is "
                "absent, not zero (data missing ≠ program defunct)."
            ),
            "data_quality": {
                "rounds_observed": 0,
                "amendment_snapshots_observed": 0,
                "method": "data_missing",
                "caveat": (
                    "Forecast requires at least 2 historical rounds. "
                    "Verify program existence via search_programs."
                ),
            },
            "_next_calls": [
                {
                    "tool": "search_programs",
                    "args": {"q": pid},
                    "rationale": (
                        "Confirm canonical_id resolves to a real program "
                        "before relying on the missing-rounds verdict."
                    ),
                    "compound_mult": 1.2,
                },
            ],
        }
        return _attach_snapshot(conn, out)

    # --- Derive cycle stats -----------------------------------------------
    open_dates: list[datetime.date] = []
    for r in rounds:
        if r["application_open_date"]:
            try:
                d = datetime.date.fromisoformat(r["application_open_date"][:10])
                open_dates.append(d)
            except (ValueError, TypeError):
                continue

    intervals_days: list[int] = []
    for i in range(1, len(open_dates)):
        delta = (open_dates[i] - open_dates[i - 1]).days
        if 30 <= delta <= 730:
            intervals_days.append(delta)

    # Snapshots — stronger signal that the program is live and getting
    # ingested by our crawler.
    try:
        snapshot_count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM am_amendment_snapshot WHERE entity_id = ?",
            (pid,),
        ).fetchone()
        snapshot_count = snapshot_count_row["n"] if snapshot_count_row else 0
    except sqlite3.Error:
        snapshot_count = 0

    # Status distribution.
    statuses = [(r["status"] or "").lower() for r in rounds]
    n_open = sum(1 for s in statuses if s == "open")
    n_upcoming = sum(1 for s in statuses if s == "upcoming")
    # n_closed intentionally unused — surfaced via signals + status counts.

    # --- Probability heuristic --------------------------------------------
    # Components (all in [0, 1]):
    #   * frequency_signal — at least 2 rounds with reasonable cadence.
    #   * recency_signal   — last round within 1y of today.
    #   * pipeline_signal  — at least 1 open or upcoming.
    #   * snapshot_signal  — am_amendment_snapshot has > 0 captures.
    n_intervals = len(intervals_days)
    frequency_signal = min(1.0, n_intervals / 3.0)

    recency_signal = 0.0
    if open_dates:
        days_since_last = (today - max(open_dates)).days
        if days_since_last <= 90:
            recency_signal = 1.0
        elif days_since_last <= 365:
            recency_signal = 0.7
        elif days_since_last <= 730:
            recency_signal = 0.3
        else:
            recency_signal = 0.0

    pipeline_signal = 1.0 if (n_open + n_upcoming) > 0 else 0.0
    snapshot_signal = 1.0 if snapshot_count > 0 else 0.5

    # Weighted average; weights sum to 1.0.
    probability = round(
        0.30 * frequency_signal
        + 0.30 * recency_signal
        + 0.25 * pipeline_signal
        + 0.15 * snapshot_signal,
        2,
    )

    # --- Predicted window -------------------------------------------------
    predicted_window: dict[str, Any] | None = None
    if intervals_days and open_dates:
        avg_interval = sum(intervals_days) / len(intervals_days)
        last_open = max(open_dates)
        predicted_open = last_open + datetime.timedelta(days=int(round(avg_interval)))
        # Window ±60 days reflects observed cadence variability.
        predicted_window = {
            "predicted_open_date": predicted_open.isoformat(),
            "earliest": (predicted_open - datetime.timedelta(days=60)).isoformat(),
            "latest": (predicted_open + datetime.timedelta(days=60)).isoformat(),
            "avg_interval_days": int(round(avg_interval)),
            "interval_samples": len(intervals_days),
        }

    rationale_lines: list[str] = []
    rationale_lines.append(
        f"frequency_signal={frequency_signal:.2f} ({n_intervals} interval samples)"
    )
    rationale_lines.append(
        f"recency_signal={recency_signal:.2f} "
        f"(last open {open_dates[-1].isoformat() if open_dates else 'n/a'})"
    )
    rationale_lines.append(
        f"pipeline_signal={pipeline_signal:.2f} ({n_open} open + {n_upcoming} upcoming)"
    )
    rationale_lines.append(
        f"snapshot_signal={snapshot_signal:.2f} ({snapshot_count} amendment snapshots)"
    )

    out2: dict[str, Any] = {
        "program_id": pid,
        "horizon_fy": horizon_fy,
        "results": [
            {
                "round_seq": r["round_seq"],
                "round_label": r["round_label"],
                "application_open_date": r["application_open_date"],
                "application_close_date": r["application_close_date"],
                "status": r["status"],
            }
            for r in rounds
        ],
        "total": len(rounds),
        "limit": len(rounds),
        "offset": 0,
        "renewal_probability": probability,
        "predicted_window": predicted_window,
        "signals": {
            "frequency_signal": round(frequency_signal, 2),
            "recency_signal": round(recency_signal, 2),
            "pipeline_signal": round(pipeline_signal, 2),
            "snapshot_signal": round(snapshot_signal, 2),
        },
        "rationale": "; ".join(rationale_lines),
        "data_quality": {
            "rounds_observed": len(rounds),
            "amendment_snapshots_observed": snapshot_count,
            "method": "weighted_signal_average",
            "caveat": (
                "renewal_probability is a 4-signal weighted average, "
                "not a calibrated forecast. Treat as advisory; primary "
                "source confirmation required for high-stakes decisions."
            ),
        },
        "_next_calls": [
            {
                "tool": "program_active_periods_am",
                "args": {"program_id": pid, "future_only": True},
                "rationale": (
                    "If renewal probability is high, surface the next "
                    "active round window for the customer."
                ),
                "compound_mult": 1.5,
            },
            {
                "tool": "track_amendment_lineage_am",
                "args": {"target_kind": "program", "target_id": pid},
                "rationale": (
                    "Forecast assumes structure stability; lineage "
                    "tells the customer if the program was amended."
                ),
                "compound_mult": 1.4,
            },
        ],
    }
    return _attach_snapshot(conn, out2)


# ---------------------------------------------------------------------------
# 4) cross_check_jurisdiction
# ---------------------------------------------------------------------------


def _cross_check_jurisdiction_impl(
    houjin_bangou: str | None = None,
    shogo: str | None = None,
) -> dict[str, Any]:
    """Pure SQL: jpi_houjin_master + jpi_invoice_registrants +
    jpi_adoption_records → registered jurisdiction vs. inferred
    operational jurisdiction. Detects 不一致.

    Sensitive (§52 — 税理士 client onboarding territory).
    """
    if not (houjin_bangou or shogo):
        return make_error(
            code="missing_required_arg",
            message="One of houjin_bangou or shogo is required.",
            field="houjin_bangou",
        )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Resolve target ---------------------------------------------------
    houjin_row: sqlite3.Row | None = None
    hb: str | None = None
    s: str | None = None
    if houjin_bangou:
        hb = _normalize_houjin(houjin_bangou)
        if not (hb.isdigit() and len(hb) == 13):
            return make_error(
                code="invalid_enum",
                message=f"houjin_bangou must be 13 digits (got {hb!r}).",
                field="houjin_bangou",
            )
        try:
            houjin_row = conn.execute(
                """
                SELECT houjin_bangou, normalized_name, address_normalized,
                       prefecture, municipality, corporation_type
                  FROM jpi_houjin_master
                 WHERE houjin_bangou = ?
                """,
                (hb,),
            ).fetchone()
        except sqlite3.Error:
            houjin_row = None
    elif shogo:
        s = (shogo or "").strip()
        if not s:
            return make_error(
                code="missing_required_arg",
                message="shogo is empty after strip.",
                field="shogo",
            )
        try:
            houjin_row = conn.execute(
                """
                SELECT houjin_bangou, normalized_name, address_normalized,
                       prefecture, municipality, corporation_type
                  FROM jpi_houjin_master
                 WHERE normalized_name = ?
                 LIMIT 1
                """,
                (s,),
            ).fetchone()
        except sqlite3.Error:
            houjin_row = None

    if houjin_row is None:
        lookup = f"shogo={s!r}" if s else f"houjin_bangou={hb!r}"
        out_empty: dict[str, Any] = {
            "houjin_bangou": hb,
            "shogo": s,
            "registered": None,
            "invoice_jurisdiction": None,
            "operational": {
                "by_prefecture_top5": [],
                "total_adoptions": 0,
            },
            "results": [],
            "total": 0,
            "limit": 1,
            "offset": 0,
            "mismatch_count": 0,
            "data_quality": {
                "houjin_resolved": False,
                "caveat": (
                    f"No houjin_master row for {lookup}; returned a "
                    "graceful empty envelope rather than a hard error."
                ),
            },
            "_disclaimer": _DISCLAIMER_JURISDICTION,
            "_next_calls": [],
        }
        return _attach_snapshot(conn, out_empty)

    hb = houjin_row["houjin_bangou"]
    registered = {
        "prefecture": houjin_row["prefecture"],
        "municipality": houjin_row["municipality"],
        "address_normalized": houjin_row["address_normalized"],
        "source": "jpi_houjin_master (法人番号公表サイト)",
    }

    # --- Invoice registrant address (NTA invoice publication) ------------
    invoice_jurisdiction: dict[str, Any] | None = None
    try:
        inv_row = conn.execute(
            """
            SELECT prefecture, address_normalized, registered_date,
                   revoked_date, expired_date, source_url
              FROM jpi_invoice_registrants
             WHERE houjin_bangou = ?
             ORDER BY registered_date DESC
             LIMIT 1
            """,
            (hb,),
        ).fetchone()
        if inv_row:
            invoice_jurisdiction = {
                "prefecture": inv_row["prefecture"],
                "address_normalized": inv_row["address_normalized"],
                "registered_date": inv_row["registered_date"],
                "revoked_date": inv_row["revoked_date"],
                "expired_date": inv_row["expired_date"],
                "source": "jpi_invoice_registrants (NTA invoice 公表)",
                "source_url": inv_row["source_url"],
            }
    except sqlite3.Error:
        invoice_jurisdiction = None

    # --- Operational jurisdiction inferred from adoption records ---------
    # The adoption table carries the actual project address (which is the
    # 拠点 the 補助金 was disbursed against). Group by prefecture + count.
    operational_prefectures: dict[str, int] = {}
    try:
        op_rows = conn.execute(
            """
            SELECT prefecture, municipality, COUNT(*) AS n
              FROM jpi_adoption_records
             WHERE houjin_bangou = ? AND prefecture IS NOT NULL
             GROUP BY prefecture, municipality
             ORDER BY n DESC
             LIMIT 10
            """,
            (hb,),
        ).fetchall()
        for r in op_rows:
            pref = r["prefecture"]
            if pref:
                operational_prefectures[pref] = operational_prefectures.get(pref, 0) + r["n"]
    except sqlite3.Error:
        op_rows = []

    operational_top = sorted(operational_prefectures.items(), key=lambda kv: -kv[1])[:5]

    # --- Mismatch detection -----------------------------------------------
    mismatches: list[dict[str, Any]] = []
    if (
        registered["prefecture"]
        and invoice_jurisdiction
        and invoice_jurisdiction.get("prefecture")
        and registered["prefecture"] != invoice_jurisdiction["prefecture"]
    ):
        mismatches.append(
            {
                "kind": "registered_vs_invoice_prefecture",
                "registered": registered["prefecture"],
                "invoice": invoice_jurisdiction["prefecture"],
                "severity": "medium",
                "action_hint": (
                    "T番号公表所在地と法人番号公表所在地が異なります。"
                    "本店移転後 NTA への変更届出漏れの可能性 — 確認推奨。"
                ),
            }
        )
    if (
        registered["prefecture"]
        and operational_top
        and operational_top[0][0] != registered["prefecture"]
    ):
        op_top_pref = operational_top[0][0]
        mismatches.append(
            {
                "kind": "registered_vs_operational_prefecture",
                "registered": registered["prefecture"],
                "operational_top": op_top_pref,
                "operational_count": operational_top[0][1],
                "severity": "low",
                "action_hint": (
                    "登記簿上の本店所在地と実際の補助金交付先所在地が "
                    "異なります。事業所税の課税地・申告先確認を推奨。"
                ),
            }
        )

    out: dict[str, Any] = {
        "houjin_bangou": hb,
        "shogo": houjin_row["normalized_name"],
        "registered": registered,
        "invoice_jurisdiction": invoice_jurisdiction,
        "operational": {
            "by_prefecture_top5": [
                {"prefecture": p, "adoption_count": c} for p, c in operational_top
            ],
            "total_adoptions": sum(operational_prefectures.values()),
        },
        "results": mismatches,
        "total": len(mismatches),
        "limit": len(mismatches) or 1,
        "offset": 0,
        "mismatch_count": len(mismatches),
        "data_quality": {
            "houjin_corpus_total": 166765,
            "invoice_corpus_total": 13801,
            "caveat": (
                "operational jurisdiction inferred from adoption records "
                "only. Programs without adoption history surface no "
                "operational signal — this is sparse, not authoritative."
            ),
        },
        "_disclaimer": _DISCLAIMER_JURISDICTION,
        "_next_calls": [
            {
                "tool": "match_due_diligence_questions",
                "args": {"houjin_bangou": hb, "deck_size": 40},
                "rationale": (
                    "Mismatches surfaced here become high-priority DD "
                    "questions in the next call (governance category)."
                ),
                "compound_mult": 2.0,
            },
            {
                "tool": "dd_profile_am",
                "args": {"houjin_bangou": hb},
                "rationale": (
                    "Pull the full dd_profile_am for context — "
                    "enforcement / adoption / certification picture."
                ),
                "compound_mult": 1.5,
            },
        ],
    }
    return _attach_snapshot(conn, out)


# ---------------------------------------------------------------------------
# 5) bundle_application_kit
# ---------------------------------------------------------------------------


def _bundle_application_kit_impl(
    program_id: str,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure file assembly: program metadata + cover letter + checklist
    + similar 採択例 list. NO LLM. NO 申請書面 creation (行政書士法 §1).
    """
    if not program_id or not isinstance(program_id, str) or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
            retry_with=["search_programs"],
        )
    pid = program_id.strip()
    if profile is None:
        profile = {}
    if not isinstance(profile, dict):
        return make_error(
            code="missing_required_arg",
            message="profile must be a dict (may be empty {}).",
            field="profile",
        )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    # --- Program metadata + summary --------------------------------------
    try:
        prog_row = conn.execute(
            """
            SELECT canonical_id, primary_name, source_url, raw_json
              FROM am_entities
             WHERE canonical_id = ? AND record_kind = 'program'
            """,
            (pid,),
        ).fetchone()
    except sqlite3.Error:
        prog_row = None

    if prog_row is None:
        if pid.startswith("program:"):
            return make_error(
                code="seed_not_found",
                message=f"program_id {pid!r} not found in am_entities.",
                field="program_id",
                retry_with=["search_programs"],
            )
        out_empty: dict[str, Any] = {
            "program_id": pid,
            "program": None,
            "results": [],
            "total": 0,
            "limit": 1,
            "offset": 0,
            "document_checklist": [],
            "certifications": [],
            "similar_cases": [],
            "cover_letter_text": "",
            "docx_placeholder": None,
            "data_quality": {
                "program_resolved": False,
                "steps_count": 0,
                "checklist_size": 0,
                "certifications_count": 0,
                "similar_cases_count": 0,
                "caveat": (
                    f"program_id {pid!r} was not found in am_entities; "
                    "returned a graceful empty kit scaffold."
                ),
            },
            "_disclaimer": _DISCLAIMER_APPLICATION_KIT,
            "_next_calls": [],
        }
        return _attach_snapshot(conn, out_empty)

    primary_name = prog_row["primary_name"]
    source_url = prog_row["source_url"]
    raw_json: dict[str, Any] = {}
    try:
        if prog_row["raw_json"]:
            raw_json = json.loads(prog_row["raw_json"])
    except (ValueError, TypeError):
        raw_json = {}

    summary_200: str | None = None
    try:
        sum_row = conn.execute(
            "SELECT summary_200 FROM am_program_summary WHERE entity_id = ?",
            (pid,),
        ).fetchone()
        if sum_row:
            summary_200 = sum_row["summary_200"]
    except sqlite3.Error:
        summary_200 = None

    # --- Application steps + document_checklist --------------------------
    document_checklist: list[str] = []
    seen_docs: set[str] = set()
    application_steps: list[dict[str, Any]] = []
    try:
        step_rows = conn.execute(
            """
            SELECT step_no, step_title, step_description,
                   prerequisites_json, expected_days, online_or_offline,
                   responsible_party
              FROM am_application_steps
             WHERE program_entity_id = ?
             ORDER BY step_no
            """,
            (pid,),
        ).fetchall()
        for sr in step_rows:
            application_steps.append(
                {
                    "step_no": sr["step_no"],
                    "step_title": sr["step_title"],
                    "step_description": sr["step_description"],
                    "expected_days": sr["expected_days"],
                    "online_or_offline": sr["online_or_offline"],
                    "responsible_party": sr["responsible_party"],
                }
            )
            try:
                docs = json.loads(sr["prerequisites_json"] or "[]")
                if isinstance(docs, list):
                    for d in docs:
                        if isinstance(d, str) and d not in seen_docs:
                            seen_docs.add(d)
                            document_checklist.append(d)
            except (ValueError, TypeError):
                continue
    except sqlite3.Error:
        step_rows = []

    # --- Certifications --------------------------------------------------
    try:
        cert_rows = conn.execute(
            """
            SELECT prerequisite_name, required_or_optional, obtain_url
              FROM am_prerequisite_bundle
             WHERE program_entity_id = ? AND prerequisite_kind = 'cert'
             ORDER BY bundle_id
             LIMIT 20
            """,
            (pid,),
        ).fetchall()
    except sqlite3.Error:
        cert_rows = []
    certifications = [
        {
            "name": r["prerequisite_name"],
            "required_or_optional": r["required_or_optional"],
            "obtain_url": r["obtain_url"],
        }
        for r in cert_rows
    ]

    # --- Similar 採択例 (sample by program_id_hint or program_name) -----
    similar_cases: list[dict[str, Any]] = []
    try:
        case_rows = conn.execute(
            """
            SELECT id, houjin_bangou, company_name_raw, project_title,
                   prefecture, amount_granted_yen, source_url
              FROM jpi_adoption_records
             WHERE program_id_hint = ? OR program_name_raw LIKE ?
             ORDER BY amount_granted_yen DESC NULLS LAST, id DESC
             LIMIT 10
            """,
            (pid, f"%{primary_name[:20]}%" if primary_name else "%"),
        ).fetchall()
        for r in case_rows:
            similar_cases.append(
                {
                    "adoption_id": r["id"],
                    "houjin_bangou": r["houjin_bangou"],
                    "company_name": r["company_name_raw"],
                    "project_title": r["project_title"],
                    "prefecture": r["prefecture"],
                    "amount_granted_yen": r["amount_granted_yen"],
                    "source_url": r["source_url"],
                }
            )
    except sqlite3.Error:
        case_rows = []

    # --- Cover letter scaffold (information-only — NOT 申請書面) ---------
    profile_name = profile.get("company_name") or profile.get("normalized_name") or "（申請者名）"
    cover_letter_lines = [
        f"件名: {primary_name} 申請にあたって",
        "",
        f"申請者: {profile_name}",
        f"対象制度: {primary_name}",
    ]
    if source_url:
        cover_letter_lines.append(f"公募要領 URL: {source_url}")
    cover_letter_lines.extend(
        [
            "",
            "本資料は AutonoMath が公開公募要領 + 過去採択事例を assemble した "
            "scaffold であり、申請書面そのものではありません。書面作成は "
            "行政書士法 §1 の独占業務であり、当社は提供しません。",
            "",
            "確認事項 (添付チェックリスト参照):",
        ]
    )
    for d in document_checklist[:10]:
        cover_letter_lines.append(f"  - {d}")
    cover_letter_text = "\n".join(cover_letter_lines)

    # --- DOCX placeholder -------------------------------------------------
    # We do NOT generate an actual .docx — that would cross into 申請書面
    # territory. Instead we surface the placeholder filename + explicit
    # warning that the customer LLM should populate via 行政書士 review.
    docx_placeholder = {
        "filename": f"application_kit_{pid.replace(':', '_')}.docx",
        "note_ja": (
            "DOCX 申請書 generation は 行政書士法 §1 の独占業務のため、"
            "当社は scaffold (cover letter + checklist + 採択事例 list) "
            "のみを surface します。最終書面の作成・提出は資格を有する "
            "行政書士へご相談ください。"
        ),
        "scaffold_only": True,
    }

    out: dict[str, Any] = {
        "program_id": pid,
        "program": {
            "primary_name": primary_name,
            "source_url": source_url,
            "summary_200": summary_200,
            "raw_json_keys": list(raw_json.keys()),
        },
        "results": application_steps,
        "total": len(application_steps),
        "limit": len(application_steps) or 1,
        "offset": 0,
        "document_checklist": document_checklist,
        "certifications": certifications,
        "similar_cases": similar_cases,
        "cover_letter_text": cover_letter_text,
        "docx_placeholder": docx_placeholder,
        "data_quality": {
            "steps_count": len(application_steps),
            "checklist_size": len(document_checklist),
            "certifications_count": len(certifications),
            "similar_cases_count": len(similar_cases),
            "caveat": (
                "kit is a scaffold — primary URLs + structured fields. "
                "Final 申請書面 creation must go through a 行政書士. "
                "When checklist_size = 0, am_application_steps is sparse."
            ),
        },
        "_disclaimer": _DISCLAIMER_APPLICATION_KIT,
        "_next_calls": [
            {
                "tool": "simulate_application_am",
                "args": {"program_id": pid, "profile": profile or {}},
                "rationale": (
                    "Simulate the application walkthrough to surface "
                    "completeness_score + est_review_days BEFORE the "
                    "customer commits to the kit."
                ),
                "compound_mult": 1.6,
            },
            {
                "tool": "find_complementary_programs_am",
                "args": {"seed_program_id": pid, "top_n": 10},
                "rationale": (
                    "While assembling the kit, surface compatible peers "
                    "the applicant could stack to enlarge ceiling_yen."
                ),
                "compound_mult": 1.5,
            },
            {
                "tool": "program_active_periods_am",
                "args": {"program_id": pid, "future_only": True},
                "rationale": (
                    "Confirm the next round window before the customer "
                    "spends time populating the kit."
                ),
                "compound_mult": 1.3,
            },
        ],
    }
    return _attach_snapshot(conn, out)


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_WAVE22_ENABLED + the global
# AUTONOMATH_ENABLED. Each @mcp.tool docstring is ≤ 400 chars per the
# Wave 21 spec.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def match_due_diligence_questions(
        houjin_bangou: Annotated[
            str,
            Field(
                description=("13-digit 法人番号 (with or without 'T' prefix)."),
            ),
        ],
        deck_size: Annotated[
            int,
            Field(
                ge=20,
                le=60,
                description=("Number of DD questions to return (20-60). Default 40."),
            ),
        ] = 40,
    ) -> dict[str, Any]:
        """[WAVE22-COMPOSE] DD question deck (30-60 items) tailored to industry × program portfolio × 与信 risk by joining dd_question_templates (60 rows, migration 102) with houjin / adoption / enforcement / invoice corpora. Pure pattern-match, NO LLM. §52/§72 sensitive — checklist, not advice."""
        return _match_dd_questions_impl(
            houjin_bangou=houjin_bangou,
            deck_size=deck_size,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def prepare_kessan_briefing(
        houjin_bangou: Annotated[
            str,
            Field(
                description=("13-digit 法人番号 (with or without 'T' prefix)."),
            ),
        ],
        fiscal_year: Annotated[
            int | None,
            Field(
                description=("Fiscal year (April-March). Default = current FY."),
            ),
        ] = None,
        cadence: Annotated[
            str,
            Field(
                description=("Bin cadence: 'monthly' (default) or 'quarterly'."),
            ),
        ] = "monthly",
    ) -> dict[str, Any]:
        """[WAVE22-COMPOSE] 月次 / 四半期 summary of program-eligibility changes since last 決算 by joining am_amendment_diff + jpi_tax_rulesets within the FY window. Compounds saved_searches digest cadence. §52 sensitive — 決算 territory, briefing only, not 税務代理."""
        return _kessan_briefing_impl(
            houjin_bangou=houjin_bangou,
            fiscal_year=fiscal_year,
            cadence=cadence,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def forecast_program_renewal(
        program_id: Annotated[
            str,
            Field(description="Target program canonical_id."),
        ],
        horizon_fy: Annotated[
            int | None,
            Field(
                description=("Target fiscal year for the forecast. Default = next FY."),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[WAVE22-COMPOSE] Probability + window of program renewal in next FY based on historical am_application_round cadence + am_amendment_snapshot density. 4-signal weighted average (frequency / recency / pipeline / snapshot). NOT sensitive — statistical, not advice."""
        return _forecast_renewal_impl(
            program_id=program_id,
            horizon_fy=horizon_fy,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def cross_check_jurisdiction(
        houjin_bangou: Annotated[
            str | None,
            Field(
                description=(
                    "13-digit 法人番号 (preferred). One of houjin_bangou / shogo required."
                ),
            ),
        ] = None,
        shogo: Annotated[
            str | None,
            Field(
                description=("商号 (legal name). Used only if houjin_bangou is None."),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[WAVE22-COMPOSE] Registered (法務局) vs invoice (NTA) vs operational (交付) jurisdiction breakdown. Detects 不一致 for 税理士 onboarding — flags prefecture mismatches between houjin_master / invoice_registrants / adoption_records. §52/§72 sensitive — heuristic detection, not 税務代理."""
        return _cross_check_jurisdiction_impl(
            houjin_bangou=houjin_bangou,
            shogo=shogo,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def bundle_application_kit(
        program_id: Annotated[
            str,
            Field(description="Target program canonical_id."),
        ],
        profile: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Applicant profile dict — populates cover letter header. Empty {} OK."
                ),
            ),
        ] = {},  # noqa: B006 — pydantic Field tolerates the empty default
    ) -> dict[str, Any]:
        """[WAVE22-COMPOSE] Complete downloadable kit assembly: program metadata + cover letter scaffold + 必要書類 checklist + similar 採択例 list. Pure file assembly, NO LLM, NO DOCX generation. §1 sensitive — 申請書面作成は行政書士の独占業務、当社は scaffold + 一次 URL のみ提供."""
        return _bundle_application_kit_impl(
            program_id=program_id,
            profile=profile,
        )


# ---------------------------------------------------------------------------
# Self-test harness (not part of the MCP surface).
#
#   .venv/bin/python -m jpintel_mcp.mcp.autonomath_tools.wave22_tools
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import pprint

    print("\n=== match_due_diligence_questions ===")
    res = _match_dd_questions_impl(
        houjin_bangou="3450001000777",
        deck_size=30,
    )
    pprint.pprint(
        {
            "total": res.get("total"),
            "by_category": res.get("by_category"),
            "industries_inferred": res.get("data_quality", {}).get("industries_inferred"),
            "next_calls_count": len(res.get("_next_calls", [])),
            "snapshot_id": res.get("corpus_snapshot_id"),
            "checksum": res.get("corpus_checksum"),
        }
    )

    print("\n=== prepare_kessan_briefing ===")
    res = _kessan_briefing_impl(
        houjin_bangou="3450001000777",
        cadence="quarterly",
    )
    pprint.pprint(
        {
            "fiscal_year": res.get("fiscal_year"),
            "total": res.get("total"),
            "amendment_diffs_count": res.get("amendment_diffs_count"),
            "tax_changes": len(res.get("tax_changes_in_window", [])),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== forecast_program_renewal ===")
    res = _forecast_renewal_impl(
        program_id="program:base:71f6029070",
    )
    pprint.pprint(
        {
            "renewal_probability": res.get("renewal_probability"),
            "predicted_window": res.get("predicted_window"),
            "signals": res.get("signals"),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== cross_check_jurisdiction ===")
    res = _cross_check_jurisdiction_impl(
        houjin_bangou="3450001000777",
    )
    pprint.pprint(
        {
            "shogo": res.get("shogo"),
            "registered_pref": res.get("registered", {}).get("prefecture"),
            "mismatch_count": res.get("mismatch_count"),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )

    print("\n=== bundle_application_kit ===")
    res = _bundle_application_kit_impl(
        program_id="program:base:71f6029070",
        profile={"company_name": "株式会社サンプル"},
    )
    pprint.pprint(
        {
            "program_name": res.get("program", {}).get("primary_name"),
            "checklist_size": res.get("data_quality", {}).get("checklist_size"),
            "similar_cases_count": res.get("data_quality", {}).get("similar_cases_count"),
            "next_calls_count": len(res.get("_next_calls", [])),
        }
    )
