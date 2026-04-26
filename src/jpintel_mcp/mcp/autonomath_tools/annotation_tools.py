"""get_annotations — V4 Phase 4 universal MCP tool (2026-04-25).

Returns rows from ``am_entity_annotation`` (created via migration 046) for a
given ``am_entities.canonical_id``. Generic across the polymorphic kind set
(currently 3 ingested: examiner_warning / quality_score / examiner_correction;
the lookup table seeds 6 kinds total). Designed so future kinds — validation
failures, ML inferences, manual notes — surface through the same call with no
schema or signature change.

Why this is a separate tool (not a view inside an existing search_*):
  * The annotation surface is cross-domain — examiner feedback hits programs,
    case_studies, certifications uniformly. Folding it into 16 per-domain
    tools would require N copies of the same join logic.
  * Customer LLMs that already have an entity_id (from search_programs etc.)
    can fan out a single follow-up call instead of re-searching.

Visibility model (mirrors migration 046 docstring):
  * default → ``visibility='public'`` only. The 16,474 currently ingested rows
    are all 'internal', so the default returns 0 results — by design.
    ``include_internal=True`` flips to public+internal for operator surfaces
    or paid integrations. ``private`` is never exposed via this tool.

Liveness model:
  * default filters ``superseded_at IS NULL`` AND ``(effective_until IS NULL
    OR effective_until > date('now'))`` — only currently-live annotations.
  * ``include_superseded=True`` returns the full audit trail including
    superseded rows + expired effective windows.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath, execute_with_retry
from .error_envelope import make_error
from .tools import _safe_json_loads, _safe_tool

logger = logging.getLogger("jpintel.mcp.new.annotations")

# Closed enum mirrored from am_annotation_kind seed (migration 046). Add to
# both the seed INSERT and this list when introducing a new kind.
_KNOWN_KINDS: frozenset[str] = frozenset({
    "examiner_warning",
    "examiner_correction",
    "quality_score",
    "validation_failure",
    "ml_inference",
    "manual_note",
})

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


def _row_to_annotation(row: Any) -> dict[str, Any]:
    """Project a sqlite3.Row from am_entity_annotation into the public dict
    shape. ``meta_json`` is parsed lazily; malformed JSON yields ``{}``."""
    return {
        "annotation_id": row["annotation_id"],
        "entity_id": row["entity_id"],
        "kind": row["kind"],
        "severity": row["severity"],
        "text_ja": row["text_ja"],
        "score": row["score"],
        "meta": _safe_json_loads(row["meta_json"]),
        "visibility": row["visibility"],
        "source_id": row["source_id"],
        "effective_from": row["effective_from"],
        "effective_until": row["effective_until"],
        "supersedes_id": row["supersedes_id"],
        "superseded_at": row["superseded_at"],
        "observed_at": row["observed_at"],
    }


@mcp.tool(annotations=_READ_ONLY)
@_safe_tool
def get_annotations(
    entity_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description=(
                "am_entities.canonical_id (TEXT). 例: "
                "'program:provisional:35be300914' / "
                "'insurance_mutual:smrj:safety-net'。"
                "search_programs / search_case_studies 等の results[].canonical_id を渡す。"
            ),
        ),
    ],
    kinds: Annotated[
        list[str] | None,
        Field(
            description=(
                "annotation kind フィルタ。1 つ以上指定すると OR 結合。"
                "未指定なら全 kind を返す。known kinds: "
                "examiner_warning / examiner_correction / quality_score / "
                "validation_failure / ml_inference / manual_note。"
            ),
        ),
    ] = None,
    include_internal: Annotated[
        bool,
        Field(
            description=(
                "True で visibility='internal' 行も返す (default False = "
                "public のみ)。private は常に隠す。現状 ingest 済の "
                "16,474 行は全て internal なので、検査用途で internal を "
                "見たい場合は True を指定。"
            ),
        ),
    ] = False,
    include_superseded: Annotated[
        bool,
        Field(
            description=(
                "True で superseded_at IS NOT NULL や effective_until 切れの "
                "行も含めた監査履歴を返す (default False = 現在 live のみ)。"
            ),
        ),
    ] = False,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=_MAX_LIMIT,
            description=(
                f"返却する annotation 行の最大件数. Range [1, {_MAX_LIMIT}]. "
                f"Default {_DEFAULT_LIMIT}. annotation 数は entity 1 件あたり 0-50 が "
                "典型なので 100 程度で大半カバー. 監査用途は max."
            ),
        ),
    ] = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """[ANNOTATION] am_entity_annotation を entity_id で逆引き — examiner feedback / quality score / validation failure / ML 推論を 1 コールで取得.

    WHAT: ``am_entity_annotation`` table (migration 046 で導入された汎用注釈
    レイヤー、現在 16,474 行) を ``entity_id`` で絞って返す。kind / severity /
    text_ja / score / meta + supersede chain + effective window を 1 行ずつ。

    WHEN:
      - 「この program はなぜ品質スコアが低いと判断された?」
      - 「採択事例 X に紐付く examiner warning を全部見たい」
      - 「過去の validation failure 履歴を audit したい」(include_superseded=True)
      - operator dashboard で internal annotation を一覧 (include_internal=True)

    WHEN NOT:
      - 全 entity 横断で「最も警告が多い program」を探したい → 別 tool を
        新設 (現状未実装、search_top_warnings 等)。get_annotations は
        single-entity 専用。
      - entity の本体属性 (primary_name / authority / amount) → search_programs
        / search_case_studies 等を直接呼ぶ。

    RETURNS (envelope):
      {
        total: int,
        limit: int,
        offset: 0,
        results: [
          {
            annotation_id, entity_id, kind, severity, text_ja, score,
            meta (dict, parsed JSON), visibility, source_id,
            effective_from, effective_until, supersedes_id, superseded_at,
            observed_at,
          }, ...
        ],
        entity_id: <echo>,
        filters: {kinds, include_internal, include_superseded},
      }

    LIMITATIONS:
      - default visibility='public' フィルタは現状 0 行を返す (16,474 全件
        internal)。include_internal=True を必ず指定する想定。
      - meta_json の schema は kind 依存 (quality_score → sections[],
        examiner_warning → field_path 等)。caller 側で kind を見て
        分岐する。
    """
    # --- arg validation -----------------------------------------------------
    eid = (entity_id or "").strip()
    if not eid:
        return make_error(
            code="missing_required_arg",
            message="entity_id must be a non-empty am_entities.canonical_id",
            hint="Pass the canonical_id from search_* tool results, e.g. 'program:provisional:35be300914'.",
            field="entity_id",
            limit=limit,
        )

    requested_kinds: list[str] = []
    if kinds:
        for k in kinds:
            if not isinstance(k, str):
                continue
            ks = k.strip()
            if not ks:
                continue
            if ks not in _KNOWN_KINDS:
                return make_error(
                    code="invalid_enum",
                    message=f"unknown annotation kind: {ks!r}",
                    hint=f"Valid kinds: {sorted(_KNOWN_KINDS)}",
                    field="kinds",
                    retry_args={"kinds": [sorted(_KNOWN_KINDS)[0]]},
                    limit=limit,
                )
            requested_kinds.append(ks)

    # --- visibility set -----------------------------------------------------
    visibilities: list[str] = ["public"]
    if include_internal:
        visibilities.append("internal")
    # 'private' is never exposed.

    # --- build SQL ----------------------------------------------------------
    where_clauses: list[str] = ["entity_id = ?"]
    params: list[Any] = [eid]

    placeholders = ",".join("?" for _ in visibilities)
    where_clauses.append(f"visibility IN ({placeholders})")
    params.extend(visibilities)

    if requested_kinds:
        kph = ",".join("?" for _ in requested_kinds)
        where_clauses.append(f"kind IN ({kph})")
        params.extend(requested_kinds)

    if not include_superseded:
        where_clauses.append("superseded_at IS NULL")
        where_clauses.append(
            "(effective_until IS NULL OR effective_until > date('now'))"
        )

    sql = (
        "SELECT annotation_id, entity_id, kind, severity, text_ja, score, "
        "meta_json, visibility, source_id, effective_from, effective_until, "
        "supersedes_id, superseded_at, observed_at "
        "FROM am_entity_annotation "
        f"WHERE {' AND '.join(where_clauses)} "
        "ORDER BY observed_at DESC, annotation_id DESC "
        "LIMIT ?"
    )
    params.append(int(limit))

    conn = connect_autonomath()
    rows = execute_with_retry(conn, sql, params)
    results = [_row_to_annotation(r) for r in rows]

    return {
        "total": len(results),
        "limit": int(limit),
        "offset": 0,
        "results": results,
        "entity_id": eid,
        "filters": {
            "kinds": requested_kinds or None,
            "include_internal": include_internal,
            "include_superseded": include_superseded,
        },
    }


__all__ = ["get_annotations"]
