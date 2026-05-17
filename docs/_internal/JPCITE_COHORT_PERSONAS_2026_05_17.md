# jpcite F2 — 5 Cohort Persona Workflow Deep Dive (2026-05-17)

作成日: 2026-05-17
担当: F2 cohort persona deep dive
Status: research-only deliverable. CONSTRAINTS = READ-ONLY / NO LLM / [lane:solo] / safe_commit.
保存先: `docs/_internal/JPCITE_COHORT_PERSONAS_2026_05_17.md`

> Scope: 5 cohort (税理士 / 会計士 / 行政書士 / 司法書士 / 中小経営者) × ~8 業務 = **40 業務**を、actual workflow + friction + jpcite endpoint mapping + ¥3/req 経済性で評価する。前提は既存 `docs/_internal/csv_output_catalog_by_user_type_deepdive_2026-05-15.md`, `R8_tax_chain_full_surface_2026-05-07.md`, `ai_professional_public_layer_plan_2026-05-06.md` の cohort 検討と現行 `docs/api-reference.md` 上の **219 path / 146 MCP tool** 体系。

---

## 0. Executive summary

- **40 業務 mapped** に対し、**「現状ほぼ 1 call」=14 業務 / 「N round trip 必要」=18 業務 / 「現状未対応」=8 業務**。
- 1 call で解ける業務の多くは「公的根拠確認・候補出し・引当」で、**¥3/req は ROI 圧倒的に positive** (代替手段 = 30-90 分人手調査 ≒ ¥1,500-¥4,500 相当)。
- N round trip 必要業務は **composed tool** (Dim P) 化で 5-10 → 1 call 圧縮可能。`tax_rule_full_chain` / `houjin_360` / `case_cohort_match` / `dd_question_match` が成功 pattern。
- 未対応 8 業務 は士業独占業務 (税務代理 / 法律解釈 / 監査意見 / 申請書面作成) に直結し、**disclaimer 軸を越えた substitution は出さない方針を堅持**。
- **Top 15 high-value endpoint** が cohort 横断で重なる → 1 surface multi-cohort 訴求が成立 (CSV coverage receipt / company_public_baseline / tax_rule_full_chain / houjin_360 / case_cohort_match)。

---

## 1. Cohort 共通 mapping framework

各 cohort × 業務を次 5 軸で評価する。出力 matrix は §3。

| 軸 | 値 |
|---|---|
| 月次/年次 cadence | monthly / quarterly / annually / event-driven |
| friction 種別 | 時間 / 知識分散 / 法改正追跡 / 名寄せ / 同名法人 / 二次情報リスク / 出典確認 |
| jpcite endpoint 適合度 | direct (1 call) / composed (composition_tool で 1 call) / N round-trip / 未対応 |
| ¥3/req 経済性 | positive (代替 >¥1,500/件) / break-even (¥300-¥1,500) / negative or 越権 |
| 既存 surface 充足 | full / partial / none |

「越権」は士業独占業務に踏み込む surface (個別税務判断、法令解釈、申請書面作成、監査意見)。jpcite 方針は **越権越え禁止 = 充足しない**。

---

## 2. Cohort 別 actual workflow + friction + endpoint mapping

### 2.1 税理士 (cohort: 月次/年次 8 業務)

| # | 業務 | cadence | friction | jpcite endpoint (現状) | round-trip | ¥3/req 経済性 | 既存充足 |
|---|---|---|---|---|---|---|---|
| 1 | 月次仕訳・試算表確認 | monthly | 顧問先 CSV ベンダー差・摘要欠落・部門/補助科目欠落 | `csv_coverage_receipt` (P0 計画) + `account_vocabulary_map` (P0 計画) | direct (1 call/月) | positive (代替=30分人手) | partial (P0 計画は landed、UI 経路は未) |
| 2 | 給与計算・年末調整サマリ | monthly + annually | 給与 CSV 列差 + 法定調書区分 + 給与所得控除区分 (制度改正追従) | `csv_coverage_receipt` + `tax_rule_full_chain` (給与所得 / 扶養控除) | direct → composed (2 axis) | positive | partial |
| 3 | 償却資産申告 | annually (1月末) | 自治体差 + 償却資産対象範囲 + 取得価額判定 | `tax_rule_full_chain` (措置法42-4 等) + `am/example_profiles` | composed (2 call) | positive | partial |
| 4 | 法人税申告 (別表4/5) | annually | 加算減算項目 + 措置法適用判定 + 法改正追跡 | `tax_rule_full_chain` (50 ruleset) + `am/by_law` + `nta_tsutatsu_index` | **composed (1 call via tax_rule_full_chain)** | positive | full (R8 landed) |
| 5 | 消費税申告 (簡易/原則/2割特例) | annually + quarterly | インボイス制度 + 区分記載 + 2割特例 sunset | `tax_rule_full_chain` (消費税) + `invoice_registrants/search` | **composed (1 call)** | positive | full |
| 6 | 顧問先インボイス登録/取引先確認 | event-driven | 13,801 row delta + 4M row 月次 zenken bulk + T番号確認 + 同名法人 | `invoice_registrants/{T番号}` + `invoice_registrants/search` | direct (1 call/件) | positive (代替=NTA bulk DL+grep) | full |
| 7 | 顧問先制度提案 (補助金/税制) | quarterly | 制度知識分散 + 業種/地域/従業員数 fence + 排他/併用ルール | `case_cohort_match` (R8) + `exclusions/check` + `programs/batch` | composed (3 call → 1 call) | positive | full |
| 8 | 月次監査証跡 (audit_seal pack) | monthly | 顧問先別 RSS + 監査痕跡 + 法改正 since 前回 | `_audit_seal.py` (mig 089) + `prepare_kessan_briefing` (Wave 22) + `recurring_engagement` (mig 099) | direct (1 call/月/顧問先) | positive | full |

**税理士 top 3 most-valuable endpoint:**
1. **`tax_rule_full_chain`** — 50 ruleset × 6 axis (規定本文/laws/通達/裁決/判例/history) を 1 call。法人税/消費税申告の知識分散 friction を直接圧縮。
2. **`invoice_registrants/*`** — 13,801 row delta + 4M row 月次 bulk + PDL v1.0 attribution。NTA bulk DL+grep を ¥3/req に圧縮、顧問先取引先確認の主軸。
3. **`prepare_kessan_briefing`** (Wave 22) — 月次/四半期 amendment summary を 1 call。`am_amendment_diff` (cron-live since 2026-05-02) を顧問先別 FY window で fan-out。

### 2.2 会計士 (cohort: 月次/年次 8 業務)

| # | 業務 | cadence | friction | jpcite endpoint (現状) | round-trip | ¥3/req 経済性 | 既存充足 |
|---|---|---|---|---|---|---|---|
| 9 | 監査計画 (リスク評価) | annually | 同名法人 + 業種/地域 + 行政処分履歴 + 開示書類連携 | `houjin_360` (R8) + `enforcement-cases/search` | composed (2 call) | positive | full |
| 10 | 内部統制評価 (J-SOX) | quarterly | 統制活動 framework + 監査基準改正追跡 | (未対応 - 監査意見越権) | 未対応 | negative (越権) | none |
| 11 | PBC list 受領 CSV 確認 | event-driven | CSV 完全性 + 列プロファイル + 法人 identity 突合 | `csv_coverage_receipt` + `public_identity_reconciliation_sheet` (P0 計画) | direct (1 call) | positive | partial |
| 12 | 関連当事者・関係会社 mapping | quarterly | 法人番号 + 旧商号 + 同名法人 + 連結範囲 | `houjin_360` + `entity_id_map` | composed (2 call) | positive | full |
| 13 | 監査調書 PBC 公的証跡 | quarterly | 法人基本 + 処分履歴 + 適格事業者 + 入札 + 法令 | `evidence/packets/query` (max 100 batch) | **direct (batch 1 call)** | positive (代替=5 site手回し) | full |
| 14 | 法令・基準改正追跡 | quarterly | e-Gov + JICPA + ASBJ + 会計士法 §47条の2 boundary | `laws/search` + `am_amendment_diff` | composed (2 call) | break-even | partial |
| 15 | レビュー/合意手続 (税効果) | annually | 税制改正 + 繰延税金資産回収可能性 | `tax_rule_full_chain` + `am/example_profiles` | composed (2 call) | positive | partial |
| 16 | DD (M&A) 公的情報パック | event-driven | 法人 360 + 処分 + 採択 + 調達 + 適格事業者 + DD 質問 deck | `houjin_360` + `match_due_diligence_questions` (Wave 22) | **composed (1 call via DD match)** | positive (代替=半日リサーチ) | full |

**会計士 top 3:**
1. **`houjin_360`** — 法人 360 with 3-axis scoring + `entity_id_map` cross-domain view。関連当事者 mapping / DD / 監査計画の共通 base layer。
2. **`evidence/packets/batch`** — 最大 100 件 `{kind, id}` を 1 往復で packet 化、`X-Cost-Cap-JPY` + `Idempotency-Key` 必須。PBC 監査調書の公的証跡を 5 site 手回しから 1 call へ。
3. **`match_due_diligence_questions`** (Wave 22) — 60-row `dd_question_templates` × 業種 × portfolio × 与信 risk。30-60 question deck を pure SQLite + Python で組成、§52/§72 sensitive disclaimer 付き。

### 2.3 行政書士 (cohort: 月次/年次 8 業務)

| # | 業務 | cadence | friction | jpcite endpoint (現状) | round-trip | ¥3/req 経済性 | 既存充足 |
|---|---|---|---|---|---|---|---|
| 17 | 許認可申請 (建設業/宅建/古物等) | event-driven | 業種別 fence + 自治体差 + 必要書類 + 期限 | `pack_construction` / `pack_real_estate` (Wave 23) + `bundle_application_kit` (Wave 22) | **composed (1 call)** | positive (代替=自治体 HP 巡回) | full |
| 18 | 補助金/助成金申請支援 | event-driven | 公募要領 + 排他ルール + 採択事例 + 必要書類 | `programs/batch` + `case_cohort_match` + `exclusions/check` + `bundle_application_kit` | composed (4→1 via kit) | positive | full |
| 19 | 法人設立支援 | event-driven | 定款 + 株主構成 + 業種許可整合 + 法務局/税務署/年金/労保 | `bundle_application_kit` + `cross_check_jurisdiction` (Wave 22) | composed (2 call) | positive | partial (司法書士境界に留意) |
| 20 | 外国人在留資格申請 | event-driven | 在留資格区分 + 雇用契約 + 行政書士法 §1 boundary | (越権/scaffold-only — `bundle_application_kit` で scaffold + 一次 URL のみ) | direct (scaffold-only 1 call) | break-even (代替=入管 HP) | partial |
| 21 | 風営法/酒類販売業免許 | event-driven | 業種別 fence + 自治体差 + 図面/距離制限 | `pack_*` (Wave 23 未拡張) + `programs/search` (許認可 tier) | partial (Wave 23 軸外) | break-even | partial |
| 22 | 自動車登録/車庫証明 | event-driven | 自治体差 + 警察庁手続 | (現状未対応 — 制度 surface 外) | 未対応 | n/a (scope 外) | none |
| 23 | 補助金申請後 monitoring (post-award) | event-driven | 中間報告 + 実績報告 + 検査 calendar | `program_post_award_calendar` (mig 098) + `calendar/deadlines` | direct (1 call) | positive | full |
| 24 | 顧客制度提案 (営業 phase) | quarterly | 業種 × 地域 × 規模 fence + 排他/併用 + 採択率 | `case_cohort_match` + `programs/search` + `pack_*` | composed (3→1) | positive | full |

**行政書士 top 3:**
1. **`bundle_application_kit`** (Wave 22) — 必要書類 checklist + cover letter scaffold + 採択例。`行政書士法 §1` boundary を「scaffold + 一次 URL only / 申請書面 creation 禁止」で固定済み。
2. **`pack_construction` / `pack_real_estate`** (Wave 23) — JSIC D/K × 制度 top 10 + 通達/裁決 citation。許認可 + 補助金 + 関連通達を 1 call、業種 SEO の起点。
3. **`program_post_award_calendar`** (mig 098) — 採択後 monitoring calendar、申請支援後の継続 engagement (士業 reach 確保)。

### 2.4 司法書士 (cohort: 月次/年次 8 業務)

| # | 業務 | cadence | friction | jpcite endpoint (現状) | round-trip | ¥3/req 経済性 | 既存充足 |
|---|---|---|---|---|---|---|---|
| 25 | 不動産登記 (売買/抵当権/相続) | event-driven | 登記事項 + 司法書士法 §3 boundary | (越権/不動産登記簿は jpcite 外) | 未対応 | n/a (scope 外) | none |
| 26 | 商業登記 (設立/役員変更/組織再編) | event-driven | 法人基本 + 役員 + 旧商号 + cross 確認 | `houjin_360` + `cross_check_jurisdiction` (Wave 22) | composed (2 call) | positive | partial |
| 27 | 相続 + 遺産分割 + 遺言執行 | event-driven | 戸籍 + 不動産 + 預貯金 + 相続税 | `tax_rule_full_chain` (相続税) + `am/example_profiles` (相続 profile) | composed (2 call) | positive (税理士連携起点) | partial |
| 28 | 事業承継支援 | event-driven | M&A + 経営承継円滑化法 + 採択事例 + 税制特例 | `succession.py` (R8 `/v1/programs/succession_match`) + `houjin_360` | **composed (1 call via succession)** | positive | full |
| 29 | 成年後見/任意後見 | event-driven | 家庭裁判所手続 + 任意後見契約書 | (越権/家裁手続は jpcite 外) | 未対応 | n/a (scope 外) | none |
| 30 | 法人 organizational restructuring (合併/会社分割) | event-driven | 組織再編税制 + 適格判定 + 商業登記 | `tax_rule_full_chain` (組織再編税制) + `succession.py` | composed (2 call) | positive | partial |
| 31 | 担保権設定 (抵当権/根抵当権) | event-driven | 不動産 + 法人基本 + 与信 + 政策融資 | `houjin_360` + `loan-programs/search` + `am/loans` (108 row 三軸分解) | composed (2 call) | break-even | partial |
| 32 | 顧問先 corp watch (M&A signal) | monthly | 法人 amendment + 役員変更 + 処分 + 公告 | `houjin_watch` (mig 088) + `dispatch_webhooks.py` cron | direct (1 call/月) | positive | full |

**司法書士 top 3:**
1. **`houjin_360`** (R8) — 商業登記支援の前段、法人 360 + 旧商号 + cross-jurisdiction。
2. **`succession.py`** (R8 `/v1/programs/succession_match`) — M&A / 事業承継 制度 matcher、`houjin_360` と組合せで税理士/会計士連携起点。
3. **`houjin_watch`** (mig 088) + webhook — 顧問先 corp watch + amendment alert、M&A signal 起点。

### 2.5 中小経営者 (cohort: 月次/年次 8 業務)

| # | 業務 | cadence | friction | jpcite endpoint (現状) | round-trip | ¥3/req 経済性 | 既存充足 |
|---|---|---|---|---|---|---|---|
| 33 | 月次資金繰り | monthly | 売掛 + 買掛 + 入金 + 銀行残高 + (制度融資 timing) | `loan-programs/search` + `am/loans` (担保/個保/三保 三軸) | direct (1 call) | break-even (代替=銀行口座 + Excel) | partial |
| 34 | 補助金検討 (年次) | annually | 11,601 program + 業種/地域 fence + 排他/併用 + 採択率 | `case_cohort_match` + `programs/search` + `programs/prescreen` | composed (3→1) | **positive (代替=士業 ¥10K-¥50K/件)** | full |
| 35 | 税制特例検討 (年次/月次) | annually + monthly | 50 ruleset + 計算式 + 適用要件 + 提出要件 | `tax_rule_full_chain` + `am/example_profiles` | **composed (1 call)** | positive | full |
| 36 | インボイス取引先確認 | monthly | T番号 + 同名法人 + 適格事業者 | `invoice_registrants/{T番号}` | direct (1 call) | positive | full |
| 37 | 取引先与信確認 | event-driven | 法人 360 + 処分 + 公告 + 旧商号 | `houjin_360` + `enforcement-cases/search` | composed (2 call) | positive | full |
| 38 | DX/IT 投資検討 (補助金併用) | event-driven | IT導入補助 + ものづくり + 事業再構築 + 排他/併用 + 税制特例 | `pack_manufacturing` (Wave 23) + `tax_rule_full_chain` (措置法42-4) | composed (2 call) | positive | full |
| 39 | M&A/事業承継検討 | event-driven | 経営承継円滑化法 + 譲渡側/譲受側制度 + 採択事例 | `succession.py` + `case_cohort_match` | composed (2 call) | positive (代替=士業) | full |
| 40 | 行政処分/コンプライアンス確認 | quarterly | 1,185 行政処分 + 業種別 + 経営者 watch | `enforcement-cases/search` + `houjin_watch` | direct (1 call) | positive | full |

**中小経営者 top 3:**
1. **`case_cohort_match`** (R8 `POST /v1/cases/cohort_match`) — 採択事例 × 業種 × 規模 × 地域 cohort matcher。「補助金検討 (年次)」の主軸、士業 ¥10K-¥50K/件 を ¥3 へ。
2. **`tax_rule_full_chain`** — 50 ruleset を経営者目線で 1 call (士業向けと同 surface だが、disclaimer + scaffold-only で sensitive 軸を保つ)。
3. **`invoice_registrants/{T番号}`** + `houjin_360` — 取引先確認の 2 大主軸、月次 cadence で安定 reach。

---

## 3. Cohort × pain_point × jpcite_endpoint matrix (40 業務)

### 3.1 「現状ほぼ 1 call」 (14 業務)

| # | cohort | 業務 | endpoint |
|---|---|---|---|
| 4 | 税理士 | 法人税申告 | `tax_rule_full_chain` |
| 5 | 税理士 | 消費税申告 | `tax_rule_full_chain` + `invoice_registrants/search` |
| 6 | 税理士 | 顧問先インボイス確認 | `invoice_registrants/{T}` |
| 8 | 税理士 | 月次監査証跡 | `_audit_seal.py` + `prepare_kessan_briefing` |
| 13 | 会計士 | PBC 公的証跡 | `evidence/packets/batch` (100件) |
| 16 | 会計士 | DD 公的情報パック | `match_due_diligence_questions` |
| 17 | 行政書士 | 許認可申請 | `pack_*` + `bundle_application_kit` |
| 23 | 行政書士 | post-award monitoring | `program_post_award_calendar` |
| 28 | 司法書士 | 事業承継支援 | `succession.py` |
| 32 | 司法書士 | corp watch | `houjin_watch` + webhook |
| 33 | 中小経営者 | 月次資金繰り (融資検索 axis) | `loan-programs/search` |
| 35 | 中小経営者 | 税制特例検討 | `tax_rule_full_chain` |
| 36 | 中小経営者 | インボイス取引先確認 | `invoice_registrants/{T}` |
| 40 | 中小経営者 | 行政処分確認 | `enforcement-cases/search` |

### 3.2 「現状 N round trip 必要」 (18 業務、composed_tool 化候補)

| # | cohort | 業務 | 必要 round-trip | composed_tool 化後 |
|---|---|---|---|---|
| 1 | 税理士 | 月次仕訳・試算表確認 | 2 call (CSV coverage + vocabulary) | 1 call (CSV intake composed) |
| 2 | 税理士 | 給与計算 + 年末調整 | 3 call (CSV + 税制 + e-Gov) | 1 call (payroll_intake_composed) |
| 3 | 税理士 | 償却資産申告 | 3 call (措置法 + 自治体 + example) | 1 call (depreciation_chain) |
| 7 | 税理士 | 顧問先制度提案 | 3 call (case + exclusions + programs/batch) | 1 call (proposal_kit composed) |
| 9 | 会計士 | 監査計画 risk eval | 3 call (houjin_360 + enforcement + 開示) | 1 call (audit_risk_brief) |
| 11 | 会計士 | PBC CSV 確認 | 2 call (coverage + identity reconcile) | 1 call (pbc_intake_composed) |
| 12 | 会計士 | 関連当事者 mapping | 2 call (houjin_360 + entity_id_map) | 1 call (related_party_map) |
| 14 | 会計士 | 法令改正追跡 | 2 call (laws/search + am_amendment_diff) | 1 call (audit_amendment_brief) |
| 15 | 会計士 | 税効果 review | 2 call (tax_rule + example_profile) | 1 call (deferred_tax_review) |
| 18 | 行政書士 | 補助金申請支援 | 4 call (programs + cohort + exclusions + kit) | 1 call (`bundle_application_kit`) |
| 19 | 行政書士 | 法人設立支援 | 3 call (kit + jurisdiction + houjin) | 1 call (incorporation_kit) |
| 24 | 行政書士 | 顧客制度提案 | 3 call (case + programs + pack) | 1 call (proposal_kit) |
| 26 | 司法書士 | 商業登記支援 | 2 call (houjin_360 + cross_check) | 1 call (corp_registry_brief) |
| 27 | 司法書士 | 相続 + 遺産分割 | 2 call (tax_rule 相続 + example) | 1 call (inheritance_kit) |
| 30 | 司法書士 | 組織再編税制判定 | 2 call (tax_rule 組織再編 + succession) | 1 call (restructuring_brief) |
| 31 | 司法書士 | 担保権設定 | 3 call (houjin + loan + am/loans) | 1 call (collateral_brief) |
| 34 | 中小経営者 | 補助金検討 | 3 call (cohort + programs + prescreen) | 1 call (subsidy_match_composed) |
| 38 | 中小経営者 | DX/IT 投資検討 | 2 call (manufacturing + tax_rule) | 1 call (dx_investment_brief) |

### 3.3 「現状未対応」 (8 業務、原則 未対応 維持)

| # | cohort | 業務 | 理由 |
|---|---|---|---|
| 10 | 会計士 | 内部統制評価 (J-SOX) | 監査意見越権 (公認会計士法 §47条の2) — disclaimer 越え禁止 |
| 20 | 行政書士 | 外国人在留資格申請 (本体) | 行政書士法 §1 boundary — scaffold-only 維持 |
| 22 | 行政書士 | 自動車登録/車庫証明 | scope 外 (制度 surface 外) |
| 25 | 司法書士 | 不動産登記 | scope 外 (登記簿は jpcite 外、司法書士法 §3) |
| 29 | 司法書士 | 成年後見 | scope 外 (家裁手続) |
| — | 全 cohort | 個別税務判断 | 税理士法 §52 — sensitive 軸維持 |
| — | 全 cohort | 法令解釈 (個別) | 弁護士法 §72 — sensitive 軸維持 |
| — | 全 cohort | 申請書面 creation | 行政書士法 §1 — scaffold-only 維持 |

---

## 4. Top 15 high-value endpoint (cohort 横断)

cohort 横断で訴求できる endpoint top 15。**5 endpoint が複数 cohort で top 3 entry** → multi-cohort surface 訴求が可能。

| rank | endpoint | covers cohort | use case (上位 3) |
|---|---|---|---|
| 1 | `tax_rule_full_chain` (R8) | 税理士 / 会計士 / 中小経営者 | 法人税/消費税/税制特例 1 call、6 axis citation chain |
| 2 | `houjin_360` (R8) | 会計士 / 司法書士 / 中小経営者 | 法人 360 with 3-axis scoring、DD/関連当事者/取引先与信 |
| 3 | `case_cohort_match` (R8 `POST /v1/cases/cohort_match`) | 税理士 / 行政書士 / 中小経営者 | 採択事例 × 業種 × 規模 × 地域 cohort、補助金提案の主軸 |
| 4 | `invoice_registrants/*` | 税理士 / 中小経営者 / 会計士 | 13,801 row delta + 4M zenken bulk、T番号確認 |
| 5 | `evidence/packets/batch` | 会計士 / DD / 監査 | 最大 100 件 / 1 往復、PBC 監査調書証跡 |
| 6 | `bundle_application_kit` (Wave 22) | 行政書士 / 中小経営者 | scaffold + checklist + 採択例、§1 boundary 厳守 |
| 7 | `match_due_diligence_questions` (Wave 22) | 会計士 / 司法書士 | 60 row × cohort、30-60 question deck |
| 8 | `prepare_kessan_briefing` (Wave 22) | 税理士 / 会計士 | 月次/四半期 amendment summary、FY window |
| 9 | `succession.py` (R8) | 司法書士 / 中小経営者 / 税理士 | M&A / 事業承継 制度 matcher |
| 10 | `pack_construction` / `pack_manufacturing` / `pack_real_estate` (Wave 23) | 行政書士 / 中小経営者 | JSIC × top 10 program + 通達/裁決 citation |
| 11 | `houjin_watch` (mig 088) + webhook | 司法書士 / M&A / 中小経営者 | corp amendment surface + webhook delivery |
| 12 | `exclusions/check` + `exclusions/rules` | 税理士 / 行政書士 / 中小経営者 | 181 rule (125 exclude + 17 prereq + 15 absolute + 24 other) |
| 13 | `loan-programs/search` + `am/loans` | 中小経営者 / 司法書士 | 108 row × 三軸分解 (担保/個保/三保)、政策融資 |
| 14 | `enforcement-cases/search` | 中小経営者 / 会計士 / 司法書士 | 1,185 行政処分、コンプラ確認 + 与信補助 |
| 15 | `program_post_award_calendar` (mig 098) + `calendar/deadlines` | 行政書士 / 税理士 / 中小経営者 | 採択後 monitoring、継続 engagement の起点 |

---

## 5. ¥3/req 経済性分析

### 5.1 1 call で解決可能なもの (positive ROI)

¥3 で代替手段 (人手調査 / 士業外注 / 複数 site 巡回) を圧縮。

| use case | 代替コスト | jpcite cost | leverage |
|---|---|---|---|
| 法人税申告知識分散 (50 ruleset 横断) | 30-90 分 = ¥1,500-¥4,500 | ¥3 | **500-1,500x** |
| インボイス T番号確認 (NTA bulk DL + grep) | 5-15 分 = ¥250-¥750 | ¥3 | **80-250x** |
| 採択事例 cohort 検索 (士業外注) | ¥10K-¥50K/件 | ¥3 | **3,000-16,000x** |
| DD 公的情報パック (5 site 半日) | ¥10K-¥30K | ¥3 | **3,000-10,000x** |
| 採択後 monitoring calendar | 月 30-60 分 = ¥1,500-¥3,000 | ¥3 | **500-1,000x** |
| corp watch (M&A signal) | 専用 SaaS ¥10K-¥30K/月 | ¥3 × 30 = ¥90 | **100-300x** |

### 5.2 N round trip 必要なもの (composed_tool 化 = ROI 拡大)

現状 N call → composition tool で 1 call 化 = N 倍 ROI 改善。

| use case | 現状 round-trip | composed 化後 | improvement |
|---|---|---|---|
| 補助金申請支援 (programs + cohort + exclusions + kit) | 4 call = ¥12 | 1 call = ¥3 | **4x** |
| 法人設立支援 (kit + jurisdiction + houjin) | 3 call = ¥9 | 1 call = ¥3 | **3x** |
| 顧問先制度提案 (case + exclusions + programs) | 3 call = ¥9 | 1 call = ¥3 | **3x** |
| 月次仕訳 + vocabulary | 2 call = ¥6 | 1 call = ¥3 | **2x** |
| 関連当事者 mapping | 2 call = ¥6 | 1 call = ¥3 | **2x** |

cohort 全体 18 業務の composed_tool 化で **平均 2.5x** ROI 改善 (= ¥3 base に対し ¥7.5 → ¥3 圧縮)。

### 5.3 ¥3/req で「成立しない」もの (越権 or scope 外)

8 業務は ¥3 で出してはいけない / scope 外。

| use case | 理由 | 方針 |
|---|---|---|
| 個別税務判断 | 税理士法 §52 | sensitive disclaimer + scaffold-only |
| 個別法令解釈 | 弁護士法 §72 | sensitive disclaimer + 引用のみ |
| 監査意見 / J-SOX 評価 | 会計士法 §47条の2 | 未対応 維持 |
| 申請書面 creation | 行政書士法 §1 | scaffold + 一次 URL のみ |
| 不動産登記 / 商業登記事項 | 司法書士法 §3 | scope 外 (登記簿 corpus なし) |
| 36協定 render (実装あり) | 労基法 §36 + 社労士法 | `AUTONOMATH_36_KYOTEI_ENABLED=False` gate 維持 |
| 自動車登録 / 車庫証明 | scope 外 | 未対応 維持 |
| 家裁手続 (成年後見等) | scope 外 | 未対応 維持 |

### 5.4 ¥3/req economics summary

- **14 業務 (35%) が現状 1 call** で ¥3 / 代替 ¥250-¥50,000 = leverage 80-16,000x
- **18 業務 (45%) が round-trip → composed 化で 2-4x ROI 改善**、追加 surface = `composition_tools.py` 系拡張
- **8 業務 (20%) は越権 or scope 外**、disclaimer + gate で sensitive 維持
- cohort 横断 top 15 endpoint で **5 endpoint が複数 cohort entry** → 1 surface multi-cohort 訴求成立
- ¥3/req 体制下で、月次 cadence 業務 (税理士月次仕訳/月次監査証跡/中小月次資金繰り/インボイス) と event-driven 高価値 (DD/事業承継/M&A) の **2 軸で組織 reach 確保**

---

## 6. Cohort 別 next-action priority

研究 deliverable として、cohort 別の "次に実装する composition tool" を 1 件ずつ提案 (実装 task は別 lane)。

| cohort | next composition tool | 圧縮対象 round-trip | 期待 leverage |
|---|---|---|---|
| 税理士 | `monthly_intake_composed` | 月次仕訳 CSV + vocabulary + review_queue (3→1) | 3x + 月次 cadence reach |
| 会計士 | `dd_brief_composed` | DD question + houjin_360 + evidence packet (3→1) | 3x + event-driven 高単価 |
| 行政書士 | `proposal_kit_composed` | case_cohort + programs + exclusions + bundle (4→1) | 4x + 業種 SEO 増幅 |
| 司法書士 | `succession_brief_composed` | succession + houjin_360 + tax_rule (3→1) | 3x + 連携起点 |
| 中小経営者 | `subsidy_match_composed` | cohort + programs + prescreen (3→1) | 3x + 士業外注代替 |

---

## 7. Honest gaps

- §3.1 の「現状 1 call」14 業務のうち、`csv_coverage_receipt` 系 (#1) は P0 計画 (`csv_output_catalog_by_user_type_deepdive_2026-05-15.md`) で landed surface はあるが UI 経路は partial、士業 reach に必要な「freee/MF/弥生 CSV 直接 upload」は未整備。
- §3.2 の round-trip 18 業務の composed 化は **`composition_tools.py` (Wave 21) + `wave22_tools.py` (Wave 22) で base 確立**、各 cohort 用に追加 5 系統が必要 (本書 §6 で提案)。
- §3.3 の未対応 8 業務は **disclaimer + gate で sensitive 軸維持**、scope 拡張は組織獲得効率より 越権 risk が大きい (operator 方針 `feedback_no_user_operation_assumption` + `CONSTITUTION 13.2` 厳守)。
- Wave 22 DD question template 60 row 中、construction cohort は saiketsu citation 1 row のみ (NTA upstream corpus 137 row × keyword overlap 薄い) — 「honest empty」を返す設計、追加 NTA ingest 後に自動補強。

---

## 8. Cross-reference (canonical)

- `docs/_internal/csv_output_catalog_by_user_type_deepdive_2026-05-15.md` — CSV-derived artifact catalog by user type (P0 計画)
- `docs/_internal/R8_tax_chain_full_surface_2026-05-07.md` — `tax_rule_full_chain` shipping doc
- `docs/_internal/R8_succession_matcher_2026-05-07.md` — `succession.py` shipping doc
- `docs/_internal/R8_compatibility_full_surface_2026-05-07.md` — `compatibility.py` shipping doc
- `docs/_internal/ai_professional_public_layer_plan_2026-05-06.md` — AI professional public layer plan
- `CLAUDE.md` — Wave 22 (DD question / kessan / forecast / cross-check / bundle kit), Wave 23 (industry packs), Cohort revenue model (8 cohort)
- `docs/api-reference.md` — current 219-path public surface

last_updated: 2026-05-17
