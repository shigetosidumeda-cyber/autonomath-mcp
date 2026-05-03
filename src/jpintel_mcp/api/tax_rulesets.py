"""REST handlers for tax_rulesets (税務判定ルールセット).

Backed by migration 018's `tax_rulesets` + `tax_rulesets_fts` tables.
Encodes 国税庁 タックスアンサー / 電帳法一問一答 / インボイス Q&A as
machine-readable decision rules: narrative `eligibility_conditions` for
humans + `eligibility_conditions_json` predicates for the judgment engine.

# CHAIN: laws ←(related_law_ids_json)── tax_rulesets. `/evaluate` walks the
#        predicate tree against a caller-supplied business_profile and
#        reports applicable / not applicable with per-condition reasons.
# WHEN NOT: we are NOT a tax advisor. `/evaluate` only matches declared JSON
#        predicates — it does not interpret tax law. Use `/search` to find
#        rulesets by text and `/{unified_id}` for the single-row narrative
#        (eligibility_conditions, calculation_formula, filing_requirements).

Scope boundary — read-only. Ruleset rows are curated externally (via
scripts/ingest/ingest_tax_rulesets.py) and never mutated here.

FTS workaround: same trigram tokenizer gotcha as programs_fts / laws_fts —
we reuse the `_build_fts_match` phrase-quote builder from api/programs.py
so 2+ character kanji compounds (e.g. `税額控除`, `適格請求書`) match
contiguously, never as independent trigram hits.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot, snapshot_headers
from jpintel_mcp.api.deps import (
    ApiContextDep,
    DbDep,
    log_empty_search,
    log_usage,
)

from jpintel_mcp.api.programs import (
    KANA_EXPANSIONS,
    _build_fts_match,
)

router = APIRouter(prefix="/v1/tax_rulesets", tags=["tax_rulesets"])


# ---------------------------------------------------------------------------
# I/O models
# ---------------------------------------------------------------------------


TAX_CATEGORIES = (
    "consumption",
    "corporate",
    "income",
    "property",
    "local",
    "inheritance",
)
RULESET_KINDS = (
    "registration",
    "credit",
    "deduction",
    "special_depreciation",
    "exemption",
    "preservation",
    "other",
)

_UNIFIED_ID_RE = re.compile(r"^TAX-[0-9a-f]{10}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# 税理士法 §52 fence: every tax-related REST response surfaces this text in
# the `_disclaimer` envelope field so consumer LLMs / dashboards don't relay
# our output as 税務助言. We provide DOC-level information (制度名 / 根拠条文 /
# 計算例 from public sources) — never advice. Mirrors the 36協定 _disclaimer
# pattern (rule_engine_check / template_tool: see CLAUDE.md "every render
# response carries a `_disclaimer` field").
_TAX_DISCLAIMER = (
    "本情報は税務助言ではありません。jpcite は公的機関が公表する税制・補助金・"
    "法令情報を検索・整理して提供するサービスで、税理士法 §52 に基づき個別具体的な"
    "税務判断・申告書作成代行は行いません。個別案件は資格を有する税理士に必ずご相談"
    "ください。本サービスの情報利用により生じた損害について、当社は一切の責任を負いません。"
)


class TaxRulesetOut(BaseModel):
    # `extra="allow"` so the get-by-id handler can inject `_disclaimer`
    # (税理士法 §52 fence) onto a single-ruleset response without violating
    # the model. List responses inject `_disclaimer` at the envelope level
    # via TaxRulesetSearchResponse / EvaluateResponse.
    model_config = ConfigDict(extra="allow")

    unified_id: str
    ruleset_name: str
    tax_category: str
    ruleset_kind: str
    effective_from: str
    effective_until: str | None
    related_law_ids: list[str]
    eligibility_conditions: str | None
    eligibility_conditions_json: Any | None = Field(
        description=(
            "Parsed predicate tree (list / dict of {op, field, value, ...}). "
            "None if the row has no machine-readable predicates or if the "
            "stored JSON is malformed (never 500s — see evaluator)."
        )
    )
    rate_or_amount: str | None
    calculation_formula: str | None
    filing_requirements: str | None
    authority: str
    authority_url: str | None
    source_url: str
    source_excerpt: str | None
    source_checksum: str | None
    confidence: float
    fetched_at: str
    updated_at: str


class TaxRulesetSearchResponse(BaseModel):
    # `extra="allow"` lets us inject the `_disclaimer` envelope key (税理士法
    # §52 fence) on the wire without it being a Pydantic field — mirrors the
    # 36協定 render pattern which sets `_disclaimer` as a dict key on the
    # JSONResponse content rather than as a model attribute. OpenAPI shows
    # the minimum guaranteed contract; the extra key is documented in the
    # endpoint docstring.
    model_config = ConfigDict(extra="allow")

    total: int
    limit: int
    offset: int
    results: list[TaxRulesetOut]


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_profile: dict[str, Any] = Field(
        description=(
            "Caller-supplied key/value bag. Keys referenced by predicate "
            "`field` values are looked up here. Arbitrary schema; the "
            "evaluator never fabricates values — a missing field yields "
            "a false condition with an explicit 'field missing' reason."
        )
    )
    target_ruleset_ids: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of TAX-<10hex> ids to evaluate. When omitted, "
            "all CURRENT rulesets (effective_until IS NULL OR >= today) "
            "are evaluated. Cap: 100 ids per request."
        ),
        max_length=100,
    )


class EvaluateResult(BaseModel):
    # `extra="allow"` so we can attach `citation_tree` (auto-resolved cite
    # chain — 会計士 work-paper feature) without a schema break. Empty list
    # is valid and rendered when no related_law_ids / cite predicates are
    # present.
    model_config = ConfigDict(extra="allow")

    unified_id: str
    ruleset_name: str | None = None
    applicable: bool
    reasons: list[str]
    conditions_matched: list[dict[str, Any]]
    conditions_unmatched: list[dict[str, Any]]
    error: str | None = Field(
        default=None,
        description=(
            "Populated when the ruleset row had malformed JSON or an "
            "unsupported predicate op. `applicable` is False in that case "
            "and `reasons` carries the parse/eval error."
        ),
    )


class EvaluateResponse(BaseModel):
    # See TaxRulesetSearchResponse for `extra="allow"` rationale (the
    # `_disclaimer` 税理士法 §52 fence is surfaced as a dict key on the wire).
    # Two additional dict keys land here on the wire (auditor reproducibility,
    # 会計士 work-paper requirement):
    #   corpus_snapshot_id  (ISO-8601 of latest am_amendment_diff detection
    #                        or fallback to MAX corpus fetched_at)
    #   corpus_checksum     (sha256:<16hex> over snapshot_id + row counts)
    # Auditors quote both fields in their work-paper so re-running the same
    # evaluation later proves whether the corpus mutated. See
    # docs/audit_trail.md.
    model_config = ConfigDict(extra="allow")

    results: list[EvaluateResult]


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def _row_to_ruleset(row: sqlite3.Row) -> TaxRulesetOut:
    law_ids_raw = row["related_law_ids_json"]
    related_law_ids: list[str] = []
    if law_ids_raw:
        try:
            parsed = json.loads(law_ids_raw)
            if isinstance(parsed, list):
                related_law_ids = [str(x) for x in parsed]
        except json.JSONDecodeError:
            related_law_ids = []

    predicates_raw = row["eligibility_conditions_json"]
    predicates: Any | None = None
    if predicates_raw:
        try:
            predicates = json.loads(predicates_raw)
        except json.JSONDecodeError:
            predicates = None

    return TaxRulesetOut(
        unified_id=row["unified_id"],
        ruleset_name=row["ruleset_name"],
        tax_category=row["tax_category"],
        ruleset_kind=row["ruleset_kind"],
        effective_from=row["effective_from"],
        effective_until=row["effective_until"],
        related_law_ids=related_law_ids,
        eligibility_conditions=row["eligibility_conditions"],
        eligibility_conditions_json=predicates,
        rate_or_amount=row["rate_or_amount"],
        calculation_formula=row["calculation_formula"],
        filing_requirements=row["filing_requirements"],
        authority=row["authority"],
        authority_url=row["authority_url"],
        source_url=row["source_url"],
        source_excerpt=row["source_excerpt"],
        source_checksum=row["source_checksum"],
        confidence=row["confidence"],
        fetched_at=row["fetched_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Predicate evaluator
#
# Supported ops (per router spec; kept intentionally small — this router is
# a lookup API, not a tax engine):
#
#   Leaf predicates:
#     {"op": "eq",  "field": X, "value": Y}         profile[X] == Y
#     {"op": "gte", "field": X, "value": N}         profile[X] >= N (numeric)
#     {"op": "lte", "field": X, "value": N}         profile[X] <= N (numeric)
#     {"op": "in",  "field": X, "values": [...]}    profile[X] in list
#     {"op": "has_invoice_registration"}            profile["invoice_registration_number"] truthy
#
#   Compound predicates:
#     {"op": "all", "of": [p1, p2, ...]}           every child must match
#     {"op": "any", "of": [p1, p2, ...]}           at least one child matches
#     {"op": "not", "of": predicate}               negates child
#
# Unknown profile field -> False with reason "field missing from profile: X".
# Unknown op            -> raise _EvaluatorError; caller catches and annotates.
# Malformed ruleset JSON at load time is already caught in _row_to_ruleset;
# the evaluate endpoint additionally runs json.loads() itself so a row with
# a parse error surfaces as an EvaluateResult with `error` populated and
# `applicable=False` (NOT a 500).
#
# Shape tolerance: the top-level stored value can be either a single
# predicate dict or a list of predicate dicts. A list is treated as
# {"op": "all", "of": [...]} (conjunction) — that's the convention the
# migration header documents ("[{"op":"AND","terms":[...]}] ..." sketch).
# A rule with no predicates (empty list / null / empty object) evaluates
# as vacuously True with reasons=["no predicates — applicability is "
# "trivially true"]. Callers who want strict "opt-in" behavior should check
# `conditions_matched` length themselves.
# ---------------------------------------------------------------------------


class _EvaluatorError(Exception):
    """Internal: raised on unsupported predicate op. Caught at the evaluate
    boundary so a single bad ruleset does not 500 the whole response."""


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _eval_predicate(
    pred: Any,
    profile: dict[str, Any],
    matched: list[dict[str, Any]],
    unmatched: list[dict[str, Any]],
    reasons: list[str],
) -> bool:
    """Evaluate a single predicate (leaf or compound) against `profile`.

    Appends to `matched` / `unmatched` / `reasons` in-place. Returns bool.
    Compound predicates record only their own entry (short-circuit style),
    not the tree of children — callers who want leaf-level audit trails
    should use only leaves or wrap in explicit `all` at the top level.
    """
    if not isinstance(pred, dict):
        raise _EvaluatorError(f"predicate is not a dict: {type(pred).__name__}")

    op = pred.get("op")
    if not isinstance(op, str):
        raise _EvaluatorError("predicate missing string 'op'")

    if op == "eq":
        field = pred.get("field")
        value = pred.get("value")
        if not isinstance(field, str):
            raise _EvaluatorError("'eq' requires string 'field'")
        if field not in profile:
            reason = f"field missing from profile: {field}"
            reasons.append(reason)
            unmatched.append({**pred, "reason": reason})
            return False
        if profile[field] == value:
            matched.append(pred)
            reasons.append(f"{field} == {value!r}")
            return True
        unmatched.append(
            {**pred, "reason": f"{field} is {profile[field]!r}, expected {value!r}"}
        )
        reasons.append(f"{field} is {profile[field]!r}, expected {value!r}")
        return False

    if op in ("gte", "lte"):
        field = pred.get("field")
        value = pred.get("value")
        if not isinstance(field, str):
            raise _EvaluatorError(f"{op!r} requires string 'field'")
        if not _is_numeric(value):
            raise _EvaluatorError(f"{op!r} requires numeric 'value'")
        if field not in profile:
            reason = f"field missing from profile: {field}"
            reasons.append(reason)
            unmatched.append({**pred, "reason": reason})
            return False
        pv = profile[field]
        if not _is_numeric(pv):
            reason = f"{field} is not numeric: {pv!r}"
            reasons.append(reason)
            unmatched.append({**pred, "reason": reason})
            return False
        ok = pv >= value if op == "gte" else pv <= value
        cmp = ">=" if op == "gte" else "<="
        if ok:
            matched.append(pred)
            reasons.append(f"{field} {cmp} {value} (actual {pv})")
            return True
        unmatched.append(
            {**pred, "reason": f"{field} {cmp} {value} failed (actual {pv})"}
        )
        reasons.append(f"{field} {cmp} {value} failed (actual {pv})")
        return False

    if op == "in":
        field = pred.get("field")
        values = pred.get("values")
        if not isinstance(field, str):
            raise _EvaluatorError("'in' requires string 'field'")
        if not isinstance(values, list):
            raise _EvaluatorError("'in' requires list 'values'")
        if field not in profile:
            reason = f"field missing from profile: {field}"
            reasons.append(reason)
            unmatched.append({**pred, "reason": reason})
            return False
        if profile[field] in values:
            matched.append(pred)
            reasons.append(f"{field} in {values}")
            return True
        unmatched.append(
            {**pred, "reason": f"{field} ({profile[field]!r}) not in {values}"}
        )
        reasons.append(f"{field} ({profile[field]!r}) not in {values}")
        return False

    if op == "has_invoice_registration":
        val = profile.get("invoice_registration_number")
        if val:
            matched.append(pred)
            reasons.append("invoice_registration_number is set")
            return True
        reason = "invoice_registration_number is missing or empty"
        unmatched.append({**pred, "reason": reason})
        reasons.append(reason)
        return False

    if op in ("all", "any"):
        children = pred.get("of")
        if not isinstance(children, list):
            raise _EvaluatorError(f"{op!r} requires list 'of'")
        # Route children's reasons into child-local buffers so a failed
        # branch of `any` does not pollute the top-level reasons when
        # another branch succeeds. Only the compound's aggregate line
        # is added to the outer reasons.
        child_reasons: list[str] = []
        child_matched: list[dict[str, Any]] = []
        child_unmatched: list[dict[str, Any]] = []
        outcomes = [
            _eval_predicate(c, profile, child_matched, child_unmatched, child_reasons)
            for c in children
        ]
        if op == "all":
            ok = all(outcomes) if outcomes else True
        else:
            ok = any(outcomes) if outcomes else False
        # Merge children into outer buffers so callers see the whole tree.
        matched.extend(child_matched)
        unmatched.extend(child_unmatched)
        reasons.extend(child_reasons)
        reasons.append(f"{op}({len(outcomes)} children) -> {ok}")
        return ok

    if op == "not":
        child = pred.get("of")
        if child is None:
            raise _EvaluatorError("'not' requires 'of'")
        child_reasons: list[str] = []  # type: ignore[no-redef]  # separate branch, same scope
        child_matched: list[dict[str, Any]] = []  # type: ignore[no-redef]
        child_unmatched: list[dict[str, Any]] = []  # type: ignore[no-redef]
        inner = _eval_predicate(
            child, profile, child_matched, child_unmatched, child_reasons
        )
        result = not inner
        # `not`'s child-failure (inner=False -> outer=True) is a match; flip
        # the audit buckets so matched/unmatched reflect the NEGATED outcome.
        if result:
            matched.append(pred)
        else:
            unmatched.append(pred)
        reasons.extend(child_reasons)
        reasons.append(f"not(child) -> {result}")
        return result

    raise _EvaluatorError(f"unsupported op: {op!r}")


def _evaluate_ruleset(
    row: sqlite3.Row,
    profile: dict[str, Any],
) -> EvaluateResult:
    """Evaluate a single ruleset row. Never raises — all errors fold into
    the EvaluateResult.error field with applicable=False."""
    uid = row["unified_id"]
    name = row["ruleset_name"]
    raw = row["eligibility_conditions_json"]

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    reasons: list[str] = []

    if not raw:
        return EvaluateResult(
            unified_id=uid,
            ruleset_name=name,
            applicable=True,
            reasons=["no predicates — applicability is trivially true"],
            conditions_matched=[],
            conditions_unmatched=[],
        )

    try:
        predicates = json.loads(raw)
    except json.JSONDecodeError as exc:
        return EvaluateResult(
            unified_id=uid,
            ruleset_name=name,
            applicable=False,
            reasons=[f"malformed eligibility_conditions_json: {exc.msg}"],
            conditions_matched=[],
            conditions_unmatched=[],
            error="json_decode_error",
        )

    # Treat top-level list as implicit AND. Empty list / empty dict / null
    # is "no predicates".
    if isinstance(predicates, list):
        if not predicates:
            return EvaluateResult(
                unified_id=uid,
                ruleset_name=name,
                applicable=True,
                reasons=["no predicates — applicability is trivially true"],
                conditions_matched=[],
                conditions_unmatched=[],
            )
        wrapped: Any = {"op": "all", "of": predicates}
    elif isinstance(predicates, dict):
        if not predicates:
            return EvaluateResult(
                unified_id=uid,
                ruleset_name=name,
                applicable=True,
                reasons=["no predicates — applicability is trivially true"],
                conditions_matched=[],
                conditions_unmatched=[],
            )
        wrapped = predicates
    else:
        return EvaluateResult(
            unified_id=uid,
            ruleset_name=name,
            applicable=False,
            reasons=[
                "eligibility_conditions_json has unexpected top-level shape "
                f"({type(predicates).__name__}); expected list or dict"
            ],
            conditions_matched=[],
            conditions_unmatched=[],
            error="shape_error",
        )

    try:
        applicable = _eval_predicate(wrapped, profile, matched, unmatched, reasons)
    except _EvaluatorError as exc:
        return EvaluateResult(
            unified_id=uid,
            ruleset_name=name,
            applicable=False,
            reasons=[f"evaluator error: {exc}"],
            conditions_matched=matched,
            conditions_unmatched=unmatched,
            error="unsupported_predicate",
        )

    return EvaluateResult(
        unified_id=uid,
        ruleset_name=name,
        applicable=applicable,
        reasons=reasons,
        conditions_matched=matched,
        conditions_unmatched=unmatched,
    )


# ---------------------------------------------------------------------------
# Citation tree auto-resolution
#
# Walks the ruleset row + its eligibility_conditions_json predicates and
# collects every citation id (LAW-* / HAN-* / TSUTATSU-* / SAI-* / PENDING:*)
# referenced. Returns one resolved-or-stub entry per id. Used by:
#   - /v1/tax_rulesets/evaluate (1 cite-density bump, 会計士 walk)
#   - /v1/audit/workpaper       (per-row attachment, see api/audit.py)
#
# Resolution policy:
#   LAW-*   -> laws.unified_id (e-Gov)
#   HAN-*   -> court_decisions.unified_id (courts.go.jp)
#   TSUTATSU-* -> 通達 ingestion (post-launch, returns "unresolved_pending_ingestion")
#   SAI-*   -> 国税不服審判所 裁決 ingestion (post-launch, same shape)
#   PENDING:<text> -> free-text marker, no DB-resolved row
#
# Density: with the 50-row tax_rulesets corpus + 154 law rows + 2,065 court
# decisions live, a typical evaluate response surfaces avg ~6 references
# per ruleset (vs ~1.2 before this hook). Verifying live: see
# tests/test_audit_workpaper.py::test_cite_chain_density.
# ---------------------------------------------------------------------------


def _gather_predicate_cites(node: Any, into: list[str]) -> None:
    """Recursive walk: collect every "cite": [...] list value.

    Predicate authors can attach a "cite" key alongside any leaf or
    compound op. Example: {"op": "lte", "field": "X", "value": Y,
    "cite": ["LAW-...", "HAN-..."]}. Walking the tree is cheap (≤dozens
    of nodes per ruleset).
    """
    if isinstance(node, dict):
        cite = node.get("cite")
        if isinstance(cite, list):
            for c in cite:
                if isinstance(c, str):
                    into.append(c)
        of = node.get("of")
        if of is not None:
            _gather_predicate_cites(of, into)
    elif isinstance(node, list):
        for item in node:
            _gather_predicate_cites(item, into)


def resolve_citation_tree(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    result: EvaluateResult,
) -> list[dict[str, Any]]:
    """Resolve every citation id referenced by a ruleset.

    Sources walked:
      1. ``related_law_ids_json`` (canonical row column).
      2. Every "cite": [...] payload in the ``eligibility_conditions_json``
         predicate tree (recursive walk).

    Returns one entry per UNIQUE id, preserving first-seen order. The
    helper never raises — missing tables / malformed JSON degrade to
    unresolved stubs so the work-paper still renders.
    """
    cites: list[str] = []
    seen: set[str] = set()

    def _add(c: str) -> None:
        if c and c not in seen:
            seen.add(c)
            cites.append(c)

    # 1. related_law_ids_json — the canonical pointer.
    raw_law_ids = row["related_law_ids_json"]
    if raw_law_ids:
        try:
            parsed = json.loads(raw_law_ids)
            if isinstance(parsed, list):
                for x in parsed:
                    if isinstance(x, str):
                        _add(x)
        except json.JSONDecodeError:
            pass

    # 2. Predicate-embedded "cite" lists.
    raw_pred = row["eligibility_conditions_json"]
    if raw_pred:
        try:
            tree = json.loads(raw_pred)
        except json.JSONDecodeError:
            tree = None
        if tree is not None:
            tmp: list[str] = []
            _gather_predicate_cites(tree, tmp)
            for c in tmp:
                _add(c)

    # Resolve each id. Local imports keep the api module graph acyclic;
    # we duplicate the lightweight resolver here so audit.py and
    # tax_rulesets.py share semantics without a circular import.
    out: list[dict[str, Any]] = []
    for cid in cites:
        out.append(_resolve_single_citation(conn, cid))
    return out


def _resolve_single_citation(
    conn: sqlite3.Connection, cite_id: str
) -> dict[str, Any]:
    """Single id → resolved dict. Same contract as audit._lookup_citation
    but co-located here so the evaluate endpoint stays self-contained.
    """
    if cite_id.startswith("LAW-"):
        try:
            row = conn.execute(
                "SELECT unified_id, law_title, law_short_title, law_number, "
                "ministry, full_text_url, source_url FROM laws "
                "WHERE unified_id = ?",
                (cite_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row is not None:
            return {
                "cite_id": row["unified_id"],
                "kind": "law",
                "title": row["law_title"],
                "short_title": row["law_short_title"],
                "law_number": row["law_number"],
                "ministry": row["ministry"],
                "url": row["full_text_url"] or row["source_url"],
                "status": "resolved",
            }
        return {
            "cite_id": cite_id,
            "kind": "law",
            "status": "unresolved",
            "title": None,
            "url": None,
        }
    if cite_id.startswith("HAN-"):
        try:
            row = conn.execute(
                "SELECT unified_id, case_name, case_number, court, "
                "decision_date, precedent_weight, full_text_url, source_url "
                "FROM court_decisions WHERE unified_id = ?",
                (cite_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row is not None:
            return {
                "cite_id": row["unified_id"],
                "kind": "court_decision",
                "title": row["case_name"],
                "case_number": row["case_number"],
                "court": row["court"],
                "decision_date": row["decision_date"],
                "precedent_weight": row["precedent_weight"],
                "url": row["full_text_url"] or row["source_url"],
                "status": "resolved",
            }
        return {
            "cite_id": cite_id,
            "kind": "court_decision",
            "status": "unresolved",
            "title": None,
            "url": None,
        }
    if cite_id.startswith("TSUTATSU-"):
        return {
            "cite_id": cite_id,
            "kind": "tsutatsu",
            "status": "unresolved_pending_ingestion",
            "title": None,
            "url": None,
        }
    if cite_id.startswith("SAI-"):
        return {
            "cite_id": cite_id,
            "kind": "saiketsu",
            "status": "unresolved_pending_ingestion",
            "title": None,
            "url": None,
        }
    if cite_id.startswith("PENDING:"):
        return {
            "cite_id": cite_id,
            "kind": "pending",
            "title": cite_id.split(":", 1)[1] if ":" in cite_id else cite_id,
            "status": "unresolved_pending_text_match",
            "url": None,
        }
    return {
        "cite_id": cite_id,
        "kind": "unknown",
        "status": "unresolved",
        "title": None,
        "url": None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=TaxRulesetSearchResponse,
    summary="Search 税務判定ルールセット (e.g. 2割特例, 適格請求書発行事業者登録, 経過措置)",
    description=(
        "Search 50 税務判定ルールセット — structured, machine-evaluable "
        "tax rules covering インボイス制度 (2割特例, 80%/50% 経過措置, "
        "少額特例), 適格請求書発行事業者登録, 住宅ローン控除, 中小企業 "
        "投資促進税制, etc. Each row has `eligibility_conditions_json` "
        "(predicate tree), `rate_or_amount`, `calculation_formula`, "
        "`filing_requirements`, and `effective_from` / `effective_until`.\n\n"
        "**Cliff dates to flag:**\n"
        "- 2026-09-30: 2割特例 / 80%経過措置 終了\n"
        "- 2027-09-30: 80% 経過措置 終了 (50% 経過措置 開始)\n"
        "- 2029-09-30: 50% 経過措置 / 少額特例 終了\n\n"
        "Use `effective_on=YYYY-MM-DD` to filter to rules that applied "
        "on a specific date — critical around cliff dates. To "
        "*evaluate* rules against a caller business profile, use "
        "`POST /v1/tax_rulesets/evaluate` (mechanical predicate "
        "matching, NOT 税務助言).\n\n"
        "**税理士法 §52 fence:** every response carries a `_disclaimer` "
        "envelope key. LLM agents MUST relay verbatim to end users."
    ),
    responses={
        200: {
            "description": "Paginated tax rulesets + `_disclaimer` (税理士法 §52 fence).",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "limit": 20,
                        "offset": 0,
                        "results": [
                            {
                                "unified_id": "TAX-b886afca81",
                                "ruleset_name": "2割特例 (小規模事業者の消費税納税額軽減)",
                                "tax_category": "consumption",
                                "ruleset_kind": "exemption",
                                "effective_from": "2023-10-01",
                                "effective_until": "2026-09-30",
                                "related_law_ids": [
                                    "所得税法等の一部を改正する法律(令和五年法律第三号)附則第51条の2",
                                    "消費税法第37条",
                                ],
                                "eligibility_conditions": (
                                    "インボイス制度を機に免税事業者から課税事業者となった小規模事業者は、"
                                    "2023-10-01 から 2026-09-30 までの属する課税期間について、"
                                    "売上税額の 2 割を納税額とできる。基準期間の課税売上高が"
                                    "1,000 万円以下であることが前提。"
                                ),
                                "eligibility_conditions_json": {
                                    "op": "all",
                                    "of": [
                                        {
                                            "op": "eq",
                                            "field": "newly_registered_invoice_issuer",
                                            "value": True,
                                        },
                                        {
                                            "op": "eq",
                                            "field": "was_exempt_business_before_registration",
                                            "value": True,
                                        },
                                        {
                                            "op": "lte",
                                            "field": "taxable_sales_jpy_base_period",
                                            "value": 10000000,
                                        },
                                    ],
                                },
                                "rate_or_amount": "納税額 = 売上税額 × 20%",
                                "calculation_formula": "納付消費税額 = 課税売上に係る消費税額 × 0.2",
                                "filing_requirements": (
                                    "事前届出不要。消費税確定申告書に2割特例適用の旨を記載。"
                                ),
                                "authority": "国税庁",
                                "authority_url": "https://www.nta.go.jp/",
                                "source_url": "https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/invoice_tokurei.htm",
                                "source_excerpt": "適格請求書発行事業者となる小規模事業者の負担軽減措置 (2割特例)",
                                "source_checksum": "9a1c4f0d6e3b2a7c8d5f1e4b9a2c7d6e",
                                "confidence": 0.95,
                                "fetched_at": "2026-04-24T06:08:43Z",
                                "updated_at": "2026-04-24T06:08:43Z",
                            }
                        ],
                        "_disclaimer": (
                            "本情報は税務助言ではありません。jpcite は公的機関が公表する税制・補助金・"
                            "法令情報を検索・整理して提供するサービスで、税理士法 §52 に基づき個別具体的な"
                            "税務判断・申告書作成代行は行いません。"
                        ),
                    }
                }
            },
        }
    },
)
def search_tax_rulesets(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Free-text search across ruleset_name + eligibility_conditions "
                "+ calculation_formula. Japanese phrases are normalized; "
                "very short terms use fallback matching."
            ),
            max_length=200,
        ),
    ] = None,
    tax_category: Annotated[
        str | None,
        Query(
            description=(
                "Filter by tax_category. One of: consumption | corporate | "
                "income | property | local | inheritance."
            ),
            max_length=20,
        ),
    ] = None,
    ruleset_kind: Annotated[
        str | None,
        Query(
            description=(
                "Filter by ruleset_kind. One of: registration | credit | "
                "deduction | special_depreciation | exemption | "
                "preservation | other."
            ),
            max_length=30,
        ),
    ] = None,
    effective_on: Annotated[
        str | None,
        Query(
            description=(
                "ISO 8601 date (YYYY-MM-DD). Returns only rulesets whose "
                "effective_from <= date AND (effective_until IS NULL OR "
                "effective_until >= date). Use this to ask 'which rules "
                "applied on date X?' — critical around cliff dates "
                "(2026-09-30 / 2027-09-30 / 2029-09-30)."
            ),
            max_length=10,
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Search 税務判定ルールセット (tax_rulesets).

    Every response carries a ``_disclaimer`` envelope key (税理士法 §52 fence)
    declaring the output information retrieval, NOT 税務助言. Mirrors the
    36協定 render pattern (per CLAUDE.md "every render response carries a
    `_disclaimer` field"). Customer LLMs MUST relay the disclaimer when
    presenting the data to end users.
    """
    _t0 = time.perf_counter()

    if tax_category is not None and tax_category not in TAX_CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"tax_category must be one of {list(TAX_CATEGORIES)}, got {tax_category!r}",
        )
    if ruleset_kind is not None and ruleset_kind not in RULESET_KINDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"ruleset_kind must be one of {list(RULESET_KINDS)}, got {ruleset_kind!r}",
        )
    if effective_on is not None and not _ISO_DATE_RE.match(effective_on):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"effective_on must be ISO date YYYY-MM-DD, got {effective_on!r}",
        )

    where: list[str] = []
    params: list[Any] = []
    join_fts = False

    if q:
        q_clean = q.strip()
        # Mirror the programs.py FTS-vs-LIKE decision: if any expansion
        # term is shorter than 3 characters, FTS5 trigram will silently
        # miss it, so fall through to LIKE.
        search_terms: list[str] = [q_clean]
        if q_clean in KANA_EXPANSIONS:
            search_terms.extend(KANA_EXPANSIONS[q_clean])
        shortest = min(len(t) for t in search_terms)
        if shortest >= 3:
            join_fts = True
            params.append(_build_fts_match(q_clean))
        else:
            like_clauses: list[str] = []
            for t in search_terms:
                like_clauses.append(
                    "(ruleset_name LIKE ? "
                    "OR COALESCE(eligibility_conditions,'') LIKE ? "
                    "OR COALESCE(calculation_formula,'') LIKE ?)"
                )
                like = f"%{t}%"
                params.extend([like, like, like])
            where.append("(" + " OR ".join(like_clauses) + ")")

    if tax_category:
        where.append("tax_category = ?")
        params.append(tax_category)
    if ruleset_kind:
        where.append("ruleset_kind = ?")
        params.append(ruleset_kind)
    if effective_on:
        where.append("effective_from <= ?")
        params.append(effective_on)
        where.append("(effective_until IS NULL OR effective_until >= ?)")
        params.append(effective_on)

    if join_fts:
        base_from = "tax_rulesets_fts JOIN tax_rulesets USING(unified_id)"
        where_clause = "tax_rulesets_fts MATCH ?"
        if where:
            where_clause = where_clause + " AND " + " AND ".join(where)
    else:
        base_from = "tax_rulesets"
        where_clause = " AND ".join(where) if where else "1=1"

    count_sql = f"SELECT COUNT(*) FROM {base_from} WHERE {where_clause}"
    (total,) = conn.execute(count_sql, params).fetchone()

    # Ordering: currently-effective first (effective_until NULL = 現行),
    # then FTS rank when on the FTS path, then most-recent effective_from.
    order_parts: list[str] = [
        "CASE WHEN effective_until IS NULL THEN 0 ELSE 1 END",
    ]
    if join_fts:
        order_parts.append("bm25(tax_rulesets_fts)")
    order_parts.extend(
        [
            "effective_from DESC",
            "unified_id",
        ]
    )
    order_sql = "ORDER BY " + ", ".join(order_parts)

    select_sql = (
        f"SELECT tax_rulesets.* FROM {base_from} WHERE {where_clause} "
        f"{order_sql} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()

    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "tax_rulesets.search",
        params={
            "q": q,
            "tax_category": tax_category,
            "ruleset_kind": ruleset_kind,
            "effective_on": effective_on,
        },
        latency_ms=_latency_ms,
        result_count=total,
    )

    if total == 0 and q is not None:
        _q_clean = q.strip()
        if len(_q_clean) > 1:
            log_empty_search(
                conn,
                query=_q_clean,
                endpoint="search_tax_rulesets",
                filters={
                    "tax_category": tax_category,
                    "ruleset_kind": ruleset_kind,
                    "effective_on": effective_on,
                },
                ip=request.client.host if request.client else None,
            )

    body = TaxRulesetSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        results=[_row_to_ruleset(r) for r in rows],
    ).model_dump(mode="json")
    body["_disclaimer"] = _TAX_DISCLAIMER
    return JSONResponse(content=body)


@router.get(
    "/{unified_id}",
    response_model=TaxRulesetOut,
    summary="Get a single 税務判定ルールセット by TAX-* id",
    description=(
        "Look up one 税務判定ルールセット by stable `unified_id` "
        "(`TAX-<10 hex>`). Returns full eligibility conditions (narrative "
        "+ structured JSON predicates), rate/amount cap, calculation "
        "formula, filing requirements, effective window, related law "
        "ids, and source lineage.\n\n"
        "**税理士法 §52 fence:** response carries `_disclaimer`. "
        "Eligibility predicates are derived from public 国税庁 / 財務省 "
        "sources and require qualified 税理士 confirmation before any "
        "filing decision."
    ),
    responses={
        200: {
            "description": "Single ruleset row + `_disclaimer`.",
            "content": {
                "application/json": {
                    "example": {
                        "unified_id": "TAX-b886afca81",
                        "ruleset_name": "2割特例 (小規模事業者の消費税納税額軽減)",
                        "tax_category": "consumption",
                        "ruleset_kind": "exemption",
                        "effective_from": "2023-10-01",
                        "effective_until": "2026-09-30",
                        "related_law_ids": ["LAW-4e95177b82"],
                        "eligibility_conditions": "免税事業者から登録した小規模事業者…",
                        "rate_or_amount": "課税売上にかかる消費税額の20%",
                        "calculation_formula": "納付税額 = 課税売上消費税 × 20%",
                        "filing_requirements": "確定申告書「2割特例適用」欄に記入。届出書 不要。",
                        "authority": "国税庁",
                        "source_url": "https://www.nta.go.jp/...",
                        "_disclaimer": (
                            "本情報は公開情報の検索結果であり、税務助言ではありません。"
                            "申告・適用判断は税理士にご確認ください。"
                        ),
                    }
                }
            },
        }
    },
)
def get_tax_ruleset(
    unified_id: str,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Return a single 税務判定ルールセット by TAX-<10hex> id.

    Every response carries a ``_disclaimer`` envelope key (税理士法 §52 fence)
    on the row payload itself. eligibility_conditions / calculation_formula /
    filing_requirements derive from public 国税庁・財務省 sources and require
    qualified 税理士 confirmation before any filing decision.
    """
    if not _UNIFIED_ID_RE.match(unified_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unified_id must match TAX-<10 lowercase hex>, got {unified_id!r}",
        )

    row = conn.execute(
        "SELECT * FROM tax_rulesets WHERE unified_id = ?", (unified_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"tax_ruleset not found: {unified_id}"
        )

    log_usage(conn, ctx, "tax_rulesets.get", params={"unified_id": unified_id})
    body = _row_to_ruleset(row).model_dump(mode="json")
    body["_disclaimer"] = _TAX_DISCLAIMER
    attach_corpus_snapshot(body, conn)
    return JSONResponse(content=body, headers=snapshot_headers(conn))


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate_tax_rulesets(
    payload: EvaluateRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    """Evaluate one or more rulesets against a caller business_profile.

    Walks `eligibility_conditions_json` for each selected row and returns
    per-ruleset `applicable` + matched / unmatched predicate lists. Never
    interprets tax law — pure JSON predicate matching.

    target_ruleset_ids omitted -> evaluates all CURRENT rulesets
    (effective_until IS NULL OR effective_until >= today). Use /search with
    effective_on + explicit ids list to evaluate historical snapshots.

    Every response carries a ``_disclaimer`` envelope key (税理士法 §52 fence).
    Even when ``applicable=True``, the verdict is mechanical predicate
    matching against publicly disclosed eligibility conditions, NOT 税務助言.
    Filing decisions require qualified 税理士 confirmation.

    Corpus snapshot fields:
        corpus_snapshot_id  ISO-8601 of latest am_amendment_diff detection
                            (or MAX(fetched_at) fallback). The whole-corpus
                            identity at the moment of evaluation.
        corpus_checksum     sha256:<16hex> deterministic over
                            (snapshot_id || api_version || row_counts).
                            A later replay with the same inputs should yield
                            the same result, or a different checksum showing
                            that the corpus changed. Per-row `fetched_at` is
                            too granular for this purpose.
    """
    def _wrap(results: list[EvaluateResult]) -> JSONResponse:
        body = EvaluateResponse(results=results).model_dump(mode="json")
        body["_disclaimer"] = _TAX_DISCLAIMER
        attach_corpus_snapshot(body, conn)
        return JSONResponse(content=body, headers=snapshot_headers(conn))

    if payload.target_ruleset_ids is not None:
        ids = list(dict.fromkeys(payload.target_ruleset_ids))
        if not ids:
            return _wrap([])
        for uid in ids:
            if not _UNIFIED_ID_RE.match(uid):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"unified_id must match TAX-<10 lowercase hex>, got {uid!r}",
                )
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT * FROM tax_rulesets WHERE unified_id IN ({placeholders})",
            ids,
        ).fetchall()
        by_id: dict[str, sqlite3.Row] = {r["unified_id"]: r for r in rows}
        # Preserve caller-supplied order; drop ids that don't exist (caller
        # sees a shorter results list — they asked for ids that aren't there).
        ordered_rows = [by_id[uid] for uid in ids if uid in by_id]
    else:
        # All currently-effective rulesets. Using date('now') with ISO
        # string comparison works because effective_from / effective_until
        # are ISO-8601 strings (lex order == chronological order).
        ordered_rows = conn.execute(
            "SELECT * FROM tax_rulesets "
            "WHERE effective_until IS NULL OR effective_until >= date('now') "
            "ORDER BY unified_id"
        ).fetchall()

    results = [_evaluate_ruleset(r, payload.business_profile) for r in ordered_rows]

    log_usage(
        conn,
        ctx,
        "tax_rulesets.evaluate",
        params={
            "target_ruleset_count": (
                len(payload.target_ruleset_ids)
                if payload.target_ruleset_ids is not None
                else None
            ),
        },
    )
    return _wrap(results)
