"""Generic intake validation MCP tool.

Surfaces the ``validate`` tool which evaluates ``am_validation_rule`` rows
(migration 047) against a caller-supplied ``applicant_data`` dict. The
backing ruleset is currently the 6 generic ``python_dispatch`` predicates
ported from ``autonomath.intake_consistency_rules`` (training_hours /
work_days / weekly_hours / start_year / birth_age / desired_amount sanity).

Why local re-implementation
---------------------------
``predicate_ref`` is shaped ``autonomath.intake.<func_name>`` but jpintel-mcp
must not import the Autonomath package (separate repo + license boundary).
Each generic predicate is therefore re-implemented in
``jpintel_mcp.api._validation_predicates`` as a tiny pure function. When a
rule's predicate_ref does NOT resolve in that registry the result row
carries ``passed=None`` and a ``message_ja`` flag pointing the agent at
the jpcite operator workflow.

Idempotency
-----------
``am_validation_result`` has a ``UNIQUE(rule_id, entity_id, applicant_hash)``
constraint. We compute ``applicant_hash = sha256(canonical_json(applicant_data))``
and ``INSERT OR IGNORE``. A SELECT-first cache lookup short-circuits the
predicate call when the same (rule_id, entity_id, applicant_hash) tuple
has already been evaluated — saves recomputing for repeated calls and keeps
``evaluated_at`` stable for audit.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import sqlite3
from typing import Annotated, Any, cast

from pydantic import Field

from jpintel_mcp.api._validation_predicates import resolve_predicate
from jpintel_mcp.mcp.server import _READ_ONLY, _with_mcp_telemetry, mcp

from .db import AUTONOMATH_DB_PATH, connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.validation")

_DEFERRED_MESSAGE_JA = "external dispatch deferred — use jpcite operator workflow"


def _canonical_applicant_hash(applicant_data: dict[str, Any]) -> str:
    """Return the lower-hex sha256 of canonical JSON of ``applicant_data``.

    Sort keys + ``ensure_ascii=False`` so unicode payloads are stable. Used
    for the UNIQUE-constraint-safe key into ``am_validation_result``.
    """
    payload = json.dumps(
        applicant_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _open_writable_validation_conn() -> sqlite3.Connection:
    """Open a writable autonomath.db connection just for am_validation_result.

    The shared per-thread RO connection from ``connect_autonomath()`` cannot
    be used because it sets ``query_only=1``. We open a separate short-lived
    rwc-mode connection scoped to a single insert; callers must close it.
    """
    uri = f"file:{AUTONOMATH_DB_PATH}?mode=rw"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=10.0,
        check_same_thread=True,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _select_applicable_rules(
    conn: sqlite3.Connection,
    scope: str,
    entity_id: str | None,
) -> list[sqlite3.Row]:
    """Return active rules matching ``scope`` (intake / applicant / global ...).

    When ``entity_id`` is provided, also include rules pinned to that entity
    via ``scope_entity_id``. ``effective_from`` / ``effective_until`` are
    respected against today's date.
    """
    sql = (
        "SELECT rule_id, applies_to, scope, predicate_kind, predicate_ref, "
        "       severity, message_ja, scope_entity_id "
        "  FROM am_validation_rule "
        " WHERE active = 1 "
        "   AND (applies_to = ? OR ? = 'intake') "
        "   AND (effective_from IS NULL OR effective_from <= date('now')) "
        "   AND (effective_until IS NULL OR effective_until >= date('now')) "
        "   AND (scope_entity_id IS NULL OR scope_entity_id = ?) "
        " ORDER BY rule_id"
    )
    return conn.execute(sql, (scope, scope, entity_id)).fetchall()


def _lookup_cached_result(
    conn: sqlite3.Connection,
    rule_id: int,
    entity_id: str | None,
    applicant_hash: str,
) -> sqlite3.Row | None:
    """Return the most recent cached evaluation row for this (rule, entity, hash)."""
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            "SELECT passed, message_ja, evaluated_at "
            "  FROM am_validation_result "
            " WHERE rule_id = ? "
            "   AND ((entity_id IS NULL AND ? IS NULL) OR entity_id = ?) "
            "   AND applicant_hash = ? "
            " LIMIT 1",
            (rule_id, entity_id, entity_id, applicant_hash),
        ).fetchone(),
    )


def _evaluate_one(
    rule: sqlite3.Row,
    applicant_data: dict[str, Any],
) -> tuple[bool | None, str]:
    """Run a single rule against the applicant data.

    Returns ``(passed, message_ja)`` where ``passed`` is:
      * ``True``  — predicate evaluated and reported no violation
      * ``False`` — predicate evaluated and reported a violation
      * ``None``  — predicate could not be evaluated locally (deferred to
                    jpcite operator workflow) or kind is non-python
    """
    kind = rule["predicate_kind"]
    ref = rule["predicate_ref"]
    rule_msg = rule["message_ja"]

    if kind == "python_dispatch":
        fn = resolve_predicate(ref)
        if fn is None:
            return None, _DEFERRED_MESSAGE_JA
        try:
            passed = bool(fn(applicant_data))
        except Exception as exc:  # noqa: BLE001 — surface as deferred, not crash
            logger.warning(
                "validation predicate %s raised %s: %s",
                ref,
                type(exc).__name__,
                exc,
            )
            return None, f"predicate raised {type(exc).__name__}"
        return passed, ("" if passed else (rule_msg or ""))

    if kind == "sql_expr":
        # V1 stub — no rules currently use this kind (count = 0).
        return None, "sql_expr predicate kind not yet implemented"

    if kind == "json_logic":
        # V1 stub — no rules currently use this kind (count = 0).
        return None, "json_logic predicate kind not yet implemented"

    return None, f"unknown predicate_kind: {kind}"


def _persist_result(
    rule_id: int,
    entity_id: str | None,
    applicant_hash: str,
    passed: bool | None,
    message_ja: str,
) -> None:
    """INSERT OR IGNORE the evaluation. ``passed=None`` skips persistence
    because ``am_validation_result.passed`` is NOT NULL — deferred rows are
    never written.
    """
    if passed is None:
        return
    try:
        conn = _open_writable_validation_conn()
    except sqlite3.OperationalError as exc:
        logger.warning("validation result write skipped (open failed): %s", exc)
        return
    try:
        conn.execute(
            "INSERT OR IGNORE INTO am_validation_result "
            "  (rule_id, entity_id, applicant_hash, passed, message_ja) "
            "VALUES (?, ?, ?, ?, ?)",
            (rule_id, entity_id, applicant_hash, 1 if passed else 0, message_ja),
        )
    except sqlite3.OperationalError as exc:
        logger.warning("validation result INSERT failed rule_id=%s: %s", rule_id, exc)
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _validate_impl(
    applicant_data: dict[str, Any],
    entity_id: str | None,
    scope: str,
) -> dict[str, Any]:
    """Shared implementation used by both the MCP tool and the REST route."""
    if not isinstance(applicant_data, dict):
        return {
            "total": 0,
            "results": [],
            **make_error(
                code="missing_required_arg",
                message="applicant_data must be a JSON object",
                hint="Pass a dict like {'plan': {...}, 'identity': {...}}.",
                field="applicant_data",
            ),
        }

    applicant_hash = _canonical_applicant_hash(applicant_data)

    try:
        ro_conn = connect_autonomath()
    except (FileNotFoundError, sqlite3.OperationalError) as exc:
        return {
            "total": 0,
            "results": [],
            **make_error(
                code="db_unavailable",
                message=f"autonomath.db unreachable: {exc}",
                hint="Verify AUTONOMATH_DB_PATH and migration 047 application.",
            ),
        }

    rules = _select_applicable_rules(ro_conn, scope, entity_id)
    results: list[dict[str, Any]] = []
    for rule in rules:
        rule_id = int(rule["rule_id"])
        cached = _lookup_cached_result(ro_conn, rule_id, entity_id, applicant_hash)
        if cached is not None:
            cached_passed = cached["passed"]
            results.append(
                {
                    "rule_id": rule_id,
                    "predicate_ref": rule["predicate_ref"],
                    "predicate_kind": rule["predicate_kind"],
                    "passed": bool(cached_passed) if cached_passed is not None else None,
                    "severity": rule["severity"],
                    "message_ja": cached["message_ja"] or "",
                    "evaluated_at": cached["evaluated_at"],
                    "cached": True,
                }
            )
            continue

        passed, msg = _evaluate_one(rule, applicant_data)
        _persist_result(rule_id, entity_id, applicant_hash, passed, msg)
        results.append(
            {
                "rule_id": rule_id,
                "predicate_ref": rule["predicate_ref"],
                "predicate_kind": rule["predicate_kind"],
                "passed": passed,
                "severity": rule["severity"],
                "message_ja": msg,
                "evaluated_at": None,
                "cached": False,
            }
        )

    # Summary counts let the LLM scan a single header instead of re-walking results.
    n_pass = sum(1 for r in results if r["passed"] is True)
    n_fail = sum(1 for r in results if r["passed"] is False)
    n_deferred = sum(1 for r in results if r["passed"] is None)

    return {
        "total": len(results),
        "applicant_hash": applicant_hash,
        "scope": scope,
        "entity_id": entity_id,
        "summary": {
            "passed": n_pass,
            "failed": n_fail,
            "deferred": n_deferred,
        },
        "results": results,
    }


@mcp.tool(annotations=_READ_ONLY)
@_with_mcp_telemetry
def validate(
    applicant_data: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Applicant intake dict. Nested object, e.g. {'plan': {...}, "
                "'identity': {...}, 'behavioral': {...}}. Hashed for caching."
            )
        ),
    ],
    entity_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional am_entities.canonical_id this applicant_data is "
                "scoped to (e.g. a specific program). Filters rules pinned "
                "via scope_entity_id and is part of the result cache key."
            ),
        ),
    ] = None,
    scope: Annotated[
        str,
        Field(
            default="intake",
            description=(
                "Rule applies_to scope. Default 'intake' selects the configured "
                "generic validation predicates."
            ),
        ),
    ] = "intake",
) -> dict[str, Any]:
    """[VALIDATE] applicant_data を am_validation_rule の active 述語で評価し、
    rule 単位の passed/failed/deferred を返す (deferred = jpcite で評価できない外部依存述語).

    WHAT:
      ``am_validation_rule`` の active=1 / effective window 有効 / scope 適合 rule を選び、
      python_dispatch 述語のうち既知の intake validation 述語はローカル実装で評価、
      それ以外 (sql_expr / json_logic / 未登録 dispatch) は ``passed=null`` で deferred 返却。
      評価結果は ``am_validation_result`` に ``INSERT OR IGNORE``、同 (rule, entity, applicant_hash)
      は SELECT-first で cache 返却。

    WHEN:
      - LLM が "この applicant_data に sanity 違反がないか" 一括 check したい
      - 画面やワークフローに出す前段で training_hours/work_days/weekly_hours の桁ミス除去
      - 申請額 50 億超 / 開始年 ±20/+10 範囲外 / 生年-自己申告年齢 1y 以上ずれ の検出

    WHEN NOT:
      - 制度個別の eligibility 判定 → check_exclusions / search_programs
      - 文書粒度の fact-check → 別 tool
      - sql_expr / json_logic 述語が登録されたら本 tool では deferred 返却

    RETURNS (envelope):
      {
        total: int,
        applicant_hash: str,
        scope: str,
        entity_id: str | null,
        summary: { passed: int, failed: int, deferred: int },
        results: [
          {
            rule_id: int,
            predicate_ref: str,
            predicate_kind: 'python_dispatch' | 'sql_expr' | 'json_logic',
            passed: true | false | null,
            severity: 'info' | 'warning' | 'critical',
            message_ja: str,
            evaluated_at: str | null,
            cached: bool,
          }, ...
        ]
      }
    """
    return _validate_impl(applicant_data, entity_id, scope)


__all__ = ["_validate_impl", "validate"]
