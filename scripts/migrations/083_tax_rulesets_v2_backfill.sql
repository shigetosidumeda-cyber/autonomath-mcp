-- target_db: jpintel
-- migration 083_tax_rulesets_v2_backfill (会計士 persona ZERO-coverage fix, 2026-04-29)
--
-- ============================================================================
-- BACKGROUND
-- ============================================================================
--   Per consultant + 会計士 walks the existing 35 tax_rulesets row set has
--   ZERO coverage of 研究開発税制 (措置法 42 条の 4) and only partial
--   coverage of 措置法 42 条の 6 / 42 条の 12 の 4. Compounding that, IT
--   導入補助金 の 会計処理 (圧縮記帳 vs 直接控除) is not separately
--   encoded — auditors evaluating补助金 receipts cannot find the rule
--   that applies to their client's bookkeeping treatment.
--
--   This migration adds 15 high-value rulesets sourced from 国税庁
--   タックスアンサー + 中小企業庁 official PDF / 経営力向上計画 認定
--   資料 (公式 一次資料 only — aggregator data sources are BANNED per
--   the data-hygiene constitution).
--
-- ============================================================================
-- WHAT THIS MIGRATION DOES
-- ============================================================================
--   1. INSERT OR IGNORE 15 new rows into `tax_rulesets`. unified_id is the
--      first 10 lowercase hex of sha256(ruleset_name) so re-runs are
--      idempotent and the values are stable across environments.
--
--   2. INSERT OR IGNORE the same 15 into `tax_rulesets_fts` so /search
--      surfaces them via FTS5 trigram matching.
--
--   3. After this migration the table holds 50 rulesets (was 35).
--
-- ============================================================================
-- IDEMPOTENCY
-- ============================================================================
--   All inserts use INSERT OR IGNORE on the unified_id PRIMARY KEY. Safe
--   to re-run on every Fly boot via entrypoint.sh §4 (jpintel-target
--   migrations are picked up the same way as autonomath-target ones —
--   see CLAUDE.md "Common gotchas: Autonomath-target migrations land via
--   entrypoint.sh", same idempotency contract).
--
-- ============================================================================
-- CONFIDENCE NOTES
-- ============================================================================
--   - 0.85 default — encoded from primary 国税庁 タックスアンサー +
--     中小企業庁 公式 PDF. Where citation is to a 通達 / 政令 / 法令の
--     条文 directly, confidence rises to 0.92.
--   - DX 投資促進税制 / カーボンニュートラル投資促進税制 carry
--     confidence 0.80 because the 経済産業省 認定要件 is partially
--     parametrised by 認定計画 contents (caller-specific) — predicate
--     evaluation is honest only on the structural conditions
--     (capital_jpy / blue_form_return / asset acquisition).
--   - eligibility_conditions_json is conservative: leaves omitted when
--     uncertainty exceeds 預金的判定範囲. 実務 judgment is fenced behind
--     `_disclaimer` (税理士法 §52).
-- ============================================================================

PRAGMA foreign_keys = OFF;

-- ----------------------------------------------------------------------------
-- 1. 研究開発税制 (措置法 42 条の 4) — ZERO coverage previously.
-- ----------------------------------------------------------------------------

INSERT OR IGNORE INTO tax_rulesets (
    unified_id, ruleset_name, tax_category, ruleset_kind,
    effective_from, effective_until,
    related_law_ids_json, eligibility_conditions, eligibility_conditions_json,
    rate_or_amount, calculation_formula, filing_requirements,
    authority, authority_url, source_url, source_excerpt, source_checksum,
    confidence, fetched_at, updated_at
) VALUES
('TAX-ca4b993ca5',
 '試験研究費税額控除 (一般型) 措置法42条の4第1項',
 'corporate', 'credit',
 '2017-04-01', NULL,
 '["PENDING:租税特別措置法第42条の4"]',
 '青色申告書を提出する法人が、各事業年度に支出した試験研究費の額に一定の割合を乗じた金額を、その事業年度の法人税額から控除できる制度 (一般型)。控除率は試験研究費の増減に応じて 1%〜14% (令和5年度改正後)。法人税額の25% (一定の場合は40%) が上限。\n\n[needs_verification: true] — 控除率カーブは 2026 年度税制改正で頻繁に更新されるため、適用年度の最新通達を必ず確認すること。',
 '{"op": "all", "of": [{"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "gte", "field": "research_expense_jpy", "value": 1}]}',
 '控除率 1%〜14% (試験研究費割合に連動)',
 '税額控除額 = 試験研究費の額 × 控除率 (法人税額の25%上限、一定の場合40%)',
 '確定申告書別表六(九)を添付。試験研究費明細書の保存。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5441.htm',
 NULL, NULL,
 0.85, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

('TAX-8db8646e62',
 '試験研究費税額控除 (中小企業向け) 措置法42条の4第4項',
 'corporate', 'credit',
 '2017-04-01', NULL,
 '["PENDING:租税特別措置法第42条の4第4項"]',
 '中小企業者等 (資本金1億円以下、大規模法人の子会社を除く) が、試験研究費を支出した場合の特別の税額控除制度。控除率は通常 12% に上乗せがあり、増減割合に応じて最大 17%。法人税額の 25% (一定の場合 35%) が上限。中小企業者等は一般型と中小企業向けのいずれか有利な方を選択適用できる。\n\n[needs_verification: true] — 上乗せ判定 (試験研究費割合 9.4% 超など) は適用年度ごとに最新の通達を確認。',
 '{"op": "all", "of": [{"op": "lte", "field": "capital_jpy", "value": 100000000}, {"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "is_subsidiary_of_large_corp", "value": false}, {"op": "gte", "field": "research_expense_jpy", "value": 1}]}',
 '控除率 12%〜17%',
 '税額控除額 = 試験研究費の額 × 12% (上乗せ条件で最大17%) (法人税額の25%上限、上乗せ条件で35%)',
 '確定申告書別表六(九)を添付。中小企業者該当判定書類を保存。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5443.htm',
 NULL, NULL,
 0.85, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

('TAX-1964f6ff26',
 '試験研究費税額控除 (オープンイノベーション型) 措置法42条の4第7項',
 'corporate', 'credit',
 '2017-04-01', NULL,
 '["PENDING:租税特別措置法第42条の4第7項"]',
 '国の試験研究機関、大学、特別試験研究機関等との共同研究・委託研究に係る試験研究費について、一般型・中小企業向けとは別枠で 20%〜30% の税額控除を認める制度 (オープンイノベーション型)。法人税額の 10% が別枠上限。共同研究契約書、委託研究契約書、相手方の確認書の保存が必要。\n\n[needs_verification: true] — 対象機関の指定範囲 (特別試験研究機関等) は 経済産業省 公表リストを年度ごとに参照すること。',
 '{"op": "all", "of": [{"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "has_collaborative_research_contract", "value": true}, {"op": "gte", "field": "collaborative_research_expense_jpy", "value": 1}]}',
 '控除率 20%〜30% (相手方の種類により異なる)',
 '税額控除額 = オープンイノベーション型試験研究費 × 20%〜30% (法人税額の10%別枠上限)',
 '確定申告書別表六(九の二)を添付。共同研究契約書 + 相手方確認書を7年間保存。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5446.htm',
 NULL, NULL,
 0.82, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

('TAX-7fae3b3baa',
 '試験研究費税額控除 (試験研究費の額が増加した場合の特例)',
 'corporate', 'credit',
 '2021-04-01', NULL,
 '["PENDING:租税特別措置法第42条の4"]',
 '当期の試験研究費の額が、比較試験研究費の額 (前3事業年度の平均) を超える場合、その増加割合に応じて控除率を上乗せする増加型の特例。一般型・中小企業向けの上乗せ計算に組み込まれており、独立した別制度ではないが、試験研究費の継続的な拡大インセンティブとして機能する。\n\n[needs_verification: true] — 増加割合と控除率カーブは令和3年度・令和5年度・令和8年度で改正されているため、適用年度に対応する条文を必ず参照。',
 '{"op": "all", "of": [{"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "gte", "field": "research_expense_jpy", "value": 1}, {"op": "gte", "field": "research_expense_growth_ratio", "value": 0.0}]}',
 '増加割合に連動する控除率上乗せ (最大2%程度の上乗せ)',
 '増加割合 = (当期試験研究費 - 比較試験研究費) / 比較試験研究費。控除率上乗せは増加割合 × 一定係数。',
 '確定申告書別表六(九)に増加割合の計算明細を記載。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5444.htm',
 NULL, NULL,
 0.78, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

-- ----------------------------------------------------------------------------
-- 2. 中小企業投資促進税制 (措置法 42 条の 6) — partial coverage previously
--    (TAX-452c604d6e is rough; this row encodes 詳細 + 7%控除の上限).
-- ----------------------------------------------------------------------------

('TAX-4b9317d2c4',
 '中小企業投資促進税制 詳細 措置法42条の6 (機械装置160万円以上等)',
 'corporate', 'credit',
 '2017-04-01', NULL,
 '["PENDING:租税特別措置法第42条の6"]',
 '中小企業者等 (資本金1億円以下) が指定期間内に取得し、指定事業の用に供した特定の機械装置等について、取得価額の30%の特別償却または7%の税額控除 (資本金3,000万円以下の特定中小企業者等のみ) を選択適用できる制度。\n\n対象資産: 機械装置 (1台160万円以上)、製品の品質管理向上等に資する工具 (1台30万円以上かつ複数合計120万円以上)、ソフトウェア (一の取得価額70万円以上)、貨物自動車 (3.5t以上)、内航船舶等。\n\n税額控除は法人税額の20%が上限。控除限度超過額は1年間繰越可。',
 '{"op": "all", "of": [{"op": "lte", "field": "capital_jpy", "value": 100000000}, {"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "in", "field": "asset_category", "values": ["machinery", "tools", "software", "cargo_truck", "inland_vessel"]}, {"op": "gte", "field": "asset_acquisition_price_jpy", "value": 1600000}]}',
 '特別償却 30% または 税額控除 7% (法人税額の20%上限)',
 '特別償却額 = 取得価額 × 30% / 税額控除額 = 取得価額 × 7%',
 '確定申告書別表六(十三)(十四) または別表十六(一)(二)を添付。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5433.htm',
 NULL, NULL,
 0.88, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

-- ----------------------------------------------------------------------------
-- 3. 中小企業経営強化税制 (措置法 42 条の 12 の 4) — A/B/C/D 類型別に
--    分割エンコード。会計士が経営力向上計画の認定証で類型を判定後、
--    どの控除条件が適用されるかを machine-evaluable に問い合わせるため。
-- ----------------------------------------------------------------------------

('TAX-369a30f0ce',
 '中小企業経営強化税制 A類型 (生産性向上設備) 措置法42条の12の4',
 'corporate', 'credit',
 '2017-04-01', NULL,
 '["PENDING:租税特別措置法第42条の12の4"]',
 '中小企業者等が経営力向上計画 (中小企業等経営強化法) の認定を受け、A類型 (生産性向上設備) に該当する一定の設備を取得・事業供用した場合、即時償却 (取得価額全額の損金算入) または 取得価額の10% (資本金3,000万円超は7%) の税額控除を選択適用できる。\n\nA類型要件: (1) 旧モデル比で生産性が年平均1%以上向上、(2) 工業会等の証明書を取得。設備区分: 機械装置160万円以上 / 工具30万円以上 / 器具備品30万円以上 / 建物附属設備60万円以上 / ソフトウェア70万円以上。',
 '{"op": "all", "of": [{"op": "lte", "field": "capital_jpy", "value": 100000000}, {"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "has_keiei_kyoka_keikaku", "value": true}, {"op": "eq", "field": "kyoka_keikaku_type", "value": "A"}, {"op": "eq", "field": "has_industry_association_cert", "value": true}, {"op": "gte", "field": "asset_acquisition_price_jpy", "value": 300000}]}',
 '即時償却 または 税額控除 10% (資本金3,000万円超は7%)',
 '即時償却額 = 取得価額全額 / 税額控除額 = 取得価額 × 10% (上限 法人税額の20%)',
 '経営力向上計画認定証 + 工業会証明書 + 確定申告書別表六(二十六)を添付。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5434.htm',
 NULL, NULL,
 0.86, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

('TAX-14cf2308be',
 '中小企業経営強化税制 B類型 (収益力強化設備) 措置法42条の12の4',
 'corporate', 'credit',
 '2017-04-01', NULL,
 '["PENDING:租税特別措置法第42条の12の4"]',
 '中小企業者等が経営力向上計画の認定を受け、B類型 (収益力強化設備) に該当する設備を取得・事業供用した場合、即時償却または取得価額の10% (資本金3,000万円超は7%) の税額控除。\n\nB類型要件: (1) 投資利益率 (年平均) が 5% 以上見込まれること、(2) 経済産業局の確認書取得。設備の取得価額・区分はA類型と同一基準。',
 '{"op": "all", "of": [{"op": "lte", "field": "capital_jpy", "value": 100000000}, {"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "has_keiei_kyoka_keikaku", "value": true}, {"op": "eq", "field": "kyoka_keikaku_type", "value": "B"}, {"op": "eq", "field": "has_keizaisangyokyoku_confirmation", "value": true}, {"op": "gte", "field": "expected_investment_roi", "value": 0.05}]}',
 '即時償却 または 税額控除 10% (資本金3,000万円超は7%)',
 '即時償却額 = 取得価額全額 / 税額控除額 = 取得価額 × 10% (上限 法人税額の20%)',
 '経営力向上計画認定証 + 経済産業局確認書 + 確定申告書別表六(二十六)を添付。',
 '中小企業庁', 'https://www.chusho.meti.go.jp/',
 'https://www.chusho.meti.go.jp/keiei/kyoka/',
 NULL, NULL,
 0.84, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

('TAX-e0debfd9e8',
 '中小企業経営強化税制 C類型 (デジタル化設備) 措置法42条の12の4',
 'corporate', 'credit',
 '2019-04-01', NULL,
 '["PENDING:租税特別措置法第42条の12の4"]',
 '中小企業者等が経営力向上計画の認定を受け、C類型 (デジタル化設備) に該当する設備を取得・事業供用した場合、即時償却または取得価額の10% (資本金3,000万円超は7%) の税額控除。\n\nC類型要件: (1) リモート操作 / 可視化 / 自動制御化 のいずれかに資する設備、(2) 経済産業局の確認書取得。COVID-19 を契機としたテレワーク対応投資を含む。',
 '{"op": "all", "of": [{"op": "lte", "field": "capital_jpy", "value": 100000000}, {"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "has_keiei_kyoka_keikaku", "value": true}, {"op": "eq", "field": "kyoka_keikaku_type", "value": "C"}, {"op": "eq", "field": "has_keizaisangyokyoku_confirmation", "value": true}, {"op": "in", "field": "digital_function", "values": ["remote_operation", "visualization", "automation"]}]}',
 '即時償却 または 税額控除 10% (資本金3,000万円超は7%)',
 '即時償却額 = 取得価額全額 / 税額控除額 = 取得価額 × 10% (上限 法人税額の20%)',
 '経営力向上計画認定証 + 経済産業局確認書 + 確定申告書別表六(二十六)を添付。',
 '中小企業庁', 'https://www.chusho.meti.go.jp/',
 'https://www.chusho.meti.go.jp/keiei/kyoka/',
 NULL, NULL,
 0.83, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

('TAX-9265ed17b7',
 '中小企業経営強化税制 D類型 (経営資源集約化設備) 措置法42条の12の4',
 'corporate', 'credit',
 '2021-08-02', NULL,
 '["PENDING:租税特別措置法第42条の12の4"]',
 '中小企業者等が M&A 等を通じた経営資源集約化を伴う経営力向上計画の認定を受け、D類型 (経営資源集約化設備) に該当する設備を取得・事業供用した場合、即時償却または取得価額の10% (資本金3,000万円超は7%) の税額控除。\n\nD類型要件: (1) M&A 等の経営資源の集約化を含む計画、(2) 投資利益率 (年平均) が 5% 以上、(3) 修正ROAまたは有形固定資産回転率の改善目標達成。',
 '{"op": "all", "of": [{"op": "lte", "field": "capital_jpy", "value": 100000000}, {"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "has_keiei_kyoka_keikaku", "value": true}, {"op": "eq", "field": "kyoka_keikaku_type", "value": "D"}, {"op": "eq", "field": "involves_ma_consolidation", "value": true}, {"op": "gte", "field": "expected_investment_roi", "value": 0.05}]}',
 '即時償却 または 税額控除 10% (資本金3,000万円超は7%)',
 '即時償却額 = 取得価額全額 / 税額控除額 = 取得価額 × 10% (上限 法人税額の20%)',
 '経営力向上計画認定証 (経営資源集約化措置含む) + 経済産業局確認書 + 確定申告書別表六(二十六)を添付。',
 '中小企業庁', 'https://www.chusho.meti.go.jp/',
 'https://www.chusho.meti.go.jp/keiei/kyoka/',
 NULL, NULL,
 0.82, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

-- ----------------------------------------------------------------------------
-- 4. IT導入補助金 会計処理 (圧縮記帳・直接控除) — 補助金会計処理 ZERO 単独収録
-- ----------------------------------------------------------------------------

('TAX-973b38511c',
 'IT導入補助金 会計処理 (圧縮記帳・直接控除の選択)',
 'corporate', 'other',
 '2017-04-01', NULL,
 '["PENDING:法人税法第42条", "PENDING:法人税基本通達10-2-2"]',
 'IT導入補助金等の国庫補助金を受けて固定資産を取得した場合、(1) 圧縮記帳 (法人税法42条) — 補助金額を取得価額から控除し、控除後の金額を帳簿価額として減価償却 — または (2) 直接控除方式 (法人税基本通達10-2-2) — 補助金収入を雑収入計上し同額を圧縮損で計上 — のいずれかを選択する。\n\nいずれの方式でも、補助金確定額が翌期以降に通知される場合は前期に概算計上した補助金収入を翌期に修正する。返還義務の生じない補助金確定後の事業年度で会計処理する。\n\n[needs_verification: true] — IT導入補助金の場合、補助対象経費がソフトウェア (無形固定資産) のため償却資産税の対象外。圧縮記帳の対象資産限定 (国庫補助金等で取得した固定資産) には含まれる。',
 '{"op": "all", "of": [{"op": "eq", "field": "received_subsidy", "value": true}, {"op": "eq", "field": "subsidy_type", "value": "kokko_hojokin"}, {"op": "eq", "field": "blue_form_return_filed", "value": true}]}',
 '圧縮記帳: 補助金額分の取得価額減額 / 直接控除: 雑収入計上 + 同額圧縮損',
 '圧縮記帳後簿価 = 取得価額 - 補助金額 / 直接控除では損益相殺 (P/L影響ゼロ)',
 '確定申告書別表十三(一) (圧縮記帳の場合) または法人税申告書別表四 (直接控除の場合) を添付。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5450.htm',
 NULL, NULL,
 0.85, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

('TAX-c96b918b41',
 '国庫補助金等の圧縮記帳 (法人税法42条)',
 'corporate', 'special_depreciation',
 '1965-04-01', NULL,
 '["PENDING:法人税法第42条"]',
 '法人が国庫補助金等の交付を受け、その補助金等をもって取得した固定資産について、補助金等の額に相当する金額を限度として、その固定資産の帳簿価額から損金経理により減額する圧縮記帳が認められる。これにより補助金収入と取得価額の損金算入額がオフセットされ、補助金交付年度に課税所得が生じない。\n\n圧縮記帳後の固定資産は、減額後の帳簿価額を取得価額として減価償却する。途中で固定資産を譲渡した場合、譲渡益課税時に圧縮損の繰戻しが必要。\n\n対象: 国・地方公共団体・独立行政法人等から交付される補助金等で、固定資産取得を目的とするもの。IT導入補助金、ものづくり補助金、事業再構築補助金、小規模事業者持続化補助金 (建物・機械等) 等が該当。',
 '{"op": "all", "of": [{"op": "eq", "field": "received_subsidy", "value": true}, {"op": "in", "field": "subsidy_type", "values": ["kokko_hojokin", "chiho_hojokin"]}, {"op": "eq", "field": "subsidy_used_for_fixed_asset", "value": true}, {"op": "eq", "field": "blue_form_return_filed", "value": true}]}',
 '圧縮限度額 = 国庫補助金等の額 (固定資産取得価額が上限)',
 '圧縮記帳後帳簿価額 = 取得価額 - 圧縮損 (圧縮限度額)',
 '確定申告書別表十三(一)を添付。圧縮損の損金経理 (損金経理要件あり、申告調整不可)。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5450.htm',
 NULL, NULL,
 0.92, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

-- ----------------------------------------------------------------------------
-- 5. 一括償却資産 (法人税法施行令139条の2)
-- ----------------------------------------------------------------------------

('TAX-d9b1b00171',
 '一括償却資産の損金算入 (法人税法施行令139条の2)',
 'corporate', 'special_depreciation',
 '1998-04-01', NULL,
 '["PENDING:法人税法施行令第139条の2"]',
 '取得価額が10万円以上20万円未満の少額減価償却資産について、個別に減価償却計算を行わず、一括して3年間で均等償却 (取得価額の3分の1ずつを各事業年度で損金算入) できる制度。事業年度の中途で取得した場合でも月割計算は不要 (取得年度・翌年度・翌々年度に1/3ずつ計上)。\n\n償却資産税 (固定資産税) の対象外となるメリットがあり、中小企業の少額減価償却資産特例 (TAX-d87099a1d1、年300万円まで30万円未満を即時償却) と並んで、設備投資の負担軽減策として広く利用されている。\n\n対象法人を限定しない (中小企業者等以外も適用可)。',
 '{"op": "all", "of": [{"op": "gte", "field": "asset_acquisition_price_jpy", "value": 100000}, {"op": "lte", "field": "asset_acquisition_price_jpy", "value": 199999}]}',
 '取得価額の3分の1ずつ3年間損金算入',
 '各事業年度の損金算入額 = 取得価額 × 1/3 (3事業年度均等)',
 '確定申告書別表十六(八)を添付。一括償却資産の明細書を保存。',
 '国税庁', 'https://www.nta.go.jp/',
 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5403.htm',
 NULL, NULL,
 0.92, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

-- ----------------------------------------------------------------------------
-- 6. 賃上げ促進税制 上乗せ要件 (措置法42条の12の5)
--    既存の TAX-8ab852254f (中小企業賃上げ促進税制) の上乗せ条件詳細を分離収録。
-- ----------------------------------------------------------------------------

('TAX-befeb267d6',
 '給与等支給額の特別控除 (措置法42条の12の5 賃上げ促進税制 上乗せ要件)',
 'corporate', 'credit',
 '2024-04-01', NULL,
 '["PENDING:租税特別措置法第42条の12の5"]',
 '令和6年度改正後の賃上げ促進税制の上乗せ要件 (中小企業者等向け)。基本控除率15%に加え、(1) 給与等支給額の前年度比増加割合が 2.5% 以上で +15% 上乗せ、(2) 教育訓練費が前年度比 5% 以上増加で +10% 上乗せ、(3) 子育て・女性活躍 (くるみん認定 / プラチナくるみん / えるぼし二段階以上) で +5% 上乗せ。最大45%の控除率。\n\n控除限度額は法人税額の20%。控除限度超過額は5年間繰越可 (令和6年度改正で導入された繰越欠損控除)。\n\n[needs_verification: true] — 上乗せ要件の判定指標は令和6年度改正で大幅変更。改正前 (令和5年度以前) と要件が異なるため適用年度を必ず確認。',
 '{"op": "all", "of": [{"op": "lte", "field": "capital_jpy", "value": 100000000}, {"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "gte", "field": "salary_increase_ratio", "value": 0.015}]}',
 '基本15% + 上乗せ最大30% (合計最大45%)',
 '税額控除額 = 給与等支給増加額 × 控除率 (15%〜45%)、法人税額の20%上限、5年繰越可',
 '確定申告書別表六(三十一)を添付。給与等支給額計算明細 + 教育訓練費領収書 + くるみん認定書等を保存。',
 '中小企業庁', 'https://www.chusho.meti.go.jp/',
 'https://www.chusho.meti.go.jp/zaimu/zeisei/chinage_zeisei.html',
 NULL, NULL,
 0.83, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

-- ----------------------------------------------------------------------------
-- 7. DX 投資促進税制 (措置法42条の12の7)
-- ----------------------------------------------------------------------------

('TAX-f0e330d8c5',
 'DX投資促進税制 (措置法42条の12の7 デジタルトランスフォーメーション投資促進)',
 'corporate', 'credit',
 '2021-08-02', '2025-03-31',
 '["PENDING:租税特別措置法第42条の12の7"]',
 '産業競争力強化法の事業適応計画 (情報技術事業適応) について経済産業大臣の認定を受けた青色申告法人が、その計画に従って取得・事業供用したソフトウェア・繰延資産・固定資産について、取得価額の30%の特別償却または3% (グループ会社外との連携で5%) の税額控除を選択適用できる制度。\n\nDX要件: (1) デジタル要件 — クラウド技術活用 + データ連携 (社内外) + サイバーセキュリティ確保、(2) 企業変革要件 — 全社レベルの計画 + 経営者の関与 + ROIC・売上高比率の目標達成。\n\n対象期間: 令和3年8月2日〜令和7年3月31日 (令和7年度税制改正で延長検討中)。設備投資総額300億円超の部分は対象外 (他制度同様)。',
 '{"op": "all", "of": [{"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "has_dx_certification", "value": true}, {"op": "in", "field": "asset_category", "values": ["software", "deferred_asset", "fixed_asset"]}]}',
 '特別償却 30% または 税額控除 3% (グループ外連携で5%、法人税額の20%上限)',
 '特別償却額 = 取得価額 × 30% / 税額控除額 = 取得価額 × 3% (5%)',
 '事業適応計画認定書 + 確定申告書別表六(三十)を添付。',
 '経済産業省', 'https://www.meti.go.jp/',
 'https://www.meti.go.jp/policy/economy/keiei_innovation/keieikyoka/dx_zeisei.html',
 NULL, NULL,
 0.80, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z'),

-- ----------------------------------------------------------------------------
-- 8. カーボンニュートラル投資促進税制 (措置法42条の12の7)
-- ----------------------------------------------------------------------------

('TAX-4b6ef9eed9',
 'カーボンニュートラル投資促進税制 (措置法42条の12の7)',
 'corporate', 'credit',
 '2021-08-02', '2026-03-31',
 '["PENDING:租税特別措置法第42条の12の7"]',
 '産業競争力強化法の事業適応計画 (エネルギー利用環境負荷低減事業適応) について経済産業大臣の認定を受けた青色申告法人が、その計画に従って取得・事業供用した機械装置等について、取得価額の50%の特別償却または5% (温室効果ガス削減割合10%以上で10%) の税額控除を選択適用できる制度。\n\n対象設備: (1) 生産工程効率化設備 — 製造工程の温室効果ガス排出量を削減する設備、(2) 需要開拓商品生産設備 — 化石燃料使用製品の代替となる商品の生産設備 (例: EV、再エネ設備、水素製造設備等)。\n\n対象期間: 令和3年8月2日〜令和8年3月31日。投資額500億円が上限 (税額控除分)。',
 '{"op": "all", "of": [{"op": "eq", "field": "blue_form_return_filed", "value": true}, {"op": "eq", "field": "has_carbon_neutral_certification", "value": true}, {"op": "in", "field": "asset_category", "values": ["machinery", "equipment"]}]}',
 '特別償却 50% または 税額控除 5%〜10% (法人税額の20%上限)',
 '特別償却額 = 取得価額 × 50% / 税額控除額 = 取得価額 × 5% (10%)',
 '事業適応計画認定書 + 確定申告書別表六(三十)を添付。',
 '経済産業省', 'https://www.meti.go.jp/',
 'https://www.meti.go.jp/policy/energy_environment/global_warming/SBT/cn_tax.html',
 NULL, NULL,
 0.80, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z');

-- ----------------------------------------------------------------------------
-- FTS5 sync — same 15 rows for trigram /search.
-- INSERT OR IGNORE on (unified_id) primary-key behavior of FTS5 contentless
-- table is achieved by a guarded existence check (FTS5 has no UNIQUE/PRIMARY
-- KEY constraint; we mirror the encode_tax_rulesets.py UPSERT pattern).
-- ----------------------------------------------------------------------------

DELETE FROM tax_rulesets_fts WHERE unified_id IN (
    'TAX-ca4b993ca5', 'TAX-8db8646e62', 'TAX-1964f6ff26', 'TAX-7fae3b3baa',
    'TAX-4b9317d2c4', 'TAX-369a30f0ce', 'TAX-14cf2308be', 'TAX-e0debfd9e8',
    'TAX-9265ed17b7', 'TAX-973b38511c', 'TAX-c96b918b41', 'TAX-d9b1b00171',
    'TAX-befeb267d6', 'TAX-f0e330d8c5', 'TAX-4b6ef9eed9'
);

INSERT INTO tax_rulesets_fts (unified_id, ruleset_name, eligibility_conditions, calculation_formula)
SELECT unified_id, ruleset_name, eligibility_conditions, calculation_formula
FROM tax_rulesets
WHERE unified_id IN (
    'TAX-ca4b993ca5', 'TAX-8db8646e62', 'TAX-1964f6ff26', 'TAX-7fae3b3baa',
    'TAX-4b9317d2c4', 'TAX-369a30f0ce', 'TAX-14cf2308be', 'TAX-e0debfd9e8',
    'TAX-9265ed17b7', 'TAX-973b38511c', 'TAX-c96b918b41', 'TAX-d9b1b00171',
    'TAX-befeb267d6', 'TAX-f0e330d8c5', 'TAX-4b6ef9eed9'
);

PRAGMA foreign_keys = ON;
