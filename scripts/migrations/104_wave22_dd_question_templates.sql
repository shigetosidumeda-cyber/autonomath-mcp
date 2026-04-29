-- target_db: autonomath
-- migration 104_wave22_dd_question_templates
--
-- Wave 22 composition tools — supporting question template DB for
-- match_due_diligence_questions. The tool returns 30-50 DD questions
-- tailored to (industry × program portfolio × 与信 risk) by joining
-- this template DB with the existing programs / tax_rulesets / jpi_*
-- tables. NO LLM call.
--
-- The question text itself is intentionally informational ("the auditor
-- should confirm X") — never advisory ("you must do Y"). This keeps the
-- output inside the §52 disclaimer fence: it is information retrieval
-- against a curated checklist, not 税務代理 / 行政書士 §1 / 弁護士法 §72.
--
-- Forward-only / idempotent. Re-running on each Fly boot is safe.
-- Every CREATE uses IF NOT EXISTS and every seed INSERT uses
-- INSERT OR IGNORE keyed on a deterministic question_id.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- dd_question_templates — DD question library
-- ---------------------------------------------------------------------------
-- Each row is one templated DD question. The question is selected at
-- query time by:
--   * industry_jsic_major  (pattern-match against target's industry; '*' = any)
--   * program_kind         ('subsidy' / 'tax_measure' / 'loan' / 'cert' / '*')
--   * risk_dimension       ('credit' / 'enforcement' / 'invoice_compliance' /
--                            'industry_specific' / 'lifecycle' / 'tax')
--   * severity_weight      (0..100; higher = surface earlier in the deck)
--
-- The dispatcher in match_due_diligence_questions composes a 30-50 row
-- result by ORDER BY severity_weight DESC then category, capping at the
-- per-category quotas (no single dimension dominates the deck).

CREATE TABLE IF NOT EXISTS dd_question_templates (
    question_id          TEXT PRIMARY KEY,        -- e.g. 'dd:credit:001'
    question_ja          TEXT NOT NULL,           -- the DD question itself
    question_category    TEXT NOT NULL,           -- 'credit' / 'enforcement' / 'invoice_compliance' / 'industry_specific' / 'lifecycle' / 'tax' / 'governance'
    industry_jsic_major  TEXT NOT NULL DEFAULT '*',  -- 'A'..'T' or '*' for any
    program_kind         TEXT NOT NULL DEFAULT '*',  -- 'subsidy' / 'tax_measure' / 'loan' / 'cert' / '*'
    risk_dimension       TEXT NOT NULL,           -- mirrors category, kept distinct for future split
    severity_weight      INTEGER NOT NULL DEFAULT 50 CHECK (severity_weight BETWEEN 0 AND 100),
    rationale_short      TEXT,                    -- 1-line why this question matters
    primary_source_hint  TEXT,                    -- URL or law reference (e.g. '法人税法 §141')
    citation_hint        TEXT,                    -- additional drill-down hint for the LLM
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dd_q_industry
    ON dd_question_templates(industry_jsic_major, severity_weight DESC);

CREATE INDEX IF NOT EXISTS idx_dd_q_kind
    ON dd_question_templates(program_kind, severity_weight DESC);

CREATE INDEX IF NOT EXISTS idx_dd_q_dim
    ON dd_question_templates(risk_dimension, severity_weight DESC);

-- ---------------------------------------------------------------------------
-- Seed data — 60 question templates covering 7 categories.
--   credit (10) / enforcement (10) / invoice_compliance (8) /
--   industry_specific (12 — 4 industries × 3) / lifecycle (8) /
--   tax (8) / governance (4)
-- Severity 80+ surfaces unconditionally; 50-70 fills the rest of the deck.
-- ---------------------------------------------------------------------------

-- == credit (10) =============================================================
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:credit:001', '直近3期の売上総利益率の推移を確認できる決算書を提示してください。', 'credit', 'credit', 90, '与信判断の基礎指標。3期連続赤字は要対応。', NULL),
('dd:credit:002', '日本政策金融公庫または民間金融機関からの借入残高と返済予定表を提示してください。', 'credit', 'credit', 90, 'jfc.go.jp / 三軸保証分解との突合せに必要。', 'https://www.jfc.go.jp/'),
('dd:credit:003', '個人保証人 / 第三者保証人の有無、および経営者保証ガイドラインの適用状況を確認してください。', 'credit', 'credit', 85, '担保・個人保証人・第三者保証人 三軸分解 (108 融資 corpus)。', NULL),
('dd:credit:004', '信用情報機関 (CIC / JICC / KSC) への登録状況、過去5年の延滞履歴を確認してください。', 'credit', 'credit', 80, '登記簿謄本では拾えない信用イベント。', NULL),
('dd:credit:005', '直近1期の現預金残高と月商比 (月商の何ヶ月分か) を確認してください。', 'credit', 'credit', 75, '運転資金枯渇リスクの早期検知指標。', NULL),
('dd:credit:006', '主要取引先 (売上上位3社) の依存度と支払条件を確認してください。', 'credit', 'credit', 70, '取引先集中リスクは与信減点要因。', NULL),
('dd:credit:007', '債務超過の有無、および直近の純資産変動を確認してください。', 'credit', 'credit', 80, '会社法 §466 / 税法上の繰越欠損金との関連。', NULL),
('dd:credit:008', '社債・転換社債型新株予約権付社債の発行残高を確認してください。', 'credit', 'credit', 60, '上場企業 / 中堅以上で関連。', NULL),
('dd:credit:009', '関係会社・グループ企業向け債権・債務の存在と回収可能性を確認してください。', 'credit', 'credit', 65, '連結・関連当事者開示の論点。', NULL),
('dd:credit:010', '担保差入資産 (不動産 / 売掛金 / 在庫) の評価と二重担保の有無を確認してください。', 'credit', 'credit', 70, '担保価値再評価で借入余力推定。', NULL);

-- == enforcement (10) ========================================================
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:enforce:001', '過去5年間の補助金返還命令・行政処分の有無を確認してください。', 'enforcement', 'enforcement', 95, '行政処分 1,185 件 corpus + am_enforcement_detail (22,258 行)。', NULL),
('dd:enforce:002', '所属する業界団体・認定機関からの除名・指名停止履歴を確認してください。', 'enforcement', 'enforcement', 80, '指名停止は補助金不採択リスク。', NULL),
('dd:enforce:003', '景表法・特定商取引法・下請法に関する指導・命令の有無を確認してください。', 'enforcement', 'enforcement', 80, '消費者庁・公正取引委員会 公表案件。', 'https://www.caa.go.jp/'),
('dd:enforce:004', '労働基準監督署からの是正勧告・送検の有無を確認してください。', 'enforcement', 'enforcement', 85, '労基法違反は補助金不採択 / 行政書士法業務範囲外。', 'https://www.mhlw.go.jp/'),
('dd:enforce:005', '過去の不正受給事案・補助金返還命令との関連性 (グループ企業 / 元代表) を確認してください。', 'enforcement', 'enforcement', 90, '適正化法 17 条 / 19 条 リスク。', NULL),
('dd:enforce:006', '租税滞納処分・差押え履歴の有無を確認してください。', 'enforcement', 'enforcement', 85, '国税徴収法 / 地方税法。', NULL),
('dd:enforce:007', '不動産登記簿上の差押え・仮差押えの記載を確認してください。', 'enforcement', 'enforcement', 70, '法務局 (登記情報提供サービス) で取得可能。', NULL),
('dd:enforce:008', '反社会的勢力との取引・関与の有無に関する誓約書の有無を確認してください。', 'enforcement', 'enforcement', 90, '暴対法 / 各都道府県暴排条例。', NULL),
('dd:enforce:009', '経営者・主要株主の刑事訴追歴を確認してください。', 'enforcement', 'enforcement', 75, '欠格事由 (補助金交付要綱) の論点。', NULL),
('dd:enforce:010', '官公庁との契約における指名停止・参加停止の有無を確認してください。', 'enforcement', 'enforcement', 80, 'CALS/EC・各府省指名停止リストとの突合せ。', NULL);

-- == invoice_compliance (8) =================================================
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:invoice:001', '適格請求書発行事業者登録番号 (T番号) の登録日と取消日 / 失効日を確認してください。', 'invoice_compliance', 'invoice_compliance', 95, 'invoice_registrants 13,801 行 corpus, NTA 一次資料。', 'https://www.invoice-kohyo.nta.go.jp/'),
('dd:invoice:002', '消費税課税事業者選択届出書 / 簡易課税制度選択届出書の提出履歴を確認してください。', 'invoice_compliance', 'invoice_compliance', 85, '免税事業者からの仕入税額控除経過措置との関連。', 'https://www.nta.go.jp/'),
('dd:invoice:003', '取引先 (主要仕入先) の T番号登録状況と免税事業者比率を確認してください。', 'invoice_compliance', 'invoice_compliance', 80, '令和8年9月までは80%控除、それ以降は50%控除の段階引下げ。', NULL),
('dd:invoice:004', '電子帳簿保存法 (令和4年改正) 対応の電子取引保存・スキャナ保存方式の整備状況を確認してください。', 'invoice_compliance', 'invoice_compliance', 75, '令和6年1月から電子取引データ保存義務化済。', NULL),
('dd:invoice:005', '会計システムが適格請求書 (8% / 10% 区分記載) に対応しているか確認してください。', 'invoice_compliance', 'invoice_compliance', 70, 'システム不対応は経理ミスからの過少申告リスク。', NULL),
('dd:invoice:006', '免税事業者であった期間の開始・終了日と、課税事業者への移行時期を確認してください。', 'invoice_compliance', 'invoice_compliance', 70, '基準期間 (前々事業年度) の課税売上1000万円判定。', NULL),
('dd:invoice:007', '輸出免税取引・非課税売上の有無と区分記載状況を確認してください。', 'invoice_compliance', 'invoice_compliance', 60, '個別対応方式 / 一括比例配分方式の選択。', NULL),
('dd:invoice:008', '適格請求書発行事業者登録の取消申請の予定有無を確認してください。', 'invoice_compliance', 'invoice_compliance', 65, '取消は翌課税期間以降に効力発生 (15日前申請)。', NULL);

-- == industry_specific (12 — 4 industries × 3) ==============================
-- A: 農業、林業
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, industry_jsic_major, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:ind:A:001', '認定農業者 / 認定新規就農者の認定状況と認定計画の進捗を確認してください。', 'industry_specific', 'A', 'industry_specific', 80, '農業経営基盤強化促進法 §12, MAFF 一次資料。', 'https://www.maff.go.jp/'),
('dd:ind:A:002', '農地所有適格法人としての要件充足 (議決権 / 役員 / 事業) を確認してください。', 'industry_specific', 'A', 'industry_specific', 85, '農地法 §2 第3項。', NULL),
('dd:ind:A:003', '青色申告の継続承認状況、収入保険 / ナラシ対策加入の有無を確認してください。', 'industry_specific', 'A', 'industry_specific', 70, '農林漁業セーフティネット。', NULL);

-- E: 製造業
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, industry_jsic_major, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:ind:E:001', '中小企業等経営強化法に基づく経営力向上計画の認定状況を確認してください。', 'industry_specific', 'E', 'industry_specific', 80, 'METI 認定計画は税制優遇 (中小企業経営強化税制) の前提。', 'https://www.chusho.meti.go.jp/'),
('dd:ind:E:002', 'ものづくり補助金 / 事業再構築補助金の交付決定 / 採択履歴を確認してください。', 'industry_specific', 'E', 'industry_specific', 75, '採択事例 2,286 件 corpus。', NULL),
('dd:ind:E:003', '環境関連法令 (廃棄物処理法・化管法 PRTR) の届出義務充足を確認してください。', 'industry_specific', 'E', 'industry_specific', 70, '届出漏れは行政処分 / 補助金不採択リスク。', NULL);

-- G: 情報通信業
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, industry_jsic_major, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:ind:G:001', 'IT導入補助金の交付決定履歴と要件充足 (DX推進指標 等) を確認してください。', 'industry_specific', 'G', 'industry_specific', 75, 'IT導入補助金 会計処理 (措置法42-4) との関連。', 'https://www.it-hojo.jp/'),
('dd:ind:G:002', '個人情報保護法 (令和2年改正) に基づく個人情報取扱事業者としての届出 / 同意取得状況を確認してください。', 'industry_specific', 'G', 'industry_specific', 80, '個人情報の漏えい等の報告義務 (令和4年4月施行)。', 'https://www.ppc.go.jp/'),
('dd:ind:G:003', 'プライバシーマーク / ISMS (ISO 27001) の認証取得状況を確認してください。', 'industry_specific', 'G', 'industry_specific', 65, '認定 corpus 66 件、認証は対外信用の前提。', NULL);

-- M: 宿泊業、飲食サービス業
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, industry_jsic_major, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:ind:M:001', '飲食店営業許可 / 旅館業法に基づく許可の有効期限を確認してください。', 'industry_specific', 'M', 'industry_specific', 90, '食品衛生法 §54 / 旅館業法 §3。許可失効中は営業不可。', NULL),
('dd:ind:M:002', '食品ロス削減 / HACCP (食品衛生法 §50-2) 対応状況を確認してください。', 'industry_specific', 'M', 'industry_specific', 70, 'HACCP は2021年6月から義務化済。', NULL),
('dd:ind:M:003', '労働基準法 §41 (管理監督者) 該当者の判定が適切か (名ばかり管理職リスク) を確認してください。', 'industry_specific', 'M', 'industry_specific', 75, '労働基準監督署からの是正勧告事例多数。', NULL);

-- == lifecycle (8) ===========================================================
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:life:001', '現在受給中の補助金の交付決定通知書と精算予定を確認してください。', 'lifecycle', 'lifecycle', 85, '事業実施期間中の M&A は変更承認 / 取消リスク。', NULL),
('dd:life:002', '直近1年以内の制度改正 (sunset / 改廃) の適用時期と経過措置を確認してください。', 'lifecycle', 'lifecycle', 80, 'am_amendment_snapshot + am_amendment_diff 由来の差分検知。', NULL),
('dd:life:003', '事業承継・組織再編 (合併 / 会社分割 / 株式交換) の予定有無を確認してください。', 'lifecycle', 'lifecycle', 70, '事業承継税制 / 経営承継円滑化法との関連。', NULL),
('dd:life:004', '主要許認可の更新時期 (建設業許可 / 産廃収集運搬業 / 古物商 等) を確認してください。', 'lifecycle', 'lifecycle', 80, '更新失念は営業停止リスク。', NULL),
('dd:life:005', '加入している共済 (中退共 / 小規模企業共済 / 経営セーフティ共済) の積立残高を確認してください。', 'lifecycle', 'lifecycle', 60, 'am_insurance_mutual corpus との突合せ。', NULL),
('dd:life:006', '直近の取締役会・株主総会議事録 (合併・解散・重要資産処分) を確認してください。', 'lifecycle', 'lifecycle', 65, '会社法 §369 / §299。', NULL),
('dd:life:007', '事業計画書 (5年程度の中期計画) と前期実績との乖離率を確認してください。', 'lifecycle', 'lifecycle', 60, '計画達成率は経営力向上計画認定の継続要件。', NULL),
('dd:life:008', '主要取引先・主要仕入先との契約終了通知 / 値上げ通知の受領状況を確認してください。', 'lifecycle', 'lifecycle', 65, '取引先依存度の経時変化。', NULL);

-- == tax (8) =================================================================
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:tax:001', '直近3期の法人税・消費税・地方税の申告書類と税務調査履歴を確認してください。', 'tax', 'tax', 90, '直近3期 = 国税通則法上の更正期間 (5年) との均衡。', NULL),
('dd:tax:002', '繰越欠損金の残高、利用可能期間、欠損金の引継ぎ要件を確認してください。', 'tax', 'tax', 85, '法人税法 §57, 組織再編税制との関連。', NULL),
('dd:tax:003', '研究開発税制 (措置法 §42-4) / 賃上げ促進税制 (措置法 §42-12-5) の適用状況を確認してください。', 'tax', 'tax', 80, 'jpi_tax_rulesets 50 件 corpus との突合せ。', NULL),
('dd:tax:004', '中小企業経営強化税制 / 中小企業投資促進税制の適用設備リストを確認してください。', 'tax', 'tax', 75, '経営力向上計画認定が前提条件。', NULL),
('dd:tax:005', '国際取引・移転価格税制 (措置法 §66-4) のリスク評価を確認してください。', 'tax', 'tax', 70, 'am_tax_treaty 70 行 国際課税 cohort surface。', NULL),
('dd:tax:006', '消費税の還付申告 (輸出 / 設備投資) と税務署の確認結果を確認してください。', 'tax', 'tax', 70, '高額還付は税務調査誘発要因。', NULL),
('dd:tax:007', '役員報酬 (定期同額給与 / 事前確定届出給与) の支給形態を確認してください。', 'tax', 'tax', 75, '法人税法 §34, 損金不算入リスク。', NULL),
('dd:tax:008', '寄附金・交際費の損金算入限度超過分の管理状況を確認してください。', 'tax', 'tax', 60, '法人税法 §37, §61-4。', NULL);

-- == governance (4) ==========================================================
INSERT OR IGNORE INTO dd_question_templates
(question_id, question_ja, question_category, risk_dimension, severity_weight, rationale_short, primary_source_hint)
VALUES
('dd:gov:001', '法人番号 / 商号 / 本店所在地が国税庁法人番号公表サイトと一致しているかを確認してください。', 'governance', 'governance', 95, 'houjin_master 166,765 行 corpus との一次資料突合せ。', 'https://www.houjin-bangou.nta.go.jp/'),
('dd:gov:002', '実質的支配者 (UBO) の届出状況、株主名簿の最新化を確認してください。', 'governance', 'governance', 80, '商業登記法 §17-2 (令和4年9月施行)。', NULL),
('dd:gov:003', '取締役会・監査役会の設置状況、社外取締役 / 独立社外監査役の有無を確認してください。', 'governance', 'governance', 70, '会社法 §327 / §327-2。', NULL),
('dd:gov:004', '内部統制 (J-SOX) の整備状況、不正事例の有無を確認してください。', 'governance', 'governance', 65, '金融商品取引法 §24-4-4 (上場企業のみ)。', NULL);

-- ---------------------------------------------------------------------------
-- Sanity check view — used by health probe / smoke tests.
-- ---------------------------------------------------------------------------

CREATE VIEW IF NOT EXISTS v_dd_question_template_summary AS
SELECT
    question_category,
    COUNT(*) AS rows_total,
    AVG(severity_weight) AS avg_severity,
    SUM(CASE WHEN severity_weight >= 80 THEN 1 ELSE 0 END) AS high_severity_count
FROM dd_question_templates
GROUP BY question_category
ORDER BY question_category;
