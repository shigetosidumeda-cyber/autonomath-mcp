-- target_db: autonomath
-- 146_audit_merkle_anchor — Daily Merkle hash chain anchor for audit log moat.
--
-- Idempotent. Safe to re-run on every Fly boot via entrypoint.sh §4.
--
-- Why
-- ---
-- jpcite issues a stream of evidence packets / billed `usage_events`
-- rows. To prove to auditors / 税務調査官 / 法務 that NO row was
-- altered after-the-fact, we anchor a daily Merkle root of every JST
-- 00:00–23:59 evidence row to two third-party clocks:
--
--   1. OpenTimestamps (Bitcoin-anchored) — `ots_proof` BLOB column
--      stores the calendar receipt; verifier can run
--      `ots verify` against the daily root.
--   2. GitHub commit — empty commit on this repo whose message
--      embeds the daily root. `github_commit_sha` carries the SHA;
--      verifier can `git log` and SHA-match.
--
-- Optional Twitter post is recorded for redundancy (`twitter_post_id`
-- nullable) — the cron does NOT post by itself; this column is
-- populated when the operator manually mirrors the daily root.
--
-- Schema posture
-- --------------
-- * `audit_merkle_anchor` is one row per JST date (`daily_date` PK).
-- * `audit_merkle_leaves` is the per-row leaf log; (daily_date,
--   leaf_index) PK guarantees deterministic tree order. The
--   `evidence_packet_id` column allows reverse lookup from a customer
--   complaint ("prove evidence packet evp_xyz was not modified")
--   to the day's anchor; covering index `ix_audit_merkle_leaves_epid`
--   makes that O(log N).
-- * `leaf_hash` is sha256(epid + content_hash + timestamp), persisted
--   so the verifier can reconstruct the proof path without
--   re-reading source rows.
-- * `merkle_root` is the canonical hex-encoded SHA256 of the
--   computed daily tree. Odd-count tree rows duplicate the last
--   left node (Bitcoin-style), matching the `OpenTimestamps`
--   convention.
--
-- Verifier flow
-- -------------
--   1. GET /v1/audit/proof/{epid} returns
--      {leaf_hash, proof_path, merkle_root, ots_url, github_commit_url}.
--   2. Verifier recomputes leaf_hash from the cited epid + content_hash
--      + timestamp, then walks proof_path to recompute the root.
--   3. Verifier compares against `ots verify` and the GitHub commit
--      message. Match on either anchor proves the row was committed
--      on or before the OpenTimestamps calendar / commit date.
--
-- NOT a tax-advice surface — pure cryptographic provenance.

CREATE TABLE IF NOT EXISTS audit_merkle_anchor (
    daily_date          TEXT PRIMARY KEY,
    row_count           INTEGER NOT NULL,
    merkle_root         TEXT NOT NULL,
    ots_proof           BLOB,
    github_commit_sha   TEXT,
    twitter_post_id     TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_merkle_leaves (
    daily_date          TEXT NOT NULL,
    leaf_index          INTEGER NOT NULL,
    evidence_packet_id  TEXT NOT NULL,
    leaf_hash           TEXT NOT NULL,
    PRIMARY KEY (daily_date, leaf_index)
);

CREATE INDEX IF NOT EXISTS ix_audit_merkle_leaves_epid
    ON audit_merkle_leaves(evidence_packet_id);
