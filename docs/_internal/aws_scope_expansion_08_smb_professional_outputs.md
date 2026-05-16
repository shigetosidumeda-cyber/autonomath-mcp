# AWS scope expansion 08: SMB and professional outputs

作成日: 2026-05-15  
担当: 拡張深掘り 8/30 / 中小企業・士業・バックオフィス向け成果物  
対象: 会計CSV private overlay + 公的一次情報から、AIエージェントが安価に推薦しやすい成果物を最大化する計画  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、スクレイピング実行、デプロイ実行、既存コード変更は行わない。  
出力制約: このMarkdownだけを追加する。  

## 0. 結論

中小企業・士業・バックオフィス向けでは、jpciteの価値は「AIに聞いたら、安く、根拠付きで、次にやることまで返る」成果物を大量に先回り生成することで最大化できる。

特に重要なのは、会計CSVを単なる入力ファイルとして扱わず、ユーザーの事業実態を推定する private overlay として使うことである。公的一次情報だけでは「制度や登録情報」は分かるが、「このユーザーに関係がありそうか」は弱い。会計CSVを一時的に解析して、売上規模、業種らしさ、費目構成、取引先、税区分、給与/外注/家賃/広告/設備投資/旅費交通費などの兆候を抽出すると、AIエージェントは次のような安価な成果物を推薦しやすくなる。

| 優先 | 成果物 | 主な買い手 | 推薦される瞬間 | 価格帯イメージ |
|---|---|---|---|---|
| P0-A | 月次経営レビューpacket | 経営者、経理、会計事務所 | 「今月の会計データを見て」 | 300-1,500円 |
| P0-A | 補助金・助成金候補packet | 経営者、士業 | 「使える補助金ある？」 | 500-3,000円 |
| P0-A | インボイス・取引先公的確認packet | 経理、BPO、士業 | 「この取引先大丈夫？」 | 100-800円/先 |
| P0-A | 税・社会保険・労務イベント候補packet | 経営者、社労士、会計事務所 | 「今月やる手続きある？」 | 300-2,000円 |
| P0-B | 許認可・業法セルフチェックpacket | 行政書士、中小企業 | 「この事業に許可が必要？」 | 500-5,000円 |
| P0-B | 決算前チェックpacket | 会計事務所、経理 | 「決算前に漏れを見て」 | 1,000-5,000円 |
| P0-B | 申請書類準備packet | 士業、経営者 | 「補助金申請の下準備して」 | 2,000-10,000円 |
| P1 | 士業向け顧客ポートフォリオ例外packet | 会計事務所、社労士、行政書士 | 「顧客をまとめて見たい」 | 5,000円以上/月 |

この領域は「正解を断定するAI」ではなく、「一次情報に基づく候補、根拠、未確認、次アクションを低価格で返すAI用 evidence layer」として売るのが最も安全で強い。

## 1. 前提と境界

### 1.1 private overlay の原則

会計CSVは顧客の私的データである。jpcite本体およびAWS拡張計画では、次の原則を守る。

| 原則 | 内容 |
|---|---|
| raw CSV不保存 | ユーザーが投入したCSV本文を永続保存しない |
| raw CSV非ログ | 行データ、摘要、取引先名、金額行をログに出さない |
| raw CSV非AWS | ユーザーの実CSVをAWS収集基盤へ送らない |
| 派生特徴のみ | 月別合計、勘定科目別合計、税区分比率、取引先候補数などの集計特徴だけを一時利用する |
| 安全な識別子 | 取引先照合は法人番号/T番号が明示されている場合を優先し、名称照合は曖昧判定にする |
| 再現可能性 | packetには「どのsourceとどの集計特徴から言ったか」を `claim_refs[]` で残す |
| 断定禁止 | 税務判断、社保加入義務、許認可要否、補助金採択可能性を断定しない |

### 1.2 jpciteの基本契約

すべての成果物は既存計画の契約に合わせる。

```json
{
  "request_time_llm_call_performed": false,
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "billing_metadata": {},
  "human_review_required": true,
  "_disclaimer": "This packet is evidence assistance, not legal, tax, labor, accounting, or grant application advice."
}
```

### 1.3 CSVだけで分かること、分からないこと

CSVだけで分かること:

- 期間、月次推移、勘定科目、補助科目、税区分、金額、摘要、取引先名らしき文字列。
- 売上/仕入/外注/給与/地代家賃/広告宣伝/旅費交通/支払手数料/租税公課/減価償却/借入返済らしき費目。
- 課税/非課税/不課税/対象外/軽減税率/インボイス関連列の有無。
- 設備投資、ITツール、広告、採用、研修、専門家報酬など補助金や制度候補につながる支出。
- 月次の粗い資金繰り、費用構造、季節性、急増急減。

CSVだけでは分からないこと:

- 実際の申告義務、税額、社会保険加入義務、労働保険料、許認可要否の最終判断。
- 従業員個別の報酬、固定的賃金変動、標準報酬月額、賞与支払届対象者。
- 補助金の採択可能性、申請可否の最終判断。
- 取引先の適法性、安全性、反社該当性、登録なしの証明。
- 業法における実態要件、営業所要件、資格者要件、人的要件。

このためpacketは必ず「候補」「未確認」「次に確認する一次情報」を返す。

## 2. CSV input profile

### 2.1 会計CSVの想定

| Provider | 扱い | 重要な注意 |
|---|---|---|
| freee | `freee_variant` として扱う | 公式仕様は機能/画面/出力目的で変わる。ヘッダ検出とユーザー確認が必要 |
| Money Forward | `mf_journal_current_or_variant` | 仕訳帳インポートは取引日、勘定科目、金額などが中心。現行サンプルは列構成が変わりうる |
| Yayoi | `yayoi_journal_25_item_or_variant` | 25項目系を中心に見るが、出力元/移行形式で差異がある |
| その他 | `generic_journal` | 日付、借方/貸方、勘定科目、金額、摘要、税区分を抽出できれば最低限対応 |

CSV仕様は固定前提にしない。以下を最初に実行する。

1. 文字コード推定: UTF-8, Shift_JIS, CP932。
2. 区切り文字推定: comma, tab。
3. ヘッダ検出: 日付、借方、貸方、金額、摘要、税区分、補助科目、部門、取引先、T番号らしき列。
4. provider推定: 既知ヘッダセットとの類似度。
5. 期間検出: min_date, max_date, fiscal_year_candidate。
6. 行品質検査: 空行、貸借不一致、日付不正、金額不正、文字化け、重複。
7. 取扱可否: raw CSVを保存せず、派生特徴だけ保持。

### 2.2 canonical derived facts

private overlayで生成する派生factは次の単位に限定する。

```json
{
  "csv_overlay_summary": {
    "provider_profile": "mf_journal_current_or_variant",
    "detected_period": {
      "start_date": "2025-04-01",
      "end_date": "2026-03-31",
      "months_covered": 12,
      "coverage_gaps": []
    },
    "row_stats": {
      "rows_total_bucket": "1000-4999",
      "invalid_rows_count": 0,
      "duplicate_candidate_count_bucket": "1-10"
    },
    "account_rollups": [
      {
        "account_group": "sales",
        "monthly_amounts": [],
        "share_of_revenue": null
      }
    ],
    "tax_category_rollups": [],
    "vendor_signal_summary": {
      "vendor_count_bucket": "50-99",
      "invoice_id_present_count_bucket": "10-49",
      "name_only_vendor_count_bucket": "10-49"
    },
    "business_signal_flags": [
      "has_payroll_expense",
      "has_subcontract_expense",
      "has_rent_expense",
      "has_it_or_software_expense"
    ]
  }
}
```

rawの摘要、取引先名、行金額はpacket本文に出さない。どうしてもユーザー確認のために表示する場合は、クライアント側でのみ表示し、API応答の保存対象から外す。

### 2.3 account taxonomy

会計ソフトや事務所で勘定科目名が揺れるため、直接ルールではなく taxonomy に寄せる。

| Taxonomy | 代表科目例 | 出せる成果物 |
|---|---|---|
| sales | 売上高、役務収益、受取手数料 | 月次レビュー、補助金規模判定、消費税関連候補 |
| cogs_purchase | 仕入高、材料費、商品仕入 | 粗利推移、在庫/原価課題候補 |
| outsourcing | 外注費、業務委託費 | 下請法/フリーランス法/源泉/インボイス確認候補 |
| payroll | 給与手当、役員報酬、賞与、法定福利費 | 社会保険/労務イベント候補。ただし個別判断不可 |
| rent | 地代家賃、賃借料 | 固定費レビュー、店舗/事務所/許認可営業所候補 |
| advertising | 広告宣伝費、販売促進費 | 補助金/販路開拓候補、ROIレビュー |
| software_it | ソフトウェア、クラウド利用料、通信費 | IT/AI/セキュリティ補助金候補 |
| capex | 工具器具備品、機械装置、車両運搬具 | 設備投資補助金、減価償却確認候補 |
| professional_fee | 支払報酬、支払手数料、顧問料 | 源泉/士業費用/申請支援候補 |
| tax_dues | 租税公課、諸会費 | 納付カレンダー、税/社会保険支出レビュー |
| travel_transport | 旅費交通費、車両費、燃料費 | 運輸/営業/出張傾向、補助金用途候補 |
| loan_finance | 支払利息、長期借入金、短期借入金 | 資金繰り、制度融資候補。ただし金融助言不可 |

## 3. Public source overlay

### 3.1 公的一次情報の役割

| Source family | 用途 | SMB packetでの使い方 |
|---|---|---|
| NTA法人番号 | 法人同定、商号/所在地/法人番号 | 取引先照合、自社同定、gBizINFO join |
| NTAインボイス | 適格請求書発行事業者の公表情報 | 仕入先/T番号確認、インボイス列の説明 |
| gBizINFO | 法人活動情報、補助金、調達、届出/認定等 | 企業の公的活動シグナル、補助金採択履歴候補 |
| e-Gov法令 | 法律、施行令、施行規則 | 業法/労務/税制度の根拠リンク |
| 国税庁タックスアンサー/手引き | 税制度説明、手続、期限 | 源泉、消費税、インボイス、電子帳簿保存などの説明根拠 |
| 日本年金機構 | 算定基礎届、月額変更届、賞与支払届等 | 社保イベント候補、必要データの説明 |
| 厚生労働省/e-Gov電子申請 | 労働保険、雇用保険、電子申請 | 労務/年度更新/届出候補 |
| 中小企業庁/ミラサポplus/J-Grants | 補助金、公募、制度 | 補助金候補、締切、対象要件の根拠 |
| 業界所管省庁 | 許認可/登録/監督処分 | 業法チェック、取引先確認 |
| 自治体 | 地域補助金、許認可窓口、条例、営業許可 | 地域別packet、地元制度候補 |
| e-Stat | 地域/産業統計 | 市場背景、補助資料、比較ベンチマーク |

### 3.2 no-hit の扱い

| 検索対象 | no-hitで言えること | 禁止表現 |
|---|---|---|
| 法人番号 | 指定条件では法人を特定できなかった | 存在しない会社 |
| インボイス | 指定条件では登録情報を確認できなかった | 免税事業者である、違法である |
| 補助金 | 収集済みsourceでは該当候補が少ない | 使える補助金はない |
| 行政処分 | 対象source/期間/条件では未検出 | 処分歴なし、問題なし、安全 |
| 許認可 | 対象source/条件では登録未検出 | 無許可営業である |
| 労務/社保 | CSV特徴だけでは判定不可 | 加入義務あり/なし |

## 4. Output-first catalog

### 4.1 SMB owner outputs

#### SMB-01 月次経営レビューpacket

AIエージェントの推薦文:

> 会計CSVを落とすだけで、今月の売上・費用・資金繰り・税/労務/補助金の確認候補を、公的根拠付きで数分で見られます。

入力:

- 会計CSV 1-24か月分。
- 任意: 法人番号、都道府県、市区町村、業種、従業員数レンジ。

返す内容:

- 月次売上、主要費用、粗利候補、固定費候補、急増急減。
- 税区分/インボイス列/取引先T番号の有無。
- 補助金/制度候補につながる支出シグナル。
- 労務/社保イベント候補につながる給与/法定福利費/賞与シグナル。
- 許認可/業法確認が必要そうな業種シグナル。
- `known_gaps`: 個別明細未確認、給与台帳未確認、申告状況未確認、従業員数未確認。

必要データ:

| Data | 必須 | Source |
|---|---|---|
| 月別勘定科目集計 | 必須 | private CSV derived |
| 税区分集計 | 推奨 | private CSV derived |
| 取引先候補数 | 推奨 | private CSV derived |
| 自社法人番号 | 任意 | user input + NTA法人番号 |
| 業種/地域 | 任意 | user input + gBizINFO where available |
| 補助金公募 | 必須 | 中小企業庁/J-Grants/自治体 |

packet schema:

```json
{
  "packet_type": "smb_monthly_review",
  "period": "2026-04",
  "highlights": [
    {
      "type": "expense_spike",
      "severity": "medium",
      "summary": "広告宣伝費グループが過去6か月中央値より大きい",
      "calculation_ref": "calc_mad_advertising_2026_04",
      "claim_refs": ["cr_csv_rollup_advertising"]
    }
  ],
  "public_opportunities": [
    {
      "type": "grant_candidate",
      "program_name": "candidate only",
      "match_reason": ["software_it_spend_detected", "smb_digitalization_source_available"],
      "source_receipts": ["sr_chusho_digital_support_page"],
      "human_review_required": true
    }
  ],
  "known_gaps": [
    "payroll_detail_not_uploaded",
    "tax_filing_status_not_known",
    "grant_eligibility_not_determined"
  ]
}
```

売上性:

- 最も頻度が高く、月次で継続課金しやすい。
- 士業が顧客ごとにまとめて使う可能性が高い。
- 低価格でも利用頻度が出るため、GEOでAIが推薦しやすい。

#### SMB-02 補助金・助成金候補packet

推薦される質問:

- 「この会社が使えそうな補助金は？」
- 「IT投資したいけど補助金ある？」
- 「設備投資や広告費に使える制度ある？」
- 「今月締切の補助金を見て」

入力:

- 会計CSV。
- 地域。
- 業種。
- 従業員数レンジ。
- やりたい投資: IT、設備、省エネ、販路開拓、人材育成、事業承継など。

返す内容:

- 候補制度の一覧。
- 公式URL、締切、対象者、対象経費、補助率/上限のsource_receipt。
- CSVから見えた関連支出/規模シグナル。
- 要件未確認の一覧。
- 申請前に集める資料チェックリスト。
- AIエージェント向け `next_best_questions[]`。

scoring:

```text
candidate_score =
  0.35 * hard_filter_coverage
+ 0.20 * expense_signal_match
+ 0.15 * region_match
+ 0.10 * industry_match
+ 0.10 * deadline_urgency
+ 0.10 * evidence_completeness
```

hard_filter_coverageは、公式要件のうちユーザー情報で確認できた割合である。未確認は0ではなく `unknown` とし、採択可能性と混同しない。

候補例:

| Signal | 公的一次情報 | Output |
|---|---|---|
| software_it支出あり | 中小企業庁デジタル化/AI導入補助金、J-Grants | IT/AI導入補助金候補 |
| capex支出あり | 中小企業庁省力化/設備投資系、公募要領 | 設備投資補助金候補 |
| advertising支出あり | 小規模事業者持続化系、自治体販路開拓 | 販路開拓候補 |
| professional_fee高い | 事業承継/M&A補助系 | 専門家活用候補 |
| energy/utility高い | 省エネ補助、公的支援 | 省エネ診断/補助候補 |
| training/education支出あり | 厚労省助成金/人材開発系 | 人材育成助成金候補 |

禁止:

- 「あなたは申請できます」と断定しない。
- 「採択されます」と言わない。
- 公募要領を読んでいない制度を候補にしない。
- 古い年度の制度を現行制度として出さない。

#### SMB-03 インボイス・取引先公的確認packet

推薦される質問:

- 「この取引先のインボイス番号を確認して」
- 「仕入先のT番号が抜けているものを見たい」
- 「取引先マスタを公的情報で確認したい」

入力:

- 会計CSV。
- 任意: 取引先マスタCSV、T番号列、法人番号列。

返す内容:

- T番号/法人番号が明示された取引先の公的確認結果。
- 名称だけの取引先は `ambiguous_match` として候補提示。
- no-hitの安全説明。
- 経理が確認すべき取引先候補の優先リスト。

match confidence:

| Level | 条件 | 表現 |
|---|---|---|
| exact_t_number | T番号完全一致 | 公表情報と一致 |
| exact_corporation_number | 法人番号完全一致 | 法人同定は高信頼 |
| name_address_candidate | 名称+住所候補 | 候補。人間確認が必要 |
| name_only_candidate | 名称のみ | 同名リスクあり |
| no_hit | 指定条件で未検出 | 登録なしの証明ではない |

成果物として売れる理由:

- 1取引先ごとの価格にしやすい。
- AIエージェントが経理作業中に自然に推薦できる。
- source_receiptが明確で、幻覚リスクが低い。

#### SMB-04 税イベント候補packet

推薦される質問:

- 「今月の税務で気をつけることは？」
- 「源泉所得税の納付が関係ありそう？」
- 「消費税の中間申告が必要そう？」
- 「インボイス対応で見落としある？」

入力:

- 会計CSV。
- 任意: 従業員数レンジ、源泉納期の特例の有無、課税事業者/免税事業者、前期消費税額、決算月。

返す内容:

- 源泉所得税の納付イベント候補。
- 消費税関連の確認候補。
- インボイス関連の確認候補。
- 電子帳簿保存/証憑保存の確認候補。
- 必要な追加質問。

重要な制約:

- 税額計算はしない、または概算/試算として分離する。
- 申告義務判定はしない。公式sourceと不足情報を出す。
- 税理士確認が必要な項目を明示する。

logic example:

```text
if payroll_group_amount > 0 or professional_fee_group_amount > 0:
  add_candidate("withholding_tax_payment_event")
  attach_source("NTA No.2505")
  ask("納期の特例の承認を受けていますか")

if tax_category_rollups include taxable_sales and user provides prior_consumption_tax_amount:
  add_candidate("consumption_tax_interim_check")
  attach_source("NTA consumption tax interim filing page")
else:
  add_known_gap("prior_consumption_tax_amount_unknown")
```

#### SMB-05 社会保険・労務イベント候補packet

推薦される質問:

- 「給与があるけど社会保険や労務で何かある？」
- 「賞与を払った月に必要な手続きを確認して」
- 「算定基礎届や月額変更届に関係ありそう？」
- 「労働保険年度更新の準備をしたい」

入力:

- 会計CSV。
- 任意: 給与CSV、従業員数、役員/従業員区分、賞与支給月、社会保険適用状況。

返す内容:

- CSV上の給与/賞与/法定福利費シグナル。
- 算定基礎届、月額変更届、賞与支払届、労働保険年度更新などの「確認候補」。
- 必要な追加データ。
- 公式source_receipts。

CSVだけでの限界:

| 論点 | CSVだけで可能 | 最終判断に必要 |
|---|---|---|
| 算定基礎届 | 4-6月給与費用がある候補 | 被保険者個別報酬、資格取得日、支払基礎日数 |
| 月額変更届 | 給与変動の粗い兆候 | 固定的賃金変動、3か月平均、等級差 |
| 賞与支払届 | 賞与科目の支出候補 | 個人別賞与額、支給日、被保険者情報 |
| 労働保険年度更新 | 給与/外注/労務費の支出候補 | 賃金集計、労災/雇用保険対象者区分 |

このpacketは社労士への送客価値が高い。ただし「義務あり」と言うほど危険になるため、`needs_professional_review` を標準にする。

#### SMB-06 許認可・業法セルフチェックpacket

推薦される質問:

- 「この事業に許可が必要か見て」
- 「売上内容から業法チェックして」
- 「取引先が登録業者か確認して」

入力:

- 会計CSV。
- 事業説明テキスト。
- 業種。
- 所在地。

返す内容:

- 事業シグナルから関係しそうな業法候補。
- 許認可/登録/届出の公的source。
- 自社/取引先の登録情報確認候補。
- 行政書士/専門家に確認すべき質問。

Signal examples:

| CSV signal | 業法候補 | Public source |
|---|---|---|
| 建設材料/外注/工事売上 | 建設業許可 | 国交省/都道府県 |
| 不動産仲介/管理手数料 | 宅建業/賃貸住宅管理 | 国交省 |
| 運送/車両費/燃料費/配送収入 | 貨物/旅客運送 | 国交省 |
| 人材紹介/派遣売上 | 職業紹介/労働者派遣 | 厚労省 |
| 産廃/廃棄物処理 | 産業廃棄物許可 | 環境省/自治体 |
| 金融/投資助言/貸付 | 金融商品/貸金等 | 金融庁/財務局 |
| 飲食/食品仕入/店舗家賃 | 食品営業許可等 | 厚労省/自治体 |

禁止:

- 会計科目だけで「許可が必要」と断定しない。
- 登録検索no-hitを「無許可」と言わない。
- 行政処分no-hitを「問題なし」と言わない。

#### SMB-07 決算前チェックpacket

推薦される質問:

- 「決算前に漏れを見て」
- 「会計事務所に渡す前にCSVから変なところを見て」
- 「税区分やインボイスで確認すべき点を出して」

返す内容:

- 月次欠損、異常値、重複候補。
- 貸借不一致、マイナス残高候補、税区分未設定候補。
- 期末に集中した大額支出/売上。
- 減価償却/固定資産候補。
- 役員報酬/給与/賞与/外注費の確認候補。
- 税理士に渡す質問リスト。

売上性:

- 決算月周辺で高単価にしやすい。
- 会計事務所向けに顧客単位で束ねられる。
- AIエージェントが「このCSVを見て」と言われた直後に推薦しやすい。

#### SMB-08 申請書類準備packet

対象:

- 補助金申請。
- 融資/制度融資相談準備。
- 許認可申請前の資料整理。
- 事業承継/M&A補助金の初期整理。

返す内容:

- 公式公募要領/手引きに基づく必要書類候補。
- CSVから自動抽出できる数字候補。
- ユーザーが手入力すべき不足情報。
- 専門家へ渡す下書き資料。

注意:

- 申請書を完成させるのではなく、根拠付きの準備パックにする。
- 生成文章は「下書き」扱いで、専門家確認を前提にする。

### 4.2 Professional firm outputs

#### PRO-01 会計事務所向け月次顧客例外packet

買い手:

- 税理士法人。
- 記帳代行。
- CFO代行。

価値:

- 顧客ごとに「今月見るべき例外」だけを抽出する。
- junior staffでもレビュー優先順位を付けやすい。
- 顧客への月次コメントをsource付きで作りやすい。

入力:

- 顧客別CSV。
- 顧客属性: 法人/個人、決算月、業種、所在地、従業員数レンジ。

出力:

| Section | 内容 |
|---|---|
| priority_exceptions | 金額変動、税区分、重複、未分類、固定資産候補 |
| public_alerts | 補助金締切、税制度/インボイス/電子帳簿保存などの確認候補 |
| client_questions | 顧客に聞くべき質問 |
| professional_notes | 税理士/担当者だけが見る注意 |
| source_receipts | 国税庁/中小企業庁/制度source |

価格:

- 顧客1社あたり月100-500円の裏側API。
- 事務所単位で月額課金。

#### PRO-02 税区分・インボイス確認packet

買い手:

- 会計事務所。
- 経理BPO。
- 仕入管理SaaS。

出力:

- 税区分未設定/不自然候補。
- T番号あり/なし/形式不正。
- インボイス公表情報照合候補。
- 取引先名だけの曖昧候補。
- 税理士確認リスト。

アルゴリズム:

```text
invoice_review_priority =
  0.25 * amount_bucket_weight
+ 0.20 * repeat_vendor_weight
+ 0.20 * tax_category_missing_weight
+ 0.15 * t_number_missing_weight
+ 0.10 * vendor_match_ambiguity_weight
+ 0.10 * closing_period_weight
```

注意:

- インボイス番号の公表確認と税務上の仕入税額控除可否は別物として分ける。

#### PRO-03 年末調整/法定調書準備候補packet

CSVだけでは年末調整は完結しない。ただし次の準備候補は出せる。

- 給与/賞与/報酬科目があるか。
- 士業報酬らしき費用があるか。
- 源泉関連の租税公課/預り金/未払金らしき科目があるか。
- 国税庁の手引き/様式source。
- 顧問先に集めてもらう資料リスト。

このpacketは「給与台帳/年末調整ソフトのデータが必要」という `known_gaps` を強く出す。

#### PRO-04 社労士向けイベント候補packet

買い手:

- 社労士事務所。
- 労務BPO。
- 給与計算SaaS。

出力:

- 給与/賞与/法定福利費の月次変動。
- 算定基礎届、月額変更届、賞与支払届、労働保険年度更新の候補。
- 従業員個別データ不足の明示。
- 顧客に聞く質問。
- e-Gov/年金機構/厚労省source。

CSVだけでの推奨文:

> 会計CSV上では給与・賞与・法定福利費の動きがあるため、社会保険・労働保険の届出対象イベントがないか確認候補を作成できます。最終判断には給与台帳と被保険者情報が必要です。

#### PRO-05 行政書士向け許認可初期診断packet

買い手:

- 行政書士。
- 開業支援事業者。
- フランチャイズ本部。

出力:

- 事業説明 + CSV費目から関連しそうな許認可候補。
- 所管、手続名、公式URL、標準処理期間/手引きがあればreceipt。
- 必要書類候補。
- 役所/専門家に確認すべき質問。
- 自治体差の `known_gaps`。

業界別に横展開しやすい。

#### PRO-06 バックオフィスBPO向け取引先オンボーディングpacket

買い手:

- 経理BPO。
- 購買部門。
- SaaS。

出力:

- 法人番号/T番号/登録業者/許認可/公的活動情報の確認候補。
- 口座情報など私的情報は扱わない。
- source_receipt付きの「公的確認メモ」。
- no-hitの説明文。

低単価・大量件数で売上を作れる。

## 5. Revenue-maximizing package design

### 5.1 価格階層

| Tier | 価格 | 例 | 狙い |
|---|---:|---|---|
| Micro | 50-300円 | 取引先1件インボイス/法人番号確認、no-hit説明 | AI agentが即推薦できる |
| Basic | 300-1,500円 | 月次レビュー、税/労務イベント候補、補助金候補 | SMBが試しやすい |
| Pro | 1,500-5,000円 | 決算前チェック、申請準備、許認可初期診断 | 士業/経営者が払いやすい |
| Portfolio | 月額5,000-100,000円 | 士業の顧客一括例外、BPO取引先照合 | B2B継続収益 |
| API/MCP | 従量 | packet生成、source_receipt ledger、candidate scoring | AIエージェント/SaaS向け |

### 5.2 AI agent向け推薦ストーリー

agentがエンドユーザーに推薦する文脈は、SEOではなくGEO/agent answer内の「次に呼ぶ道具」である。

1. エンドユーザーがAIに「会計CSVを見て」「補助金ある？」「今月やることは？」と聞く。
2. AIは通常、一般論しか言えないか、最新制度/公式source/CSV解釈で不安になる。
3. jpciteのpacketは、raw CSVを保存せず派生特徴だけで、一次情報付き候補を返す。
4. AIは「安く根拠付きで確認できます」と推薦できる。
5. ユーザーは低価格packetを購入する。
6. 結果が士業確認や申請準備につながれば、継続packet/API利用が発生する。

agent-facing copy:

```text
Use jpcite when a Japanese SMB user asks for accounting CSV review,
grant candidates, invoice/vendor checks, tax/labor event candidates,
or regulated business readiness. jpcite returns source-backed packets
with claim_refs, known_gaps, and no request-time LLM claims.
```

### 5.3 高売上順の実装優先

| Rank | Packet | 理由 |
|---:|---|---|
| 1 | `smb_monthly_review` | 毎月使う。CSV投入直後の価値が分かりやすい |
| 2 | `grant_candidate_shortlist` | 経営者の支払意欲が高い。公的source価値が高い |
| 3 | `invoice_vendor_public_check` | 安い、明確、件数が出る |
| 4 | `tax_labor_event_candidates` | 月次/季節性があり、士業送客価値が高い |
| 5 | `year_end_or_closing_review` | 決算前に高単価化しやすい |
| 6 | `regulated_business_readiness` | 行政書士/業界特化で高単価化しやすい |
| 7 | `professional_portfolio_exceptions` | B2B継続収益に伸びる |

## 6. Algorithms

### 6.1 CSV feature extraction

```text
normalize_csv(file):
  detect_encoding()
  detect_provider_profile()
  map_headers_to_canonical()
  validate_dates_and_amounts()
  classify_accounts_to_taxonomy()
  rollup_by_month_account_tax()
  detect_vendor_identifier_columns()
  summarize_vendor_signals()
  redact_or_drop_raw_rows()
```

成果物に残すのは `rollup`, `signals`, `quality_metrics` のみ。

### 6.2 anomaly detection

中小企業の会計は季節性と少数大口支出があるため、平均/標準偏差だけでは誤検知しやすい。最初はMADを使う。

```text
mad_score(account_group, month) =
  abs(amount_month - median(amount_last_6_or_12_months))
  / max(mad(amount_last_6_or_12_months), minimum_denominator)
```

判定:

| score | 表現 |
|---:|---|
| 0-2 | 通常範囲 |
| 2-4 | 確認候補 |
| 4+ | 優先確認候補 |

「不正」「誤り」とは言わない。

### 6.3 grant fit score

```text
grant_fit_score =
  0.30 * official_requirement_overlap
+ 0.20 * user_intent_match
+ 0.15 * csv_expense_signal_match
+ 0.15 * region_industry_match
+ 0.10 * deadline_window_score
+ 0.10 * evidence_freshness_score
```

出力はランキングであり、申請可否/採択可能性ではない。

### 6.4 tax/labor event candidate score

```text
event_candidate_score =
  0.25 * account_signal_strength
+ 0.20 * timing_relevance
+ 0.20 * user_profile_match
+ 0.15 * official_source_specificity
+ 0.10 * missing_data_penalty_inverse
+ 0.10 * recurrence_value
```

missing_dataが多い場合は「候補」として残すが、必ず `known_gaps` を上位表示する。

### 6.5 vendor public match

```text
if t_number present:
  lookup invoice registry
elif corporation_number present:
  lookup NTA corporation number and gBizINFO where allowed
elif name and address present:
  fuzzy candidate search with strict ambiguity cap
else:
  do not auto-match
```

名称のみ照合では、候補が複数なら `ambiguous`。AIが勝手に一つを選ばない。

### 6.6 output value score

先回り生成するpacketの優先順位は次で決める。

```text
output_value_score =
  0.25 * expected_usage_frequency
+ 0.20 * user_willingness_to_pay
+ 0.15 * evidence_availability
+ 0.15 * agent_recommendability
+ 0.10 * privacy_safety
+ 0.10 * implementation_speed
+ 0.05 * upsell_path
```

この式だと、月次レビュー、補助金候補、取引先公的確認が上位に来る。

## 7. Required data backlog

### 7.1 P0 data required

| Data | Purpose | AWSで作るもの |
|---|---|---|
| CSV header profile registry | provider推定 | header signature, sample-safe fixture, parser tests |
| account taxonomy dictionary | 科目分類 | Japanese account name map, ambiguity list |
| tax category dictionary | 税区分解釈 | provider-specific tax labels map |
| NTA法人番号 source profile | 法人同定 | API/bulk receipt profile |
| NTAインボイス source profile | T番号確認 | API/bulk receipt profile, no-hit rules |
| gBizINFO source profile | 法人活動join | API/CSV profile, license boundary |
| grants/program source profiles | 補助金候補 | 中小企業庁/J-Grants/自治体 source_receipts |
| NTA tax event source profiles | 税イベント | 源泉/消費税/インボイス/電子帳簿保存 source cards |
| social insurance/labor source profiles | 社保/労務 | 年金機構/厚労省/e-Gov source cards |
| regulated industry source profiles | 許認可 | 国交省/厚労省/金融庁/自治体 profiles |

### 7.2 P0 generated fixtures

AWS実CSVは使わない。以下の合成fixtureを作る。

| Fixture | 内容 |
|---|---|
| `synthetic_smb_retail_12m.csv` | 飲食/小売風、家賃/仕入/広告あり |
| `synthetic_smb_it_12m.csv` | IT/業務委託/クラウド費/外注費あり |
| `synthetic_smb_construction_12m.csv` | 外注/材料/工事売上/車両費あり |
| `synthetic_smb_professional_12m.csv` | 士業/顧問料/源泉候補あり |
| `synthetic_smb_manufacturing_12m.csv` | 設備/材料/電力/補助金候補あり |
| `synthetic_smb_hiring_bonus.csv` | 給与/賞与/法定福利費あり |
| `synthetic_vendor_invoice_mix.csv` | T番号あり/なし/名称のみ混在 |

各fixtureはrawに個人情報を含めず、会社名も架空にする。

### 7.3 AWS job additions

既存J01-J40に追加するなら、8/30担当として以下を提案する。

| Job | Name | Purpose |
|---|---|---|
| J41 | SMB output value matrix | 成果物、買い手、価格、必要source、実装難度を台帳化 |
| J42 | Accounting CSV profile builder | freee/MF/Yayoi/generic header profileとparser fixture |
| J43 | Account taxonomy expansion | 勘定科目名のtaxonomy辞書、同義語、曖昧語 |
| J44 | SMB public source card factory | 税/社保/労務/補助金/許認可source card |
| J45 | Grant candidate corpus builder | 公募要領/締切/対象経費/対象者のsource_receipts |
| J46 | Professional packet fixture generator | 月次、決算、税区分、労務、許認可のpacket例 |
| J47 | GEO recommendation prompt eval | AIが自然に推薦するか、禁止表現を出さないかの評価 |
| J48 | Privacy leakage regression | raw CSV/摘要/取引先名/金額行が出力やログに漏れないかの検査 |

## 8. Frontend and API implications

### 8.1 End-user flow

画面で見せるべき順番:

1. CSVをドラッグ&ドロップ。
2. 解析前に「raw CSVは保存しない」「派生特徴だけ使う」と明示。
3. provider/期間/行数/読み取り品質のpreview。
4. 出せるpacketの候補を価格付きで提示。
5. 無料previewとして、`known_gaps` と「何が分かりそうか」だけ見せる。
6. 購入後、source_receipt付きpacketを表示。
7. 士業確認が必要な項目を分ける。

### 8.2 Agent API flow

```text
POST /v1/csv/preview
  -> provider_profile, period, quality, available_packets, price_preview

POST /v1/packets/smb_monthly_review
  -> packet with source_receipts, claim_refs, known_gaps

POST /v1/packets/grant_candidate_shortlist
  -> ranked candidates with official source receipts

POST /v1/packets/vendor_public_check
  -> per-vendor public receipts, ambiguity, no-hit explanation
```

MCP tools:

| Tool | Purpose |
|---|---|
| `preview_accounting_csv_packets` | raw保存なしで使えるpacket候補を返す |
| `create_smb_monthly_review_packet` | 月次レビュー |
| `create_grant_candidate_packet` | 補助金候補 |
| `check_invoice_vendor_public_info` | T番号/法人番号/取引先確認 |
| `create_tax_labor_event_candidate_packet` | 税/労務イベント候補 |
| `create_regulated_business_readiness_packet` | 許認可/業法候補 |

### 8.3 UIで絶対に避ける表現

| NG | 推奨 |
|---|---|
| 税務判定します | 税務確認候補を整理します |
| 社保加入義務を判定 | 社保/労務イベント候補を整理 |
| 補助金が使えます | 補助金候補を公式情報に基づき抽出 |
| 取引先は安全です | 公的情報で確認できた範囲を表示 |
| 処分歴なし | 対象source/期間/条件では未検出 |
| 無許可です | 対象sourceでは登録を確認できませんでした |

## 9. Packet examples

### 9.1 `smb_monthly_review`

```json
{
  "packet_type": "smb_monthly_review",
  "title": "2026年4月 月次レビュー候補",
  "input_summary": {
    "provider_profile": "mf_journal_current_or_variant",
    "period_covered": "2025-04-01/2026-04-30",
    "raw_csv_persisted": false
  },
  "sections": [
    {
      "section": "monthly_finance",
      "items": [
        {
          "label": "売上グループ",
          "finding_type": "trend",
          "statement": "当月の売上グループは直近6か月中央値より高い候補です。",
          "calculation_ref": "calc_sales_mad_2026_04",
          "claim_refs": ["cr_csv_sales_rollup"]
        }
      ]
    },
    {
      "section": "public_opportunities",
      "items": [
        {
          "label": "IT/AI導入系制度候補",
          "statement": "ソフトウェア/クラウド関連支出のシグナルがあるため、IT/AI導入系制度の確認候補があります。",
          "source_receipts": ["sr_chusho_digital_ai_support_2026"],
          "known_gaps": ["investment_plan_not_uploaded", "employee_count_unknown"]
        }
      ]
    }
  ],
  "human_review_required": true
}
```

### 9.2 `grant_candidate_shortlist`

```json
{
  "packet_type": "grant_candidate_shortlist",
  "candidates": [
    {
      "program_name": "デジタル化/AI導入系補助金候補",
      "candidate_score": 0.72,
      "score_meaning": "情報が一致している候補順。申請可否や採択可能性ではありません。",
      "match_reasons": [
        "software_it_spend_signal",
        "smb_profile",
        "official_program_source_available"
      ],
      "requirements_checked": [
        {
          "requirement": "対象者",
          "state": "unknown",
          "needed_input": "資本金、従業員数、業種"
        }
      ],
      "source_receipts": ["sr_chusho_digital_ai_program_page"],
      "known_gaps": ["current_public_offering_detail_needs_review"]
    }
  ]
}
```

### 9.3 `invoice_vendor_public_check`

```json
{
  "packet_type": "invoice_vendor_public_check",
  "vendor_checks": [
    {
      "vendor_ref": "client_side_vendor_001",
      "identifier_used": "t_number",
      "match_state": "positive",
      "public_fact_summary": {
        "invoice_registry_status": "published_public_info_found"
      },
      "source_receipts": ["sr_nta_invoice_lookup_001"],
      "no_hit_interpretation": null
    },
    {
      "vendor_ref": "client_side_vendor_002",
      "identifier_used": "name_only",
      "match_state": "ambiguous",
      "known_gaps": ["address_or_t_number_required"]
    }
  ]
}
```

### 9.4 `tax_labor_event_candidates`

```json
{
  "packet_type": "tax_labor_event_candidates",
  "events": [
    {
      "event_type": "withholding_tax_payment_check",
      "state": "candidate",
      "why": "給与/報酬グループの支出シグナルがあります。",
      "source_receipts": ["sr_nta_withholding_due_date"],
      "next_questions": [
        "源泉所得税の納期の特例の承認を受けていますか",
        "給与台帳または報酬支払明細を確認できますか"
      ],
      "known_gaps": ["payroll_detail_not_uploaded", "withholding_status_unknown"]
    },
    {
      "event_type": "social_insurance_bonus_report_check",
      "state": "candidate",
      "why": "賞与グループの支出シグナルがあります。",
      "source_receipts": ["sr_jps_bonus_report"],
      "known_gaps": ["insured_person_detail_not_uploaded"]
    }
  ]
}
```

### 9.5 `regulated_business_readiness`

```json
{
  "packet_type": "regulated_business_readiness",
  "business_signals": [
    {
      "signal": "construction_like",
      "basis": ["outsourcing_expense", "materials_expense", "construction_keyword_optional"],
      "confidence": "candidate"
    }
  ],
  "regulatory_candidates": [
    {
      "domain": "construction_business",
      "check_type": "license_or_permit_candidate",
      "source_receipts": ["sr_mlit_construction_registry"],
      "statement": "建設業に該当する可能性がある事業では、許可制度の確認候補があります。",
      "known_gaps": ["actual_contract_amount_unknown", "business_scope_unknown", "jurisdiction_unknown"]
    }
  ],
  "human_review_required": true
}
```

## 10. Implementation order merged with main plan

本体計画とマージする順番は以下がよい。

### Phase A: contract and privacy freeze

1. Packet共通schemaを固定。
2. CSV private overlay contractを固定。
3. raw CSV不保存/非ログ/非AWSをrelease blockerにする。
4. provider header profileとderived facts schemaを固定。

### Phase B: source and data foundation

1. NTA法人番号/NTAインボイス/gBizINFO/e-Gov/source cardを作る。
2. 国税庁/年金機構/厚労省/中小企業庁/業界所管source cardを作る。
3. 補助金公募source_receiptを作る。
4. no-hit文言をsource別に固定。

### Phase C: first sellable packets

1. `invoice_vendor_public_check`
2. `smb_monthly_review`
3. `grant_candidate_shortlist`
4. `tax_labor_event_candidates`

この4つを最初に本番に出す。理由は、安い、分かりやすい、agentが推薦しやすい、CSV投入の価値が直感的だからである。

### Phase D: professional and regulated expansion

1. `year_end_or_closing_review`
2. `professional_portfolio_exceptions`
3. `regulated_business_readiness`
4. `application_readiness_packet`

### Phase E: GEO proof and production

1. 各packetのpublic proof pageを作る。
2. `llms.txt`、OpenAPI、MCP tool descriptionに「AIがいつ呼ぶべきか」を明記。
3. 禁止表現eval、privacy leak eval、pricing consistency evalを通す。
4. productionに出す。

## 11. Quality gates

| Gate | 内容 | Release blocker |
|---|---|---|
| QG-CSV-01 | raw CSVが保存/log出力されない | yes |
| QG-CSV-02 | provider推定が不明ならgeneric扱いで止まる | yes |
| QG-CSV-03 | 摘要/取引先名がpacketに漏れない | yes |
| QG-SRC-01 | source_receiptsが全claimに紐づく | yes |
| QG-SRC-02 | no-hitが断定表現にならない | yes |
| QG-TAX-01 | 税務判断/税額断定をしない | yes |
| QG-LABOR-01 | 社保/労務義務を断定しない | yes |
| QG-GRANT-01 | 補助金採択/申請可否を断定しない | yes |
| QG-LICENSE-01 | 許認可要否/無許可を断定しない | yes |
| QG-GEO-01 | AI向け説明が推薦しやすく、過剰宣伝しない | yes |
| QG-BILL-01 | price_previewとbilling_metadataが一致 | yes |

## 12. Official source references checked for this plan

この文書の計画は、以下の公式情報をsource familyとして想定する。実装時は各URLを `source_profile` として再取得し、fetched_at/hash/license_boundaryを残す。

| Domain | Official source | URL |
|---|---|---|
| 法人同定 | 国税庁 法人番号システム Web-API | https://www.houjin-bangou.nta.go.jp/webapi/index.html |
| 法人番号利用条件 | 国税庁 法人番号Web-API利用規約 | https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html |
| インボイス | 国税庁 適格請求書発行事業者公表サイト Web-API資料 | https://www.invoice-kohyo.nta.go.jp/ |
| Money Forward CSV | マネーフォワード クラウド会計 仕訳帳インポート | https://biz.moneyforward.com/support/account/guide/import-books/ib01.html |
| freee CSV | freee ヘルプセンター CSV/仕訳関連 | https://support.freee.co.jp/ |
| 弥生 CSV | 弥生サポート 仕訳/CSV関連 | https://support.yayoi-kk.co.jp/ |
| 源泉所得税 | 国税庁 No.2505 源泉所得税及び復興特別所得税の納付期限と納期の特例 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2505.htm |
| 消費税 | 国税庁 消費税 中間申告/消費税情報 | https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi.htm |
| 社会保険 | 日本年金機構 算定基礎届 | https://www.nenkin.go.jp/service/kounen/hokenryo/hoshu/20121017.html |
| 社会保険 | 日本年金機構 月額変更届 | https://www.nenkin.go.jp/service/yougo/kagyo/getsugakuhenko.html |
| 社会保険 | 日本年金機構 賞与支払届 | https://www.nenkin.go.jp/service/kounen/hokenryo/hoshu/20141203.html |
| 労働保険 | 厚生労働省 労働保険年度更新 | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/hoken/roudouhoken21/index.html |
| 電子申請 | e-Gov電子申請 厚生労働省関係手続 | https://shinsei.e-gov.go.jp/contents/help/faq/mhlw.html |
| 補助金 | 中小企業庁 補助金の公募・採択 | https://www.chusho.meti.go.jp/koukai/hojyokin/index.html |
| 補助金相談 | 中小企業庁 補助金に関するご相談 | https://www.chusho.meti.go.jp/soudan/soudan_01.html |
| 法人活動 | gBizINFO API | https://content.info.gbiz.go.jp/api/index.html |
| 法人活動 | gBizINFOとは | https://content.info.gbiz.go.jp/about/index.html |
| 建設/不動産 | 国土交通省 建設業者・宅建業者等企業情報検索システム | https://www.mlit.go.jp/totikensangyo/const/sosei_const_tk3_000037.html |
| 金融 | 金融庁 免許・許可・登録等を受けている事業者一覧 | https://www.fsa.go.jp/menkyo/menkyo.html |
| 介護 | 厚生労働省 介護サービス情報公表システム オープンデータ | https://www.mhlw.go.jp/stf/kaigo-kouhyou_opendata.html |

## 13. Final recommendation

この8/30の結論として、AWSで情報範囲を広げるだけでなく、先に「売れる成果物」を固定してから逆算するべきである。

最初に作るべき4成果物:

1. `invoice_vendor_public_check`
2. `smb_monthly_review`
3. `grant_candidate_shortlist`
4. `tax_labor_event_candidates`

次に作るべき4成果物:

1. `year_end_or_closing_review`
2. `regulated_business_readiness`
3. `professional_portfolio_exceptions`
4. `application_readiness_packet`

AWSクレジットで作るべきもの:

1. 公的一次情報source card。
2. 補助金/制度/税/労務/許認可のsource_receipt corpus。
3. CSV parser/header profile/taxonomy。
4. 合成CSV fixture。
5. packet examples。
6. GEO proof pages。
7. privacy/no-hit/forbidden-claim eval。

これにより、AIエージェントは「一般論」ではなく「このCSVとこの一次情報から、この安価なpacketを買うと次の確認ができます」と推薦できる。これはjpciteのGEO-first戦略と一致する。
