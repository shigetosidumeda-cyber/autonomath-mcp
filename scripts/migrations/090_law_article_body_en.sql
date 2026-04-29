-- target_db: autonomath
-- migration 090_law_article_body_en (Foreign FDI cohort capture, feature 4)
--
-- Adds an English-translation column to am_law_article so the e-Gov
-- 「日本法令外国語訳」(japaneselawtranslation.go.jp, CC-BY 4.0) ingest
-- can deposit hand-translated EN article body alongside the canonical
-- JP text. The disclaimer that translations are unofficial and JP is
-- authoritative is surfaced verbatim in every API/MCP response that
-- exposes body_en.
--
-- Forward-only / idempotent: re-running on each Fly boot is safe.
-- Sister migration 040 (am_alias.language) is folded in here so the
-- offline batch translate has a stable target column before the script
-- runs. Migration 040 was originally collection-CLI scope per the
-- english_v4_plan but the column never landed in the live DB; we
-- include it here defensively (the IF NOT EXISTS on the column add
-- pattern in SQLite 3.43+ keeps the operation idempotent).

-- ---------------------------------------------------------------------------
-- 1. am_law_article.body_en  (new — feature 4)
-- ---------------------------------------------------------------------------

-- SQLite has no IF NOT EXISTS for ADD COLUMN; entrypoint.sh swallows the
-- "duplicate column" error so re-runs are safe.
ALTER TABLE am_law_article ADD COLUMN body_en TEXT;

ALTER TABLE am_law_article ADD COLUMN body_en_source_url TEXT;

ALTER TABLE am_law_article ADD COLUMN body_en_fetched_at TEXT;

ALTER TABLE am_law_article ADD COLUMN body_en_license TEXT
    DEFAULT 'cc_by_4.0';

-- Provenance check: any non-null body_en MUST cite a source_url so the
-- "translations unofficial, JP authoritative" disclaimer can point at
-- the e-Gov translation page that produced the row. Soft-enforced via
-- ingest script; we do not add a CHECK constraint because the existing
-- table has rows with body_en = NULL that must remain valid.

CREATE INDEX IF NOT EXISTS ix_am_law_article_body_en_present
    ON am_law_article(law_canonical_id)
    WHERE body_en IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. am_alias.language  (defensive backfill — sister migration 040)
-- ---------------------------------------------------------------------------
-- The english_v4_plan declared this column should land via 040 from the
-- collection-CLI side. As of 2026-04-29 the column does not exist on
-- the production autonomath.db — we land it here so the batch_translate
-- script has a known target. CHECK constraint stays loose (TEXT, not
-- enum) because adding a CHECK to an existing table requires table
-- rebuild and we cannot afford that on a 8.29 GB table at boot time.

ALTER TABLE am_alias ADD COLUMN language TEXT
    NOT NULL DEFAULT 'ja';

CREATE INDEX IF NOT EXISTS ix_am_alias_language
    ON am_alias(canonical_id, language);

-- Backfill historical alias_kind='english' rows to language='en' so
-- existing 10,676 english-tagged aliases stay queryable through the
-- new lang=en path. Idempotent (re-running re-applies same UPDATE).
UPDATE am_alias SET language = 'en' WHERE alias_kind = 'english';
UPDATE am_alias SET language = 'kana' WHERE alias_kind = 'kana';

-- ---------------------------------------------------------------------------
-- 3. Disclaimer constant (operator-side reference; not a column)
-- ---------------------------------------------------------------------------
-- The operator-facing canonical disclaimer text — used by:
--   - scripts/ingest_egov_en_translations.py   (sets body_en_license)
--   - src/jpintel_mcp/api/laws.py              (every body_en response)
--   - site/en/laws/*.html                       (footer)
--
-- Verbatim string (do NOT paraphrase; it is consumed by the foreign-investor
-- audience page as the kill-statement reference):
--
--   "Translations of Japanese laws on this page are courtesy translations
--    sourced from the Japanese Ministry of Justice's e-Gov 日本法令外国語訳
--    (japaneselawtranslation.go.jp) under CC-BY 4.0. The Japanese-language
--    original is the only legally authoritative version. AutonoMath provides
--    these translations as a reference and assumes no responsibility for
--    legal interpretation derived from them."
--
-- This row is intentionally left as a SQL comment rather than a settings
-- table — settings live in src/jpintel_mcp/config.py and the disclaimer
-- needs to be translatable per-request (ja/en) which a static SQL row
-- cannot serve. Search the codebase for `_EGOV_TRANSLATION_DISCLAIMER`
-- to find the live string.
