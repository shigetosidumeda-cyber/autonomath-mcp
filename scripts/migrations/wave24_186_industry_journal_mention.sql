-- target_db: autonomath
-- migration: wave24_186_industry_journal_mention
-- generated_at: 2026-05-07
-- author: DEEP-40 industry journal mention monthly grep cron (IA-08 #10 + IA-12 #7)
-- idempotent: every CREATE uses IF NOT EXISTS; first-line target_db hint
--             routes this file to autonomath.db via entrypoint.sh §4.
--
-- Purpose
-- -------
-- Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_40_industry_journal_mention.md
--
-- Tracks 自然言及 of jpcite / Bookyou / AutonoMath (legacy decay observation)
-- across 8 業界誌 covering the four 業法 sensitive cohorts (税理士 /
-- 公認会計士 / 司法書士 / 補助金 consultant). Single objective KPI for
-- organic 自走 brand health under the 100% organic + zero-touch +
-- ¥3/req metered + LLM-call-zero constraints. Populated monthly by
-- `scripts/cron/ingest_industry_journal_mention.py` (3-layer fallback:
-- CiNii Articles API → J-STAGE API → publisher TOC HTML grep). Pure
-- regex grep — NO LLM. Snippet capped at 50 chars (著作権法 §32 fence).
--
-- Field semantics
-- ---------------
-- id                       AUTOINCREMENT primary key.
-- journal_name             8 誌の正規名 (e.g. "税務通信" / "月刊税務事例").
-- cohort                   税理士 / 公認会計士 / 司法書士 / 行政書士.
-- issue_date               ISO YYYY-MM (publisher 発行月; 業界誌は基本 monthly).
-- article_title            記事タイトル (TOC 表記そのまま).
-- article_authors          semicolon 区切 (e.g. "山田太郎; 佐藤花子").
-- mention_keyword          jpcite / ジェイピーサイト / Bookyou / AutonoMath /
--                          オートノマス / T8010001213708 のいずれか.
-- mention_context_snippet  50 chars cap — 著作権法 §32 適法引用 fence.
-- is_self_authored         1 = jpcite operator (梅田茂利 / Bookyou) authored,
--                          0 = 他者発信 (IA-12 #7 root signal).
-- source_url               必須; 引用 出典 URL の primary 値.
-- source_layer             cinii / jstage / publisher_html / manual.
-- retrieved_at             ISO 8601 UTC; cron run timestamp.
--
-- IA-12 root signal
-- -----------------
-- 自発 vs 他発 比率 = COUNT(is_self_authored=0) / COUNT(*).
-- 比率 < 0.5 を 3 ヶ月続けたら brand 自走未達 → cohort 別 organic
-- editorial pitch トリガ (paid PR は厳禁、 spec §7 参照).

CREATE TABLE IF NOT EXISTS industry_journal_mention (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  journal_name TEXT NOT NULL,
  cohort TEXT NOT NULL CHECK(cohort IN ('税理士','公認会計士','司法書士','行政書士')),
  issue_date TEXT NOT NULL,
  article_title TEXT NOT NULL,
  article_authors TEXT,
  mention_keyword TEXT NOT NULL,
  mention_context_snippet TEXT,
  is_self_authored INTEGER NOT NULL DEFAULT 0 CHECK(is_self_authored IN (0,1)),
  source_url TEXT NOT NULL,
  source_layer TEXT NOT NULL CHECK(source_layer IN ('cinii','jstage','publisher_html','manual')),
  retrieved_at TEXT NOT NULL,
  UNIQUE(journal_name, issue_date, article_title, mention_keyword)
);

CREATE INDEX IF NOT EXISTS ix_ijm_issue_cohort ON industry_journal_mention(issue_date, cohort);
CREATE INDEX IF NOT EXISTS ix_ijm_self_authored ON industry_journal_mention(is_self_authored, issue_date);
CREATE INDEX IF NOT EXISTS ix_ijm_keyword ON industry_journal_mention(mention_keyword);
CREATE INDEX IF NOT EXISTS ix_ijm_journal ON industry_journal_mention(journal_name, issue_date);
