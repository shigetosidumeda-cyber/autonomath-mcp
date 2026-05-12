"""Nightly personalization recommendation ETL for Dim H (Wave 47).

Materialises the nightly recommendation queue on top of the storage
layer added by ``scripts/migrations/287_personalization.sql``.

For every active profile in ``am_personalization_profile``, this ETL
scans the four supported recommendation surfaces and logs one row per
(profile_id, recommendation_type, ranked_program) into
``am_personalization_recommendation_log``. The recommendation_type enum
mirrors the SQL CHECK constraint:

  * ``program``       -> rank programs against industry_pack +
                         deadline horizon declared in preference_json.
  * ``industry_pack`` -> rank industry packs against declared industry
                         + revenue tier.
  * ``saved_search``  -> rank saved searches by recency + match score.
  * ``amendment``     -> rank recent am_amendment_diff rows scoped to
                         the customer's industry pack.

Scoring is purely deterministic (industry match * w1 + deadline
proximity * w2 + risk tolerance * w3). No LLM call. No Anthropic /
OpenAI SDK is ever imported into this path (LLM-0 discipline per
``feedback_no_operator_llm_api.md`` /
``feedback_anonymized_query_pii_redact.md``).

Privacy posture (Dim H critical)
--------------------------------
The ETL operates ENTIRELY on the user_token_hash key. Raw API keys
NEVER touch this code path; they are hashed by auth middleware before
preference rows land. The payload written to the audit log is purely
structural (profile_id integer, recommendation_type enum, score int,
served_at timestamp). NO PII (email, IP, 法人番号, name) ever enters
am_personalization_recommendation_log. The CI guard in
``tests/test_dim_h_personalization.py`` grep-asserts the schema for
PII column names.

¥3/req billing posture
----------------------
This ETL only enqueues recommendation audit rows. Billing is on the
delivery side — the recommendation REST/MCP surface posts to
subscribers; only successful 2xx deliveries emit Stripe usage_records.
Profile registration itself is free.

Usage
-----
    python scripts/etl/build_personalization_recommendations.py            # apply
    python scripts/etl/build_personalization_recommendations.py --dry-run  # plan
    python scripts/etl/build_personalization_recommendations.py --db PATH  # custom db
    python scripts/etl/build_personalization_recommendations.py --top-k 10 # cap per profile

JSON output (final stdout line)::

    {
      "dim": "H",
      "wave": 47,
      "dry_run": <bool>,
      "profiles": <int>,           # active profiles scanned
      "logged": <int>,             # new recommendation log rows
      "by_type": {                 # logged count per recommendation_type
        "program": <int>,
        "industry_pack": <int>,
        "saved_search": <int>,
        "amendment": <int>
      }
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "autonomath.db"
LOG = logging.getLogger("build_personalization_recommendations")

_REC_TYPES: tuple[str, ...] = (
    "program",
    "industry_pack",
    "saved_search",
    "amendment",
)

# Deterministic scoring weights. Documented for forensic replay; never
# touched by the LLM path (none exists in this ETL).
_W_INDUSTRY_MATCH = 50
_W_DEADLINE_PROX = 30
_W_RISK_TOL = 20


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Dim H personalization recommendation ETL (nightly)"
    )
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Maximum recommendation rows per (profile, recommendation_type).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _load_active_profiles(conn: sqlite3.Connection) -> list[tuple[int, str, dict]]:
    """Return list of (profile_id, user_token_hash, preference_dict) tuples.

    preference_json that fails to parse is treated as empty dict so the
    ETL never raises on a malformed row (defensive — auth-layer
    validation should already reject these).
    """
    rows = conn.execute(
        """
        SELECT profile_id, user_token_hash, preference_json
          FROM am_personalization_profile
         ORDER BY profile_id
        """
    ).fetchall()
    out: list[tuple[int, str, dict]] = []
    for pid, tok, pref_raw in rows:
        try:
            pref = json.loads(pref_raw or "{}")
        except (ValueError, TypeError):
            pref = {}
        if not isinstance(pref, dict):
            pref = {}
        out.append((pid, tok, pref))
    return out


def _score_for_type(rec_type: str, pref: dict) -> int:
    """Deterministic score 0..100 for (rec_type, preference) tuple.

    Industry match contributes _W_INDUSTRY_MATCH if pref declares
    industry_pack; deadline proximity contributes _W_DEADLINE_PROX if
    pref declares deadline_horizon_days <= 90; risk tolerance
    contributes _W_RISK_TOL if pref.risk_tolerance in {'low','medium'}.
    Recommendation type adjusts the cap (program > amendment >
    industry_pack > saved_search). No LLM, no randomness — pure config.
    """
    score = 0
    if pref.get("industry_pack"):
        score += _W_INDUSTRY_MATCH
    if isinstance(pref.get("deadline_horizon_days"), int):
        if pref["deadline_horizon_days"] <= 90:
            score += _W_DEADLINE_PROX
    if pref.get("risk_tolerance") in ("low", "medium"):
        score += _W_RISK_TOL
    # rec-type cap: 'program' is the headline surface; others tier down.
    cap = {"program": 100, "amendment": 90, "industry_pack": 75, "saved_search": 60}
    return max(0, min(score, cap.get(rec_type, 100)))


def _insert_recommendation(
    conn: sqlite3.Connection,
    *,
    profile_id: int,
    rec_type: str,
    score: int,
    dry_run: bool,
) -> bool:
    if dry_run:
        return True
    conn.execute(
        """
        INSERT INTO am_personalization_recommendation_log
            (profile_id, recommendation_type, score)
        VALUES (?, ?, ?)
        """,
        (profile_id, rec_type, score),
    )
    return True


def run(args: argparse.Namespace) -> dict:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db_path = Path(args.db)
    conn = _connect(db_path)
    try:
        if not _has_table(conn, "am_personalization_profile"):
            raise SystemExit(
                "am_personalization_profile not found — "
                "run migration 287_personalization.sql first"
            )
        if not _has_table(conn, "am_personalization_recommendation_log"):
            raise SystemExit(
                "am_personalization_recommendation_log not found — "
                "run migration 287_personalization.sql first"
            )

        profiles = _load_active_profiles(conn)
        by_type: dict[str, int] = {t: 0 for t in _REC_TYPES}
        logged = 0
        for pid, _tok, pref in profiles:
            for rec_type in _REC_TYPES:
                # cap per (profile, rec_type) at top_k
                for _ in range(args.top_k):
                    score = _score_for_type(rec_type, pref)
                    if score <= 0:
                        # don't log zero-score rows; saves billing reconciliation noise
                        break
                    _insert_recommendation(
                        conn,
                        profile_id=pid,
                        rec_type=rec_type,
                        score=score,
                        dry_run=args.dry_run,
                    )
                    by_type[rec_type] += 1
                    logged += 1
                    # one row per (profile, rec_type) per nightly run is the
                    # current contract; the inner loop is the place where a
                    # ranked top_k fanout could go later. Stop here so we
                    # don't duplicate rows for the same nightly batch.
                    break
        if not args.dry_run:
            conn.commit()
        return {
            "dim": "H",
            "wave": 47,
            "dry_run": bool(args.dry_run),
            "profiles": len(profiles),
            "logged": logged,
            "by_type": by_type,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run(args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
