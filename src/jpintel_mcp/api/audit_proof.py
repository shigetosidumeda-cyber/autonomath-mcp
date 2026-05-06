"""Public Merkle proof endpoint — third-party verifiable audit log moat.

Exposes per-evidence-packet Merkle inclusion proofs from
`audit_merkle_anchor` + `audit_merkle_leaves` (autonomath.db, migration
146; populated daily by ``scripts/cron/merkle_anchor_daily.py``).

Why public read
---------------
The audit log moat IS the moat. Hiding inclusion proofs behind paid
auth would defeat the trust-by-transparency posture: anyone who holds
a citation to ``evidence_packet_id`` (e.g. a §52 disclaimer string in
their own audit working paper) must be able to verify, without an
account, that:

  1. the row was committed to a daily Merkle root, and
  2. the root was anchored to OpenTimestamps + a GitHub commit.

If both anchors check out, the row can be proven to have existed at
or before the anchor's calendar timestamp — strong cryptographic
evidence against post-hoc tampering.

Endpoint
--------
``GET /v1/audit/proof/{evidence_packet_id}``

Response envelope (always JSON):

```
{
  "epid": "evp_12345",
  "daily_date": "2026-05-04",
  "leaf_index": 73,
  "leaf_hash": "<hex>",
  "proof_path": [{"position": "left"|"right", "hash": "<hex>"}, ...],
  "merkle_root": "<hex>",
  "ots_url": "https://opentimestamps.org/...",  // null if no OTS proof
  "github_commit_url": "https://github.com/.../commit/<sha>",  // null if no commit
  "_disclaimer": "..."
}
```

The verifier fold:
    h = leaf_hash
    for entry in proof_path:
        if entry.position == "left":
            h = sha256(entry.hash || h)
        else:
            h = sha256(h || entry.hash)
    assert h == merkle_root

NOT a tax-advice surface — pure cryptographic provenance.
Carries `_disclaimer` per Wave 30 §52 hardening for consistency with
sibling /v1/audit/* surfaces, but the disclaimer here is the
provenance / non-substitution variant (no tax interpretation).
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.audit_proof")

router = APIRouter(prefix="/v1/audit", tags=["audit-proof"])


_PROOF_DISCLAIMER = (
    "本エンドポイントは Merkle 包含証明を返却する暗号学的監査基盤であり、"
    "税理士法 §52 / 公認会計士法 §47条の2 に基づく税務判断・監査意見の代替で"
    "はありません。 検証は OpenTimestamps + GitHub commit の両証跡で行ってく"
    "ださい。"
)

_EPID_RE = re.compile(r"^evp_[A-Za-z0-9_]{1,64}$")


def _open_autonomath_rw() -> sqlite3.Connection:
    """Read-only-by-intent connection to autonomath.db at the configured path.

    We use the same ``AUTONOMATH_DB_PATH`` env var as the cron writer.
    Note: connect_autonomath() in autonomath_tools.db is thread-locally
    cached and Wave-3-gated to read-only mode; we replicate the file
    open here without polluting that cache (this endpoint may run on
    request threads that should not pin a connection).
    """
    path = os.environ.get("AUTONOMATH_DB_PATH", str(settings.autonomath_db_path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ots_url_for(proof: bytes | None) -> str | None:
    """Best-effort URL into the OpenTimestamps web verifier.

    OpenTimestamps does not have a stable per-proof URL; the canonical
    verification flow is the `ots verify` CLI against the .ots blob.
    We expose the public web upload form so a manual verifier can
    paste the hex root, and we let the JSON envelope include the raw
    proof via a sibling endpoint if needed (out of scope for v1).
    """
    if not proof:
        return None
    return "https://opentimestamps.org/"


def _github_commit_url(sha: str | None) -> str | None:
    if not sha:
        return None
    repo = os.environ.get("GITHUB_REPOSITORY", "bookyou/jpcite")
    return f"https://github.com/{repo}/commit/{sha}"


def _fetch_leaf(am_conn: sqlite3.Connection, epid: str) -> tuple[str, int, str] | None:
    """Return (daily_date, leaf_index, leaf_hash) for `epid` or None."""
    row = am_conn.execute(
        "SELECT daily_date, leaf_index, leaf_hash "
        "FROM audit_merkle_leaves WHERE evidence_packet_id = ? "
        "ORDER BY daily_date DESC LIMIT 1",
        (epid,),
    ).fetchone()
    if row is None:
        return None
    return (row["daily_date"], int(row["leaf_index"]), row["leaf_hash"])


def _fetch_anchor(am_conn: sqlite3.Connection, daily_date: str) -> dict[str, Any] | None:
    row = am_conn.execute(
        "SELECT daily_date, row_count, merkle_root, ots_proof, "
        "       github_commit_sha, twitter_post_id, created_at "
        "FROM audit_merkle_anchor WHERE daily_date = ?",
        (daily_date,),
    ).fetchone()
    if row is None:
        return None
    return {
        "daily_date": row["daily_date"],
        "row_count": int(row["row_count"]),
        "merkle_root": row["merkle_root"],
        "ots_proof": row["ots_proof"],
        "github_commit_sha": row["github_commit_sha"],
        "twitter_post_id": row["twitter_post_id"],
        "created_at": row["created_at"],
    }


def _fetch_all_leaves(am_conn: sqlite3.Connection, daily_date: str) -> list[str]:
    rows = am_conn.execute(
        "SELECT leaf_hash FROM audit_merkle_leaves WHERE daily_date = ? ORDER BY leaf_index ASC",
        (daily_date,),
    ).fetchall()
    return [r["leaf_hash"] for r in rows]


def _merkle_parent(left_hex: str, right_hex: str) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(bytes.fromhex(left_hex))
    h.update(bytes.fromhex(right_hex))
    return h.hexdigest()


def _build_proof_path(leaf_hashes: list[str], leaf_index: int) -> list[dict[str, str]]:
    """Same algorithm as the cron — kept local so the endpoint has zero cron deps."""
    if not leaf_hashes or leaf_index < 0 or leaf_index >= len(leaf_hashes):
        return []
    layer = list(leaf_hashes)
    idx = leaf_index
    out: list[dict[str, str]] = []
    while len(layer) > 1:
        sibling_idx = idx ^ 1
        if sibling_idx >= len(layer):
            sibling_idx = idx
        position = "right" if idx % 2 == 0 else "left"
        out.append({"position": position, "hash": layer[sibling_idx]})
        nxt: list[str] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left
            nxt.append(_merkle_parent(left, right))
        layer = nxt
        idx //= 2
    return out


@router.get(
    "/proof/{evidence_packet_id}",
    summary="Merkle inclusion proof for one evidence_packet_id",
    description=(
        "Returns the daily Merkle root + sibling-hash proof path that "
        "anchors this `evidence_packet_id` to OpenTimestamps + a "
        "GitHub commit. **Public read** — verification must remain "
        "available without an account so any third party (auditor, "
        "税務調査官, 法務) can prove the row was not tampered with "
        "after-the-fact.\n\n"
        "**Verifier fold:**\n\n"
        "```\n"
        "h = leaf_hash\n"
        "for entry in proof_path:\n"
        "    if entry.position == 'left':\n"
        "        h = sha256(bytes.fromhex(entry.hash) + bytes.fromhex(h))\n"
        "    else:\n"
        "        h = sha256(bytes.fromhex(h) + bytes.fromhex(entry.hash))\n"
        "assert h == merkle_root\n"
        "```\n\n"
        "Then verify `merkle_root` against the GitHub commit message "
        "and against `ots verify` on the OpenTimestamps proof "
        "(downloadable separately via the `ots_url`)."
    ),
    responses={
        200: {"description": "Proof envelope."},
        400: {"description": "Malformed evidence_packet_id."},
        404: {"description": "Unknown evidence_packet_id (not yet anchored or never logged)."},
    },
)
def get_audit_proof(
    evidence_packet_id: Annotated[
        str,
        PathParam(
            min_length=5,
            max_length=80,
            description="Evidence packet identifier, e.g. 'evp_12345'.",
        ),
    ],
) -> JSONResponse:
    """Return the inclusion proof envelope for `evidence_packet_id`."""
    if not _EPID_RE.match(evidence_packet_id):
        raise HTTPException(
            status_code=400,
            detail=("evidence_packet_id must match ^evp_[A-Za-z0-9_]{1,64}$ (e.g. 'evp_12345')."),
        )

    am_conn = _open_autonomath_rw()
    try:
        try:
            leaf = _fetch_leaf(am_conn, evidence_packet_id)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                # Migration 146 not yet applied — degrade cleanly.
                _log.warning("audit_merkle_leaves missing: %s", exc)
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"audit_merkle_anchor not yet provisioned on this "
                        f"volume; evidence_packet_id={evidence_packet_id} "
                        f"has no inclusion proof available."
                    ),
                ) from exc
            raise

        if leaf is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"evidence_packet_id={evidence_packet_id} not found in "
                    f"audit_merkle_leaves. Either the id is unknown, or "
                    f"its anchor cron has not run yet (anchors close at "
                    f"00:30 JST for the prior JST day)."
                ),
            )
        daily_date, leaf_index, leaf_hash = leaf

        anchor = _fetch_anchor(am_conn, daily_date)
        if anchor is None:
            # Should never happen given FK-by-convention, but be defensive.
            raise HTTPException(
                status_code=404,
                detail=(
                    f"audit_merkle_anchor missing for daily_date={daily_date} "
                    f"despite leaf row existing — anchor cron run incomplete."
                ),
            )

        all_leaves = _fetch_all_leaves(am_conn, daily_date)
        proof_path = _build_proof_path(all_leaves, leaf_index)
    finally:
        try:
            am_conn.close()
        except Exception:  # pragma: no cover
            pass

    body: dict[str, Any] = {
        "epid": evidence_packet_id,
        "daily_date": daily_date,
        "leaf_index": leaf_index,
        "leaf_hash": leaf_hash,
        "proof_path": proof_path,
        "merkle_root": anchor["merkle_root"],
        "row_count": anchor["row_count"],
        "ots_url": _ots_url_for(anchor["ots_proof"]),
        "ots_proof_b64": (
            base64.b64encode(anchor["ots_proof"]).decode("ascii") if anchor["ots_proof"] else None
        ),
        "github_commit_url": _github_commit_url(anchor["github_commit_sha"]),
        "github_commit_sha": anchor["github_commit_sha"],
        "twitter_post_id": anchor["twitter_post_id"],
        "anchor_created_at": anchor["created_at"],
        "_disclaimer": _PROOF_DISCLAIMER,
        "_meta": {
            "verifier_algorithm": "merkle_sha256_bitcoin_style",
            "leaf_hash_recipe": "sha256(epid || params_digest || ts)",
            "creator": "Bookyou株式会社 (T8010001213708)",
        },
    }
    return JSONResponse(content=body)
