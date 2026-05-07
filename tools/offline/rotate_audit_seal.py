#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""Rotate the JPINTEL_AUDIT_SEAL_KEYS HMAC secret (operator only).

MASTER_PLAN_v1 §S1 — audit_seal HMAC rotation policy + dual-key.

What this script does
---------------------
1. Generates a new secret via ``secrets.token_urlsafe(48)``.
2. Reads the current ``JPINTEL_AUDIT_SEAL_KEYS`` env var (if any) plus
   the live key registry rows from ``audit_seal_keys`` to compute the
   next ``key_version`` (max(v) + 1).
3. INSERTs the new key into ``audit_seal_keys`` with ``activated_at``
   = now, ``retired_at`` = NULL.
4. UPDATEs the previously active row(s) — ``retired_at`` IS NULL —
   to set ``retired_at`` = now (every old key keeps verifying because
   the verifier walks all keys; ``retired_at`` only signals "do not
   sign with this anymore").
5. Emits the merged JSON array. By default it goes to stdout (legacy
   behaviour); use ``--output-file PATH`` to write a chmod-600 file
   instead so the secret never touches stdout / shell history.

WARNING
-------
stdout output contains plaintext secrets. The operator's shell
history, clipboard buffer, terminal scrollback, tmux capture-pane log,
and iTerm2 shell-integration record can all retain plaintext copies.

Recommended invocations:

    # Safest: write a 0600 file the operator deletes after use.
    .venv/bin/python tools/offline/rotate_audit_seal.py \\
        --db data/jpintel.db --output-file /tmp/jpintel_keys.json

    # macOS: pipe straight into clipboard, never touching the screen.
    .venv/bin/python tools/offline/rotate_audit_seal.py \\
        --db data/jpintel.db | pbcopy

Never copy/paste the JSON inside a shared / recorded terminal session.

Anti-patterns this script avoids
--------------------------------
- **NO Anthropic / OpenAI / Gemini SDK import.** Per
  ``feedback_no_operator_llm_api`` the entire ``tools/offline/`` tree
  is now treated like the production runtime for the LLM-API ban.
  Rotation is pure deterministic Python + sqlite + secrets.
- **NO Fly secret push from inside the script.** The operator must run
  ``fly secrets set`` manually so the new key never touches a script
  log / shell history / CI artifact.

Usage (manual, on operator workstation)
---------------------------------------
    .venv/bin/python tools/offline/rotate_audit_seal.py \\
        --db data/jpintel.db \\
        --output-file /tmp/jpintel_keys.json \\
        --notes "2026-05-04 quarterly rotation"

    # Then on the operator's workstation, with the file contents:
    fly secrets set -a autonomath-api \\
        JPINTEL_AUDIT_SEAL_KEYS="$(cat /tmp/jpintel_keys.json)"
    shred -u /tmp/jpintel_keys.json   # or `rm -P` on macOS
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Hard guard: never let an LLM SDK leak in here. Operator memory
# `feedback_no_operator_llm_api` extends the no-LLM invariant to
# tools/offline/ for the rotation tool. The CI guard
# tests/test_no_llm_in_production.py is being extended to cover this
# directory; this assert is defence-in-depth so a future edit cannot
# silently introduce one.
# ---------------------------------------------------------------------------
_FORBIDDEN_MODULES = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
for _m in _FORBIDDEN_MODULES:
    if _m in sys.modules:
        raise RuntimeError(
            f"tools/offline/rotate_audit_seal.py must not import {_m!r} "
            "(feedback_no_operator_llm_api)"
        )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_env_keys() -> list[dict]:
    """Return JPINTEL_AUDIT_SEAL_KEYS parsed, or [] when unset/invalid."""
    raw = os.environ.get("JPINTEL_AUDIT_SEAL_KEYS")
    if not raw:
        return []
    try:
        keys = json.loads(raw)
    except (TypeError, ValueError) as exc:
        print(f"[warn] JPINTEL_AUDIT_SEAL_KEYS is not valid JSON: {exc}", file=sys.stderr)
        return []
    if not isinstance(keys, list):
        return []
    out: list[dict] = []
    for k in keys:
        if not isinstance(k, dict):
            continue
        v = k.get("v")
        s = k.get("s")
        if not isinstance(v, int) or not isinstance(s, str) or not s:
            continue
        out.append({"v": v, "s": s, "retired_at": k.get("retired_at")})
    return out


def _next_key_version(env_keys: list[dict], db_max: int | None) -> int:
    candidates = [int(k["v"]) for k in env_keys] + ([int(db_max)] if db_max else [])
    return (max(candidates) if candidates else 0) + 1


def _ensure_registry_table(conn: sqlite3.Connection) -> None:
    """Create the registry if migration wave24_105 has not yet run.

    Idempotent — uses IF NOT EXISTS. The script can run on a fresh DB
    (e.g. operator running rotation before the next Fly boot applies
    migrations) without crashing.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_seal_keys (
            key_version    INTEGER PRIMARY KEY,
            secret_argon2  TEXT,
            activated_at   TEXT NOT NULL,
            retired_at     TEXT,
            last_seen_at   TEXT,
            notes          TEXT
        );
        """
    )


def rotate(
    *,
    db_path: Path,
    notes: str | None = None,
    dry_run: bool = False,
    clear_old_keys_after: int | None = None,
) -> dict:
    """Perform one rotation step. Returns a dict with the new key + JSON.

    ``clear_old_keys_after`` (operator option): when set to N>=1, after
    inserting the new active row delete the oldest rows from
    ``audit_seal_keys`` so that at most N retired rows remain. The
    currently-active row is never deleted. No-op when ``dry_run`` is
    True. Default ``None`` keeps every historical row.
    """
    new_secret = secrets.token_urlsafe(48)

    env_keys = _load_env_keys()

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_registry_table(conn)
        # Compute next key_version from both the env var and the registry,
        # so a partially-applied previous rotation cannot collide.
        row = conn.execute("SELECT MAX(key_version) FROM audit_seal_keys").fetchone()
        db_max = row[0] if row and row[0] is not None else None
        new_v = _next_key_version(env_keys, db_max)
        now = _now_iso()

        if not dry_run:
            # 1. Mark every previously active row as retired.
            conn.execute(
                "UPDATE audit_seal_keys SET retired_at = ? WHERE retired_at IS NULL",
                (now,),
            )
            # 2. Insert the new active row. We do NOT store the secret
            #    in the DB (only the secret_argon2 column would qualify
            #    and operators may opt in via a future hashed-store path
            #    — for now, leave NULL so a DB compromise never reveals
            #    secret material).
            conn.execute(
                "INSERT INTO audit_seal_keys("
                "  key_version, secret_argon2, activated_at, retired_at,"
                "  last_seen_at, notes) "
                "VALUES (?, NULL, ?, NULL, NULL, ?)",
                (new_v, now, notes),
            )
            # 3. Optional sweep: keep at most N retired rows.
            if clear_old_keys_after is not None and clear_old_keys_after >= 1:
                conn.execute(
                    "DELETE FROM audit_seal_keys "
                    "WHERE key_version IN ("
                    "  SELECT key_version FROM audit_seal_keys "
                    "  WHERE retired_at IS NOT NULL "
                    "  ORDER BY key_version DESC "
                    "  LIMIT -1 OFFSET ?"
                    ")",
                    (int(clear_old_keys_after),),
                )
            conn.commit()
    finally:
        conn.close()

    # Build the merged JSON for the new env var:
    #   * every previously known key (v < new_v) gets retired_at set if
    #     it was still active in the env var,
    #   * the new key is appended as active.
    merged: list[dict] = []
    for k in env_keys:
        merged.append(
            {
                "v": k["v"],
                "s": k["s"],
                "retired_at": k.get("retired_at") or now,
            }
        )
    merged.append({"v": new_v, "s": new_secret, "retired_at": None})

    return {
        "new_key_version": new_v,
        "new_secret": new_secret,
        "activated_at": now,
        "json_array": merged,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Rotate the JPINTEL_AUDIT_SEAL_KEYS HMAC secret (operator only). "
            "WARNING: stdout output contains plaintext secrets — prefer "
            "--output-file <path> (writes chmod 600) over capturing stdout "
            "in shells that record history / scrollback / tmux logs."
        )
    )
    p.add_argument(
        "--db",
        type=Path,
        default=Path("data/jpintel.db"),
        help="Path to jpintel.db (default: data/jpintel.db)",
    )
    p.add_argument(
        "--notes",
        type=str,
        default=None,
        help="Optional free-text notes recorded in audit_seal_keys.notes",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute the next key_version and report the count without "
            "mutating the registry. NEVER prints secret material — even "
            "the merged JSON is suppressed; use --output-file to commit."
        ),
    )
    p.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help=(
            "Write the merged JSON array to PATH with permission 0600 "
            "and emit nothing on stdout. Recommended over the legacy "
            "stdout path — stdout leaks into shell history / scrollback / "
            "tmux logs / iTerm shell-integration."
        ),
    )
    p.add_argument(
        "--clear-old-keys-after",
        type=int,
        default=None,
        metavar="N",
        help=(
            "After inserting the new active row, keep at most N retired "
            "rows in audit_seal_keys (oldest deleted first). The active "
            "row is always preserved. Default: keep every row."
        ),
    )
    args = p.parse_args(argv)

    if not args.db.exists():
        print(f"[err] DB not found: {args.db}", file=sys.stderr)
        return 2

    if args.clear_old_keys_after is not None and args.clear_old_keys_after < 1:
        print(
            "[err] --clear-old-keys-after must be a positive integer",
            file=sys.stderr,
        )
        return 2

    result = rotate(
        db_path=args.db,
        notes=args.notes,
        dry_run=args.dry_run,
        clear_old_keys_after=args.clear_old_keys_after,
    )

    # Human-readable summary on stderr so the JSON on stdout (when used)
    # stays clean for shell pipelines.
    print(
        f"[ok] new key_version = {result['new_key_version']} "
        f"(activated_at = {result['activated_at']})",
        file=sys.stderr,
    )

    if args.dry_run:
        # Defence-in-depth against secret leak: dry-run NEVER emits the
        # merged JSON, even though the secret was generated in-memory.
        # Operator gets a count + an explicit nudge to re-run with
        # --output-file when they want to commit.
        print(
            f"[dry-run] {len(result['json_array'])} keys would be rotated; "
            "no mutation performed and no secret material printed. "
            "Re-run without --dry-run and with --output-file <path> to commit.",
            file=sys.stderr,
        )
        return 0

    if args.output_file is not None:
        out_path = args.output_file
        # Write atomically via os.open with 0600 so the file is never
        # world-readable even between `open` and `chmod`.
        fd = os.open(
            str(out_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(result["json_array"], ensure_ascii=False))
        except BaseException:
            # If the open succeeded but write failed, fdopen already
            # closed fd above; nothing else to clean up.
            raise
        # Belt-and-braces: chmod 600 again in case umask interfered.
        os.chmod(str(out_path), 0o600)
        print(
            f"[ok] wrote merged keys to {out_path} (chmod 600). "
            "After loading into Fly secrets, securely delete: "
            f"`shred -u {out_path}` (Linux) or `rm -P {out_path}` (macOS).",
            file=sys.stderr,
        )
        print(
            f'[next] fly secrets set -a autonomath-api JPINTEL_AUDIT_SEAL_KEYS="$(cat {out_path})"',
            file=sys.stderr,
        )
        return 0

    # Legacy stdout path. Still supported for `| pbcopy` pipelines, but
    # warn the operator on stderr that the secret is now exposed.
    print(
        "[next] copy the JSON below into:\n"
        "    fly secrets set -a autonomath-api JPINTEL_AUDIT_SEAL_KEYS='<paste>'",
        file=sys.stderr,
    )
    print(json.dumps(result["json_array"], ensure_ascii=False))
    print(
        "WARNING: secret in stdout — clear shell history with: "
        "`history -c && history -w` (bash/zsh). Also consider clearing "
        "tmux scrollback (`Ctrl-b :clear-history`) and iTerm session log.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
