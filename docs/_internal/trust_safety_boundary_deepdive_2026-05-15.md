# Trust / Safety / Legal Boundary Deep Dive

作成日: 2026-05-15  
担当: Trust/safety/legal boundary  
状態: pre-implementation planning only  
制約: 実装コードは触らない。jpcite は証拠/確認用レイヤーであり、税務・法務・監査・融資・補助金採択判断をしない。

## 0. Executive Boundary

jpcite の安全境界は「根拠を返すが、結論を職業専門家の代わりに出さない」ことである。AI エージェントが end-user へ推薦する場合も、jpcite を「判断エンジン」「採択判定」「税務/法務アドバイザー」「与信判定」と呼んではいけない。

許される中心表現:

- 公開情報・一次資料・公的データの根拠確認。
- 出典 URL、取得日時、content hash、source receipt、known gaps の整理。
- 人間レビューや専門家確認へ渡す前段資料。
- AI 回答前の evidence packet / evidence prefetch layer。
- 対象 source 内での hit / no-hit / blocked / stale の区別。

許されない中心表現:

- 税務・法務・監査・融資・補助金採択・与信・安全性の最終判断。
- no_hit を不存在証明、安全証明、登録なし確定、違反なし確定として扱うこと。
- CSV 取引明細、摘要、取引先、個人情報、銀行/カード/給与/医療等の機微情報を、出典付き成果物の外部出力へ転記すること。
- AI が jpcite の出力を使って「申請できます」「税務上有利です」「法的に問題ありません」「融資可能です」等と断定すること。

## 1. 禁止表現リスト

禁止表現は、public copy、OpenAPI/MCP description、examples、agent prompt、生成 markdown、CSV export、営業資料、CI fixture のすべてで避ける。下表の表現は完全一致だけでなく、同義表現も禁止する。

| Category | 禁止表現 | 禁止理由 | 置換方向 |
|---|---|---|---|
| 専門判断 | 税務判断できます | 税理士業務への接近 | 税務確認のための根拠を整理します |
| 専門判断 | 法的に問題ありません | 法律鑑定・非弁リスク | 法務レビューで確認すべき根拠を示します |
| 専門判断 | 監査済み / 監査完了 | 監査意見の誤認 | 監査調書の前段資料として使える公開根拠を整理します |
| 専門判断 | 融資可能 / 与信OK | 与信・金融判断 | 公開情報ベースの確認材料を整理します |
| 専門判断 | 採択されます / 採択確実 | 補助金採択判断・保証 | 申請前に確認すべき候補条件を示します |
| 専門判断 | 申請できます | 行政書士業務・個別可否判断への接近 | 公開要件に照らした候補/要確認点を示します |
| 専門判断 | 税額はいくらです | 税務相談/税額計算結果の提示 | 税額確認に必要な根拠項目を整理します |
| 専門判断 | 契約上有効です | 法律鑑定への接近 | 契約レビューで確認すべき公開根拠を示します |
| 専門判断 | 登記できます | 司法書士業務への接近 | 登記手続前に確認すべき公開情報を整理します |
| 専門判断 | 労務上問題なし | 社労士業務・法的判断への接近 | 労務レビューで確認すべき制度/根拠を示します |
| no_hit | 存在しません | no_hit は不存在証明ではない | 対象 source では確認できませんでした |
| no_hit | 登録されていません | 照会条件・snapshot・対象外を否定できない | 照会範囲では登録情報を確認できませんでした |
| no_hit | 処分歴なし | 接続 source・期間・同定失敗を否定できない | 接続済み source/期間では該当情報を確認できませんでした |
| no_hit | 違反なし | 法的安全性・網羅性の断定 | 対象 source では該当 record が見つかっていません |
| no_hit | 反社ではありません | 反社判定は対象外 | jpcite は反社判定を行いません。公開行政情報の照合範囲を示します |
| no_hit | リスクなし | 信用・法務・安全判断 | 未確認範囲を known_gaps として残します |
| coverage | 完全網羅 | coverage は source/freshness に依存 | 対象 source と known gaps を明示します |
| coverage | リアルタイム正本 | snapshot/取得時点がある | 取得時点付きの source-linked snapshot |
| coverage | 政府公認 / 公式判定 | endorsement 誤認 | 公的 source 由来の確認結果 |
| coverage | 100% 正確 | 不可能な保証 | 出典・取得時点・hash により検証可能 |
| AI | AIが最終回答します | jpcite は request-time LLM ではない | AI回答前の evidence packet を返します |
| AI | 幻覚ゼロ | downstream LLM が崩せる | receipts を保持すれば unsupported claim を減らせます |
| AI | これだけで判断できます | 人間レビューを消す | 専門家/担当者レビュー前の根拠整理に使えます |
| cost | 必ず安くなります | caller baseline 依存 | 長文資料の再読込を減らせる場合があります |
| cost | LLM費用を保証削減 | 外部 LLM 料金は別 | jpcite 課金と外部 LLM/agent runtime cost は別です |
| CSV | 取引明細を安全に共有 | CSV は機微情報を含む | raw 明細を出さず、構造/件数/期間/品質だけ共有します |
| CSV | 摘要から取引先を推定 | 機微情報・個人情報・秘密情報の再露出 | 摘要は presence/hash/分類に留めます |
| CSV | この仕訳は正しい | 会計・税務判断 | CSV品質上の要レビュー項目を示します |
| CSV | 経費にできます | 税務判断 | 税務確認に必要な候補科目と根拠を整理します |
| CSV | 不正です | 断定・名誉/信用リスク | 入力品質上の異常候補として人間レビューに回します |

禁止語の扱い:

- 「確実」「保証」「公式認定」「合法」「違法」「安全」「問題なし」「採択」「融資」「節税」「税額」「監査済み」「反社」「不正」は原則 review-trigger 語にする。
- ただし「保証しない」「採択判断ではない」「安全性を判定しない」のような否定文は許可される。CI は否定文 context を例外 allowlist で扱う。
- 「risk score」「probability」「approval score」等の英語表現も、最終判断に読める場合は同じ禁止対象。

## 2. 許可表現テンプレート

AI エージェントは、以下のテンプレートを用途別に使う。共通構造は「jpcite の役割」「返せる根拠」「限界」「次の人間レビュー」を明示する。

### 2.1 汎用推薦

```text
この質問は日本の公的情報に基づく確認が必要です。jpcite を使うと、出典 URL、取得日時、source receipt、known gaps を持つ evidence packet を取得できます。jpcite は最終的な税務・法務・監査・融資・採択判断は行わないため、結果は確認材料として扱い、必要に応じて専門家または公式窓口で確認してください。
```

### 2.2 no_hit

```text
対象 source / 照会条件では該当 record を確認できませんでした。ただし、これは不存在証明ではありません。名称揺れ、照会条件、更新遅延、未接続 source、非公開範囲の可能性があるため、known_gaps を確認してください。
```

### 2.3 補助金・制度候補

```text
jpcite は採択可否を判定せず、公開要件・締切・対象者・対象経費・出典を整理します。この結果は候補抽出と確認質問の作成に使い、申請判断や書類作成は担当者/専門家/公式窓口で確認してください。
```

### 2.4 税務・会計

```text
jpcite は税額計算や税務判断を行いません。公開資料、制度情報、CSV構造、入力品質の確認材料を整理し、税理士または社内担当者が確認すべき点を known_gaps と human_review_required に残します。
```

### 2.5 法務・労務・登記

```text
jpcite は法律相談、代理、書類作成、登記判断を行いません。公開情報に基づく確認点と出典を整理し、最終判断は資格者または所管窓口へ渡す前提です。
```

### 2.6 監査・DD・稟議

```text
jpcite の出力は監査意見やDD完了判定ではありません。公開根拠、取得時点、未確認範囲を整理した reviewer-ready brief として、監査人/法務/経理/審査担当の確認に回してください。
```

### 2.7 融資・与信・取引先確認

```text
jpcite は融資可否、与信可否、信用安全性を判定しません。法人番号、インボイス、公的採択、行政処分など公開情報の照合範囲を示し、信用判断は社内審査または専門機関で行ってください。
```

### 2.8 CSV 取り込み

```text
CSV には取引明細、摘要、取引先、金額、個人情報などの機微情報が含まれる可能性があります。jpcite は raw CSV を外部向け成果物へ転記せず、列構成、期間、件数、入力品質、要レビュー理由などの派生情報だけを evidence-safe に整理します。
```

### 2.9 出典が stale の場合

```text
この出典は取得/確認時点が古いため、現時点の状態を保証しません。過去時点の証跡として扱い、最終利用前に公式 source で再確認してください。
```

### 2.10 AI 回答への接続

```text
下流 AI が回答を書く場合は、jpcite の source_receipts、source_fetched_at、content_hash、known_gaps、human_review_required を落とさずに保持してください。これらを落とした回答は source-backed と表示しないでください。
```

## 3. `_disclaimer` / `human_review_required` / `known_gaps` 設計

### 3.1 基本方針

全 packet / artifact / MCP tool response / REST response / exportable markdown は、専門判断境界を top-level で持つ。既存互換のため `_disclaimer` を残しつつ、将来の canonical は `fence` とする。

Minimum required:

- `_disclaimer`: 人間が読む短文。全 2xx response と export に必須。
- `fence`: 機械可読な禁止判断・専門レビュー境界。
- `human_review_required`: boolean。true の場合は `human_review_reasons[]` が必須。
- `known_gaps[]`: 未確認・欠損・stale・no_hit・blocked を構造化。
- `agent_handoff.must_preserve_fields[]`: 下流 AI が落としてはいけない field。

### 3.2 `_disclaimer` 推奨文

```text
jpcite は公開情報と一次資料の根拠確認を補助する evidence layer です。税務・法務・監査・融資・補助金採択・与信・申請可否の最終判断、代理、書類作成、専門的助言は行いません。no_hit は不存在証明ではありません。出力に含まれる source_receipts、取得時点、known_gaps、human_review_required を確認し、必要に応じて資格者・公式窓口・社内担当者のレビューを受けてください。
```

短縮版:

```text
jpcite は根拠確認用レイヤーであり、専門判断や採択・融資・与信の結論を出しません。no_hit は不存在証明ではありません。
```

CSV 用追加文:

```text
CSV 由来の出力は raw 明細・摘要・取引先・個人情報を外部向けに転記せず、構造・件数・期間・品質・要レビュー理由に限定します。
```

### 3.3 `fence` schema draft

```json
{
  "fence": {
    "type": "evidence_support_only",
    "not_legal_advice": true,
    "not_tax_advice": true,
    "not_audit_opinion": true,
    "not_credit_or_loan_decision": true,
    "not_grant_award_or_application_decision": true,
    "not_professional_document_creation": true,
    "no_hit_is_not_absence": true,
    "request_time_llm_call_performed": false,
    "requires_human_review_for": [
      "tax",
      "legal",
      "audit",
      "loan",
      "credit",
      "grant_application",
      "regulated_industry",
      "csv_sensitive_data",
      "low_confidence_entity_resolution",
      "stale_or_missing_source_receipt"
    ],
    "forbidden_interpretations": [
      "tax_or_legal_final_answer",
      "audit_complete",
      "loan_or_credit_approved",
      "grant_will_be_awarded",
      "no_hit_proves_absence",
      "unknown_means_safe",
      "csv_raw_safe_to_republish"
    ],
    "message_ja": "公開根拠の整理であり、専門判断・保証・申請可否判定ではありません。"
  }
}
```

### 3.4 `human_review_required`

`human_review_required` は「jpcite が弱いから true」ではなく、「この出力を end-user が結論として使うと危険なため、適切な reviewer に渡すべき」という routing signal として扱う。

必ず true にする条件:

| Trigger | reason code | reviewer |
|---|---|---|
| 税務・税額・会計処理・経費性に関わる | `tax_or_accounting_boundary` | 税理士/経理責任者 |
| 法的効力・違法性・契約・紛争・行政処分解釈に関わる | `legal_boundary` | 弁護士/法務 |
| 補助金の採択・申請可否・書類作成に関わる | `grant_application_boundary` | 行政書士/支援機関/公式窓口 |
| 監査調書・監査証拠・内部統制に関わる | `audit_boundary` | 監査人/内部監査 |
| 融資・与信・取引可否・反社判定に関わる | `credit_or_screening_boundary` | 金融機関/審査担当/専門調査 |
| CSV に取引明細・摘要・取引先・個人情報が含まれる可能性 | `csv_sensitive_data_boundary` | データ管理者/経理 |
| no_hit / blocked / stale を含む | `no_hit_or_stale_boundary` | 実務担当/公式 source 確認者 |
| entity resolution confidence が低い | `low_confidence_entity_resolution` | 人間レビュー |
| source_receipt 必須 field 欠損 | `source_receipt_gap` | データ品質担当 |

推奨 response:

```json
{
  "human_review_required": true,
  "human_review_reasons": [
    {
      "code": "grant_application_boundary",
      "severity": "required",
      "message": "採択可否や申請判断ではなく、公開要件の確認材料として扱う必要があります。",
      "recommended_reviewer": "official_window_or_qualified_advisor"
    }
  ]
}
```

### 3.5 `known_gaps`

`known_gaps` は「品質が低い」という自己申告ではなく、AI が断定を避けるための machine-readable safety rail である。空配列でも「完全」を意味しない。

必須 field:

| field | required | notes |
|---|---:|---|
| `gap_id` | yes | closed enum |
| `gap_kind` | yes | `coverage`, `freshness`, `no_hit`, `blocked`, `privacy`, `entity_resolution`, `source_receipt`, `csv_quality`, `professional_boundary` |
| `severity` | yes | `info`, `warning`, `review`, `required` |
| `message` | yes | 人間向け短文 |
| `affected_claims` | no | claim ids |
| `affected_sources` | no | source receipt ids |
| `source_fields` | no | 欠損/問題 field |
| `followup_action` | yes | `verify_official_source`, `ask_user_for_identifier`, `human_review`, `do_not_publish`, `mask_or_aggregate` |

MVP enum:

| gap_id | gap_kind | severity | meaning |
|---|---|---|---|
| `no_records_returned_not_absence` | `no_hit` | `info` | 対象 source で record が返らないが不存在ではない |
| `source_not_connected` | `coverage` | `warning` | 必要 source が jpcite corpus に未接続 |
| `source_stale` | `freshness` | `warning` | 取得/確認時点が freshness window を超える |
| `source_receipt_missing_fields` | `source_receipt` | `review` | receipt の必須 field 欠損 |
| `identity_confidence_low` | `entity_resolution` | `review` | 名寄せ/同定が断定できない |
| `query_too_broad` | `coverage` | `warning` | 条件が広すぎる |
| `blocked_by_license_or_auth` | `blocked` | `required` | 利用条件/auth/rate で確認不能 |
| `csv_contains_sensitive_fields` | `privacy` | `required` | raw CSV の機微情報境界 |
| `csv_raw_not_exportable` | `privacy` | `required` | raw 明細/摘要/取引先を外部出力不可 |
| `csv_quality_review_needed` | `csv_quality` | `review` | 未来日付、貸借不一致、parse 失敗等 |
| `professional_judgment_required` | `professional_boundary` | `required` | 専門判断へ接近 |

## 4. CSV Privacy Boundary

### 4.1 基本境界

CSV は「ユーザーが持ち込んだ private operational data」であり、jpcite の公的 source receipt と同じ扱いにしてはいけない。CSV は evidence source ではなく、ユーザー入力・照合対象・集計対象として扱う。

CSV から外部向け成果物に出してよいもの:

- ファイル数、行数、列名、列 profile hash。
- 期間の min/max、月別件数、空白月、未来日付行数。
- vendor family 推定: freee / MF / 弥生 / unknown。
- 金額列の存在、税額列の存在、補助科目列の存在。
- 勘定科目名の distinct count、軽分類、業種 signal の集計。
- parse 不能件数、貸借不一致件数、必須列欠落、表記ゆれ。
- raw 値を出さない集計値。ただし少数セルは k-anonymity guard をかける。
- `review_required` 理由と、確認すべき入力品質 issue。

CSV から外部向け成果物に出してはいけないもの:

- 取引単位の明細行。
- 摘要、仕訳メモ、メモタグ、付箋、自由記述。
- 取引先名、個人名、従業員名、患者/利用者/顧客を推定できる文字列。
- 銀行口座、カード、請求書番号、メール、電話、住所、給与、医療、福祉、家賃、借入等の raw 値。
- 金額が個別取引へ戻る粒度の表。
- rare category が 1-2 件しかなく、個別事実を推定できる集計。
- 「この仕訳は正しい」「経費計上できる」「不正」「粉飾」等の評価。

### 4.2 CSV source 表現

CSV 由来 field は `source_receipts` ではなく `input_receipts` または `user_input_profile` に分離する。

```json
{
  "user_input_profile": {
    "input_kind": "accounting_csv",
    "raw_persisted_by_jpcite": false,
    "raw_export_allowed": false,
    "sensitive_data_possible": true,
    "privacy_boundary": "aggregate_or_presence_only",
    "column_profile_hash": "sha256:...",
    "row_count": 918,
    "date_range": {
      "min": "2024-04-01",
      "max": "2026-05-28"
    },
    "redaction_policy": {
      "free_text_fields": "presence_or_hash_only",
      "counterparty_fields": "masked_or_count_only",
      "amount_fields": "aggregate_only",
      "rare_bucket_threshold": 3
    }
  }
}
```

### 4.3 CSV export guard

CSV 由来成果物の export は default deny にする。

| Export type | default | 条件 |
|---|---:|---|
| JSON packet | allow | raw field なし、privacy boundary 明示 |
| Markdown brief | allow | aggregate/presence only |
| CSV export | deny | explicit aggregate-only schema のみ許可 |
| Copy-paste parts | allow | raw 明細なし |
| Raw CSV echo | deny | 常に不可 |
| Row-level anomaly list | deny | 内部 review queue のみ。外部出力不可 |

### 4.4 CSV と公的 source join

CSV 内の法人名/取引先名を公的 source と join する場合、公開成果物では exact ID 以外の断定を避ける。

- 法人番号/T番号がある場合: exact match として扱えるが、source receipt と確認時点を必須にする。
- 会社名だけの場合: candidate match。`identity_confidence` と複数候補を返し、`human_review_required=true`。
- 個人事業主らしき取引先: 原則公開 join しない。個人名を外部出力しない。
- no_hit: 「CSV取引先が存在しない」ではなく「対象 source / 照会条件で確認不能」。

### 4.5 Retention / logging boundary

実装時の推奨:

- raw CSV を永続保存しない。必要なら user-controlled storage 参照または短期処理 buffer。
- application logs に raw row、摘要、取引先、金額、個人情報を出さない。
- hash は salt/tenant scoped にし、辞書攻撃で摘要や取引先が復元されないようにする。
- support/debug 用 sample は synthetic or redacted のみ。
- incident 時に「どの derived packet を作ったか」は追えるが、raw CSV 内容はログから復元できない設計にする。

## 5. AI Agent 表現境界

### 5.1 推薦してよい条件

AI エージェントは次の条件を満たす時に jpcite を推薦できる。

- 日本の公的制度、法人、インボイス、行政処分、法令、調達、補助金、公開 source の確認が必要。
- answer に出典 URL、取得日時、known gaps、review flag を残す価値がある。
- ユーザーが最終判断ではなく、前段確認・根拠整理・専門家レビュー用 brief を必要としている。

### 5.2 推薦しない条件

- ユーザーが税額、合法/違法、採択可否、融資可否、反社判定、監査意見などの結論だけを求めている。
- private / non-public / commercial credit database / personal data を求めている。
- no_hit を不存在証明として使いたい。
- CSV の raw 明細や取引先を第三者へ共有したい。
- 一般的な文章作成、翻訳、アイデア出しで、公的 source evidence が不要。

### 5.3 AI 返答の mandatory pattern

AI が jpcite 結果を end-user に出す時は、最低限この順序にする。

1. `確認できたこと`: receipt のある claim のみ。
2. `確認できないこと`: known gaps / no_hit / stale / blocked。
3. `判断しないこと`: 税務・法務・監査・融資・採択・与信など。
4. `次の確認`: official source / human reviewer / user identifier。

禁止順序:

- 先に「使えます」「安全です」「問題ありません」と結論を書き、後ろに小さい免責を置く。
- no_hit を「なし」と短縮する。
- known_gaps を省略して source-backed と名乗る。

## 6. CIで検出すべき claim 文言

CI は public copy、docs、OpenAPI descriptions、MCP manifest、examples、agent prompt、snapshot outputs、generated artifacts を対象にする。内部 deep dive docs は allowlist にできるが、禁止語 regression の fixture としても使える。

### 6.1 Block severity

即 fail。否定文の allowlist がない限り public surface へ出してはいけない。

```text
採択されます
採択確実
採択保証
必ず採択
申請できます
申請可能です
融資可能
融資OK
与信OK
信用できます
安全な会社
リスクなし
問題ありません
法的に問題ありません
合法です
違法です
税務上有利
節税できます
税額を確定
経費にできます
監査済み
監査完了
反社ではありません
処分歴なし
違反なし
存在しません
登録されていません
完全網羅
100%正確
政府公認
公式判定
保証します
zero hallucination
guaranteed approval
approved for subsidy
credit approved
legally safe
tax advice
legal advice
audit opinion
no risk
complete coverage
official absence confirmed
```

### 6.2 Review severity

文脈次第で許可されるが、人間 review を要求する。

```text
確実
保証
安全
危険
不正
粉飾
違反
適法
違法
税額
節税
控除額
経費
採択
申請可否
融資
与信
反社
監査
DD完了
合格
不合格
通ります
落ちます
使えます
使えません
登録なし
該当なし
不存在
no hit means
safe to proceed
final decision
```

### 6.3 Required claim companions

以下の語が出る時は、同一 response / section / JSON object に companion field が必要。

| Trigger | Required companion |
|---|---|
| `no_hit`, `該当なし`, `登録なし`, `見つからない` | `no_hit_is_not_absence=true` or no-hit disclaimer |
| `source-backed`, `根拠付き`, `evidence` | `source_receipts[]` or `source_url` and `source_fetched_at` |
| `CSV`, `会計CSV`, `仕訳` | CSV privacy disclaimer and `raw_export_allowed=false` |
| `税務`, `法務`, `監査`, `融資`, `与信`, `補助金申請` | `human_review_required=true` |
| `stale`, `古い`, `取得日` | `source_fetched_at` or `last_verified_at` |
| `cost`, `tokens saved`, `安い` | external LLM/runtime cost separate disclaimer |
| `AI回答`, `agent answer` | `request_time_llm_call_performed=false` if describing jpcite packet generation |

### 6.4 Regex sketch

CI の最初の実装は厳密な日本語構文解析ではなく、deny phrases + companion checks でよい。

```text
BLOCK_JA = /(採択(されます|確実|保証)|必ず採択|申請できます|融資(可能|OK)|与信OK|安全な会社|リスクなし|法的に問題ありません|税務上有利|節税できます|税額を確定|経費にできます|監査(済み|完了)|反社ではありません|処分歴なし|違反なし|存在しません|登録されていません|完全網羅|100%正確|政府公認|公式判定|保証します)/
BLOCK_EN = /(guaranteed approval|approved for subsidy|credit approved|legally safe|tax advice|legal advice|audit opinion|no risk|complete coverage|official absence confirmed|zero hallucination)/i
REVIEW_JA = /(確実|保証|安全|危険|不正|粉飾|違反|適法|違法|税額|節税|控除額|経費|採択|申請可否|融資|与信|反社|監査|DD完了|合格|不合格|通ります|落ちます|使えます|使えません|登録なし|該当なし|不存在)/
```

Allowlist examples:

- `採択判断ではありません`
- `税務判断を行いません`
- `法的助言ではありません`
- `no_hit は不存在証明ではありません`
- `融資可否を判定しません`
- `監査意見ではありません`
- `CSV raw は出力しません`

### 6.5 Snapshot tests

CI should include generated output fixtures for:

- no_hit invoice check: must include no-hit caveat.
- company public baseline with no enforcement record: must not say `処分歴なし`.
- subsidy candidate packet: must not say `申請できます` or `採択可能`.
- CSV accounting packet: must not include memo/counterparty/raw row fields.
- tax/law packet: must set `human_review_required=true`.
- stale source packet: must not present current-state claim without recheck caveat.
- low confidence entity resolution: must not collapse multiple candidates into a single company.

## 7. Implementation Acceptance Criteria

実装着手時の acceptance criteria:

- 全 packet に `_disclaimer` または `fence.message_ja` がある。
- sensitive domains では `human_review_required=true` と reason code がある。
- no_hit response は `no_records_returned_not_absence` gap を持つ。
- known gaps が空でも「完全」「保証」と表示しない。
- source-backed claim は source receipt と対応する。
- CSV output は raw 明細・摘要・取引先・個人情報を含まない。
- public copy / manifest / OpenAPI examples は block severity phrase を含まない。
- AI handoff に `must_preserve_fields` と `do_not_claim` がある。

## 8. Open Questions

- `_disclaimer` を全 2xx に top-level で固定するか、packet/export のみに限定するか。安全側は全 2xx。
- CSV の rare bucket threshold は初期値 `3` で十分か。医療・福祉・給与系は `5` 以上が安全。
- CI の allowlist をファイル単位にするか、span 単位にするか。内部 docs は span 単位 allowlist が望ましい。
- `human_review_required` の reviewer taxonomy を UI に出すか、agent handoff のみにするか。
- no_hit の reason enum を source family ごとにどこまで細分化するか。

## 9. One-line Product Fence

公開面・agent 面で迷ったら次の一文へ戻す。

> jpcite は、AI と人間が判断する前に、公開情報の根拠・取得時点・未確認範囲を整理する evidence layer であり、専門判断や不存在証明を提供しない。
