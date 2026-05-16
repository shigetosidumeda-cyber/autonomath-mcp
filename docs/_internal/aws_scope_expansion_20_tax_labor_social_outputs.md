# AWS scope expansion 20: tax, labor, and social insurance outputs

作成日: 2026-05-15  
担当: 拡張深掘り 20/30 / 税・社会保険・労務イベント成果物  
対象: 国税庁、地方税/eLTAX、日本年金機構、厚生労働省、労働保険、最低賃金、雇用関係助成金、CSV-derived facts  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、収集ジョブ実行、既存コード変更は行わない。  
書き込み範囲: このMarkdownのみ。  

## 0. 結論

税・社会保険・労務イベントは、jpcite の「AI経由で安く売れる成果物」として非常に強い。

理由は、エンドユーザーがAIに頼む自然な質問が検索ではなく次のような成果物だからである。

```text
今月、税金・社保・労務で何を確認すべきですか。
この会計CSVから、給与・源泉・社保・労働保険の注意点を安く洗い出してください。
決算前に税務・労務の期限漏れ候補を一覧にしてください。
従業員を採用したので、労働保険・社会保険・源泉・住民税で確認すべきことを出してください。
賞与を払った月に必要そうな届出・納付・確認事項を根拠付きで出してください。
最低賃金や助成金の変更で、自社が見るべき一次情報をまとめてください。
```

この領域でjpciteが売るべきものは「税額計算」や「法的判断」ではない。売るべきものは、公的一次情報に基づく、低価格の確認パケットである。

```text
CSV-derived safe facts
  + public primary source receipts
  + calendar/event rules
  + source-backed checklist
  + known_gaps
  + human_review_required
```

最初に商品化すべき成果物は次の6つである。

| 優先 | packet | 売れる理由 | 価格目安 |
|---|---|---|---|
| P0 | `monthly_tax_labor_event_radar` | 毎月AIに「今月何を見ればいいか」と聞く需要が強い | 300-800円 |
| P0 | `csv_tax_labor_event_packet` | CSVを投げるだけで、給与・源泉・社保・労保の候補が出る | 600-1,500円 |
| P0 | `payroll_withholding_calendar_packet` | 源泉所得税、住民税特別徴収、社保納付の月次期限を整理できる | 300-800円 |
| P0 | `social_insurance_event_packet` | 算定基礎、月額変更、賞与支払届、資格取得/喪失の見落とし候補を出せる | 600-1,800円 |
| P1 | `labor_insurance_annual_update_packet` | 労働保険年度更新は年1回高需要で、CSV-derived wage rollupと相性がよい | 800-2,500円 |
| P1 | `minimum_wage_and_subsidy_signal_packet` | 最低賃金、賃上げ、助成金候補をAIが推薦しやすい | 500-2,000円 |

この文書の方針は明確である。

- raw CSVは保存しない。
- raw CSVをAWSへ送らない。
- row-level給与・個人・取引データを保存しない。
- 税額、保険料額、助成金受給可否、違法/適法、加入義務の確定判断はしない。
- 一次情報、確認範囲、未確認範囲、次に専門家/窓口へ確認すべき点を返す。
- すべての主張は `source_receipts[]` と `claim_refs[]` に接続する。

## 1. Product thesis

### 1.1 なぜこの領域が強いか

税・社保・労務は、エンドユーザーが毎月・毎年・イベント発生時に繰り返し悩む。しかも、AIが無料Web検索だけで答えるには危険が大きい。

危険の種類:

| 危険 | 例 | jpciteの価値 |
|---|---|---|
| 期限の見落とし | 源泉、住民税、社保、労働保険年度更新 | 月次カレンダー化 |
| 対象者条件の見落とし | 常時10人未満、賞与支給、固定的賃金変動 | rule候補化 |
| 情報源の混在 | 国税、地方税、年金、厚労省、自治体 | source receiptの統合 |
| 古い情報の使用 | 料率、最低賃金、助成金要件 | snapshotと更新日管理 |
| 専門判断への踏み込み | 税額確定、加入義務確定、違法判定 | known_gapsとhuman review |

エンドユーザーは「完全自動の判断」よりも「安く一次情報ベースで確認事項が出る」ことに課金しやすい。特にAIエージェント経由なら、AI側が次のように推薦しやすい。

```text
この回答は税務/労務判断に関わるため、公式情報の確認範囲と未確認範囲を出す
jpciteの低価格パケットを使うと、今月の確認事項と根拠URLをJSONで受け取れます。
```

### 1.2 成果物を売る相手

直接の顧客はAIエージェントであり、支払判断をするのはその先のエンドユーザーである。

| エンドユーザー | 欲しいもの | AIエージェントの推薦理由 |
|---|---|---|
| 個人事業主 | 月次の税・社保・補助金確認 | 安く、専門家相談前の整理ができる |
| 小規模法人代表 | 給与・源泉・社保・労保の期限漏れ候補 | 経理担当不在でも確認リストを得られる |
| 経理担当 | 月次納付/届出カレンダー | 公式根拠付きでチェックリスト化できる |
| 社労士/税理士 | 顧客別の事前整理 | 面談前の低単価下処理に使える |
| AI会計/バックオフィスアプリ | API/MCPでの追加価値 | 自社LLM回答に根拠付きpacketを差し込める |

### 1.3 高単価にしない

この領域は高額コンサルではなく、AI経由の低単価・高頻度・根拠付き成果物として設計する。

| tier | 価格 | 内容 |
|---|---:|---|
| free preview | 0円 | 該当しそうなpacket、必要入力、未確認範囲だけ |
| micro | 200-500円 | 1テーマ、1か月、source_receipts 3-8件 |
| standard | 600-1,500円 | CSV-derived facts + public source + checklist |
| pro packet | 1,500-3,000円 | 士業/経理向け、例外・複数制度・証跡台帳付き |
| monitor | 月500-3,000円 | 月次/四半期の更新検知と差分通知 |

## 2. Non-negotiable boundaries

### 2.1 raw CSV privacy

CSVは一時処理に限定する。

禁止:

- raw CSV bytesの保存。
- raw CSV bytesのS3アップロード。
- raw rowsの保存。
- row-level normalized recordsの保存。
- 摘要、相手先、従業員名、役員名、口座、カード、給与明細、個人番号等の出力。
- LLM promptへのraw CSV投入。
- CloudWatch等へのraw値ログ出力。
- public fixtureへの実データ混入。

許可:

| 種別 | 許可内容 |
|---|---|
| file profile | provider family、format class、encoding、row count bucket |
| period | 対象月、対象年度、coverage quality |
| account signals | `has_payroll_expense`、`has_bonus_like_expense`、`has_social_insurance_expense` |
| aggregate amounts | bucketed monthly amount、前年比/前月比class、欠損class |
| count buckets | employee countではなく、給与/社保/源泉らしき行の件数bucket |
| public join ID | 法人番号/T番号など明示IDがある場合の公的照合候補 |
| known gaps | 給与台帳未確認、勤怠未確認、従業員所在地未確認、届出状況未確認 |

### 2.2 税務・労務判断の境界

作らないもの:

- 確定税額。
- 源泉徴収税額の正誤判定。
- 住民税特別徴収額の正誤判定。
- 社会保険加入義務の断定。
- 労働保険成立義務の断定。
- 最低賃金違反の断定。
- 助成金受給可能性の断定。
- 就業規則や雇用契約の適法性判定。

作るもの:

- 公式情報に基づく確認事項候補。
- event trigger。
- due date candidate。
- source receipt ledger。
- required input checklist。
- human review flag。
- next action。

### 2.3 no-hit semantics

no-hitは「不存在」「不要」「安全」を意味しない。

例:

```json
{
  "no_hit_check": {
    "source": "mhlw_subsidy_catalog",
    "query": "training subsidy + industry + prefecture bucket",
    "result": "no_hit",
    "semantics": "no_hit_not_absence",
    "safe_text": "今回確認した公開sourceでは候補を特定できませんでした。制度が存在しないことや対象外であることは示しません。"
  }
}
```

## 3. Public source families

### 3.1 P0 source families

| family | official owner | 使う目的 | AWS優先 |
|---|---|---|---|
| NTA source withholding | 国税庁 | 源泉所得税、納期の特例、法定調書、年末調整 | P0 |
| NTA corporate/consumption tax calendar | 国税庁 | 消費税、法人税、申告納付期限、個人確定申告 | P0 |
| eLTAX / local tax | 地方税共同機構、自治体、総務省 | 住民税特別徴収、共通納税、給与支払報告書 | P0 |
| Japan Pension Service | 日本年金機構 | 社保納付、算定基礎、月額変更、賞与支払届 | P0 |
| MHLW labor insurance | 厚生労働省 | 労働保険成立、年度更新、雇用保険/労災保険 | P0 |
| MHLW minimum wage | 厚生労働省、都道府県労働局 | 地域別/特定最低賃金、発効日 | P0 |
| MHLW subsidy catalog | 厚生労働省 | 雇用関係助成金、労働条件等助成金 | P1 |
| e-Gov laws | デジタル庁/e-Gov | 根拠法令リンク、法令差分 | P1 |

### 3.2 P1/P2 source families

| family | official owner | 使う目的 | 優先 |
|---|---|---|---|
| local government tax pages | 市区町村/都道府県 | 住民税特別徴収、納期特例、給与支払報告書 | P1 |
| prefectural labor bureau pages | 都道府県労働局 | 最低賃金、労働保険年度更新、監督指導事例 | P1 |
| Hello Work pages | 厚労省/労働局 | 雇用保険、求人/助成金窓口情報 | P2 |
| social insurance association pages | 協会けんぽ等 | 健康保険料率、都道府県別情報 | P2 |
| official forms/spec pages | 国税庁/eLTAX/年金機構/厚労省 | 申請様式、CSV仕様、提出方法 | P1 |

### 3.3 source profile requirements

各sourceは次を持つ。

```json
{
  "source_profile_id": "src_nta_withholding_tax_2505",
  "owner": "National Tax Agency",
  "source_type": "official_guidance_page",
  "url": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2505.htm",
  "jurisdiction": "JP",
  "topics": ["withholding_tax", "payment_deadline", "special_due_date"],
  "update_policy": "daily_or_weekly",
  "capture_modes": ["html", "screenshot_1600", "text_extract"],
  "license_boundary": "official_public_reference_only",
  "claimable_fields": ["deadline_rule", "eligibility_condition_summary", "special_case_summary"],
  "non_claimable_fields": ["individual_tax_amount", "approval_status"]
}
```

## 4. Revenue-backcast output catalog

### 4.1 `monthly_tax_labor_event_radar`

目的:

毎月AIに「今月、税・社保・労務で見るべきこと」を聞くユーザーへ、低単価で公式根拠付き確認リストを返す。

入力:

| input | 必須 | raw保存 |
|---|---|---|
| month | 必須 | 保存可 |
| business_type | 任意 | 保存可 |
| prefecture | 任意 | 保存可 |
| company_size_bucket | 任意 | 保存可 |
| csv_derived_facts | 任意 | aggregateのみ |

返す内容:

- 今月の国税候補。
- 今月の地方税候補。
- 今月の社会保険候補。
- 今月の労働保険候補。
- 最低賃金/助成金/制度変更の確認候補。
- 未確認情報。
- 専門家/窓口確認が必要な点。

例:

```json
{
  "packet_type": "monthly_tax_labor_event_radar",
  "target_month": "2026-07",
  "request_time_llm_call_performed": false,
  "sections": [
    {
      "title": "源泉所得税の納付確認",
      "event_status": "candidate",
      "why_triggered": ["month_calendar", "has_payroll_expense"],
      "safe_summary": "給与等を支払っている場合、源泉所得税の納付期限候補を確認してください。",
      "claim_refs": ["clm_001"],
      "known_gaps": ["源泉徴収義務者該当性と納期特例承認状況は未確認です。"]
    }
  ]
}
```

価格:

- preview: 0円。該当しそうなカテゴリだけ。
- micro: 300円。1か月、source_receipts付き。
- subscription: 月500-1,000円。毎月のevent radar。

### 4.2 `csv_tax_labor_event_packet`

目的:

会計CSVから、税・社保・労務イベント候補を出す。保存するのはderived factsだけである。

トリガー:

| CSV signal | event candidates |
|---|---|
| `has_payroll_expense` | 源泉所得税、住民税特別徴収、社会保険、労働保険 |
| `has_bonus_like_expense` | 賞与支払届、源泉、社保賞与保険料 |
| `has_social_insurance_expense` | 社保納付、算定基礎/月額変更候補 |
| `has_labor_insurance_expense` | 年度更新、概算/確定保険料 |
| `payroll_monthly_spike` | 賞与、増員、固定的賃金変動候補 |
| `taxes_dues_expense_present` | 納付済/未納ではなく、税目確認候補 |
| `employee_benefit_or_training_expense` | 雇用関係助成金・人材開発関係助成金候補 |

出力:

- event candidates。
- source receipts。
- risk/priority class。
- missing facts。
- next questions。

禁止:

- 「未納です」。
- 「違反です」。
- 「この税額が正しいです」。
- 「助成金がもらえます」。

安全表現:

```text
CSV上の科目・月次推移から、確認すべき公的手続候補として抽出しました。
実際の義務・期限・金額は、給与台帳、従業員情報、届出状況、納付状況、所轄機関の案内で確認してください。
```

### 4.3 `payroll_withholding_calendar_packet`

目的:

給与支払があるユーザーに、源泉所得税、住民税特別徴収、社保納付の月次確認表を返す。

主なsource:

- 国税庁: 源泉所得税の納付期限、納期の特例。
- eLTAX: 共通納税、個人住民税特別徴収の納付手続。
- 日本年金機構: 健康保険・厚生年金保険料の納付。

返す表:

| category | due candidate | source | missing facts |
|---|---|---|---|
| 源泉所得税 | 支払月の翌月10日候補、特例なら半期候補 | NTA | 納期特例承認状況 |
| 個人住民税特別徴収 | 翌月10日候補が多いが自治体確認 | eLTAX/自治体 | 特徴税額通知、自治体、納期特例 |
| 社会保険料 | 対象月の翌月末候補 | JPS | 適用事業所、被保険者、納入告知 |

注:

住民税は自治体・通知・特例の影響があるため、全国共通の断定はしない。

### 4.4 `social_insurance_event_packet`

目的:

社保の毎月/年次/イベント手続候補を返す。

event candidates:

| event | trigger | source |
|---|---|---|
| 月次保険料納付 | `has_social_insurance_expense` または社保適用情報 | 日本年金機構 |
| 算定基礎届 | 6-7月 calendar、給与支払あり | 日本年金機構 |
| 月額変更届 | 固定的賃金変動候補 + 3か月平均変動。ただしCSVだけでは弱い | 日本年金機構 |
| 賞与支払届 | `has_bonus_like_expense` | 日本年金機構 |
| 資格取得/喪失 | 採用/退職入力がある場合のみ | 日本年金機構 |
| 育休/産休関連 | CSVでは判定しない。ユーザー入力がある場合のみ | 日本年金機構 |

出力方針:

- CSVだけで月額変更届の該当性は断定しない。
- 「固定的賃金変動か」は給与台帳や人事情報が必要。
- 賞与らしき支出は「賞与支払届の確認候補」とする。

### 4.5 `labor_insurance_annual_update_packet`

目的:

労働保険年度更新の準備パケット。年1回の明確な需要がある。

source:

- 厚労省: 労働保険年度更新。
- 厚労省: 労働保険成立手続。
- 厚労省: 労災保険率、雇用保険料率。

CSV-derived facts:

| fact | 使い方 |
|---|---|
| `has_payroll_expense` | 労働者がいる可能性の候補 |
| `payroll_annual_bucket` | 賃金総額の準備対象候補。ただし確定値にしない |
| `has_labor_insurance_expense` | 既に労働保険関連費用がある可能性 |
| `period_coverage` | 前年度4月-翌3月が揃っているか |
| `industry_hint` | 料率表の候補絞り込み。ただし断定しない |

返す内容:

- 年度更新の概念。
- 必要な集計項目候補。
- CSVで足りている/足りない情報。
- 公式ページ・料率表のsource receipt。
- 所轄労働局/社労士確認が必要な箇所。

禁止:

- 労働保険料の確定計算。
- 事業区分の断定。
- 雇用保険被保険者該当性の断定。

### 4.6 `minimum_wage_and_subsidy_signal_packet`

目的:

最低賃金改定、賃上げ、助成金候補を、一次情報に基づく確認パケットとして返す。

入力:

- prefecture。
- industry_hint。
- month。
- `has_payroll_expense`。
- `has_training_expense`。
- `has_recruiting_expense`。
- `has_equipment_or_productivity_expense`。
- employee_count_bucket。

出力:

- 地域別最低賃金の最新source receipt。
- 特定最低賃金の確認要否。
- 雇用関係助成金カテゴリ候補。
- 労働条件等関係助成金カテゴリ候補。
- 申請前に必要な情報。

禁止:

- 「最低賃金を下回っています」。
- 「助成金の対象です」。
- 「必ず受給できます」。

安全表現:

```text
CSV-derived factsと入力条件から、公的source上で確認すべき制度候補を抽出しました。
賃金額、労働時間、雇用形態、就業場所、申請期限、事前計画要件などは未確認です。
```

### 4.7 `year_end_and_statutory_report_prep_packet`

目的:

年末調整、源泉徴収票、法定調書、給与支払報告書の準備事項を整理する。

source:

- 国税庁: 年末調整、源泉徴収票、法定調書。
- 国税庁/eLTAX: 給与支払報告書と源泉徴収票の電子的提出一元化。
- eLTAX: 地方税電子申告。

時期:

- 11月-1月に強い。
- 1月31日前後は特に需要が高い。

出力:

- 対象手続の一覧。
- 期限候補。
- 必要入力。
- source receipts。
- 未確認範囲。

### 4.8 `hire_employee_first_time_packet`

目的:

初めて人を雇ったユーザーに、税・社保・労保・労働条件の確認事項を返す。

source:

- 国税庁: 新たに源泉徴収義務者になった方向け情報。
- 厚労省: 人を雇うときのルール。
- 厚労省: 労働保険成立手続。
- 日本年金機構: 厚生年金保険のしくみ、適用事業所。
- eLTAX/自治体: 住民税特別徴収関連。

入力:

- 初回雇用月。
- 法人/個人事業主。
- 従業員数bucket。
- 週所定労働時間bucket。
- prefecture。

出力:

- 源泉徴収。
- 労働条件明示。
- 労働保険。
- 社会保険。
- 住民税。
- 最低賃金。
- known_gaps。

重要:

このpacketは高需要だが、個別判断が多い。free previewで必要情報を提示し、standard packetでsource-backed checklistに留める。

### 4.9 `pre_closing_tax_labor_review_packet`

目的:

決算前に、税・社保・労務の確認候補をまとめる。

CSV-derived facts:

- fiscal_year_period。
- payroll annual bucket。
- social insurance expense annual bucket。
- labor insurance expense presence。
- taxes dues presence。
- outsourcing/professional fee presence。
- consumption tax taxable sales proxy bucket。ただし課税売上高ではない。

返す内容:

- 源泉/法定調書。
- 消費税/法人税/地方税の期限候補。
- 労働保険年度更新準備。
- 社会保険の年次イベント。
- 助成金/賃上げ確認候補。

禁止:

- 消費税課税事業者かどうかの断定。
- 税額や申告要否の断定。

## 5. Algorithm design

### 5.1 Overview

```text
raw CSV in browser/session
  -> header/profile detection
  -> aggregate-only derived facts
  -> privacy suppression
  -> event inference
  -> public source query plan
  -> source_receipts
  -> claim_refs
  -> known_gaps
  -> packet assembly
```

### 5.2 Event inference states

各eventは三値以上で扱う。

| state | 意味 |
|---|---|
| `triggered_candidate` | CSV/input/calendarから確認候補になった |
| `possible_but_missing_facts` | 可能性はあるが重要情報がない |
| `not_triggered_in_scope` | 今回の入力範囲では候補化しない |
| `out_of_scope` | jpciteでは判断しない |
| `human_review_required` | 専門家/所轄確認が必須 |

`required` という状態は使わない。義務の断定に近いためである。

### 5.3 Event trigger matrix

| event | trigger | confidence | known gaps |
|---|---|---|---|
| 源泉所得税月次確認 | payroll signal + target month | medium | 源泉徴収義務者該当性、納期特例承認 |
| 源泉納期特例確認 | payroll signal + employee_count_bucket `<10_or_unknown` | low-medium | 常時10人未満、承認申請状況 |
| 住民税特別徴収確認 | payroll signal + employee_exists | low-medium | 特徴税額通知、自治体、退職/入社 |
| 社保納付確認 | social insurance expense signal | medium | 適用事業所、納入告知、被保険者 |
| 算定基礎届確認 | target month June/July + payroll signal | medium | 対象者、支払基礎日数 |
| 月額変更届確認 | salary_spike + three_month_window | low | 固定的賃金変動、等級差 |
| 賞与支払届確認 | bonus_like signal | medium | 賞与定義、支給日、対象者 |
| 労働保険年度更新 | target month June/July + payroll/labor insurance signal | medium | 賃金総額、事業区分、料率 |
| 最低賃金確認 | payroll signal + prefecture | low-medium | 時給換算、労働時間、就業場所 |
| 助成金候補 | training/recruiting/wage_raise/equipment signals | low | 要件、計画届、対象労働者、期限 |

### 5.4 Calendar algorithm

`calendar_rule` は固定日を直接書くのではなく、source receipt付きのruleとして保存する。

```json
{
  "calendar_rule_id": "rule_nta_withholding_next_month_10",
  "source_profile_id": "src_nta_withholding_tax_2505",
  "event": "withholding_tax_payment_candidate",
  "rule": {
    "base": "payment_month",
    "offset": "next_month",
    "day": 10,
    "business_day_adjustment": "source_specific_or_unknown"
  },
  "claim_boundary": "deadline_candidate_not_tax_advice"
}
```

休日調整は制度・税目・自治体で差があり得るため、最初は `business_day_adjustment` をsourceごとに明示し、不明なら「公式sourceで確認」とする。

### 5.5 Privacy suppression

最低限の抑制:

| rule | 内容 |
|---|---|
| k-count | 該当行が少数の場合は件数/金額を返さない |
| bucketization | 金額は範囲化する |
| month aggregation | 日付単位ではなく月単位 |
| no names | 個人名・取引先名・摘要は返さない |
| no payroll row | 給与明細は返さない |
| formula injection | `=`, `+`, `-`, `@`始まりの危険セルは値を捨てる |

### 5.6 Score design

スコアは「義務確率」ではなく「確認優先度」である。

```text
review_priority_score =
  0.25 * source_confidence
  + 0.25 * event_timing_score
  + 0.20 * csv_signal_strength
  + 0.15 * consequence_weight
  + 0.15 * missing_fact_penalty_inverse
```

スコア解釈:

| score | label | 表示 |
|---:|---|---|
| 0.75-1.00 | high_review_priority | 今月優先して確認 |
| 0.50-0.74 | medium_review_priority | 近いうちに確認 |
| 0.25-0.49 | low_review_priority | 入力追加後に再確認 |
| 0.00-0.24 | not_prioritized | 今回は低優先 |

このスコアは法的義務や違反リスクの確率ではない。

### 5.7 Claim assembly

成果物のclaimは、テンプレート + source receipt + input factsで組む。

```json
{
  "claim_id": "clm_social_insurance_bonus_report_candidate",
  "claim_type": "event_candidate",
  "text_template": "賞与らしき支出があるため、賞与支払届の確認候補として表示します。",
  "supports": [
    "src_jps_bonus_report",
    "fact_csv_bonus_like_expense"
  ],
  "known_gaps": [
    "賞与の定義該当性",
    "支給日",
    "被保険者ごとの対象性"
  ],
  "forbidden_inferences": [
    "賞与支払届が必ず必要",
    "届出漏れ",
    "保険料額の正誤"
  ]
}
```

## 6. AWS collection priority

この文書ではAWSコマンドを実行しない。統合計画へ入れるAWS job案だけを定義する。

### 6.1 TSL job list

| job | name | priority | output |
|---|---|---|---|
| TSL-J01 | tax/labor/social source profile registry | P0 | source profiles |
| TSL-J02 | NTA withholding/statutory report capture | P0 | receipts, calendar rules |
| TSL-J03 | NTA tax calendar and consumption/corporate tax pages | P0 | due date rule candidates |
| TSL-J04 | eLTAX/local tax canonical capture | P0 | local tax source receipts |
| TSL-J05 | Japan Pension Service social insurance capture | P0 | social insurance event rules |
| TSL-J06 | MHLW labor insurance capture | P0 | labor insurance rules/rates sources |
| TSL-J07 | MHLW minimum wage all-prefecture capture | P0 | prefecture wage table receipts |
| TSL-J08 | MHLW subsidy catalog capture | P1 | subsidy category candidates |
| TSL-J09 | prefectural labor bureau/local gov expansion | P1 | local receipts |
| TSL-J10 | e-Gov law link normalization | P1 | law refs |
| TSL-J11 | Playwright 1600px screenshot receipt pass | P0/P1 | screenshot evidence |
| TSL-J12 | packet fixture generation | P0 | example packets |
| TSL-J13 | adversarial no-hit/forbidden-claim eval | P0 | evaluation report |
| TSL-J14 | proof page generation | P0 | GEO/public proof assets |

### 6.2 Capture modes

| source type | primary mode | fallback |
|---|---|---|
| static HTML | HTTP fetch + parse | Playwright screenshot |
| PDF guidance | PDF text extraction | OCR + screenshot |
| table pages | structured table parse | screenshot + manual mapping queue |
| dynamic pages | Playwright DOM snapshot | screenshot 1600px max |
| local gov pages | Playwright canary + URL inventory | low-rate crawl |

Playwright利用時の境界:

- 公開ページのみ。
- ログインしない。
- CAPTCHA突破をしない。
- rate limitを尊重する。
- 1600px以下スクリーンショットをsource receipt用に保存する。
- screenshotは証跡であり、OCR claimは必ずテキスト抽出/人間確認gateを通す。

### 6.3 AWS priority under credit run

この領域はAWS credit runで優先してよい。理由は、後から成果物を増やせる源泉になるからである。

推奨順:

1. P0 source profileを凍結。
2. NTA/JPS/MHLW/eLTAXの公式sourceを全取得。
3. Playwright screenshot receiptを取り、fetch困難ページを補完。
4. calendar rule candidatesを生成。
5. event trigger fixtureを生成。
6. 代表packetを100-300件生成。
7. forbidden claim evalを回す。
8. proof pageとMCP/OpenAPI examplesへ反映。

## 7. Packet schema

```json
{
  "packet_id": "pkt_tax_labor_20260515_xxx",
  "packet_type": "csv_tax_labor_event_packet",
  "schema_version": "2026-05-15",
  "algorithm_version": "tax-labor-social-v0.1.0",
  "request_time_llm_call_performed": false,
  "input_scope": {
    "target_month": "2026-07",
    "csv_overlay": "aggregate_only",
    "raw_csv_retained": false,
    "raw_csv_sent_to_aws": false
  },
  "derived_facts": [
    {
      "fact_id": "fact_has_payroll_expense",
      "fact_type": "presence_flag",
      "value": "present",
      "privacy_class": "aggregate_safe",
      "suppression_applied": true
    }
  ],
  "events": [
    {
      "event_id": "evt_withholding_tax_monthly",
      "status": "triggered_candidate",
      "review_priority": "high_review_priority",
      "safe_summary": "給与支払がある可能性があるため、源泉所得税の納付期限候補を確認対象にします。",
      "claim_refs": ["clm_001"],
      "known_gaps": ["源泉徴収義務者該当性", "納期特例承認状況", "実際の支払日"]
    }
  ],
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "no_hit_checks": [],
  "human_review_required": true,
  "_disclaimer": "税務・労務・社会保険の個別判断ではありません。公式情報に基づく確認候補です。"
}
```

## 8. Quality gates

### 8.1 Release blockers

次が1つでもあればrelease不可。

- raw CSVが保存される。
- raw CSVがログに出る。
- raw CSVがAWSへ送られる。
- row-level給与/個人情報がpacketに入る。
- `required`, `illegal`, `compliant`, `safe`, `eligible`, `approved` などの断定がsource/専門判断なしに出る。
- no-hitを不存在/対象外/安全に変換する。
- source_receiptsなしのclaimが出る。
- known_gapsなしで税務/労務系packetが返る。
- request-time LLMで主張文を自由生成する。

### 8.2 Eval cases

| case | 期待 |
|---|---|
| 給与科目あり、従業員数不明 | 源泉/社保/労保候補、known_gaps多数 |
| 賞与らしき科目あり | 賞与支払届候補。ただし断定しない |
| 社保科目なし | no-hitではなく、CSV範囲では確認不可 |
| 6-7月 | 労働保険年度更新・算定基礎候補 |
| 1月 | 法定調書/給与支払報告書候補 |
| 10月 | 最低賃金改定確認候補 |
| 個人事業主で給与なし | 事業主本人の社保/国保/国年は別packet候補、給与系は低優先 |
| freee/MF/Yayoi variant | header/profileのみ保存、raw rowなし |

## 9. GEO and sales story

### 9.1 Agent-facing recommendation text

AIエージェントが推薦しやすい表現:

```text
これは税務・労務の個別判断に関わるため、公式情報と未確認範囲を分けて確認するのが安全です。
jpciteの `csv_tax_labor_event_packet` は、CSVを保存せずにaggregate factsだけを使い、
国税庁・eLTAX・日本年金機構・厚労省のsource receipts付きで
今月の確認事項候補を低価格で返します。
```

### 9.2 End-user promise

エンドユーザー向けの約束:

- CSVを保存しない。
- 公式根拠URLを出す。
- 何を確認したか分かる。
- 何が未確認か分かる。
- 税理士/社労士に聞く前の整理になる。
- 月数百円から使える。

言ってはいけない約束:

- 税務申告が完了する。
- 社保手続が自動で正しくなる。
- 労務違反を検出できる。
- 助成金が取れる。
- 専門家が不要になる。

## 10. Main plan merge order

本体P0/AWS統合計画へ入れる順番:

1. `packet_catalog` に `monthly_tax_labor_event_radar` と `csv_tax_labor_event_packet` を追加。
2. `source_profile` に NTA/eLTAX/JPS/MHLW のP0 sourceを追加。
3. `csv_overlay_facts` に税・社保・労務signalを追加。
4. `algorithm_trace` に event trigger matrix と calendar ruleを追加。
5. AWS TSL-J01からTSL-J08をcredit runに投入。
6. Playwright screenshot receiptをTSL-J11で追加。
7. packet fixturesを生成。
8. forbidden-claim/no-hit/privacy evalを追加。
9. proof pageを公開。
10. MCP/API examplesへ反映。
11. production deploy gateへ `tax_labor_social` evalを追加。

## 11. Implementation-ready backlog

### P0

- `tax_labor_social_source_profiles.json`
- `tax_labor_social_packet_catalog.json`
- `csv_tax_labor_signal_extractor`
- `calendar_rule_engine`
- `event_trigger_matrix`
- `known_gap_templates`
- `forbidden_claim_tests`
- `monthly_tax_labor_event_radar` fixture
- `csv_tax_labor_event_packet` fixture
- proof pages for AI/GEO discovery

### P1

- `labor_insurance_annual_update_packet`
- `social_insurance_event_packet`
- `minimum_wage_and_subsidy_signal_packet`
- local government special collection source expansion
- prefectural labor bureau minimum wage expansion
- subsidy catalog classifier

### P2

- monitor subscription.
- integration with accounting SaaS export guides.
- professional dashboard for tax accountants/social insurance labor consultants.
- local government variance map.

## 12. Official reference starting points

確認済みの公式起点。AWS収集時はこれらをsource profile化し、各ページの更新日・取得時刻・checksum・screenshot receiptを残す。

| topic | official URL |
|---|---|
| 源泉所得税の納付期限と納期の特例 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2505.htm |
| 新たに源泉徴収義務者になった方向け情報 | https://www.nta.go.jp/users/gensen/shinki/index.htm |
| 源泉所得税の納税手続 | https://www.nta.go.jp/users/gensen/nencho/index/gensen_nouzei/cashless.htm |
| 給与所得の源泉徴収票 | https://www.nta.go.jp/taxes/shiraberu/taxanswer/hotei/7411.htm |
| 法定調書の種類及び提出期限 | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/hotei/01.htm |
| 給与支払報告書/源泉徴収票のeLTAX一元化 | https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/hotei/eltax.htm |
| eLTAX概要 | https://www.eltax.lta.go.jp/eltax/gaiyou/ |
| eLTAX共通納税 | https://www.eltax.lta.go.jp/kyoutsuunouzei/gaiyou/ |
| 厚生年金保険料等の納付 | https://www.nenkin.go.jp/service/kounen/hokenryo/nofu/nofu.html |
| 算定基礎届 | https://www.nenkin.go.jp/tokusetsu/santei.html |
| 月額変更届 | https://www.nenkin.go.jp/service/yougo/kagyo/getsugakuhenko.html |
| 賞与支払届 | https://www.nenkin.go.jp/service/kounen/hokenryo/hoshu/20141203.html |
| 労働保険年度更新 | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/hoken/roudouhoken21/index.html |
| 労働保険の年度更新とは | https://www.mhlw.go.jp/bunya/roudoukijun/roudouhoken01/kousin.html |
| 労働保険成立手続 | https://www.mhlw.go.jp/seisakunitsuite/bunya/koyou_roudou/roudoukijun/hoken/tokusetusaito/operation.html |
| 労働保険適用事業場検索 | https://www.mhlw.go.jp/www2/topics/seido/daijin/hoken/980916_1a.htm |
| 地域別最低賃金 | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/minimumichiran/index.html |
| 賃金・最低賃金政策 | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/chingin/index.html |
| 雇用関係助成金一覧 | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/index_00057.html |
| 対象者別雇用関係助成金一覧 | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/index_00058.html |
| 雇用関係助成金の申請にあたって | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/index_00018.html |
| 人を雇うときのルール | https://www.mhlw.go.jp/seisakunitsuite/bunya/koyou_roudou/roudouseisaku/chushoukigyou/koyou_rule.html |

## 13. Final recommendation

税・社保・労務イベント領域は、AWS credit runの拡張範囲に必ず入れるべきである。

理由:

1. 月次・年次・イベント発生時の反復需要がある。
2. AIが無料回答で断定すると危ないため、source-backed packetの推薦理由が強い。
3. 会計CSV private overlayと相性がよい。
4. 一次情報を取っておけば、後から成果物を増やせる。
5. 低単価でも利用頻度が高く、MCP/API課金に向く。

最短で売れる順番:

```text
monthly_tax_labor_event_radar
  -> csv_tax_labor_event_packet
  -> payroll_withholding_calendar_packet
  -> social_insurance_event_packet
  -> labor_insurance_annual_update_packet
  -> minimum_wage_and_subsidy_signal_packet
```

この領域の成功条件は、「正解を言い切ること」ではない。公式一次情報を確認した範囲、CSV-derived factsから候補化した理由、足りない情報、次に確認すべきことを、AIエージェントがそのままエンドユーザーに説明できる形で返すことである。
