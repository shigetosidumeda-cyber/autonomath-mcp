#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""W20 am_program_narrative_full batch sharder — full prose + 反駁 bank.

PURPOSE (migration wave24_149_am_program_narrative_full):
    Pre-render ONE coherent prose narrative + a paired 反駁 (counter-
    argument) markdown bank per program, keyed `program_id PRIMARY KEY`
    in `am_program_narrative_full`. Distinct from the 4-section
    `am_program_narrative` table (wave24_136); see migration 149 header
    for the schema split rationale.

WORKFLOW:
    1. operator: `python tools/offline/generate_program_narratives.py
                  --shards 25 --tier S,A,B,C [--limit N] [--dry-run]`
    2. THIS script (NO LLM CALL): SELECTs eligible (tier S/A/B/C) programs
                  from jpintel.db that are NOT yet in
                  autonomath.am_program_narrative_full, splits them into
                  N round-robin shards, and writes one batch JSON per
                  shard into tools/offline/_inbox/narrative/_batches/agentN.json.
    3. operator: launches N parallel Claude Code subagents (Max Pro Plan,
                  fixed cost). Each subagent reads its assigned batch JSON
                  and writes one JSONL row per program into
                  tools/offline/_inbox/narrative/{date}_{N}.jsonl.
    4. operator: runs the ingest cron (W20 §4) to UPSERT into
                  am_program_narrative_full keyed on program_id; CONFLICT
                  resolution = content_hash diff overwrites + bumps
                  generated_at, same hash = no-op (idempotent re-ingest).

NO LLM IMPORT. NO API KEY. The subagent invocation happens out-of-band
on the operator workstation per `feedback_no_operator_llm_api`.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
BATCHES_DIR = Path(__file__).resolve().parent / "_inbox" / "narrative" / "_batches"

DEFAULT_SHARDS = 25
DEFAULT_TIERS = "S,A,B,C"

# Output JSONL row shape that each subagent must produce per program.
# Validated downstream by the W20 ingest cron; mismatched rows are quarantined.
EXPECTED_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "program_id",
        "narrative_md",
        "counter_arguments_md",
        "model_used",
        "content_hash",
        "generated_at",
    ],
    "properties": {
        "program_id": {
            "type": "string",
            "description": "Must echo back the unified_id supplied in the input row (UNI-...).",
        },
        "narrative_md": {
            "type": "string",
            "minLength": 600,
            "description": "Coherent prose narrative in Japanese, ~600-1500字, markdown-formatted. "
            "Must reference the 一次資料 source_url. Must include 趣旨・対象・上限額・"
            "申請窓口・主要な落とし穴 in flowing prose (not bullet lists).",
        },
        "counter_arguments_md": {
            "type": "string",
            "minLength": 200,
            "description": "反駁 bank — この narrative の弱点・反論・よくある誤解 を箇条書き 3-7 項目で。"
            "auditor 補助用、申請者向けでない。",
        },
        "model_used": {
            "type": "string",
            "description": "Subagent / model identifier, e.g. 'claude-opus-4-7' or 'claude-code-subagent'.",
        },
        "content_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "description": "SHA-256 hex over narrative_md + '\\n---\\n' + counter_arguments_md.",
        },
        "source_program_corpus_snapshot_id": {
            "type": ["string", "null"],
            "description": "Opaque trace id of the corpus snapshot the subagent saw at gen time (audit).",
        },
        "generated_at": {
            "type": "string",
            "description": "ISO8601 UTC timestamp.",
        },
    },
}


SQL_PROGRAMS_PENDING_TEMPLATE = """
    SELECT unified_id, primary_name, authority_name, prefecture,
           program_kind, source_url, tier
      FROM programs
     WHERE excluded = 0
       AND tier IN ({tier_placeholders})
     ORDER BY tier ASC, unified_id ASC
"""

SQL_DONE = """
    SELECT program_id
      FROM am_program_narrative_full
"""


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def query_rows(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Read-only SELECT helper. No write paths in this script."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def list_pending(
    jpintel_db: Path,
    autonomath_db: Path,
    tiers: list[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in tiers)
    sql = SQL_PROGRAMS_PENDING_TEMPLATE.format(tier_placeholders=placeholders)
    programs = query_rows(jpintel_db, sql, tuple(tiers))

    # If the autonomath DB is missing the table (migration 149 not yet
    # applied on this machine), treat ALL programs as pending — the
    # ingest cron's UPSERT is idempotent so re-runs after the migration
    # ships are safe.
    try:
        done_rows = query_rows(autonomath_db, SQL_DONE)
        done_pids = {r["program_id"] for r in done_rows}
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        done_pids = set()

    pending = [p for p in programs if p["unified_id"] not in done_pids]
    if limit is not None:
        pending = pending[:limit]
    return pending


def shard_rows(rows: list[dict[str, Any]], n_shards: int) -> list[list[dict[str, Any]]]:
    """Round-robin shard assignment. Keeps tier mix balanced across agents."""
    shards: list[list[dict[str, Any]]] = [[] for _ in range(n_shards)]
    for i, row in enumerate(rows):
        shards[i % n_shards].append(row)
    return shards


def build_batch_payload(
    *,
    agent_index: int,
    shard_index_one_based: int,
    n_shards: int,
    rows: list[dict[str, Any]],
    tiers: list[str],
    inbox_jsonl_path: Path,
) -> dict[str, Any]:
    return {
        "_meta": {
            "tool": "generate_program_narratives",
            "migration": "wave24_149_am_program_narrative_full",
            "agent_id": f"agent{shard_index_one_based:02d}",
            "agent_index_zero_based": agent_index,
            "shard_index_one_based": shard_index_one_based,
            "n_shards": n_shards,
            "tiers": tiers,
            "row_count": len(rows),
            "generated_at": utc_now_iso(),
            "schema_version": 1,
            "inbox_jsonl_path": str(inbox_jsonl_path),
            "no_llm_in_this_script": True,
        },
        "instructions": {
            "task": (
                "For each input program below, write ONE JSONL row to "
                "the inbox_jsonl_path. Each row MUST conform to the "
                "expected_row_schema. Do NOT invent source URLs; cite "
                "only the source_url given. If you cannot reach the "
                "stated quality bar, skip the row (do not write a "
                "low-quality fallback)."
            ),
            "narrative_rules": [
                "narrative_md は 600-1500 字程度の連続した日本語散文。markdown 段落で書く。",
                "趣旨 / 対象 / 上限額 / 申請窓口 / 主要な落とし穴 を本文中で触れる。",
                "数字は source_url が裏付けるもののみ記載。推測の数値を書かない。",
                "「公募要領を必ずご確認ください」等の一次資料参照を末尾に含める。",
                "申請書面の作成 (行政書士法 §1 独占業務) を代替する文章は書かない。"
                " あくまで制度概説に留める。",
            ],
            "counter_arguments_rules": [
                "counter_arguments_md は 200-600 字程度、3-7 項目の箇条書き。",
                "「この narrative の弱点」「反論」「よくある誤解」「対象外と勘違いされやすい点」"
                "「上限額の頭打ち事例」等を auditor 補助の視点で列挙。",
                "申請者向けでなく、内部 reviewer / 監査向けの notes として書く。",
            ],
            "content_hash_rule": (
                "content_hash = SHA-256 hex over (narrative_md + '\\n---\\n' "
                "+ counter_arguments_md). Python: "
                "hashlib.sha256((narrative_md + '\\n---\\n' + counter_arguments_md)"
                ".encode('utf-8')).hexdigest()."
            ),
            "model_used_rule": (
                "model_used は subagent / model 識別子。例: 'claude-opus-4-7' or "
                "'claude-code-subagent'。"
            ),
            "completion_marker": (
                "全 row 書き込み完了後、stdout に "
                "`AGENT_DONE shard=<i>/<n> rows=<k>` を 1 行で出すこと。"
            ),
        },
        "expected_row_schema": EXPECTED_ROW_SCHEMA,
        "rows": rows,
    }


def write_batch(payload: dict[str, Any], out_path: Path, dry_run: bool) -> None:
    if dry_run:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--shards",
        type=int,
        default=DEFAULT_SHARDS,
        help=f"Number of agent shards (default {DEFAULT_SHARDS}).",
    )
    p.add_argument(
        "--tier",
        default=DEFAULT_TIERS,
        help=f"Comma-separated tier list (default '{DEFAULT_TIERS}').",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap total pending rows before sharding (smoke test convenience).",
    )
    p.add_argument(
        "--jpintel-db",
        default=str(DEFAULT_JPINTEL_DB),
        help=f"Path to jpintel.db (default {DEFAULT_JPINTEL_DB}).",
    )
    p.add_argument(
        "--autonomath-db",
        default=str(DEFAULT_AUTONOMATH_DB),
        help=f"Path to autonomath.db (default {DEFAULT_AUTONOMATH_DB}).",
    )
    p.add_argument(
        "--out-dir",
        default=str(BATCHES_DIR),
        help=f"Output directory for agentN.json files (default {BATCHES_DIR}).",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    tiers = [t.strip().upper() for t in args.tier.split(",") if t.strip()]
    if not tiers:
        print("ERROR: --tier must include at least one tier.", file=sys.stderr)
        return 2
    if args.shards < 1:
        print("ERROR: --shards must be >= 1.", file=sys.stderr)
        return 2

    jpintel_db = Path(args.jpintel_db)
    autonomath_db = Path(args.autonomath_db)
    out_dir = Path(args.out_dir)

    if not jpintel_db.exists():
        print(f"ERROR: jpintel db not found: {jpintel_db}", file=sys.stderr)
        return 2

    pending = list_pending(jpintel_db, autonomath_db, tiers, args.limit)
    n_shards = min(args.shards, max(1, len(pending)))
    shards = shard_rows(pending, n_shards)

    print("=" * 78)
    print("# generate_program_narratives.py  (W20 / migration 149)")
    print(f"# tiers              : {tiers}")
    print(f"# pending program ct : {len(pending)}")
    print(f"# shards             : {n_shards}")
    print(f"# out dir            : {out_dir}")
    print(f"# dry_run            : {args.dry_run}")
    print(f"# generated_at       : {utc_now_iso()}")
    print("=" * 78)

    written: list[Path] = []
    for i, shard in enumerate(shards):
        agent_id = f"agent{i + 1:02d}"
        inbox_jsonl_path = (
            Path(__file__).resolve().parent
            / "_inbox"
            / "narrative"
            / f"{datetime.now(UTC).strftime('%Y%m%d')}_{agent_id}.jsonl"
        )
        payload = build_batch_payload(
            agent_index=i,
            shard_index_one_based=i + 1,
            n_shards=n_shards,
            rows=shard,
            tiers=tiers,
            inbox_jsonl_path=inbox_jsonl_path,
        )
        out_path = out_dir / f"{agent_id}.json"
        write_batch(payload, out_path, args.dry_run)
        written.append(out_path)
        print(f"  {agent_id}: rows={len(shard):>5}  -> {out_path}")

    print("=" * 78)
    print(f"# wrote {len(written)} batch file(s) (dry_run={args.dry_run})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
