#!/usr/bin/env bash
# bootstrap_eval_db.sh — build a curated ~10 MB slice of autonomath.db + jpintel.db
# for CI. The full 8.29 GB autonomath.db cannot ride GitHub Actions; this script
# extracts the rows that Tier A seeds + Tier B SQL templates + Tier C traps need.
#
# Output: tests/eval/fixtures/seed.db (single SQLite file, ~10 MB target).
# Run locally to refresh:  bash scripts/bootstrap_eval_db.sh
# CI uses the same script via .github/workflows/eval.yml.
#
# When the source DB(s) are absent (e.g. fresh CI checkout), the script
# initialises an empty schema-compatible seed.db so the eval harness can
# still start and report 0/0 metrics rather than crashing.

set -euo pipefail
cd "$(dirname "$0")/.."

SRC_AM="autonomath.db"
SRC_JP="data/jpintel.db"
DEST_DIR="tests/eval/fixtures"
DEST="${DEST_DIR}/seed.db"

mkdir -p "${DEST_DIR}"

# R8 fix 2026-05-07 (R8_DAILY_FORENSIC_FIX): when source DBs are missing
# (e.g. fresh CI checkout where the 8.29 GB autonomath.db is gitignored),
# preserve the committed pre-baked seed.db at tests/eval/fixtures/seed.db
# instead of wiping it for an empty stub. The pre-baked fixture (~190 KB,
# verified to carry the 5 Tier A gold rows: 第12回 budget+close, 2割特例
# effective_until, 80%控除 effective_until, 雇用就農資金 240) makes Tier A
# precision@1 hit the 0.85 floor on CI without dragging the 8.29 GB blob
# through the runner.
#
# The previous behaviour created an empty schema-only stub which caused the
# eval gate to red 8 nights running with `Tier A precision@1=0.000 < 0.85`.
if [[ ! -f "${SRC_AM}" && ! -f "${SRC_JP}" ]]; then
    if [[ -f "${DEST}" ]]; then
        # Quick sanity probe — must contain at least one Tier A gold row, else
        # treat the on-disk fixture as broken and fall back to empty stub.
        ta001_rows="$(sqlite3 "${DEST}" "SELECT COUNT(*) FROM am_application_round WHERE round_label='第12回' AND budget_yen=150000000000;" 2>/dev/null || echo 0)"
        if [[ "${ta001_rows}" -ge 1 ]]; then
            bytes="$(wc -c < "${DEST}" | tr -d ' ')"
            echo "[bootstrap_eval_db] no source DBs found - using committed fallback fixture ${DEST} (${bytes} bytes, TA001 row OK)"
            exit 0
        fi
        echo "[bootstrap_eval_db] committed fixture present but TA001 row missing - rebuilding empty stub" >&2
        rm -f "${DEST}" "${DEST}-shm" "${DEST}-wal"
    fi
    echo "[bootstrap_eval_db] no source DBs found - initialising empty seed.db" >&2
    sqlite3 "${DEST}" <<'SQL'
CREATE TABLE IF NOT EXISTS am_application_round (
  round_id INTEGER PRIMARY KEY,
  round_label TEXT,
  application_close_date TEXT,
  budget_yen INTEGER
);
CREATE TABLE IF NOT EXISTS jpi_tax_rulesets (
  unified_id TEXT PRIMARY KEY,
  ruleset_name TEXT,
  effective_until TEXT
);
CREATE TABLE IF NOT EXISTS am_law_article (
  article_id INTEGER PRIMARY KEY,
  law_canonical_id TEXT,
  article_number TEXT,
  text_summary TEXT
);
CREATE TABLE IF NOT EXISTS programs (
  unified_id INTEGER PRIMARY KEY,
  primary_name TEXT,
  amount_max_man_yen REAL,
  tier TEXT,
  excluded INTEGER DEFAULT 0,
  source_url TEXT
);
CREATE TABLE IF NOT EXISTS am_entities (
  canonical_id TEXT PRIMARY KEY,
  record_kind TEXT,
  primary_name TEXT,
  source_url TEXT
);
SQL
    echo "[bootstrap_eval_db] empty seed.db created at ${DEST}"
    exit 0
fi

# Source DBs exist - rebuild fresh slice from them.
rm -f "${DEST}" "${DEST}-shm" "${DEST}-wal"

echo "[bootstrap_eval_db] building ${DEST} from ${SRC_AM} + ${SRC_JP}"

# Use ATTACH within a single sqlite3 invocation so the slice is one file.
# We carve only the rows the Tier A seeds + a 100-row tier-S/A program sample
# touch. ~10 MB target.
sqlite3 "${DEST}" <<SQL
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;

ATTACH DATABASE '${SRC_AM}' AS am;
ATTACH DATABASE '${SRC_JP}' AS jp;

-- Schema mirrors (subset of columns the harness actually reads).
CREATE TABLE am_application_round AS
  SELECT round_id, round_label, application_close_date, budget_yen
  FROM am.am_application_round
  WHERE round_label IN ('第12回','第11回','第13回')
     OR application_close_date >= '2024-01-01'
  LIMIT 200;

CREATE TABLE jpi_tax_rulesets AS
  SELECT unified_id, ruleset_name, effective_until
  FROM am.jpi_tax_rulesets;

CREATE TABLE am_law_article AS
  SELECT article_id, law_canonical_id, article_number, text_summary
  FROM am.am_law_article
  WHERE text_summary IS NOT NULL
  ORDER BY article_id
  LIMIT 200;

-- Tier S/A programs (~100 row cap) + the 雇用就農資金 row TA030 needs.
CREATE TABLE programs AS
  SELECT unified_id, primary_name, amount_max_man_yen, tier, excluded, source_url
  FROM jp.programs
  WHERE tier IN ('S','A')
    AND excluded = 0
    AND amount_max_man_yen IS NOT NULL
  ORDER BY unified_id
  LIMIT 100;

INSERT INTO programs (unified_id, primary_name, amount_max_man_yen, tier, excluded, source_url)
  SELECT unified_id, primary_name, amount_max_man_yen, tier, excluded, source_url
  FROM jp.programs
  WHERE primary_name = '雇用就農資金'
    AND amount_max_man_yen = 240
    AND unified_id NOT IN (SELECT unified_id FROM programs);

-- Skinny am_entities pull so future Phase A tools have something to bind to.
CREATE TABLE am_entities AS
  SELECT canonical_id, record_kind, primary_name, source_url
  FROM am.am_entities
  WHERE record_kind IN ('program','tax_measure','law','authority')
  LIMIT 500;

-- Detach so VACUUM works.
DETACH DATABASE am;
DETACH DATABASE jp;

VACUUM;
SQL

bytes=$(wc -c < "${DEST}" | tr -d ' ')
echo "[bootstrap_eval_db] ${DEST} = ${bytes} bytes"

# Sanity: the 5 Tier A seeds must resolve against the slice.
sqlite3 "${DEST}" <<'SQL'
.headers on
SELECT 'TA001/2', round_label, application_close_date, budget_yen
  FROM am_application_round WHERE round_label='第12回' AND budget_yen=150000000000;
SELECT 'TA005', ruleset_name, effective_until
  FROM jpi_tax_rulesets WHERE ruleset_name LIKE '%2割特例%';
SELECT 'TA006', ruleset_name, effective_until
  FROM jpi_tax_rulesets WHERE ruleset_name LIKE '%80%控除%';
SELECT 'TA030', primary_name, amount_max_man_yen
  FROM programs WHERE primary_name='雇用就農資金' AND amount_max_man_yen=240;
SQL

echo "[bootstrap_eval_db] done"
