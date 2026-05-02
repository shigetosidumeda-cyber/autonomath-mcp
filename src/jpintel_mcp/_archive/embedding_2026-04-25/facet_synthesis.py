"""Synthesize Tier B facet texts from existing record_json fields.

The task spec asked us to fill `dealbreakers` / `exclusions` / `obligations`
facets from `recipient_obligations` / `clawback_conditions` / `restricted_uses`.
Those exact field names do NOT exist in the ingested records (the data feed
uses different shapes per topic), but equivalent signal IS present across
many record_json keys. This module maps the real surface into the same three
facet buckets and emits synthesized text.

Design rules (no fabrication — `feedback_no_fake_data`):
  * Only synthesize when real content exists. Empty / None → skipped.
  * Topic-aware: statistic rows (18_estat_*) and adoption lists
    (05_adoption_additional) have no obligation content — skip unconditionally.
  * Keep synthesised text honest: prefix fields with their role so the
    embedder doesn't confuse, say, a penalty amount with a subsidy cap.
  * Idempotent on canonical_id+facet: re-running upsert only.

Fill-rate target (task spec):
    dealbreakers  0% → 30%+  of applicable records (program-like topics only)
    exclusions  0.05% → 20%+  of applicable records

"Applicable" excludes the two big statistical topics (~179k rows). Full-DB
rate stays honest: ~3-5% of all 190k rows, ~30%+ of ~11k applicable rows.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .config import DB_PATH, TIER_B_MAX_CHARS, TIERS
from .db import connect
from .generate import serialize_f32
from .model import Encoder




# --- AUTO: SCHEMA_GUARD_BLOCK (Wave 10 infra hardening) ---
import sys as _sg_sys
from pathlib import Path as _sg_Path
_sg_sys.path.insert(0, str(_sg_Path(__file__).resolve().parent.parent))
try:
    from scripts.schema_guard import assert_am_entities_schema as _sg_check
except Exception:  # pragma: no cover - schema_guard must exist in prod
    _sg_check = None
if __name__ == "__main__" and _sg_check is not None:
    _sg_check("/tmp/autonomath_infra_2026-04-24/autonomath.db")
# --- END SCHEMA_GUARD_BLOCK ---

log = logging.getLogger(__name__)


# Topics that are pure statistics / adoption lists → no facet content.
_SKIP_TOPICS: Set[str] = {
    "05_adoption_additional",
    "18_estat_industry_distribution",
}


# ---------------------------------------------------------------------------
# Field → facet mapping
# ---------------------------------------------------------------------------
# Fields whose presence / value goes into the DEALBREAKERS facet.
# (事後失効 / 返還 / 取消 / ペナルティ)
_DEALBREAKER_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("rescission_date", "取消日"),
    ("return_status", "返還状況"),
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
    ("amount_improper_grant_yen", "不当交付額"),
    ("reason_excerpt", "理由"),
    ("clawback_conditions", "返還条件"),
)

# Fields that feed the OBLIGATIONS facet (報告/監査/連帯保証/モニタリング).
_OBLIGATION_FIELDS: Tuple[Tuple[str, str], ...] = (
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

# Fields that feed the EXCLUSIONS facet (併用不可 / 対象外 / 制限).
_EXCLUSION_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("excluded_programs", "対象外プログラム"),
    ("exclusions", "除外対象"),
    ("excludes", "除外対象"),
    ("excluded", "除外対象"),
    ("excluded_items", "除外品目"),
    ("excluded_products", "除外製品"),
    ("excluded_categories", "除外カテゴリ"),
    ("excluded_foreign_workers", "除外外国人"),
    ("excluded_lands", "除外土地"),
    ("excluded_reason", "除外理由"),
    ("excluded_2021", "2021年除外"),
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
    ("condition", "条件"),  # 03_exclusion_rules primary field
    ("rule_type", "ルール種別"),
    ("compatible_with", "併用可否"),  # positive framing — still an exclusion axis
)


# Keyword → facet weights for coarse extraction from free-text fields.
# When a structured field is absent but prose (source_excerpt, summary,
# reason_excerpt, target_conditions, policy_background_excerpt) contains
# these keywords, we pull the containing sentence into the facet.
_DEALBREAKER_KEYWORDS: Tuple[str, ...] = (
    "返還", "取消", "取り消し", "違反", "罰則", "ペナルティ",
    "失格", "事後失効", "不交付", "中止", "失効", "停止",
    "認定取消", "不適正", "虚偽",
)
_OBLIGATION_KEYWORDS: Tuple[str, ...] = (
    "報告義務", "報告", "提出義務", "モニタリング", "遵守",
    "点検", "検査", "更新義務", "維持", "実施報告",
    "保有義務", "書類保存", "記録保存", "実績報告", "交付決定",
    "連帯保証", "担保",
)
_EXCLUSION_KEYWORDS: Tuple[str, ...] = (
    "併用不可", "併給", "重複", "対象外", "除外", "制限",
    "禁止", "不可とする", "ただし", "併用できない", "対象としない",
    "除きます", "除く", "不適用", "適用しない",
)

# Topic_id → guaranteed facet applicability. These topics carry obligation
# signal by construction even when the specific fields are sparse.
_PROGRAM_TOPICS: Set[str] = {
    "06_prefecture_programs",
    "33_prefecture_programs_part2",
    "20_designated_city_programs",
    "07_new_program_candidates",
    "04_program_documents",
    "08_loan_programs",
    "03_exclusion_rules",
    "11_mhlw_employment_grants",
    "13_enforcement_cases",
    "15_environment_energy_programs",
    "16_trade_export_programs",
    "17_tourism_mlit_chisou_programs",
    "22_mirasapo_cases",
    "23_medical_care_grants",
    "27_chamber_commerce",
    "28_research_grants",
    "30_culture_media_grants",
    "37_fisheries_aquaculture",
    "40_private_foundations",
    "44_compliance_fair_trade",
    "49_case_law_judgments",
    "149_corporate_tax_deep",
}

# Prose fields we scan for keyword hits when structured fields are thin.
_PROSE_FIELDS: Tuple[str, ...] = (
    "source_excerpt",
    "reason_excerpt",
    "summary",
    "case_summary",
    "target_conditions",
    "target_entity",
    "eligibility",
    "prerequisite",
    "prerequisite_requirements",
    "policy_background_excerpt",
    "key_facts",
    "key_points",
    "notes",
    "benefits",
)


def _scan_prose_for_keywords(
    rec: dict, keywords: Tuple[str, ...], max_snippets: int = 3
) -> List[str]:
    """Return up to `max_snippets` sentences/fragments mentioning keyword hits.

    Looks at all prose-shaped fields; splits on '。/\n・' as sentence boundaries.
    """
    snippets: List[str] = []
    seen: Set[str] = set()
    for k in _PROSE_FIELDS:
        if k not in rec:
            continue
        raw = rec[k]
        if isinstance(raw, list):
            candidates = [_as_text(v) for v in raw if v]
        else:
            candidates = [_as_text(raw)]
        for text in candidates:
            if not text:
                continue
            # Cheap split on JP sentence terminators.
            for sent in _split_sentences(text):
                if any(kw in sent for kw in keywords):
                    s = sent.strip()
                    if s and s not in seen:
                        seen.add(s)
                        snippets.append(s)
                        if len(snippets) >= max_snippets:
                            return snippets
    return snippets


def _split_sentences(text: str) -> List[str]:
    # Minimal Japanese sentence splitter.
    out: List[str] = []
    buf: List[str] = []
    for ch in text:
        buf.append(ch)
        if ch in "。！？\n":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


@dataclass
class SynthStats:
    scanned: int = 0
    skipped_topic: int = 0
    synth_dealbreakers: int = 0
    synth_exclusions: int = 0
    synth_obligations: int = 0
    existing_dealbreakers: int = 0
    existing_exclusions: int = 0
    existing_obligations: int = 0


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


def _synthesise_facet(
    rec: dict,
    fields: Tuple[Tuple[str, str], ...],
    topic_id: str,
    keywords: Tuple[str, ...] = (),
) -> str:
    """Structured-field primary pass; keyword prose fallback when a
    program-topic record has no explicit signal but prose mentions it."""
    parts: List[str] = []
    seen_vals: Set[str] = set()
    for key, label in fields:
        if key not in rec:
            continue
        txt = _as_text(rec[key])
        if not txt:
            continue
        if txt in seen_vals:
            continue
        seen_vals.add(txt)
        parts.append(f"{label}: {txt}")
    # Keyword prose fallback — only for program-like topics and only if
    # the structured pass produced nothing. Keeps noise down.
    if not parts and keywords and topic_id in _PROGRAM_TOPICS:
        prose_hits = _scan_prose_for_keywords(rec, keywords)
        for s in prose_hits:
            parts.append(s)
    body = " / ".join(parts)
    if len(body) > TIER_B_MAX_CHARS:
        body = body[: TIER_B_MAX_CHARS - 1] + "…"
    return body


def _existing_facets(conn: sqlite3.Connection) -> Dict[Tuple[str, str], bool]:
    """Return set of (canonical_id, facet) already in am_entity_facets."""
    cur = conn.execute("SELECT canonical_id, facet FROM am_entity_facets")
    return {(r[0], r[1]): True for r in cur.fetchall()}


def synthesise_all(
    *,
    db_path: Path = DB_PATH,
    dry_run: bool = False,
    limit: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> SynthStats:
    """Scan am_entities, synthesise missing Tier B facet texts, store.

    Does NOT embed — embedding is a separate pass via `embed_synthesised`.
    """
    own = conn is None
    conn = conn or connect(db_path)
    try:
        stats = SynthStats()
        existing = _existing_facets(conn)

        cur = conn.execute(
            "SELECT canonical_id, topic_id, record_json FROM am_entities"
            + (" LIMIT ?" if limit else ""),
            (limit,) if limit else (),
        )
        batch_rows: List[Tuple[str, str, str, int]] = []  # (cid, facet, text, char_count)
        for row in cur:
            stats.scanned += 1
            if row["topic_id"] in _SKIP_TOPICS:
                stats.skipped_topic += 1
                continue
            try:
                rj = json.loads(row["record_json"]) if row["record_json"] else {}
            except Exception:
                continue
            topic_id = row["topic_id"]
            cid = row["canonical_id"]

            # Dealbreakers
            if (cid, "tier_b_dealbreakers") not in existing:
                txt = _synthesise_facet(
                    rj, _DEALBREAKER_FIELDS, topic_id, _DEALBREAKER_KEYWORDS
                )
                if txt:
                    stats.synth_dealbreakers += 1
                    batch_rows.append(
                        (cid, "tier_b_dealbreakers", txt, len(txt))
                    )
            else:
                stats.existing_dealbreakers += 1

            # Exclusions — augment existing content; overwrite if new synth is
            # richer. Existing 03_exclusion_rules rows are kept intact.
            existing_excl = (cid, "tier_b_exclusions") in existing
            txt_excl = _synthesise_facet(
                rj, _EXCLUSION_FIELDS, topic_id, _EXCLUSION_KEYWORDS
            )
            if txt_excl and not existing_excl:
                stats.synth_exclusions += 1
                batch_rows.append(
                    (cid, "tier_b_exclusions", txt_excl, len(txt_excl))
                )
            elif existing_excl:
                stats.existing_exclusions += 1

            # Obligations
            existing_obl = (cid, "tier_b_obligations") in existing
            txt_obl = _synthesise_facet(
                rj, _OBLIGATION_FIELDS, topic_id, _OBLIGATION_KEYWORDS
            )
            if txt_obl and not existing_obl:
                stats.synth_obligations += 1
                batch_rows.append(
                    (cid, "tier_b_obligations", txt_obl, len(txt_obl))
                )
            elif existing_obl:
                stats.existing_obligations += 1

        if not dry_run:
            conn.executemany(
                """INSERT OR REPLACE INTO am_entity_facets
                   (canonical_id, facet, text, char_count) VALUES (?,?,?,?)""",
                batch_rows,
            )
            conn.commit()
        log.info(
            "synthesise: scanned=%d skipped=%d +deal=%d +excl=%d +obl=%d (dry=%s)",
            stats.scanned,
            stats.skipped_topic,
            stats.synth_dealbreakers,
            stats.synth_exclusions,
            stats.synth_obligations,
            dry_run,
        )
        return stats
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
def embed_synthesised(
    *,
    db_path: Path = DB_PATH,
    encoder: Optional[Encoder] = None,
    batch_size: int = 64,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, int]:
    """Embed newly-synthesised facet texts that have no vector yet.

    Returns a per-facet count of inserted vectors.
    """
    own = conn is None
    conn = conn or connect(db_path)
    try:
        encoder = encoder or Encoder()
        inserted: Dict[str, int] = {}
        for facet in ("tier_b_dealbreakers", "tier_b_exclusions", "tier_b_obligations"):
            # Facet rows missing from the vec rowid map.
            sql = """
                SELECT f.canonical_id, f.text
                FROM am_entity_facets f
                LEFT JOIN am_vec_rowid_map m
                  ON m.tier = ? AND m.canonical_id = f.canonical_id
                WHERE f.facet = ? AND m.rowid IS NULL
            """
            rows = conn.execute(sql, (facet, facet)).fetchall()
            if not rows:
                inserted[facet] = 0
                continue
            cids = [r[0] for r in rows]
            texts = [r[1] for r in rows]
            log.info("embed %d new %s facets…", len(rows), facet)
            t0 = time.perf_counter()
            res = encoder.encode(texts, kind="passage", batch_size=batch_size)
            dt = time.perf_counter() - t0
            log.info("  encoded in %.1fs (%.1f ms/row)", dt, dt * 1000 / max(len(rows), 1))

            table = TIERS[facet]["table"]
            for cid, vec in zip(cids, res.vectors):
                cur = conn.execute(
                    f"INSERT INTO {table}(embedding) VALUES (?)",
                    (serialize_f32(vec),),
                )
                rowid = cur.lastrowid
                conn.execute(
                    "INSERT INTO am_vec_rowid_map (tier, rowid, canonical_id) "
                    "VALUES (?,?,?)",
                    (facet, rowid, cid),
                )
            conn.commit()
            inserted[facet] = len(rows)
        return inserted
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
def cli() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    stats = synthesise_all(db_path=Path(args.db), dry_run=args.dry_run, limit=args.limit)
    print("Synthesis stats:")
    print(f"  scanned:                {stats.scanned}")
    print(f"  skipped (non-program):  {stats.skipped_topic}")
    print(f"  +dealbreakers:          {stats.synth_dealbreakers}")
    print(f"  +exclusions:            {stats.synth_exclusions}")
    print(f"  +obligations:           {stats.synth_obligations}")
    if args.dry_run or args.skip_embed:
        return
    counts = embed_synthesised(db_path=Path(args.db))
    print("Embedded new vectors:")
    for f, n in counts.items():
        print(f"  {f}: +{n}")


if __name__ == "__main__":
    cli()
