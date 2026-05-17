"""Product A2 — 会計士監査調書 Pack (``product_audit_workpaper_pack``).

One MCP call returns a complete 監査調書 (workpaper) draft for an audit
period (年次 / 四半期 / レビュー), composing:

* HE-2 ``prepare_implementation_workpaper`` — N1 template + N3 reasoning +
  N4 filing window + N6 amendment alerts.
* N3 ``walk_reasoning_chain`` — corporate_tax + commerce + labor chains.
* N7 ``get_segment_view`` — industry × size × prefecture risk benchmark.

Tier-D pricing band (Stage 3 F4 design):

* Per-call: ¥200 (= 66x ¥3/req baseline).

NO LLM. Pure SQLite + dict composition. §47条の2 (公認会計士法) sensitive
surface. 監査意見表明は会計士の独占業務、本 product は調書補助のみ。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ..moat_lane_tools._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.products.a2_audit_workpaper")

_PRODUCT_ID = "A2"
_PRODUCT_NAME = "会計士監査調書 Pack"
_SCHEMA_VERSION = "product.a2.v1"
_UPSTREAM_MODULE = "jpintel_mcp.products.a2_audit_workpaper"
_SEGMENT_JA = "会計士"

_PRICE_PER_REQ_JPY = 200
_VALUE_PROXY_LLM_LOW_JPY = 5000
_VALUE_PROXY_LLM_HIGH_JPY = 15000

_AUDIT_TYPES: tuple[str, ...] = ("年次", "四半期", "レビュー")
_AUDIT_TYPE_TO_ARTIFACT: dict[str, str] = {
    "年次": "kansa_chosho",
    "四半期": "kansa_chosho",
    "レビュー": "kansa_chosho",
}
_OPINION_BUCKETS: tuple[str, ...] = (
    "無限定適正意見",
    "限定付適正意見",
    "不適正意見",
    "意見不表明",
)

_A2_DISCLAIMER = (
    DISCLAIMER + " 監査意見表明は 公認会計士法 §47条の2 のもと、会計士の独占業務です。"
    "本 product は監査調書 (workpaper) 作成補助 (retrieval + scaffold) "
    "に留まり、意見表明 / 監査報告書 の確定提出物ではありません。"
    "監査基準 (財務諸表監査の基準) + 独立性要件は 必ず会計士判断で確認。"
    "サンプル件数 / 重要性基準値 / 統制評価 はすべて一次資料 "
    "(企業会計審議会 監査基準 / 監査・保証実務委員会報告) で再検証必須。"
)


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _open_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:  # pragma: no cover
        logger.warning("autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _compose_workpaper_skeleton(audit_type: str, fiscal_year: int) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = [
        {
            "section_id": "ra",
            "section_name": "リスク評価 (Risk Assessment)",
            "purpose": (
                "重要な虚偽表示リスクの識別と評価 (固有リスク × 統制リスク)。"
                f"対象期 {fiscal_year} ({audit_type}) の業界動向 + 改正 +"
                "前年差異の 3 軸で評価。"
            ),
            "content": "",
            "citation_anchor": [
                "監査基準 III.4 (リスク評価の実施)",
                "監査・保証実務委員会報告 第85号 (財務諸表監査における不正の検討)",
            ],
            "required_fields": [
                "identified_risk_areas",
                "risk_classification (固有/統制/結合)",
                "industry_benchmark_reference (N7 segment_view)",
            ],
        },
        {
            "section_id": "ct",
            "section_name": "統制テスト (Tests of Controls)",
            "purpose": (
                "識別したリスクに対応する内部統制の運用評価。"
                "IT/業務 統制を 5 軸 (権限分離 / 自動化 / モニタリング / "
                "リスク評価 / 報告) で評価。"
            ),
            "content": "",
            "citation_anchor": [
                "監査基準 III.5 (統制活動の評価)",
                "J-SOX 内部統制の評価及び監査の基準",
            ],
            "required_fields": [
                "tested_controls",
                "control_deficiencies",
                "remediation_plan",
            ],
        },
        {
            "section_id": "st",
            "section_name": "実証手続 (Substantive Procedures)",
            "purpose": (
                "リスク評価 + 統制テスト の結果に基づく実証手続。"
                "サンプリング規模 + 母集団 + 信頼水準 を Population / "
                "Sample-Size 計算式で決定。"
            ),
            "content": "",
            "citation_anchor": [
                "監査基準 III.6 (実証手続)",
                "監査・保証実務委員会報告 第90号 (監査サンプリング)",
            ],
            "required_fields": [
                "sampling_method",
                "sample_size",
                "confidence_level",
                "tested_items",
            ],
        },
        {
            "section_id": "cn",
            "section_name": "結論 (Conclusion)",
            "purpose": (
                "監査手続全体の結論。意見区分 (4 区分) + 重要な発見事項 + 翌期への申送り事項。"
            ),
            "content": "",
            "citation_anchor": [
                "監査基準 IV (監査意見の形成と監査報告書)",
            ],
            "required_fields": [
                "opinion_classification",
                "key_audit_matters (KAM)",
                "carryforward_notes",
            ],
        },
    ]
    if audit_type == "レビュー":
        for section in sections:
            if section["section_id"] == "st":
                section["purpose"] = (
                    "レビュー業務における 質問 + 分析的手続 (実証手続より "
                    "限定的)。サンプリング規模は監査基準より縮小可。"
                )
                section["citation_anchor"] = [
                    "中間財務諸表のレビュー業務に関する報告基準",
                ]
    return sections


def _compose_internal_control_evaluation(audit_type: str) -> dict[str, Any]:
    return {
        "framework": "J-SOX (財務報告に係る内部統制の評価及び監査の基準)",
        "axes": [
            {
                "axis_id": "permission_separation",
                "axis_name_ja": "権限分離 (Segregation of Duties)",
                "evaluation": "",
                "evidence_required": ["権限マトリクス", "システムアクセスログ"],
            },
            {
                "axis_id": "automation",
                "axis_name_ja": "業務プロセスの自動化",
                "evaluation": "",
                "evidence_required": ["業務フローチャート", "システム連携図"],
            },
            {
                "axis_id": "monitoring",
                "axis_name_ja": "モニタリング",
                "evaluation": "",
                "evidence_required": ["内部監査報告書", "経営者レビュー記録"],
            },
            {
                "axis_id": "risk_assessment",
                "axis_name_ja": "リスク評価",
                "evaluation": "",
                "evidence_required": ["リスクマップ", "リスク評価会議議事録"],
            },
            {
                "axis_id": "reporting",
                "axis_name_ja": "報告体制",
                "evaluation": "",
                "evidence_required": ["内部統制報告書", "経営者確認書"],
            },
        ],
        "note": (
            f"{audit_type} の場合、J-SOX 評価範囲は 重要勘定 + 重要拠点 + "
            "決算財務報告プロセス + IT 全社統制 に限定。会計士判断必須。"
        ),
    }


def _compose_materiality_items(audit_type: str) -> list[dict[str, Any]]:
    base = [
        {
            "item_id": "rev_recognition",
            "item_name_ja": "収益認識",
            "rationale": (
                "収益認識会計基準 (企業会計基準第29号) 適用下では、契約識別 + "
                "履行義務識別 + 取引価格配分 が重要な判断領域。"
            ),
            "risk_level": "high",
            "audit_response": "",
        },
        {
            "item_id": "going_concern",
            "item_name_ja": "継続企業の前提",
            "rationale": ("資金繰り / 純資産 / 営業 CF の悪化兆候を 3 期比較で確認。"),
            "risk_level": "medium",
            "audit_response": "",
        },
        {
            "item_id": "related_party",
            "item_name_ja": "関連当事者取引",
            "rationale": "関連当事者間取引の取引条件 + 開示の妥当性。",
            "risk_level": "medium",
            "audit_response": "",
        },
    ]
    if audit_type == "年次":
        base.append(
            {
                "item_id": "tax_provision",
                "item_name_ja": "税効果会計",
                "rationale": "繰延税金資産の回収可能性 (5 分類判定) の妥当性。",
                "risk_level": "high",
                "audit_response": "",
            }
        )
    return base


def _compose_sampling_recommendation(audit_type: str) -> dict[str, Any]:
    if audit_type == "年次":
        sample_size = 60
        confidence = 0.95
    elif audit_type == "四半期":
        sample_size = 25
        confidence = 0.90
    else:
        sample_size = 15
        confidence = 0.80
    return {
        "audit_type": audit_type,
        "sampling_method": "属性サンプリング (Attribute Sampling)",
        "confidence_level": confidence,
        "tolerable_error_rate": 0.05 if audit_type == "年次" else 0.08,
        "expected_error_rate": 0.0,
        "sample_size_baseline": sample_size,
        "population_floor_for_sampling": 250,
        "note": (
            "監査・保証実務委員会報告 第90号 (監査サンプリング) 抜粋。"
            "実際のサンプル件数は 母集団 / 過去誤謬率 / 統制依拠度 に応じ "
            "再計算必須 (会計士判断)。"
        ),
    }


def _compose_audit_opinion_draft(audit_type: str) -> dict[str, Any]:
    return {
        "audit_type": audit_type,
        "opinion_classification_options": list(_OPINION_BUCKETS),
        "default_recommendation": "operator decision required",
        "drafts": {
            "無限定適正意見": (
                f"我々は、財務諸表が {audit_type} 期において、適正に表示している "
                "と認める。"
                "(監査基準 IV.1.(1) — 重要な点で適正)。"
            ),
            "限定付適正意見": (
                "限定付適正意見区分。財務諸表 X 部分を除き、適正に表示している。"
                "(監査基準 IV.1.(2) — 監査範囲制約 or 重要な不適切)。"
            ),
            "不適正意見": (
                "財務諸表は、X 重要事項により、適正に表示していない。"
                "(監査基準 IV.1.(3) — 全体として不適切)。"
            ),
            "意見不表明": (
                "監査範囲の制約により、財務諸表に対する意見を表明しない。"
                "(監査基準 IV.1.(4) — 重要な監査手続実施不可)。"
            ),
        },
        "note": (
            "意見区分の確定は 会計士判断必須。本 draft は 4 区分の draft 文面 "
            "を提示するのみ、最終 意見表明は §47条の2 のもと会計士の独占業務。"
        ),
    }


def _compose_risk_assessment_skeleton(audit_type: str) -> dict[str, Any]:
    return {
        "audit_type": audit_type,
        "risk_axes": [
            {
                "axis_id": "inherent_risk",
                "axis_name_ja": "固有リスク (Inherent Risk)",
                "level": "",
                "rationale": "",
                "industry_benchmark": "",
            },
            {
                "axis_id": "control_risk",
                "axis_name_ja": "統制リスク (Control Risk)",
                "level": "",
                "rationale": "",
                "control_axis_reference": "internal_control_evaluation.axes",
            },
            {
                "axis_id": "detection_risk",
                "axis_name_ja": "発見リスク (Detection Risk)",
                "level": "",
                "rationale": "",
                "sampling_reference": "sampling_recommendation",
            },
        ],
        "formula": "監査リスク = 固有リスク × 統制リスク × 発見リスク",
        "note": "監査基準 III.3 (リスク評価) — 数値化ではなく定性的評価で可。",
    }


def _fetch_amendment_alerts_sync(
    houjin_bangou: str, horizon_days: int = 365
) -> list[dict[str, Any]]:
    if not houjin_bangou:
        return []
    conn = _open_ro()
    if conn is None:
        return []
    try:
        if not _table_present(conn, "am_amendment_alert_impact"):
            return []
        try:
            rows = conn.execute(
                """
                SELECT alert_id, amendment_diff_id, impact_score,
                       impacted_program_ids, impacted_tax_rule_ids,
                       detected_at, notified_at
                  FROM am_amendment_alert_impact
                 WHERE houjin_bangou = ?
                   AND datetime(detected_at) >= datetime('now', ?)
                 ORDER BY impact_score DESC, detected_at DESC
                 LIMIT 20
                """,
                (houjin_bangou, f"-{int(horizon_days)} days"),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            programs = json.loads(r["impacted_program_ids"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            programs = []
        try:
            tax_rules = json.loads(r["impacted_tax_rule_ids"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            tax_rules = []
        out.append(
            {
                "alert_id": int(r["alert_id"]),
                "amendment_diff_id": int(r["amendment_diff_id"]),
                "impact_score": int(r["impact_score"]),
                "impacted_program_ids": [str(p) for p in programs],
                "impacted_tax_rule_ids": [str(t) for t in tax_rules],
                "detected_at": r["detected_at"],
                "notified_at": r["notified_at"],
            }
        )
    return out


def _fetch_reasoning_chains_sync(limit: int = 5) -> list[dict[str, Any]]:
    conn = _open_ro()
    if conn is None:
        return []
    try:
        if not _table_present(conn, "am_legal_reasoning_chain"):
            return []
        rows = conn.execute(
            """
            SELECT chain_id, topic_id, topic_label, tax_category,
                   conclusion_text, confidence, opposing_view_text,
                   citations
              FROM am_legal_reasoning_chain
             WHERE tax_category IN ('corporate_tax','commerce','labor')
             ORDER BY confidence DESC, chain_id
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            cites = json.loads(r["citations"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            cites = {}
        out.append(
            {
                "chain_id": r["chain_id"],
                "topic_id": r["topic_id"],
                "topic_label": r["topic_label"],
                "tax_category": r["tax_category"],
                "conclusion_text": r["conclusion_text"],
                "confidence": float(r["confidence"] or 0.0),
                "opposing_view_text": r["opposing_view_text"],
                "citations": cites,
            }
        )
    return out


def _fetch_segment_view_sync(houjin_bangou: str) -> dict[str, Any]:
    if not houjin_bangou:
        return {"matches": [], "axes": None, "status": "skeleton_no_houjin"}
    conn = _open_ro()
    if conn is None:
        return {"matches": [], "axes": None, "status": "db_unavailable"}
    try:
        if not _table_present(conn, "am_segment_view"):
            return {"matches": [], "axes": None, "status": "segment_view_missing"}
        jsic_major: str | None = None
        size_band: str | None = None
        prefecture: str | None = None
        try:
            row = conn.execute(
                "SELECT canonical_id FROM am_entities "
                "WHERE record_kind='corporate_entity' AND canonical_id = ? LIMIT 1",
                (f"houjin:{houjin_bangou}",),
            ).fetchone()
            if row is not None:
                facts_cur = conn.execute(
                    "SELECT field_name, value_text FROM am_entity_facts "
                    "WHERE entity_id=? AND field_name IN "
                    "('corp.jsic_major','corp.industry_jsic','corp.size_band',"
                    " 'corp.employee_size_band','corp.prefecture','corp.registered_prefecture')",
                    (row["canonical_id"],),
                ).fetchall()
                for fact in facts_cur:
                    fn = str(fact["field_name"])
                    vt = str(fact["value_text"]) if fact["value_text"] is not None else None
                    if vt is None:
                        continue
                    if fn in ("corp.jsic_major", "corp.industry_jsic"):
                        jsic_major = vt[:1].upper() if vt else None
                    elif fn in ("corp.size_band", "corp.employee_size_band"):
                        size_band = vt
                    elif fn in ("corp.prefecture", "corp.registered_prefecture"):
                        prefecture = vt
        except sqlite3.OperationalError:
            pass
        if not jsic_major:
            return {
                "matches": [],
                "axes": {
                    "jsic_major": jsic_major,
                    "size_band": size_band,
                    "prefecture": prefecture,
                },
                "status": "jsic_major_unresolved",
            }
        try:
            base_q = (
                "SELECT segment_key, jsic_major, jsic_name_ja, size_band, "
                "prefecture, program_count, judgment_count, tsutatsu_count, "
                "popularity_rank, adoption_count "
                "FROM am_segment_view WHERE jsic_major=?"
            )
            params: list[Any] = [jsic_major]
            if size_band:
                base_q += " AND size_band=?"
                params.append(size_band)
            if prefecture:
                base_q += " AND prefecture=?"
                params.append(prefecture)
            base_q += " ORDER BY popularity_rank ASC NULLS LAST LIMIT 5"
            rows = conn.execute(base_q, params).fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        conn.close()
    matches = [
        {
            "segment_key": str(r["segment_key"]),
            "jsic_major": str(r["jsic_major"]),
            "jsic_name_ja": (str(r["jsic_name_ja"]) if r["jsic_name_ja"] is not None else None),
            "size_band": str(r["size_band"]),
            "prefecture": str(r["prefecture"]),
            "program_count": int(r["program_count"]),
            "judgment_count": int(r["judgment_count"]),
            "tsutatsu_count": int(r["tsutatsu_count"]),
            "popularity_rank": (
                int(r["popularity_rank"]) if r["popularity_rank"] is not None else None
            ),
            "adoption_count": int(r["adoption_count"]),
        }
        for r in rows
    ]
    return {
        "matches": matches,
        "axes": {
            "jsic_major": jsic_major,
            "size_band": size_band,
            "prefecture": prefecture,
        },
        "status": "ok" if matches else "no_match",
    }


def _billing_envelope() -> dict[str, Any]:
    return {
        "tier": "D",
        "product_id": _PRODUCT_ID,
        "price_per_req_jpy": _PRICE_PER_REQ_JPY,
        "value_proxy": {
            "model": "claude-opus-4-7",
            "llm_equivalent_low_jpy": _VALUE_PROXY_LLM_LOW_JPY,
            "llm_equivalent_high_jpy": _VALUE_PROXY_LLM_HIGH_JPY,
            "saving_low_pct": round(
                100.0 * (1 - _PRICE_PER_REQ_JPY / _VALUE_PROXY_LLM_HIGH_JPY), 1
            ),
            "saving_high_pct": round(
                100.0 * (1 - _PRICE_PER_REQ_JPY / _VALUE_PROXY_LLM_LOW_JPY), 1
            ),
            "note": (
                "Opus 4.7 で同等成果物 (監査調書 skeleton + 内部統制評価 + "
                "重要事項 + サンプリング + 意見 draft + リスク評価) を "
                f"生成する場合 ≒ ¥5,000-15,000 LLM cost。jpcite ¥{_PRICE_PER_REQ_JPY} "
                "は deterministic 計算で 96-99% 節約。"
            ),
        },
        "no_llm": True,
        "scaffold_only": True,
    }


def _empty_envelope(
    *, primary_input: dict[str, Any], rationale: str, status: str = "empty"
) -> dict[str, Any]:
    return {
        "tool_name": "product_audit_workpaper_pack",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": status,
            "product_id": _PRODUCT_ID,
            "product_name": _PRODUCT_NAME,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "workpaper_skeleton": [],
        "internal_control_evaluation": None,
        "materiality_items": [],
        "sampling_recommendation": None,
        "audit_opinion_draft": None,
        "risk_assessment": None,
        "segment_view": {"matches": [], "axes": None, "status": "empty"},
        "amendment_alerts": [],
        "reasoning_chains": [],
        "billing": _billing_envelope(),
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a2_pack",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["HE-2", "N3", "N7"],
        },
        "_billing_unit": 1,
        "_disclaimer": _A2_DISCLAIMER,
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["HE-2", "N3", "N7"],
            "observed_at": today_iso_utc(),
        },
    }


@mcp.tool(annotations=_READ_ONLY)
async def product_audit_workpaper_pack(
    houjin_bangou: Annotated[
        str,
        Field(
            min_length=0,
            max_length=13,
            description=(
                "13-digit corporate number. Empty string is allowed for "
                "skeleton-mode (workpaper sections + 4 opinion drafts + 3 "
                "risk axes only, no houjin-specific N6 alerts / N7 segment)."
            ),
        ),
    ] = "",
    fiscal_year: Annotated[
        int,
        Field(
            ge=2000,
            le=2100,
            description="Fiscal year of audit period (西暦, e.g. 2026).",
        ),
    ] = 2026,
    audit_type: Annotated[
        str,
        Field(
            pattern=r"^(年次|四半期|レビュー)$",
            description=(
                "Audit type: 年次 (annual statutory audit), 四半期 (quarterly "
                "review under 金商法), or レビュー (interim review / "
                "voluntary engagement)."
            ),
        ),
    ] = "年次",
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §47条の2/監査基準] A2 Product — 会計士監査調書 Pack.

    Composes HE-2 (workpaper template) + N3 (reasoning) + N7 (industry
    segment view) into one deterministic 監査調書 (workpaper) draft.

    Returns the canonical A2 envelope: workpaper_skeleton +
    internal_control_evaluation + materiality_items + sampling_recommendation
    + audit_opinion_draft + risk_assessment + segment_view + amendment_alerts
    + reasoning_chains + billing (¥200/req) + value_proxy (¥5,000-¥15,000
    LLM-equivalent) + §47条の2 disclaimer.

    NO LLM. Scaffold-only. 監査意見表明は会計士の独占業務、本 product は
    調書補助のみ。Pricing tier D; 1 ¥200 billable unit per call.
    """
    primary_input = {
        "houjin_bangou": houjin_bangou,
        "fiscal_year": fiscal_year,
        "audit_type": audit_type,
        "segment": _SEGMENT_JA,
        "artifact_type": _AUDIT_TYPE_TO_ARTIFACT.get(audit_type, "kansa_chosho"),
    }
    if audit_type not in _AUDIT_TYPES:  # pragma: no cover
        return _empty_envelope(
            primary_input=primary_input,
            rationale=f"audit_type must be one of {list(_AUDIT_TYPES)}",
        )
    loop = asyncio.get_event_loop()
    is_skeleton = not houjin_bangou
    if is_skeleton:
        amendment_alerts: list[dict[str, Any]] = []
        reasoning_chains = await loop.run_in_executor(None, _fetch_reasoning_chains_sync, 5)
        segment_view: dict[str, Any] = {
            "matches": [],
            "axes": None,
            "status": "skeleton_no_houjin",
        }
    else:
        alerts_task = loop.run_in_executor(None, _fetch_amendment_alerts_sync, houjin_bangou, 365)
        chains_task = loop.run_in_executor(None, _fetch_reasoning_chains_sync, 5)
        segment_task = loop.run_in_executor(None, _fetch_segment_view_sync, houjin_bangou)
        amendment_alerts, reasoning_chains, segment_view = await asyncio.gather(
            alerts_task, chains_task, segment_task
        )
    workpaper_skeleton = _compose_workpaper_skeleton(audit_type, fiscal_year)
    internal_control_evaluation = _compose_internal_control_evaluation(audit_type)
    materiality_items = _compose_materiality_items(audit_type)
    sampling_recommendation = _compose_sampling_recommendation(audit_type)
    audit_opinion_draft = _compose_audit_opinion_draft(audit_type)
    risk_assessment = _compose_risk_assessment_skeleton(audit_type)
    citations: list[dict[str, Any]] = []
    for chain in reasoning_chains[:3]:
        cites = chain.get("citations") or {}
        if isinstance(cites, dict):
            for kind in ("law", "tsutatsu", "hanrei"):
                entries = cites.get(kind, []) or []
                if isinstance(entries, list):
                    for entry in entries[:2]:
                        if isinstance(entry, dict):
                            citations.append({"kind": kind, **entry})
    return {
        "tool_name": "product_audit_workpaper_pack",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "product_id": _PRODUCT_ID,
            "product_name": _PRODUCT_NAME,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "is_skeleton": is_skeleton,
            "segment": _SEGMENT_JA,
            "audit_type": audit_type,
        },
        "workpaper_skeleton": workpaper_skeleton,
        "internal_control_evaluation": internal_control_evaluation,
        "materiality_items": materiality_items,
        "sampling_recommendation": sampling_recommendation,
        "audit_opinion_draft": audit_opinion_draft,
        "risk_assessment": risk_assessment,
        "segment_view": segment_view,
        "amendment_alerts": amendment_alerts,
        "reasoning_chains": reasoning_chains,
        "billing": _billing_envelope(),
        "results": workpaper_skeleton,
        "total": len(workpaper_skeleton),
        "limit": len(workpaper_skeleton),
        "offset": 0,
        "citations": citations[:10],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a2_pack",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["HE-2", "N3", "N7"],
            "audit_type": audit_type,
            "amendment_alert_count": len(amendment_alerts),
            "reasoning_chain_count": len(reasoning_chains),
            "segment_view_match_count": len(segment_view.get("matches", [])),
        },
        "_billing_unit": 1,
        "_disclaimer": _A2_DISCLAIMER,
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["HE-2", "N3", "N7"],
            "observed_at": today_iso_utc(),
        },
    }


__all__ = ["product_audit_workpaper_pack"]
