#!/usr/bin/env python3
"""GG7 — Fan out 432 Wave 60-94 outcome × 5 cohort variants (2,160 rows).

Per ``(outcome × cohort)`` cell the generator emits:

* ``gloss`` — 1-2 sentence cohort-specific viewpoint on the generic
  outcome. Derived from the cohort persona style + the outcome cohort
  bucket. Pure template composition, NO LLM.
* ``next_step`` — 1-2 sentence cohort-specific workflow integration
  hint. Joins the outcome cohort to the cohort's canonical practical
  step set.
* ``cohort_saving_yen_per_query`` — integer ¥ saving / query, computed
  from the FF1 SOT tier table (Tier A=¥3 ... D=¥30) × cohort tier mix.

All inputs are deterministic and pre-computed; the generator never
imports an LLM SDK. Wall time on a M1 macbook: ~3-5 sec serial
(no need for the ProcessPool for 2,160 rows of pure-Python work).

Constraints
-----------
* NO LLM API. Rule-based template generation only.
* Idempotent — INSERT OR REPLACE on ``(outcome_id, cohort)``.
* mypy --strict clean / ruff clean / no LLM SDK import.
* The 432 outcome catalog is sourced from
  ``scripts/aws_credit_ops/pre_map_outcomes_to_top_chunks_2026_05_17.py``
  (single source of truth — GG4 already established the synthetic 432-row
  fallback that this generator re-uses).

Usage
-----
    .venv/bin/python scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py \\
        --db autonomath.db \\
        --commit
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from scripts.aws_credit_ops.pre_map_outcomes_to_top_chunks_2026_05_17 import (
    WAVE_60_94_OUTCOMES,
    OutcomeRow,
    load_outcomes,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger("jpcite.gg7.cohort_variants")

# Canonical 5 cohort enumeration (mirrors moat_lane_tools._shared_cohort
# when that module is present).
COHORT_IDS: Final[tuple[str, ...]] = (
    "zeirishi",
    "kaikeishi",
    "gyouseishoshi",
    "shihoshoshi",
    "chusho_keieisha",
)

#: Per-cohort Japanese label used in gloss + next_step composition.
COHORT_LABELS_JA: Final[dict[str, str]] = {
    "zeirishi": "税理士",
    "kaikeishi": "会計士",
    "gyouseishoshi": "行政書士",
    "shihoshoshi": "司法書士",
    "chusho_keieisha": "中小経営者",
}

#: Per-cohort rep tier (FF1 SOT §4.2 mix-weighted, primary tier per
#: cohort).
COHORT_REP_TIER: Final[dict[str, str]] = {
    "zeirishi": "B",
    "kaikeishi": "C",
    "gyouseishoshi": "B",
    "shihoshoshi": "A",
    "chusho_keieisha": "C",
}

#: Tier -> jpcite ¥/req (FF1 SOT §3).
TIER_YEN: Final[dict[str, int]] = {
    "A": 3,
    "B": 6,
    "C": 12,
    "D": 30,
}

#: Tier -> Opus equivalent ¥ (FF1 SOT §3, equivalent-depth Opus value).
TIER_OPUS_YEN: Final[dict[str, int]] = {
    "A": 54,
    "B": 170,
    "C": 347,
    "D": 500,
}

#: Per-cohort canonical viewpoint phrase (gloss template head).
COHORT_VIEWPOINT_HEAD: Final[dict[str, str]] = {
    "zeirishi": (
        "顧問先実務に直結する税務処理として、別表記載 + 損金算入判定 + "
        "措置法適用要件の観点で本 outcome を読み解きます。"
    ),
    "kaikeishi": (
        "監査計画 + リスク評価 + 関連当事者 mapping + 内部統制 reference の "
        "観点で本 outcome を監査調書 draft に折り込みます。"
    ),
    "gyouseishoshi": (
        "許認可申請 / 補助金申請の必要書類 + 添付書類 + 副本部数 + "
        "申請順序の観点で本 outcome を実務 workflow に組み込みます。"
    ),
    "shihoshoshi": (
        "商業登記 / 不動産登記の申請書面 + 添付書類 + 登記原因証明情報 "
        "の観点で本 outcome を申請順序通りに編成します。"
    ),
    "chusho_keieisha": (
        "経営判断に直結する補助金 / 税制 / 融資 portfolio の観点で "
        "本 outcome を 5年 roadmap に組み込みます。"
    ),
}

#: Per-cohort canonical next-step phrase tail (workflow integration).
COHORT_NEXTSTEP_TAIL: Final[dict[str, str]] = {
    "zeirishi": (
        "別表4 加算減算項目を確定し、損金算入 / 益金算入 を仕訳に紐付けて "
        "月次 closing workflow に追加してください。"
    ),
    "kaikeishi": (
        "リスク評価 risk matrix (5x5) を更新し、関連当事者取引 mapping を "
        "PBC list に折り込んで監査計画書 draft を更新してください。"
    ),
    "gyouseishoshi": (
        "業種別 fence (建設業 / 宅建 / 古物 等) を申請先 自治体毎に確定し、"
        "必要書類 checklist を顧客に交付してください。"
    ),
    "shihoshoshi": (
        "登記原因 (売買 / 相続 / 増資 / 役員変更) を houjin_360 で特定し、"
        "添付書類の有効期限 (印鑑証明書 3ヶ月以内 等) を check してください。"
    ),
    "chusho_keieisha": (
        "月次資金繰り + 運転資金 needs を 3ヶ月 forecast で見える化し、"
        "補助金 portfolio 候補 3 件を quarterly review に折り込んでください。"
    ),
}

#: Cohort × outcome-category match table. The outcome catalog has 12
#: synthetic cohorts (Wave 60-94 buckets: ma / talent / brand / safety /
#: real_estate / insurance / tax / audit / gyousei / shihoshoshi / sme /
#: municipality). Each cohort persona has a natural overlap with a subset
#: of those buckets — this match boosts the gloss specificity.
COHORT_OUTCOME_BUCKET_MATCH: Final[dict[str, frozenset[str]]] = {
    "zeirishi": frozenset({"tax", "audit", "sme"}),
    "kaikeishi": frozenset({"audit", "tax", "ma"}),
    "gyouseishoshi": frozenset({"gyousei", "municipality", "sme"}),
    "shihoshoshi": frozenset({"shihoshoshi", "real_estate", "ma"}),
    "chusho_keieisha": frozenset({"sme", "tax", "talent", "brand", "ma"}),
}

#: Wave 60-94 canonical 12 buckets (mirrors
#: ``pre_map_outcomes_to_top_chunks_2026_05_17.py``).
WAVE_60_94_BUCKETS: Final[tuple[str, ...]] = (
    "ma",
    "talent",
    "brand",
    "safety",
    "real_estate",
    "insurance",
    "tax",
    "audit",
    "gyousei",
    "shihoshoshi",
    "sme",
    "municipality",
)


@dataclass(frozen=True)
class CohortVariantRow:
    """One row of am_outcome_cohort_variant."""

    outcome_id: int
    cohort: str
    gloss: str
    next_step: str
    cohort_saving_yen_per_query: int
    computed_at: str


def _iso_utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _outcome_bucket(slug: str) -> str:
    """Extract the outcome bucket from a Wave 60-94 slug.

    The synthetic-fallback slug format is
    ``wave60_94_{bucket}_{idx}`` where ``{bucket}`` itself may contain
    underscores (e.g. ``real_estate``). Returns "other" if the bucket
    cannot be parsed (the cohort-mismatch path is still well-defined).
    """
    body = slug
    if body.startswith("wave60_94_"):
        body = body[len("wave60_94_") :]
    # Longest-bucket-prefix match wins so ``real_estate`` beats ``real``.
    for bucket in sorted(WAVE_60_94_BUCKETS, key=len, reverse=True):
        if body == bucket or body.startswith(f"{bucket}_"):
            return bucket
    # Production short slug fallback: first underscore-token.
    parts = slug.split("_")
    return parts[0] if parts else "other"


def _cohort_saving_yen(cohort: str, *, match: bool) -> int:
    """Per-query cohort saving in ¥.

    Formula (FF1 SOT §3 + §4):
        saving = opus_yen(tier) - jpcite_yen(tier)
        boost  = +20% when (cohort bucket × outcome bucket) match.
    """
    tier = COHORT_REP_TIER[cohort]
    raw_saving = TIER_OPUS_YEN[tier] - TIER_YEN[tier]
    if match:
        return int(round(raw_saving * 1.20))
    return int(raw_saving)


def build_gloss(outcome: OutcomeRow, cohort: str) -> str:
    """Compose the cohort-specific gloss for one (outcome, cohort) cell."""
    bucket = _outcome_bucket(outcome.slug)
    label = COHORT_LABELS_JA[cohort]
    head = COHORT_VIEWPOINT_HEAD[cohort]
    matched_buckets = COHORT_OUTCOME_BUCKET_MATCH[cohort]
    if bucket in matched_buckets:
        tail = (
            f"特に本 outcome は {label} の業務軸 ({bucket}) と直接重なるため、"
            f"そのまま顧問先業務 (月次 / 年次 closing / 申請 cycle) に折り込めます。"
        )
    else:
        tail = (
            f"本 outcome の業種軸 ({bucket}) は {label} の主担当ではないものの、"
            f"周辺領域として顧問先の Q&A / 通達 reference に使えます。"
        )
    return f"{head} {tail}"


def build_next_step(outcome: OutcomeRow, cohort: str) -> str:
    """Compose the cohort-specific next-step for one (outcome, cohort) cell."""
    bucket = _outcome_bucket(outcome.slug)
    label = COHORT_LABELS_JA[cohort]
    tail = COHORT_NEXTSTEP_TAIL[cohort]
    return (
        f"{label} の業務 workflow に本 outcome (#{outcome.outcome_id} / "
        f"bucket={bucket}) を組込む手順: {tail}"
    )


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply wave24_221 in-place if the table is missing.

    Idempotent — the migration is CREATE IF NOT EXISTS. Inline application
    lets the pipeline be the single-step seed for fresh checkouts.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS am_outcome_cohort_variant (
            variant_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_id                  INTEGER NOT NULL,
            cohort                      TEXT NOT NULL,
            gloss                       TEXT NOT NULL,
            next_step                   TEXT NOT NULL,
            cohort_saving_yen_per_query INTEGER NOT NULL,
            computed_at                 TEXT NOT NULL,
            CONSTRAINT ck_outcome_cohort_variant_cohort CHECK (cohort IN (
                'zeirishi', 'kaikeishi', 'gyouseishoshi',
                'shihoshoshi', 'chusho_keieisha'
            )),
            CONSTRAINT ck_outcome_cohort_variant_outcome_id CHECK (
                outcome_id >= 1 AND outcome_id <= 432
            ),
            CONSTRAINT ck_outcome_cohort_variant_saving_positive CHECK (
                cohort_saving_yen_per_query >= 0
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_outcome_cohort_variant_tuple
            ON am_outcome_cohort_variant(outcome_id, cohort);
        CREATE INDEX IF NOT EXISTS ix_outcome_cohort_variant_outcome_id
            ON am_outcome_cohort_variant(outcome_id);
        CREATE INDEX IF NOT EXISTS ix_outcome_cohort_variant_cohort
            ON am_outcome_cohort_variant(cohort);
        CREATE INDEX IF NOT EXISTS ix_outcome_cohort_variant_computed_at
            ON am_outcome_cohort_variant(computed_at);
        """
    )


def generate_variants(
    outcomes: Sequence[OutcomeRow],
    *,
    computed_at: str,
) -> list[CohortVariantRow]:
    """Generate the 432 × 5 = 2,160 cohort-variant rows."""
    rows: list[CohortVariantRow] = []
    for outcome in outcomes:
        bucket = _outcome_bucket(outcome.slug)
        for cohort in COHORT_IDS:
            match = bucket in COHORT_OUTCOME_BUCKET_MATCH[cohort]
            row = CohortVariantRow(
                outcome_id=outcome.outcome_id,
                cohort=cohort,
                gloss=build_gloss(outcome, cohort),
                next_step=build_next_step(outcome, cohort),
                cohort_saving_yen_per_query=_cohort_saving_yen(cohort, match=match),
                computed_at=computed_at,
            )
            rows.append(row)
    return rows


def upsert_variants(
    conn: sqlite3.Connection,
    rows: Sequence[CohortVariantRow],
) -> int:
    """INSERT OR REPLACE every (outcome_id, cohort) row."""
    if not rows:
        return 0
    payload = [
        (
            r.outcome_id,
            r.cohort,
            r.gloss,
            r.next_step,
            r.cohort_saving_yen_per_query,
            r.computed_at,
        )
        for r in rows
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO am_outcome_cohort_variant "
        "(outcome_id, cohort, gloss, next_step, "
        " cohort_saving_yen_per_query, computed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        payload,
    )
    return len(rows)


def run_generator(
    db_path: Path,
    *,
    commit: bool,
    outcomes_limit: int | None = None,
) -> dict[str, int]:
    """Top-level pipeline entry point."""
    if not db_path.exists():
        msg = f"DB not found: {db_path}"
        raise FileNotFoundError(msg)

    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)
        outcomes = load_outcomes(conn)
        if outcomes_limit is not None:
            outcomes = outcomes[:outcomes_limit]
        computed_at = _iso_utc_now()
        rows = generate_variants(outcomes, computed_at=computed_at)
        written = upsert_variants(conn, rows)
        if commit:
            conn.commit()
        else:
            conn.rollback()
        return {
            "outcomes": len(outcomes),
            "cohorts": len(COHORT_IDS),
            "rows_written": written,
            "rows_expected": len(outcomes) * len(COHORT_IDS),
        }
    finally:
        conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("autonomath.db"),
        help="Path to autonomath.db (default: ./autonomath.db).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit the transaction (default: dry-run / rollback).",
    )
    parser.add_argument(
        "--outcomes-limit",
        type=int,
        default=None,
        help="Limit the number of outcomes (debug only).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    summary = run_generator(
        args.db,
        commit=args.commit,
        outcomes_limit=args.outcomes_limit,
    )
    expected = WAVE_60_94_OUTCOMES * len(COHORT_IDS)
    logger.info(
        "GG7 cohort variants: outcomes=%d cohorts=%d rows=%d (expected=%d)",
        summary["outcomes"],
        summary["cohorts"],
        summary["rows_written"],
        expected,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
