#!/usr/bin/env python3
"""Daily Merkle hash chain anchor — audit log moat.

Walks the previous JST calendar day's `usage_events` rows (jpintel.db),
hashes them as Merkle leaves, computes a daily root, persists into
`audit_merkle_anchor` + `audit_merkle_leaves` (autonomath.db, migration
146), and anchors the root to two third-party clocks:

  1. **OpenTimestamps** — `ots stamp <tmpfile>` writes a calendar
     receipt (.ots) which we read back into `ots_proof` BLOB. If the
     `ots` binary (`opentimestamps-client`) is not installed, we log
     a warning and proceed with `ots_proof = NULL`.
  2. **GitHub commit** — `gh api` posts an empty commit on `main`
     with the daily root in the message. SHA goes into
     `github_commit_sha`. If `gh` is unavailable / unauthenticated,
     we log a warning and proceed with `github_commit_sha = NULL`.

Idempotent. Re-running for the same `daily_date` is a no-op (PK
collision triggers UPDATE if `--reanchor` is passed; default is INSERT
OR IGNORE so a re-run after partial completion only fills the missing
anchor without rewriting the leaves).

Leaf hash recipe
----------------
    leaf_hash = sha256(epid || content_hash || timestamp)

where:
    epid          = "evp_" || str(usage_events.id)
    content_hash  = usage_events.params_digest (canonical request hash)
    timestamp     = usage_events.ts (ISO-8601 UTC string)

Merkle build
------------
* Pairwise SHA256(left || right) of leaf hashes (Bitcoin-style).
* Odd-count rows duplicate the last `left` node so the tree always
  closes to a single root.
* All hashes are lowercase hex.

Invocation
----------
    python scripts/cron/merkle_anchor_daily.py
    python scripts/cron/merkle_anchor_daily.py --dry-run
    python scripts/cron/merkle_anchor_daily.py --date 2026-05-04
    python scripts/cron/merkle_anchor_daily.py --skip-ots --skip-github

Schedule
--------
GitHub Actions cron at 00:30 JST (15:30 UTC prior day) so the
previous JST day is fully closed when we anchor.

NO LLM. Pure SQLite + standard library + subprocess to `ots` / `gh`.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402

logger = logging.getLogger("autonomath.cron.merkle_anchor_daily")

# JST = UTC+9. The day boundary for "prior day" is JST 00:00 → 23:59:59.
_JST = timezone(timedelta(hours=9))


def _epid(usage_event_id: int) -> str:
    """Stable evidence-packet identifier for a usage_events row."""
    return f"evp_{usage_event_id}"


def _leaf_hash(epid: str, content_hash: str | None, ts: str) -> str:
    """sha256(epid || content_hash || timestamp), hex-encoded.

    `content_hash` is the canonical params_digest; if NULL we substitute
    an empty string so the hash is still well-defined (the leaf is
    cryptographically anchored to whatever the row literally contained).
    """
    h = hashlib.sha256()
    h.update(epid.encode("utf-8"))
    h.update((content_hash or "").encode("utf-8"))
    h.update((ts or "").encode("utf-8"))
    return h.hexdigest()


def _merkle_parent(left_hex: str, right_hex: str) -> str:
    """SHA256(left || right) over the raw bytes (not hex), hex-encoded."""
    h = hashlib.sha256()
    h.update(bytes.fromhex(left_hex))
    h.update(bytes.fromhex(right_hex))
    return h.hexdigest()


def _build_merkle_root(leaf_hashes: list[str]) -> str:
    """Compute the Merkle root from an ordered list of leaf hex hashes.

    Empty input returns the SHA256 of the empty byte string (well-defined
    sentinel root for "no leaves on this day"); the caller can decide
    whether to persist that or skip.
    """
    if not leaf_hashes:
        return hashlib.sha256(b"").hexdigest()
    layer = list(leaf_hashes)
    while len(layer) > 1:
        nxt: list[str] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left  # duplicate odd tail
            nxt.append(_merkle_parent(left, right))
        layer = nxt
    return layer[0]


def _build_proof_path(leaf_hashes: list[str], leaf_index: int) -> list[dict[str, str]]:
    """Return the sibling-hash path from `leaf_index` up to the root.

    Each entry is {"position": "left"|"right", "hash": "<hex>"}. Verifier
    folds them into the leaf left-to-right.
    """
    if not leaf_hashes or leaf_index < 0 or leaf_index >= len(leaf_hashes):
        return []
    layer = list(leaf_hashes)
    idx = leaf_index
    out: list[dict[str, str]] = []
    while len(layer) > 1:
        sibling_idx = idx ^ 1
        if sibling_idx >= len(layer):
            sibling_idx = idx  # odd-tail duplicate
        position = "right" if idx % 2 == 0 else "left"
        out.append({"position": position, "hash": layer[sibling_idx]})
        # Build next layer.
        nxt: list[str] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left
            nxt.append(_merkle_parent(left, right))
        layer = nxt
        idx //= 2
    return out


def _jst_window(target_date: str) -> tuple[str, str]:
    """Return (start_utc_iso, end_utc_iso) for JST 00:00 → 23:59:59.999999 of `target_date`.

    `target_date` is YYYY-MM-DD interpreted in JST. We translate to UTC
    bounds because `usage_events.ts` is stored as UTC ISO-8601.
    """
    d = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=_JST)
    start_utc = d.astimezone(UTC).isoformat()
    end_utc = (d + timedelta(days=1)).astimezone(UTC).isoformat()
    return start_utc, end_utc


def _fetch_leaves(jp_conn: sqlite3.Connection, target_date: str) -> list[tuple[str, str]]:
    """Return ordered (epid, leaf_hash) for the JST-day `usage_events` rows.

    Order is `(ts ASC, id ASC)` so re-runs reproduce identical roots.
    Missing `params_digest` (older rows) is treated as empty string.
    """
    start_utc, end_utc = _jst_window(target_date)
    rows = jp_conn.execute(
        "SELECT id, params_digest, ts FROM usage_events "
        "WHERE ts >= ? AND ts < ? "
        "ORDER BY ts ASC, id ASC",
        (start_utc, end_utc),
    ).fetchall()
    out: list[tuple[str, str]] = []
    for r in rows:
        epid = _epid(int(r["id"]))
        out.append((epid, _leaf_hash(epid, r["params_digest"], r["ts"])))
    return out


def _stamp_with_ots(root_hex: str) -> bytes | None:
    """Anchor `root_hex` via `ots stamp`. Returns the .ots bytes or None on failure."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "root.bin"
        src.write_bytes(bytes.fromhex(root_hex))
        try:
            res = subprocess.run(
                ["ots", "stamp", str(src)],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("ots binary not found — skipping OpenTimestamps anchor")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("ots stamp timed out — skipping OpenTimestamps anchor")
            return None
        if res.returncode != 0:
            logger.warning(
                "ots stamp returned %d: %s",
                res.returncode,
                res.stderr.decode("utf-8", "replace")[:500],
            )
            return None
        proof_path = src.with_suffix(src.suffix + ".ots")
        if not proof_path.exists():
            logger.warning("ots stamp produced no .ots file at %s", proof_path)
            return None
        return proof_path.read_bytes()


def _commit_to_github(daily_date: str, root_hex: str) -> str | None:
    """Post an empty commit embedding the root via `gh api`. Returns SHA or None.

    Uses GitHub's "create commit" API endpoint chain (get parent → create
    blob-less commit → update ref). We collapse this to a single `gh
    api` "create empty commit" via the dispatch_workflow alternative is
    fragile; instead we use `gh api repos/.../git/commits` after fetching
    HEAD. Any failure falls through to None — the OpenTimestamps proof
    is the primary anchor.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")  # set by Actions; required.
    if not repo:
        logger.warning("GITHUB_REPOSITORY unset — skipping GitHub anchor")
        return None
    msg = f"merkle-anchor {daily_date} root={root_hex}"
    try:
        # Fetch current HEAD SHA on default branch.
        head = subprocess.run(
            ["gh", "api", f"repos/{repo}/commits/HEAD", "--jq", ".sha"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("gh binary not found — skipping GitHub anchor")
        return None
    if head.returncode != 0:
        logger.warning("gh api HEAD returned %d: %s", head.returncode, head.stderr[:200])
        return None
    parent_sha = head.stdout.decode("utf-8").strip()
    if not parent_sha:
        logger.warning("gh api HEAD returned empty SHA")
        return None
    # Get the parent's tree SHA so we can re-use it (empty commit = same tree).
    tree = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits/{parent_sha}", "--jq", ".commit.tree.sha"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if tree.returncode != 0 or not tree.stdout.strip():
        logger.warning("gh api commit-tree returned %d", tree.returncode)
        return None
    tree_sha = tree.stdout.decode("utf-8").strip()
    # Create commit object with same tree (empty diff).
    create = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repo}/git/commits",
            "-f",
            f"message={msg}",
            "-f",
            f"tree={tree_sha}",
            "-f",
            f"parents[]={parent_sha}",
            "--jq",
            ".sha",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if create.returncode != 0 or not create.stdout.strip():
        logger.warning(
            "gh api create-commit returned %d: %s", create.returncode, create.stderr[:200]
        )
        return None
    new_sha = create.stdout.decode("utf-8").strip()
    # Advance the default branch ref. Discover the default branch name first.
    branch = subprocess.run(
        ["gh", "api", f"repos/{repo}", "--jq", ".default_branch"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    default_branch = branch.stdout.decode("utf-8").strip() or "main"
    upd = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{repo}/git/refs/heads/{default_branch}",
            "-f",
            f"sha={new_sha}",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if upd.returncode != 0:
        logger.warning("gh api update-ref returned %d: %s", upd.returncode, upd.stderr[:200])
        # Commit object exists but ref didn't move; SHA is still verifiable.
    return new_sha


def _persist(
    am_conn: sqlite3.Connection,
    daily_date: str,
    leaves: list[tuple[str, str]],
    merkle_root: str,
    ots_proof: bytes | None,
    github_commit_sha: str | None,
    *,
    reanchor: bool,
) -> None:
    """Write the anchor + leaves under a single transaction."""
    am_conn.execute("BEGIN IMMEDIATE")
    try:
        if reanchor:
            am_conn.execute(
                "INSERT INTO audit_merkle_anchor "
                "(daily_date, row_count, merkle_root, ots_proof, github_commit_sha) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(daily_date) DO UPDATE SET "
                "  row_count=excluded.row_count, "
                "  merkle_root=excluded.merkle_root, "
                "  ots_proof=COALESCE(excluded.ots_proof, audit_merkle_anchor.ots_proof), "
                "  github_commit_sha=COALESCE(excluded.github_commit_sha, audit_merkle_anchor.github_commit_sha)",
                (daily_date, len(leaves), merkle_root, ots_proof, github_commit_sha),
            )
        else:
            am_conn.execute(
                "INSERT OR IGNORE INTO audit_merkle_anchor "
                "(daily_date, row_count, merkle_root, ots_proof, github_commit_sha) "
                "VALUES (?, ?, ?, ?, ?)",
                (daily_date, len(leaves), merkle_root, ots_proof, github_commit_sha),
            )
        # Bulk insert leaves; (daily_date, leaf_index) PK guards re-runs.
        am_conn.executemany(
            "INSERT OR IGNORE INTO audit_merkle_leaves "
            "(daily_date, leaf_index, evidence_packet_id, leaf_hash) "
            "VALUES (?, ?, ?, ?)",
            [(daily_date, idx, epid, leaf_hash) for idx, (epid, leaf_hash) in enumerate(leaves)],
        )
        am_conn.execute("COMMIT")
    except Exception:
        am_conn.execute("ROLLBACK")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=None,
        help="JST date (YYYY-MM-DD) to anchor. Default: yesterday in JST.",
    )
    parser.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path).",
    )
    parser.add_argument(
        "--jp-db",
        type=Path,
        default=None,
        help="Path to jpintel.db (default: settings.db_path).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute root + leaves but do not write."
    )
    parser.add_argument("--skip-ots", action="store_true", help="Skip OpenTimestamps stamping.")
    parser.add_argument(
        "--skip-github", action="store_true", help="Skip GitHub empty-commit anchor."
    )
    parser.add_argument(
        "--reanchor",
        action="store_true",
        help="UPSERT the anchor row (overwrite ots_proof / github_commit_sha if newly available).",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    target_date = args.date or (datetime.now(_JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    am_db = Path(args.am_db) if args.am_db else Path(settings.autonomath_db_path)
    jp_db = Path(args.jp_db) if args.jp_db else Path(settings.db_path)

    if not am_db.exists():
        logger.error("autonomath.db not found at %s", am_db)
        return 2
    if not jp_db.exists():
        logger.warning("jpintel.db not found at %s — treating as zero leaves", jp_db)
        leaves: list[tuple[str, str]] = []
    else:
        jp_conn = sqlite3.connect(str(jp_db))
        jp_conn.row_factory = sqlite3.Row
        try:
            try:
                leaves = _fetch_leaves(jp_conn, target_date)
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc).lower():
                    logger.warning("usage_events missing on jpintel.db — treating as zero leaves")
                    leaves = []
                else:
                    raise
        finally:
            with contextlib.suppress(Exception):
                jp_conn.close()

    leaf_hashes = [lh for _, lh in leaves]
    merkle_root = _build_merkle_root(leaf_hashes)
    logger.info(
        "merkle root for %s: %s (leaves=%d)",
        target_date,
        merkle_root,
        len(leaves),
    )

    if args.dry_run:
        logger.info("dry-run: skipping anchor + persist")
        return 0

    ots_proof: bytes | None = None
    if not args.skip_ots and leaves:
        ots_proof = _stamp_with_ots(merkle_root)
        if ots_proof is not None:
            logger.info("OpenTimestamps proof: %d bytes", len(ots_proof))

    github_commit_sha: str | None = None
    if not args.skip_github and leaves:
        github_commit_sha = _commit_to_github(target_date, merkle_root)
        if github_commit_sha:
            logger.info("GitHub commit SHA: %s", github_commit_sha)

    am_conn = sqlite3.connect(str(am_db))
    try:
        _persist(
            am_conn,
            daily_date=target_date,
            leaves=leaves,
            merkle_root=merkle_root,
            ots_proof=ots_proof,
            github_commit_sha=github_commit_sha,
            reanchor=args.reanchor,
        )
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()

    logger.info("persisted anchor for %s (rows=%d)", target_date, len(leaves))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
