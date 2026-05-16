# CSV Accounting Outputs Deep Dive

作成日: 2026-05-15  
担当: 会計CSVから作れるsource-backed成果物  
対象: `/Users/shigetoumeda/Desktop/CSV` 配下の9 CSV  
制約: CSV rawは保存しない。取引明細、摘要、取引先、金額明細を成果物へ転記しない。会計・税務判断はしない。派生事実だけをsource-backed evidenceとして扱う。

## 1. 観測したCSV差異

### 1.1 ファイル構成と期間

| ファイル | 推定系統 | 行数 | 期間 | 注意点 |
|---|---:|---:|---|---|
| `freee_personal_freelance.csv` | freee | 372 | 2024-04-01..2026-03-31 | 個人事業・フリーランス系。按分、事業主貸借、源泉相殺の補助科目が多い。 |
| `freee_personal_rental.csv` | freee | 455 | 2024-04-05..2026-03-31 | 不動産賃貸系。借入、利息、修繕、前払費用、減価償却が目立つ。 |
| `freee_sme_agri.csv` | freee | 918 | 2024-04-01..2026-05-28 | 農業法人系。2026-05-15時点の未来日付1行あり。交付金、共済、農産物棚卸が出る。 |
| `freee_sme_welfare.csv` | freee | 797 | 2024-04-01..2026-03-31 | 福祉系。介護保険収入、自費サービス収入、処遇改善、送迎車両など。 |
| `mf_sme_medical.csv` | MF | 1906 | 2024-04-01..2026-03-31 | 医療系。社会保険診療収入、自由診療収入、窓口負担、医療材料等。 |
| `mf_sme_subsidy.csv` | MF | 653 | 2024-04-01..2026-03-31 | 補助金・製造業系。国庫補助金受贈益、圧縮、助成金、機械装置等。 |
| `yayoi_apple_farm.csv` | 弥生 | 1347 | 2023-01-01..2025-12-31 | りんご農家系。弥生の税金額列あり。農薬衛生費など弥生側語彙。 |
| `conglomerate_yayoi.csv` | 弥生 | 3768 | 2024-04-01..2026-05-28 | 複合企業系。未来日付2行、貸借差額あり。弥生の伝票列名ゆれあり。 |
| `media_conglomerate_yayoi.csv` | 弥生 | 4084 | 2024-04-01..2026-05-28 | メディア複合企業系。未来日付2行、貸借差額あり。収益科目が細かい。 |

期間の含意:

- 2024-04..2026-03の2期相当CSVが中心。
- 弥生りんご農家は2023-01..2025-12で暦年・農業系の長期比較に向く。
- freee農業、弥生複合企業、弥生メディア複合企業は2026-05-15時点で未来日付を含むため、公開成果物では「入力CSVに未来日付あり」とだけ示し、金額判断や会計処理判断は避ける。

### 1.2 列構成

freee系4ファイルは21列で安定:

- 日付: `取引日`
- ID: `伝票番号`
- 借方/貸方: `借方勘定科目`, `借方補助科目`, `借方部門`, `借方品目`, `借方メモタグ`, `借方取引先`, `借方税区分`, `借方税額`, `借方金額`, `貸方...`
- 説明: `摘要`

MF系2ファイルは25列で安定:

- 日付: `取引日`
- ID: `取引No`
- 金額列: `借方金額(円)`, `貸方金額(円)`
- 監査系メタ: `仕訳メモ`, `タグ`, `MF仕訳タイプ`, `決算整理仕訳`, `作成日時`, `作成者`, `最終更新日時`, `最終更新者`

弥生系3ファイルは25列相当:

- 日付: `取引日付`
- ID: `伝票No` と `伝票No.` の表記ゆれ
- 金額列: `借方金額`, `借方税金額`, `貸方金額`, `貸方税金額`
- 弥生メタ: `識別フラグ`, `決算`, `番号`, `期日`, `タイプ`, `生成元`, `仕訳メモ`, `付箋1`, `付箋2`, `調整`

取り込み上の最小共通列:

- `source_file_id`
- `vendor_family`
- `entry_date`
- `voucher_id`
- `debit_account`
- `debit_subaccount`
- `debit_department`
- `debit_tax_category`
- `debit_amount`
- `debit_tax_amount`
- `credit_account`
- `credit_subaccount`
- `credit_department`
- `credit_tax_category`
- `credit_amount`
- `credit_tax_amount`
- `memo_presence`
- `raw_column_profile_hash`

### 1.3 勘定科目差異

観測された勘定科目の性質:

- freee個人系: `事業主貸`, `事業主借`, `不動産賃貸料`, `長期借入金`, `支払利息`, `前払費用` など個人・不動産向けの語彙がある。
- freee農業系: `農薬費`, `飼料費`, `肥料費`, `種苗費`, `動力光熱費`, `専従者給与`, `経営所得安定対策交付金`, `農業共済金収入` など。
- 弥生農業系: `農薬衛生費`, `荷造運賃`, `給料賃金`, `燃料費` など、同じ農業でもfreee農業と語彙が完全一致しない。
- 福祉・医療系: `介護保険収入`, `自費サービス収入`, `社会保険診療収入`, `自由診療収入`, `医療材料費`, `検査委託費`, `廃棄物処理費` など業種別科目が強い。
- 補助金・製造系: `国庫補助金受贈益`, `固定資産圧縮損`, `機械装置`, `ソフトウェア`, `建物`, `外注加工費` など。
- 複合企業・メディア系: `入場料収入`, `出版売上`, `音楽配信収入`, `配給収入`, `ゲーム内課金収入`, `コンテンツ資産`, `仕掛コンテンツ`, `支払印税`, `のれん償却額` など、一般中小企業テンプレートより細かい。

設計上は勘定科目を一律に正規化しすぎない。成果物では次の2層に分ける。

- 原語維持層: CSV由来の勘定科目名をそのまま派生事実として保持する。
- 軽分類層: `revenue`, `expense`, `asset`, `liability`, `equity_or_owner`, `contra_asset`, `grant_or_subsidy_like`, `payroll_related`, `industry_specific`, `unknown` 程度の非判断カテゴリに留める。

## 2. Source-backed成果物候補

### 2.1 CSV Coverage Receipt

ユーザー価値:

- 「このCSVから何が読めるか」を会計判断なしに示す。
- 取り込み前後の不安を減らし、freee/MF/弥生ごとの列ゆれを可視化できる。

内容:

- ファイル数、行数、期間、ベンダー推定、列プロファイル。
- 日付列・ID列・金額列・税額列・補助科目列の検出結果。
- raw行は出さず、列名と期間・件数・distinct countだけを出す。

AIエージェント推薦文:

> このCSVは会計判断に入る前の構造確認に向いています。まずCoverage Receiptを作ると、期間、列、科目の読める範囲と、レビューが必要な入力条件を安全に共有できます。

### 2.2 Period Activity Packet

ユーザー価値:

- 期間別の活動密度を把握できる。
- 事業の季節性、月別入力の抜け、未来日付混入を説明できる。

内容:

- 月別行数。
- 借方/貸方合計の月次集計。
- 金額の最大・最小・中央値など。ただし取引単位の明細は出さない。
- 未来日付、空白月、会計期間外の有無。

AIエージェント推薦文:

> 月次の入力密度を確認すると、欠けている月や未来日付の混入を先に検出できます。税務判断ではなく、CSVの期間品質チェックとして使うのが安全です。

### 2.3 Account Vocabulary Map

ユーザー価値:

- freee/MF/弥生の科目名差異を、事業者や支援者が同じ地図で見られる。
- 業種別の特徴語彙をAIエージェントが推薦材料にできる。

内容:

- 勘定科目の出現件数、借方のみ・貸方のみ・両方出現。
- 補助科目distinct count。
- 科目語彙を軽分類へ割り当てる。ただし分類確信度と`review_required`を持つ。
- `農薬費` と `農薬衛生費` のような近接語彙は「候補」扱いで、同一科目と断定しない。

AIエージェント推薦文:

> 同じ農業CSVでも、freeeと弥生で科目名がずれることがあります。Account Vocabulary Mapを作ると、原語を残したまま比較用の軽分類を付けられます。

### 2.4 Industry Signal Packet

ユーザー価値:

- 会計CSVから、業種らしさを説明する非判断の根拠を作れる。
- jpcite内の士業・BPO・補助金・業種別案内への入口にできる。

内容:

- 農業: 肥料、種苗、農薬、交付金、共済、農産物棚卸。
- 医療: 社会保険診療、自由診療、医療材料、検査委託、感染性廃棄物。
- 福祉: 介護保険収入、自費サービス、処遇改善、送迎、介護用品。
- 製造・補助金: 国庫補助金受贈益、固定資産圧縮損、機械装置、外注加工。
- メディア: コンテンツ資産、印税、配信収入、ゲーム課金、出版売上。

AIエージェント推薦文:

> このCSVには業種を示す勘定科目が含まれています。Industry Signal Packetなら、取引明細を出さずに「どの業種向け支援が近そうか」を説明できます。

### 2.5 Review Queue Packet

ユーザー価値:

- 入力CSVで人間確認が必要な箇所を、税務助言ではなくデータ品質として列挙できる。
- AIエージェントが「次に確認すべきこと」を安全に案内できる。

内容:

- 未来日付行数。
- 貸借不一致行数またはファイル合計差額。
- 金額列パース不能、日付パース不能。
- 必須列欠落、列名表記ゆれ。
- `諸口`比率が高い場合の補助確認。
- 決算整理仕訳・調整・付箋・生成元などベンダーメタの存在。

AIエージェント推薦文:

> Review Queue Packetは、会計処理の正否ではなくCSV品質の確認リストです。未来日付や貸借差額など、人間が確認すべき入力条件だけを先に分離できます。

### 2.6 Evidence-safe Advisor Brief

ユーザー価値:

- 士業・BPO・バックオフィス担当へ渡せる短いブリーフを作れる。
- raw CSVを渡さず、期間・列・集計・レビュー理由だけで会話を開始できる。

内容:

- 取り込み元種別、期間、行数。
- 主要科目グループの件数。
- 業種シグナル。
- `review_required`の有無と理由。
- 「本ブリーフは会計・税務判断ではない」という明示。

AIエージェント推薦文:

> raw CSVを共有する前に、Evidence-safe Advisor Briefで構造と要レビュー理由だけを共有できます。支援者との初回確認に向いています。

## 3. freee/MF/弥生別の取り込み揺れとfallback

### 3.1 freee

揺れ:

- 4ファイルとも21列で安定している。
- `借方品目`, `貸方品目`, `借方メモタグ`, `貸方メモタグ`, `借方取引先`, `貸方取引先` があるため、補助分析の材料が多い。
- 税額列は `借方税額`, `貸方税額`。弥生の `税金額` と名称が違う。
- 個人事業では `事業主貸`, `事業主借` が出る。

fallback:

- `伝票番号`が空の場合は、`source_file_id + row_index + entry_date + debit_amount + credit_amount` のハッシュを内部entry idにする。
- 補助科目が空でも、品目・メモタグ・取引先の存在フラグを保持する。
- 税額が空または0でも税判断はしない。`tax_amount_present=false` として扱う。
- 個人系は法人向け分類へ無理に寄せず、`owner_related_present=true` を持たせる。

### 3.2 MF

揺れ:

- 金額列が `借方金額(円)`, `貸方金額(円)`。
- `取引No`, `MF仕訳タイプ`, `決算整理仕訳`, `作成日時`, `作成者`, `最終更新日時`, `最終更新者` がある。
- 作成・更新メタにより、取り込み後の監査用派生事実を作りやすい。

fallback:

- `取引No`が空の場合はfreeeと同じハッシュidへfallback。
- `決算整理仕訳`はboolean正規化し、値解釈不能なら`unknown`。
- `MF仕訳タイプ`は列挙値として保持するが、処理の正否判断に使わない。
- 金額列名の`(円)`はスキーマ正規化で除去し、内部では`debit_amount`, `credit_amount`へ統一。

### 3.3 弥生

揺れ:

- `取引日付`を日付列として扱う。
- `伝票No` と `伝票No.` の表記ゆれがある。
- 税額列が `借方税金額`, `貸方税金額`。
- `識別フラグ`, `決算`, `タイプ`, `生成元`, `付箋1`, `付箋2`, `調整` があり、レビュー用メタが豊富。
- cp932系エンコーディングの可能性が高い。

fallback:

- エンコーディングは`utf-8-sig`失敗時に`cp932`へfallback。
- `伝票No.`があれば`voucher_id`に採用し、なければ`伝票No`を採用。
- `付箋`, `調整`, `決算`は人間確認フラグの材料にするが、会計判断には使わない。
- `諸口`を多用するファイルでは、相手科目・補助科目distinct countを併記して、内訳不足と断定しない。

## 4. 派生事実スキーマ

### 4.1 Source File Profile

```json
{
  "source_file_id": "sha256:file_bytes_or_upload_id",
  "source_kind": "accounting_csv",
  "vendor_family": "freee|mf|yayoi|unknown",
  "encoding_detected": "utf-8-sig|cp932|unknown",
  "row_count": 0,
  "column_count": 0,
  "column_names": ["..."],
  "column_profile_hash": "sha256:normalized_column_names",
  "date_min": "YYYY-MM-DD",
  "date_max": "YYYY-MM-DD",
  "period_months": ["YYYY-MM"],
  "raw_retention": "none",
  "created_at": "ISO-8601"
}
```

### 4.2 Normalized Entry Fact

raw行を保存しない運用では、これは永続保存しない一時正規化レコードとする。保存対象は4.3以降の集計のみ。

```json
{
  "entry_id": "sha256:source_file_id+row_index+stable_fields",
  "source_file_id": "sha256:...",
  "row_index": 0,
  "entry_date": "YYYY-MM-DD",
  "period_month": "YYYY-MM",
  "voucher_id_hash": "sha256:voucher_id_or_null",
  "debit_account": "original_account_name",
  "debit_subaccount_present": true,
  "debit_department_present": true,
  "debit_tax_category_present": true,
  "debit_amount": 0,
  "debit_tax_amount": 0,
  "credit_account": "original_account_name",
  "credit_subaccount_present": true,
  "credit_department_present": true,
  "credit_tax_category_present": true,
  "credit_amount": 0,
  "credit_tax_amount": 0,
  "memo_present": true,
  "vendor_meta_presence": {
    "tags": true,
    "settlement_entry_flag": false,
    "adjustment_flag": false,
    "sticky_note": false,
    "created_updated_meta": false
  }
}
```

### 4.3 Aggregated Fact

```json
{
  "source_file_id": "sha256:...",
  "aggregation_level": "file|month|account|account_month|industry_signal",
  "period_month": "YYYY-MM|null",
  "account_original": "string|null",
  "account_side": "debit|credit|both|null",
  "account_light_class": "revenue|expense|asset|liability|equity_or_owner|contra_asset|grant_or_subsidy_like|payroll_related|industry_specific|unknown",
  "entry_count": 0,
  "debit_amount_sum": 0,
  "credit_amount_sum": 0,
  "tax_amount_sum": 0,
  "distinct_subaccount_count": 0,
  "distinct_department_count": 0,
  "first_date": "YYYY-MM-DD",
  "last_date": "YYYY-MM-DD",
  "confidence": "high|medium|low",
  "review_required": false,
  "review_reasons": []
}
```

### 4.4 Review Fact

```json
{
  "source_file_id": "sha256:...",
  "review_required": true,
  "severity": "info|warning|blocker",
  "condition_code": "future_date_present",
  "observed_count": 0,
  "observed_scope": "file|month|account|column",
  "human_message_ja": "CSVに2026-05-15時点の未来日付が含まれます。入力日付の確認が必要です。",
  "not_a_tax_or_accounting_opinion": true
}
```

## 5. 集計設計

最小集計:

- file profile: 行数、列数、期間、ベンダー推定、列プロファイル。
- monthly activity: 月別行数、借方合計、貸方合計、税額合計、distinct account count。
- account vocabulary: 科目別件数、借方/貸方側、補助科目distinct count、部門distinct count。
- account pair summary: 借方科目 x 貸方科目の件数と合計。ただし摘要・取引先・伝票番号は出さない。
- vendor meta summary: 決算整理、調整、付箋、タグ、作成更新メタの存在件数。
- industry signal: 業種特徴語彙の存在件数。

避ける集計:

- 個別取引が推定できる日別少数セルの公開。
- 摘要、取引先、伝票番号、作成者名の出力。
- 税区分から納税要否・控除可否を判断する出力。
- 勘定科目の正誤、仕訳の正誤、申告上の有利不利を示す出力。

少数セル抑制:

- 公開/共有成果物では、`entry_count < 3` のaccount_monthセルは金額を非表示または上位分類へ丸める。
- 内部レビュー用でも、raw行再構成につながる組み合わせは出さない。

## 6. review_required条件

blocker:

- 必須列がない: 日付列、借方科目、貸方科目、借方金額、貸方金額。
- 日付・金額のパース不能行が存在し、集計結果に影響する。
- エンコーディングを確定できない。

warning:

- 2026-05-15時点の未来日付が存在する。
- 貸借合計差額が0でない。
- 行単位で借方金額と貸方金額が一致しない。
- `伝票No`/`伝票No.`/`伝票番号`/`取引No`が欠落し、ハッシュid fallbackになった。
- `諸口`の出現比率が高く、account pairだけでは内訳を説明しにくい。
- `決算整理仕訳`, `調整`, `付箋`, `仕訳メモ`, `タグ`など、人間の補足メタが存在する。
- 期間が期待年度をまたぐ、または空白月がある。

info:

- 税額列が存在しない、または常に空。
- 補助科目・部門・品目・タグが存在しない。
- ベンダー固有列が未知。
- 個人事業科目と法人科目が混在している。

観測CSVで即時に立つレビュー例:

- `freee_sme_agri.csv`: 未来日付1行。
- `conglomerate_yayoi.csv`: 未来日付2行、貸借合計差額、行単位不一致2行。
- `media_conglomerate_yayoi.csv`: 未来日付2行、貸借合計差額、行単位不一致2行。
- `freee_personal_freelance.csv`: 行単位不一致24行、ファイル合計差額。ただし源泉相殺等の表現が原因である可能性があるため、正誤判断はしない。

## 7. エンドユーザー価値

個人事業者:

- freee個人系CSVから、事業主貸借、按分、源泉相殺、家賃・通信・水道光熱などの構造を明細非公開で整理できる。
- 支援者へ渡す前に「期間、列、要確認点」だけを共有できる。

中小企業:

- MF/freee/弥生のCSVを横断して、科目語彙と月別活動を同じ形式で見られる。
- 決算整理・調整・付箋・更新メタのようなレビュー材料を先に切り出せる。

士業・BPO:

- raw CSVを受け取る前に、業種、期間、列、品質リスクを把握できる。
- 顧客への追加依頼を「未来日付があります」「ID列が欠落しています」「補助科目が少ないです」のようなデータ品質の言葉に限定できる。

AIエージェント:

- 会計・税務判断へ踏み込まず、CSV構造と派生集計に基づく次アクションを推薦できる。
- jpciteのsource-backed方針に沿い、根拠のある成果物名、レビュー理由、次の確認項目を生成できる。

## 8. 実装前の推奨パイプライン

1. CSVを一時領域で読み込み、encodingとdialectを検出する。
2. ベンダー列プロファイルで`freee|mf|yayoi|unknown`を推定する。
3. 列マッピングを適用し、必須列の有無を確認する。
4. 行単位の一時正規化を行う。raw行、摘要、取引先、伝票番号そのものは永続保存しない。
5. file/month/account/account_pair/vendor_meta/industry_signalへ集計する。
6. 少数セル抑制とreview_required付与を行う。
7. 成果物ごとの文章テンプレートへ流し込む。
8. 最終成果物に「会計・税務判断ではない」「CSV由来の派生事実のみ」を明示する。

## 9. 推奨成果物セット

初期リリースで優先:

- CSV Coverage Receipt
- Review Queue Packet
- Account Vocabulary Map
- Evidence-safe Advisor Brief

次段階:

- Period Activity Packet
- Industry Signal Packet
- Account Pair Summary
- Vendor Import Variance Report

推薦ロジック:

- `review_required=true`なら、まずReview Queue Packetを推薦。
- `vendor_family`が複数なら、Vendor Import Variance Reportを推薦。
- `industry_signal_count > 0`なら、Industry Signal Packetを推薦。
- `distinct_account_count`が多い、または`諸口`比率が高いなら、Account Vocabulary Mapを推薦。
- 士業・BPO共有文脈なら、Evidence-safe Advisor Briefを推薦。

## 10. 実装で守る境界

- raw CSVの保存禁止。
- 摘要・取引先・伝票番号・作成者名の成果物出力禁止。
- 勘定科目名は派生事実として必要最小限に保持するが、個別取引再識別につながる粒度では出さない。
- 税区分・税額は集計可能だが、消費税判定、所得税判定、法人税判定、申告助言には使わない。
- 仕訳の正誤を言わない。
- 未来日付・貸借差額・列欠損は「入力CSVのレビュー条件」としてだけ扱う。
