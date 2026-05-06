-- target_db: autonomath
-- migration: wave24_178_document_requirement_layer
-- generated_at: 2026-05-06
-- author: M00-F data spine DF-05 (document_requirement_layer)
-- idempotent: every CREATE uses IF NOT EXISTS; every DML is INSERT OR IGNORE
--
-- Purpose
-- -------
-- Normalize 必要書類 (required application materials) across:
--   - 補助金 / 助成金 (jGrants, METI 経済産業省 公募, 各都道府県・市区町村)
--   - 融資 (日本政策金融公庫, 信用保証協会, 制度融資, 信用金庫プレ申込)
--   - 許認可 (建設業許可, 産廃, 旅館業, 飲食店, 古物商 etc.)
--   - 認定 (経営革新計画, 事業継続力強化, 健康経営優良法人 etc.)
--   - 税制特例 (青色申告承認申請, 設備投資減税申請 etc.)
--
-- Each `programs` row historically embedded a free-text 必要書類 paragraph
-- ("申請書、決算書3期分、事業計画書、見積書 etc."). That blob is
-- *unsearchable*, *uncomparable across programs*, and *unstable when the
-- ministry edits the boilerplate*. This table extracts each line into a
-- normalized row so that:
--   1. application_strategy_pack_v2 can show "you need this same
--      事業計画書 for 5 of your 7 candidate programs — write it once".
--   2. paid customer can filter "show me programs whose required documents
--      I already have on hand".
--   3. ETL freshness checks can detect when a ministry adds / removes a
--      document without diff'ing the entire program description blob.
--
-- Field semantics
-- ---------------
-- req_id            PK, deterministic = sha1(program_id || ':' ||
--                   document_kind || ':' || gov_authority)
-- program_id        FK → programs.program_id (jpintel.db side; cross-DB
--                   join is intentionally avoided — joining is done at
--                   the application layer or via materialized view).
-- document_kind     enum, see CHECK constraint. The 22 canonical kinds
--                   below cover ~92% of observed boilerplates per the
--                   programs.必要書類_text scan.
-- required_or_optional  enum: 'required' / 'conditionally_required' /
--                       'optional' / 'recommended'
-- format_hint       enum: 'PDF' / 'Excel' / 'Word' / 'CSV' / 'paper_only' /
--                   'online_form' / 'mixed' / 'unknown'
-- template_url      URL of an official template, or NULL when no template
--                   is published. Honest NULL — do not invent.
-- how_obtained_hint Short free-text. e.g. '法務局で取得 (オンライン300円)' or
--                   '自社作成' or '税理士発行'. Empty string when unknown.
-- gov_authority     名 of the issuing authority. e.g. '法務局', '税務署',
--                   '都道府県知事', '市区町村長', '中小企業庁', '金融機関'.
-- estimated_cost_yen INTEGER, NULL when no fixed fee. e.g. 履歴事項全部証明書 = 600.
-- typical_turnaround_days INTEGER, NULL when not predictable. e.g.
--                         住民票=即日=0, 履歴事項全部証明書=即日=0,
--                         確定申告書写し=税務署発行=5-10日.
-- created_at        ISO 8601 (UTC, millisecond precision)
-- updated_at        ISO 8601 (UTC, millisecond precision)
--
-- Indexes
-- -------
-- (program_id)                       — primary lookup pattern
-- (document_kind)                    — "what programs need 履歴事項全部証明書"
-- (gov_authority, document_kind)     — "what does 法務局 issue across all programs"
-- (required_or_optional)             — quickly find mandatory items only
--
-- 22 canonical document_kind enum values (CHECK enforced)
-- -------------------------------------------------------
-- 1.  application_form           申請書 (program-specific 様式)
-- 2.  business_plan              事業計画書 / 経営計画書
-- 3.  financial_statement        決算書 / 確定申告書 / 月次試算表
-- 4.  registry_certificate       履歴事項全部証明書 / 現在事項全部証明書
-- 5.  invoice_registration_cert  適格請求書発行事業者登録証 / 番号
-- 6.  resident_certificate       住民票 / 印鑑登録証明書
-- 7.  permit_or_license          許可証 / 免許証 (建設業許可証 etc.)
-- 8.  certification_award        認定証 / 表彰状 / 認証書
-- 9.  estimate_or_quote          見積書 / 注文書 / 契約書 案
-- 10. delivery_receipt           納品書 / 受領書 / 請求書 控
-- 11. payment_evidence           支払証憑 / 振込控 / 領収書
-- 12. employment_record          雇用契約書 / 給与台帳 / 源泉徴収簿
-- 13. labor_insurance_evidence   労働保険番号 / 雇用保険適用事業所番号
-- 14. social_insurance_evidence  社会保険適用事業所証 / 加入証明
-- 15. tax_payment_certificate    納税証明書 (その1 / その2 / その3 / その4)
-- 16. corporate_charter          定款 / 寄附行為 / 規約
-- 17. shareholder_register       株主名簿 / 出資者名簿
-- 18. organization_chart         組織図 / 役員名簿
-- 19. asset_evidence             資産明細 / 担保物件評価書 / 不動産登記
-- 20. spec_or_drawing            仕様書 / 図面 / 設計図 / 配置図
-- 21. self_check_form            自己診断 / チェックリスト / 確認書
-- 22. other_supporting_doc       その他 添付資料

CREATE TABLE IF NOT EXISTS document_requirement_layer (
    req_id                    TEXT NOT NULL PRIMARY KEY,
    program_id                TEXT NOT NULL,
    document_kind             TEXT NOT NULL CHECK (document_kind IN (
        'application_form',
        'business_plan',
        'financial_statement',
        'registry_certificate',
        'invoice_registration_cert',
        'resident_certificate',
        'permit_or_license',
        'certification_award',
        'estimate_or_quote',
        'delivery_receipt',
        'payment_evidence',
        'employment_record',
        'labor_insurance_evidence',
        'social_insurance_evidence',
        'tax_payment_certificate',
        'corporate_charter',
        'shareholder_register',
        'organization_chart',
        'asset_evidence',
        'spec_or_drawing',
        'self_check_form',
        'other_supporting_doc'
    )),
    required_or_optional      TEXT NOT NULL DEFAULT 'required'
                              CHECK (required_or_optional IN (
                                  'required',
                                  'conditionally_required',
                                  'optional',
                                  'recommended'
                              )),
    format_hint               TEXT NOT NULL DEFAULT 'unknown'
                              CHECK (format_hint IN (
                                  'PDF', 'Excel', 'Word', 'CSV',
                                  'paper_only', 'online_form',
                                  'mixed', 'unknown'
                              )),
    template_url              TEXT,
    how_obtained_hint         TEXT NOT NULL DEFAULT '',
    gov_authority             TEXT NOT NULL DEFAULT '',
    estimated_cost_yen        INTEGER
                              CHECK (estimated_cost_yen IS NULL
                                     OR estimated_cost_yen >= 0),
    typical_turnaround_days   INTEGER
                              CHECK (typical_turnaround_days IS NULL
                                     OR typical_turnaround_days >= 0),
    created_at                TEXT NOT NULL
                              DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                TEXT NOT NULL
                              DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_doc_req_program
    ON document_requirement_layer (program_id);

CREATE INDEX IF NOT EXISTS idx_doc_req_kind
    ON document_requirement_layer (document_kind);

CREATE INDEX IF NOT EXISTS idx_doc_req_authority_kind
    ON document_requirement_layer (gov_authority, document_kind);

CREATE INDEX IF NOT EXISTS idx_doc_req_required
    ON document_requirement_layer (required_or_optional);

-- View: per-program rollup. Used by application_strategy_pack to render
-- "必要書類 checklist" with template links inline.
CREATE VIEW IF NOT EXISTS v_doc_req_per_program AS
SELECT program_id,
       COUNT(*) AS doc_count,
       SUM(CASE WHEN required_or_optional='required' THEN 1 ELSE 0 END)
           AS required_count,
       SUM(CASE WHEN template_url IS NOT NULL AND template_url != '' THEN 1 ELSE 0 END)
           AS templates_available,
       SUM(COALESCE(estimated_cost_yen, 0)) AS minimum_cost_yen,
       MAX(updated_at) AS last_updated
  FROM document_requirement_layer
 GROUP BY program_id;

-- View: shared documents across programs. Used to surface
-- "the same 履歴事項全部証明書 covers 5 of your 7 candidate programs".
CREATE VIEW IF NOT EXISTS v_doc_req_cross_program AS
SELECT document_kind,
       gov_authority,
       COUNT(DISTINCT program_id) AS program_count,
       COUNT(*) AS occurrence_count
  FROM document_requirement_layer
 WHERE required_or_optional IN ('required','conditionally_required')
 GROUP BY document_kind, gov_authority;
