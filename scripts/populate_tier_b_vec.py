#!/usr/bin/env python3
"""Populate the 4 Tier-B vec tables (dealbreakers / eligibility / exclusions /
obligations) using the existing e5-small embedding stack.

NO Anthropic API. Pure local sentence-transformers + sqlite-vec.

Idempotent: only inserts rows missing from `am_vec_rowid_map` for that tier.
Safe to re-run; already-embedded canonical_ids are skipped.

Why this script exists:
  The original `embedding/facet_synthesis.py` was written against an idealised
  schema (`am_entities(topic_id, record_json)` + a separate `am_entity_facets`
  table) that does NOT match the production `autonomath.db` shape on this
  machine. Production schema is:
       am_entities(canonical_id, record_kind, source_topic, primary_name, raw_json, ...)
  and there is no `am_entity_facets` table at all.

  Rather than back-fill the missing facet table (190k rows of intermediate
  state we don't need), this script synthesises facet text in-memory and goes
  straight from raw_json -> embedding -> vec table.

Run order on Fly container (where torch + transformers are installed):
    flyctl ssh console -a autonomath-api -C \
        'cd /app && python scripts/populate_tier_b_vec.py'

Or on a workstation that has the full embedding stack and a copy of the DB:
    .venv/bin/python scripts/populate_tier_b_vec.py

Env knobs:
    AUTONOMATH_DB_PATH    override DB path (default: autonomath.db at repo root)
    POPULATE_LIMIT        cap rows scanned per facet (debug; default: no cap)
    POPULATE_BATCH        encode batch_size (default: 64; lower for 2x machine)
    POPULATE_TOPIC_FILTER optional source_topic substring filter

Schema notes:
  am_vec_tier_b_*       :  USING vec0(embedding float[384])
  am_vec_rowid_map      :  (tier TEXT, rowid INT, canonical_id TEXT) PK(tier,rowid)

Performance budget on this 7.4 GB DB:
  ~404k entities x ~30% applicable = ~120k facet rows per tier (worst case).
  Encoding cost: e5-small ~2 ms/row CPU on M-class HW, ~250s per tier ideal.
  Disk write: 384 * 4 bytes = 1.5 KB/vector + map row -> ~200 MB / 4 tiers.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import struct
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", REPO_ROOT / "autonomath.db"))
LIMIT = int(os.environ["POPULATE_LIMIT"]) if "POPULATE_LIMIT" in os.environ else None
BATCH = int(os.environ.get("POPULATE_BATCH", "64"))
TOPIC_FILTER = os.environ.get("POPULATE_TOPIC_FILTER")  # optional substring

EMBED_DIM = 384
MODEL_PRIMARY = "intfloat/multilingual-e5-small"
# In the Fly container, the model is pre-staged at /models/e5-small; otherwise
# fall back to the HF hub (cached at ~/.cache/huggingface on first run).
MODEL_CONTAINER_PATH = "/models/e5-small"

TIER_B_FACETS = ("dealbreakers", "eligibility", "exclusions", "obligations")
TIER_B_MAX_CHARS = 1_000

# Topics that carry no obligation / dealbreaker / exclusion content at all
# (statistic dumps, adoption-only lists). Skip unconditionally.
SKIP_TOPICS: set[str] = {
    "05_adoption_additional",
    "18_estat_industry_distribution",
}

# Subset of fields per facet. Mirrors `embedding/facet_synthesis.py` but kept
# self-contained to avoid the broken schema-guard import in that module.
DEALBREAKER_FIELDS: tuple[tuple[str, str], ...] = (
    # Strong enforcement-record signal (100% on record_kind=enforcement).
    ("rescission_date", "取消日"),
    ("return_status", "返還状況"),
    ("reason_excerpt", "理由"),
    ("amount_improper_grant_yen", "不当交付額"),
    ("amount_improper_project_cost_yen", "不当事業費"),
    ("amount_grant_paid_yen", "交付済額"),
    ("disclosed_date", "公表日"),
    ("disclosed_until", "公表期限"),
    ("legal_basis", "法的根拠"),
    # Generic across other record kinds.
    ("excluded_reason", "不交付理由"),
    ("rejection_reason", "却下理由"),
    ("rejection_reasons", "却下理由"),
    ("withdrawal_reason", "取下げ理由"),
    ("revocation_conditions", "取消条件"),
    ("forfeiture", "失効条件"),
    ("penalty", "罰則"),
    ("penalties", "罰則"),
    ("penalty_conditions", "罰則条件"),
    ("penalty_non_compliance", "違反時ペナルティ"),
    ("penalty_for_violation", "違反時ペナルティ"),
    ("penalty_for_non_compliance", "違反時ペナルティ"),
    ("penalty_max", "罰則上限"),
    ("penalty_rule", "罰則ルール"),
    ("penalty_type", "罰則種別"),
    ("penalty_types", "罰則種別"),
    ("penalty_structure", "罰則構造"),
    ("violation", "違反内容"),
    ("violations", "違反内容"),
    ("violation_penalty", "違反時罰則"),
    ("violation_penalties", "違反時罰則"),
    ("violation_measures", "違反時措置"),
    ("breach_reporting", "違反通報"),
    ("breach_reporting_triggers", "違反通報のトリガー"),
    ("return_exemption", "返還免除"),
    ("return_exemption_condition", "返還免除条件"),
    ("clawback_conditions", "返還条件"),
)

ELIGIBILITY_FIELDS: tuple[tuple[str, str], ...] = (
    # Discovered via DB sampling 2026-04-25; ordered by observed frequency.
    ("target_types", "対象種別"),
    ("target", "対象"),
    ("target_conditions", "対象条件"),
    ("target_entity", "対象事業者"),
    ("target_entities", "対象事業者"),
    ("target_entity_type", "対象事業者種別"),
    ("target_taxpayer", "対象納税者"),
    ("target_recipient", "対象受給者"),
    ("target_business_size", "対象規模"),
    ("target_employee_type", "対象従業員種別"),
    ("target_business", "対象事業"),
    ("target_business_kind", "対象業種"),
    ("target_industry", "対象業種"),
    ("target_industries", "対象業種"),
    ("target_size", "対象規模"),
    ("target_persons", "対象者"),
    ("target_name", "対象名称"),
    ("target_age", "対象年齢"),
    ("target_stage", "対象ステージ"),
    ("target_fields", "対象分野"),
    ("target_area", "対象地域"),
    ("target_type", "対象種別"),
    ("eligibility", "適用要件"),
    ("eligibility_conditions", "適用要件"),
    ("eligibility_criteria", "適用基準"),
    ("eligibility_requirements", "適用要件"),
    ("eligibility_key_criteria", "主要適用基準"),
    ("prerequisite", "前提条件"),
    ("prerequisites", "前提条件"),
    ("prerequisite_requirements", "前提条件"),
    ("prerequisite_certification", "前提認定"),
    ("requires_prerequisite", "前提要件"),
    ("requirement", "要件"),
    ("requirements", "要件"),
    ("core_requirement", "中核要件"),
    ("key_requirements", "主要要件"),
    ("required_employment_number", "必要雇用人数"),
    ("application_requirements", "申請要件"),
    ("certification_requirements", "認定要件"),
    ("approval_criteria", "認定基準"),
    ("scope", "対象範囲"),
    ("support_scope", "支援範囲"),
    ("eligible_use", "適用用途"),
    ("eligible_uses", "適用用途"),
    ("eligible_purposes", "適用目的"),
    ("eligible_period", "適用期間"),
    ("eligible_region", "適用地域"),
    ("eligible_industries", "適用業種"),
    ("eligible_assets", "適用資産"),
    ("applicable_to", "適用対象"),
    ("applicable_period", "適用期間"),
    ("applicant", "申請者"),
    ("applicant_type", "申請者種別"),
    ("application_period", "申請期間"),
    ("application_period_r7", "申請期間(令和7)"),
    ("application_period_from", "申請期間開始"),
    ("application_period_to", "申請期間終了"),
    ("application_window", "申請窓口"),
    ("application_window_2025", "申請枠2025"),
    ("application_window_r7", "申請枠(令和7)"),
    ("application_channel", "申請経路"),
    ("application_deadline", "申請期限"),
    ("application_fee_yen", "申請手数料(円)"),
    ("expected_2026_window", "2026年予定枠"),
    ("subsidy_rate", "補助率"),
    ("rate", "適用率"),
    ("amount_max_yen", "上限額(円)"),
    ("amount_min_yen", "下限額(円)"),
    ("amount_average_yen", "平均交付額(円)"),
    ("amount_total_yen", "総額(円)"),
    ("benefit_amount", "給付額"),
    ("benefit_type", "給付種別"),
    ("benefits", "給付内容"),
    ("legal_basis", "法的根拠"),
    ("law_basis", "根拠法"),
    ("source_excerpt", "出典抜粋"),
    ("policy_background_excerpt", "政策背景抜粋"),
    ("summary", "概要"),
    ("title", "タイトル"),
    ("category", "区分"),
    ("category_detail", "区分詳細"),
    ("program_kind", "制度種別"),
    ("program_kind_hint", "制度種別ヒント"),
    ("support_period_years", "支援期間(年)"),
    ("certification_period_years", "認定期間(年)"),
    ("research_period_years", "研究期間(年)"),
    ("duration_months", "期間(月)"),
)

EXCLUSION_FIELDS: tuple[tuple[str, str], ...] = (
    # Discovered keys (program records have compatible_with / incompatible_with).
    ("compatible_with", "併用可否"),
    ("incompatible_with", "併用不可"),
    ("excluded_programs", "対象外プログラム"),
    ("exclude_equity", "出資除外"),
    ("excluded_2021", "2021年除外"),
    ("exclusions", "除外対象"),
    ("excludes", "除外対象"),
    ("excluded", "除外対象"),
    ("excluded_items", "除外品目"),
    ("excluded_products", "除外製品"),
    ("excluded_categories", "除外カテゴリ"),
    ("excluded_foreign_workers", "除外外国人"),
    ("excluded_lands", "除外土地"),
    ("excluded_reason", "除外理由"),
    ("incompatible_programs", "併用不可プログラム"),
    ("restricted_items", "制限品目"),
    ("restricted_uses", "用途制限"),
    ("restrictions", "制限事項"),
    ("restriction", "制限事項"),
    ("key_restrictions", "主要制限"),
    ("practice_restriction", "実務制限"),
    ("zoning_restriction", "区域制限"),
    ("advertising_restriction", "広告制限"),
    ("exclusion_conditions", "除外条件"),
    ("exclusion_status", "除外状況"),
    ("use_of_funds_excluded", "資金使途除外"),
    ("usage_conditions", "使用条件"),
    ("condition", "条件"),
    ("rule_type", "ルール種別"),
)

OBLIGATION_FIELDS: tuple[tuple[str, str], ...] = (
    ("obligations", "義務"),
    ("obligation", "義務"),
    ("key_obligations", "主要義務"),
    ("obligation_type", "義務種別"),
    ("obligation_content", "義務内容"),
    ("obligation_scope", "義務範囲"),
    ("obligation_target", "義務対象"),
    ("operator_obligations", "事業者義務"),
    ("owner_obligations", "所有者義務"),
    ("company_obligations", "企業義務"),
    ("employer_obligations_harassment", "事業主義務(ハラスメント)"),
    ("post_approval_obligations", "承認後義務"),
    ("recipient_obligations", "受給者義務"),
    ("required_documents", "必要書類"),
    ("required_docs", "必要書類"),
    ("required_document", "必要書類"),
    ("monitoring", "モニタリング"),
    ("reporting", "報告"),
    ("reporting_obligation", "報告義務"),
    ("reporting_requirement", "報告要件"),
    ("reporting_period", "報告期間"),
    ("reporting_deadline", "報告期限"),
    ("reporting_cadence", "報告頻度"),
    ("reporting_cycle", "報告サイクル"),
    ("retention_obligation", "保存義務"),
    ("retention_requirement", "保存要件"),
    ("security_required", "担保要否"),
    ("security_requirement", "担保要件"),
    ("notification_obligation", "通知義務"),
    ("notification_required", "通知要否"),
    ("disclosure_obligation", "開示義務"),
    ("display_obligation", "掲示義務"),
    ("display_obligations", "掲示義務"),
    ("statutory_rate_compliance_required", "法定率遵守要件"),
    ("post_grant_obligations", "交付後義務"),
    ("joint_liability", "連帯保証"),
    ("collateral_requirements", "担保要件"),
    ("filing_requirements", "届出要件"),
    ("filing_requirement", "届出要件"),
    ("min_wage_obligation", "最低賃金遵守義務"),
    ("continuation_requirements", "継続要件"),
    ("renewal_required", "更新要否"),
    ("obligation_renewal", "義務更新"),
    ("continuous_monitoring", "継続監視"),
    ("key_requirements", "主要要件"),
)

FACET_FIELDS = {
    "dealbreakers": DEALBREAKER_FIELDS,
    "eligibility": ELIGIBILITY_FIELDS,
    "exclusions": EXCLUSION_FIELDS,
    "obligations": OBLIGATION_FIELDS,
}

log = logging.getLogger("populate_tier_b_vec")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_as_text(v) for v in value]
        return "; ".join(p for p in parts if p)
    if isinstance(value, dict):
        for k in ("text", "value", "name", "label"):
            if k in value:
                return _as_text(value[k])
        return "; ".join(f"{k}={_as_text(v)}" for k, v in value.items() if v)
    return str(value)


def synthesize_facet(rec: dict, fields: tuple[tuple[str, str], ...]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for key, label in fields:
        if key not in rec:
            continue
        txt = _as_text(rec[key])
        if not txt or txt in seen:
            continue
        seen.add(txt)
        parts.append(f"{label}: {txt}")
    body = " / ".join(parts)
    if len(body) > TIER_B_MAX_CHARS:
        body = body[: TIER_B_MAX_CHARS - 1] + "…"
    return body


def serialize_f32(vec) -> bytes:
    """Pack a 384-d float32 vector into the bytes layout sqlite-vec expects."""
    # numpy is the cleanest path; struct fallback for tiny envs.
    try:
        import numpy as np  # noqa: F401

        return vec.astype("float32").tobytes()
    except Exception:
        return struct.pack(f"{len(vec)}f", *vec)


def load_encoder():
    """Load e5-small via sentence-transformers. Hard fail (no stub fallback).

    Stub vectors would produce useless retrieval and silently break recall —
    we'd rather error out and run on Fly than ship 120k random embeddings.
    """
    from sentence_transformers import SentenceTransformer

    model_path = MODEL_CONTAINER_PATH if Path(MODEL_CONTAINER_PATH).exists() else MODEL_PRIMARY
    log.info("loading sentence-transformer model=%s", model_path)
    m = SentenceTransformer(model_path)

    dim_fn = getattr(m, "get_embedding_dimension", None) or m.get_sentence_embedding_dimension
    dim = dim_fn()
    if dim != EMBED_DIM:
        raise SystemExit(
            f"model dim={dim} but vec table is float[{EMBED_DIM}] — refusing to write garbage"
        )
    return m


# ---------------------------------------------------------------------------
# Per-facet ingest
# ---------------------------------------------------------------------------
def existing_canonical_ids(conn: sqlite3.Connection, tier: str) -> set[str]:
    rows = conn.execute(
        "SELECT canonical_id FROM am_vec_rowid_map WHERE tier = ?",
        (f"tier_b_{tier}",),
    ).fetchall()
    return {r[0] for r in rows}


def stream_entities(conn: sqlite3.Connection, limit: int | None) -> Iterable[tuple[str, str, str]]:
    """Yield (canonical_id, source_topic, raw_json) for non-skipped entities."""
    sql = (
        "SELECT canonical_id, source_topic, raw_json FROM am_entities "
        "WHERE source_topic IS NULL OR source_topic NOT IN ({})".format(
            ",".join("?" * len(SKIP_TOPICS))
        )
    )
    params: list = list(SKIP_TOPICS)
    if TOPIC_FILTER:
        sql += " AND source_topic LIKE ?"
        params.append(f"%{TOPIC_FILTER}%")
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    cur = conn.execute(sql, params)
    for cid, topic, raw in cur:
        yield cid, topic or "", raw or "{}"


def populate_facet(
    conn: sqlite3.Connection,
    encoder,
    facet: str,
    fields: tuple[tuple[str, str], ...],
) -> tuple[int, int, int]:
    """Synthesize -> encode -> insert for one facet.

    Returns (scanned, synthesised, inserted).
    """
    tier_label = f"tier_b_{facet}"
    table = f"am_vec_tier_b_{facet}"
    already = existing_canonical_ids(conn, facet)
    log.info("[%s] %d already embedded — skipping those", facet, len(already))

    # Pass 1: scan + synthesise (in memory). Holds up to ~150k 1KB strings
    # = ~150 MB RAM worst case. Acceptable on shared-cpu-2x; if not, batch
    # by source_topic.
    todo_cids: list[str] = []
    todo_texts: list[str] = []
    scanned = 0
    for cid, _topic, raw in stream_entities(conn, LIMIT):
        scanned += 1
        if cid in already:
            continue
        try:
            rec = json.loads(raw) if raw else {}
        except Exception:
            continue
        text = synthesize_facet(rec, fields)
        if not text:
            continue
        todo_cids.append(cid)
        todo_texts.append(text)
        if scanned % 50000 == 0:
            log.info("[%s] scanned=%d, queued=%d", facet, scanned, len(todo_cids))

    if not todo_cids:
        log.info("[%s] nothing to embed", facet)
        return scanned, 0, 0

    log.info("[%s] encoding %d texts (batch=%d)", facet, len(todo_cids), BATCH)
    t0 = time.perf_counter()
    # e5 convention: passage prefix on the docs being embedded.
    prepped = [f"passage: {t}" for t in todo_texts]
    vecs = encoder.encode(
        prepped,
        batch_size=BATCH,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    enc_dt = time.perf_counter() - t0
    log.info(
        "[%s] encoded in %.1fs (%.1f ms/row)",
        facet,
        enc_dt,
        enc_dt * 1000 / len(todo_cids),
    )

    # Pass 2: write. One transaction; vec0 INSERT auto-assigns rowid; we mirror
    # to am_vec_rowid_map for canonical_id lookup.
    t0 = time.perf_counter()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for cid, vec in zip(todo_cids, vecs, strict=False):
            cur = conn.execute(
                f"INSERT INTO {table}(embedding) VALUES (?)",
                (serialize_f32(vec),),
            )
            rowid = cur.lastrowid
            conn.execute(
                "INSERT OR REPLACE INTO am_vec_rowid_map (tier, rowid, canonical_id) VALUES (?, ?, ?)",
                (tier_label, rowid, cid),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    write_dt = time.perf_counter() - t0
    log.info("[%s] wrote %d vectors in %.1fs", facet, len(todo_cids), write_dt)
    return scanned, len(todo_cids), len(todo_cids)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if not DB_PATH.exists():
        log.error("DB not found: %s", DB_PATH)
        return 2
    log.info("DB: %s", DB_PATH)

    encoder = load_encoder()

    conn = sqlite3.connect(str(DB_PATH), timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.enable_load_extension(True)
    try:
        # Try the container path first (Fly machine), fall back to the bundled
        # python wheel sqlite_vec.load(conn).
        try:
            conn.load_extension("/opt/vec0.so")
            log.info("loaded /opt/vec0.so")
        except sqlite3.OperationalError:
            import sqlite_vec  # type: ignore

            sqlite_vec.load(conn)
            log.info("loaded sqlite_vec via python wheel")
    finally:
        conn.enable_load_extension(False)

    # Show before-counts.
    for f in TIER_B_FACETS:
        n = conn.execute(f"SELECT COUNT(*) FROM am_vec_tier_b_{f}").fetchone()[0]
        log.info("before: am_vec_tier_b_%s = %d", f, n)

    summary: list[str] = []
    for facet, fields in FACET_FIELDS.items():
        scanned, synthesised, inserted = populate_facet(conn, encoder, facet, fields)
        summary.append(
            f"  {facet}: scanned={scanned} synthesised={synthesised} inserted={inserted}"
        )

    # Show after-counts.
    log.info("done. summary:")
    for line in summary:
        log.info(line)
    for f in TIER_B_FACETS:
        n = conn.execute(f"SELECT COUNT(*) FROM am_vec_tier_b_{f}").fetchone()[0]
        log.info("after:  am_vec_tier_b_%s = %d", f, n)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
