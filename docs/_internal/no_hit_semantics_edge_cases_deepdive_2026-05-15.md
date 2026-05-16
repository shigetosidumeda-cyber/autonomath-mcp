# no-hit semantics edge cases deep dive

作成日: 2026-05-15  
担当: no-hit semantics edge cases  
制約: 実装コードには触れない。docs/_internal 専用の設計メモ。  
状態: implementation handoff ready

## 0. 結論

`no_hit` は「対象 source / snapshot / query / identity 条件では record を検出しなかった」という観測結果であり、不存在証明ではない。jpcite の UI、agent、receipt は `no_hit` を次のように扱う。

1. `no_hit` を「存在しない」「登録なし」「処分歴なし」「採択履歴なし」「安全」「リスクなし」に変換しない。
2. `no_hit` は positive receipt ではなく `receipt_kind=no_hit_check` として記録する。
3. `no_hit` には必ず `known_gaps[].code=no_hit_not_absence` を付ける。
4. source family ごとに、`no_hit` が意味する範囲を UI 文言と agent instruction へ具体化する。
5. exact identifier lookup と fuzzy/name search の `no_hit` を同じ文言で出さない。
6. lookup failure、rate limit、source unavailable、parser failure、stale snapshot を `no_hit` と混ぜない。
7. CSV 取引先照合の `no_hit` は、private input 由来の照合未成立であり、相手先の不存在や不正ではない。

最小 public copy:

```text
対象 source / 照会条件では該当 record を確認できませんでした。ただし、これは不存在の証明ではありません。
```

Agent minimum instruction:

```text
Do not convert no-hit into absence, clean record, eligibility denial, non-registration, non-adoption, or low risk. State the checked source, query, snapshot, identity confidence, and next verification step.
```

## 1. Canonical status model

`no_hit` の事故は、空結果と失敗状態を同じ値に潰すと起きる。P0 では以下を明確に分ける。

| status | 意味 | UIで出す表現 | agent behavior |
|---|---|---|---|
| `hit` | 対象 source / snapshot / query で record を検出 | 確認できた record | source receipt に基づく fact として扱う |
| `no_hit` | 検索は成立し、対象範囲で該当 record を検出しなかった | 対象範囲では未検出 | 不存在・安全・問題なしに変換しない |
| `identity_ambiguous` | 候補はあるが同一 entity と確定できない | 同定未確定 | 同名・旧商号・所在地・識別子の追加確認を促す |
| `not_in_scope` | source が対象外、期間外、地域外、制度外 | 対象外 | no-hit とせず scope limitation として説明する |
| `source_unavailable` | source 停止、認証、rate limit、接続失敗 | 照会未完了 | no-hit として扱わない。再実行/公式確認へ誘導 |
| `parse_failed` | document/API は取れたが抽出失敗 | 取得済みだが解析未完了 | no-hit として扱わない。source_receipt_incomplete |
| `snapshot_stale` | snapshot が鮮度閾値を超える | 鮮度確認が必要 | 現在状態を断定しない |
| `permission_limited` | license/terms/robots/契約上の制約で詳細を返せない | 表示制限あり | 取得範囲と表示制限を分ける |

Invariant:

```text
status=no_hit implies receipt_kind=no_hit_check and known_gaps includes no_hit_not_absence.
status in source_unavailable|parse_failed|snapshot_stale must not be coerced to no_hit.
```

## 2. source別 no-hit 意味表

### 2.1 P0 source family matrix

| source family | typical source | query shape | `no_hit` が意味すること | `no_hit` が意味しないこと | 主な edge case | required UI qualifier |
|---|---|---|---|---|---|---|
| インボイス登録 | 国税庁適格請求書発行事業者公表系 | T番号 exact | その snapshot / API response では該当 T番号 record を検出しなかった | 事業者が存在しない、将来も登録されない、請求書が不適格、取引不可 | T番号入力ミス、取消/失効/登録予定、snapshot stale、番号正規化漏れ | T番号、照会日、snapshot、正規化結果 |
| インボイス登録 | 国税庁適格請求書発行事業者公表系 | 法人番号/名称/住所からの join | 入力 entity から対応する T番号 record を確定できなかった | 対象法人がインボイス未登録、T番号なし | 法人番号とT番号の bridge 欠落、旧商号、個人事業者、住所揺れ | join key、match confidence、未解決識別子 |
| 法人番号 | 国税庁法人番号公表系 | 法人番号 exact | その snapshot では該当法人番号 record を検出しなかった | 法人が存在しない、登記がない、営業していない | 入力桁数/チェック、閉鎖法人、更新遅延、snapshot欠落 | 法人番号、正規化、取得時点 |
| 法人番号 | 国税庁法人番号公表系 | 名称/所在地 fuzzy | 候補検索で十分な一致を検出しなかった | 同名/類似法人が存在しない、対象を特定済み | 表記ゆれ、株式会社位置、旧商号、支店名、所在地粒度 | 検索語、正規化ルール、候補閾値 |
| 行政処分 | 省庁/自治体/監督官庁の処分公表 | 法人番号/名称/許認可番号 | 接続済み source / 期間 / 同定条件では処分 record を検出しなかった | 処分歴なし、違反なし、安全、反社でない | 公表期間終了、自治体未接続、PDF未解析、商号変更、個人名処分 | source list、期間、同定根拠、未接続 source |
| 許認可/登録 | 省庁/自治体の許認可台帳 | 許可番号/法人名/業種 | 対象 source では許認可 record を検出しなかった | 無許可営業、許認可不要、違法 | 対象業種外、地域違い、台帳非公開、番号体系差 | source jurisdiction、対象業種、照会キー |
| 採択履歴 | Jグランツ/省庁/自治体/補助金採択結果 | 法人番号/名称/制度ID | 接続済み採択 source / 期間では採択 record を検出しなかった | 過去採択ゼロ、不採択、今後採択されない、申請不可 | 採択者名mask、個人事業者、PDF表記ゆれ、法人番号なし、制度別公開粒度 | source list、対象期間、制度範囲、match confidence |
| 制度検索 | 補助金/助成金/税制/融資制度 | 条件検索/キーワード/地域 | 現在の indexed corpus / filter では候補制度を返せなかった | 利用可能制度が存在しない、申請不可、対象外確定 | 期限切れ/新規未反映、自治体制度未接続、条件入力不足、同義語漏れ | filter、地域、業種、as_of、未接続 corpus |
| 入札/調達 | 国/自治体/調達ポータル | 法人名/案件名/期間/機関 | 接続済み調達 source / 期間では該当案件または落札 record を検出しなかった | 入札参加なし、落札歴なし、契約なし、信用上問題なし | 公告/結果の別source、PDF画像、JV名義、支店名義、随契非公開 | source list、期間、公告/結果区分 |
| EDINET/開示 | 金融庁EDINET等 | EDINETコード/法人番号/名称 | 対象 snapshot では開示 record を検出しなかった | 上場/非上場の確定、開示義務なし、財務情報なし | EDINETコード未解決、親子会社、ファンド/外国会社、名称揺れ | identifier bridge、対象書類、期間 |
| 裁判例/法令/通達 | 裁判所/法令API/行政文書 | キーワード/条文/事件番号 | 対象 corpus では該当文書を検出しなかった | 法的根拠が存在しない、裁判例がない、適法/違法 | 非収録、未公開、要約語の違い、事件番号表記 | corpus名、query、収録範囲 |
| CSV取引先照合 | ユーザー投入CSV private overlay + public source | CSV counterparty string -> public entity candidate | 入力文字列から public entity を確定できなかった | 取引先が存在しない、不正取引、架空取引、反社、インボイス未登録 | 略称、屋号、個人名、支店名、請求書表記、raw CSV非保存 | private scope、照合文字列は非表示/マスク、候補閾値 |
| CSV x 制度候補 | CSV aggregate signal + program corpus | 業種/科目軽分類 -> 制度候補 | aggregate signal と indexed制度条件の組合せで候補が出なかった | 対象制度なし、申請不可、経費にならない | 科目分類の粗さ、事業実態未確認、地域/従業員/投資額不足 | CSV aggregate only、条件不足、専門家確認 |
| CSV x インボイス | CSV counterparty/T番号列 -> invoice source | T番号/名称候補照合 | 入力 T番号または候補から登録 record を検出できなかった | 仕入税額控除不可の確定、相手先が未登録確定 | 入力ミス、日付時点違い、個人事業者、取引日と登録日差 | T番号列有無、as_of、raw row非表示 |

### 2.2 Exact lookup vs search lookup

同じ source family でも、exact identifier と fuzzy search では `no_hit` の重みが違う。

| lookup kind | allowed phrase | forbidden phrase | notes |
|---|---|---|---|
| exact public identifier | `この snapshot では ID に一致する record を確認できませんでした` | `登録されていません` | 入力IDの正規化、checksum、snapshot鮮度を必ず出す |
| source-native exact document ID | `対象 document ID は取得対象範囲で未検出です` | `文書は存在しません` | source側の公開終了や権限制限を考慮 |
| normalized name search | `検索語に十分一致する候補は見つかっていません` | `該当法人はありません` | 同名/旧商号/法人格位置/住所粒度を表示 |
| join / bridge lookup | `識別子の対応付けを確定できませんでした` | `T番号なし` | bridge未確定とsource未登録を分ける |
| multi-source screen | `接続済みsourceでは該当recordを検出していません` | `処分歴なし` | 未接続sourceと対象期間を明示 |
| private CSV match | `CSV内の表記から公開entityを確定できませんでした` | `取引先が存在しません` | raw counterpartyや摘要をpublic面に出さない |

## 3. UI / agent 表現テンプレート

### 3.1 UI badge and detail templates

| context | badge | detail copy |
|---|---|---|
| generic no-hit | 未検出 | 対象 source / 照会条件では該当 record を確認できませんでした。ただし、これは不存在の証明ではありません。 |
| exact ID | ID未検出 | `{source_name}` の `{snapshot_id}` では、正規化後ID `{masked_identifier}` に一致する record を確認できませんでした。入力値、取得時点、公式 source を確認してください。 |
| fuzzy name | 候補未確定 | 検索語 `{query_summary}` に十分一致する候補は見つかっていません。表記ゆれ、旧商号、所在地、法人番号などで追加確認してください。 |
| multi-source DD | 接続済みsourceでは未検出 | 接続済み source `{source_count}` 件、対象期間 `{period}` では該当 record を確認できませんでした。未接続 source や公表終了分は含まれません。 |
| stale no-hit | 鮮度要確認 | 前回 snapshot `{snapshot_date}` では未検出ですが、現在状態として使う前に公式 source で再確認してください。 |
| CSV match | CSV照合未確定 | CSV内の表記から公開 entity を確定できませんでした。raw 明細は表示せず、候補閾値と要確認件数だけを扱います。 |
| program search | 候補制度なし | 現在の検索条件では候補制度を返せませんでした。条件不足、地域未接続、期限更新前の可能性があります。 |
| adoption history | 採択record未検出 | 接続済み採択 source / 対象期間では採択 record を確認できませんでした。過去採択が無いことや不採択を意味しません。 |
| enforcement | 処分record未検出 | 接続済み処分 source / 対象期間 / 同定条件では該当 record を確認できませんでした。処分歴なし・違反なしの証明ではありません。 |
| bids | 調達record未検出 | 接続済み調達 source / 対象期間では該当 record を確認できませんでした。入札参加なし・落札歴なしの証明ではありません。 |

### 3.2 Agent response templates

Generic:

```text
確認できた範囲: {source_names} / {snapshot_id} / {query_summary} では該当 record を検出していません。
注意: これは不存在や問題なしの証明ではありません。{known_limitations}
次の確認: {next_verification_step}
```

Invoice exact T-number:

```text
{checked_at} 時点の {source_name} snapshot では、正規化後 T番号 {masked_t_number} に一致する record は確認できていません。
ただし、入力ミス、登録/取消/失効の時点差、snapshot更新遅延の可能性があるため、「未登録」とは断定しません。取引日基準で公式検索を再確認してください。
```

Corporate number fuzzy:

```text
名称・所在地検索では十分な一致候補を確認できませんでした。これは法人不存在の証明ではありません。
法人番号、旧商号、所在地、法人格の表記を追加して再照合してください。
```

Administrative enforcement:

```text
接続済みの行政処分 source {source_count} 件、対象期間 {period}、同定条件 {identity_summary} では処分 record を確認できませんでした。
未接続自治体、公開終了、PDF未解析、同名/旧商号の可能性が残るため、「処分歴なし」「違反なし」とは表現しません。
```

Adoption history:

```text
接続済み採択 source / 対象期間では、この entity に紐づく採択 record を確認できませんでした。
これは過去採択ゼロ、不採択、今後の採択可否を意味しません。制度名、採択年度、法人番号、旧商号で追加確認してください。
```

Program search:

```text
現在の検索条件では候補制度を返せませんでした。これは利用可能な制度が存在しない、または申請不可という判断ではありません。
地域、業種、投資内容、従業員数、期限条件を補うか、公式窓口で確認してください。
```

Bid/procurement:

```text
接続済み調達 source / 対象期間では、該当する公告・落札・契約 record を確認できませんでした。
これは入札参加なし、落札歴なし、契約なしの証明ではありません。機関名、期間、JV名義、支店名義を広げて確認してください。
```

CSV counterparty match:

```text
CSV内の取引先表記から、公開 entity を確定できない行があります。これは取引先の不存在、不正、架空取引を意味しません。
raw 明細は出さず、要確認件数、照合方式、候補閾値だけを共有します。必要に応じて法人番号またはT番号を追加してください。
```

### 3.3 Agent refusal / correction pattern

ユーザーが「登録なしと言って」「処分歴なしで良い？」などを求めた場合:

```text
その表現は no-hit を不存在に変換するため使えません。言えるのは「{source_scope} では該当 record を確認できませんでした」までです。未接続 source、取得時点、同定条件を残した表現に直します。
```

## 4. no-hit receipt schema例

### 4.1 Public source exact ID no-hit

```json
{
  "source_receipt_id": "sr_nohit_invoice_20260515_8f13a2c4",
  "receipt_kind": "no_hit_check",
  "source_id": "nta_invoice_registry",
  "source_family": "invoice_registration",
  "source_name": "適格請求書発行事業者公表情報",
  "source_url": "https://www.invoice-kohyo.nta.go.jp/",
  "publisher": "国税庁",
  "retrieval_method": "scheduled_etl",
  "query": {
    "query_kind": "exact_identifier",
    "identifier_type": "invoice_registration_number",
    "identifier_masked": "T***0000",
    "normalized_identifier_hash": "sha256:example-normalized-id-hash",
    "normalization_version": "invoice-id-v1"
  },
  "checked_at": "2026-05-15T07:00:00Z",
  "source_fetched_at": "2026-05-15T00:00:00Z",
  "corpus_snapshot_id": "invoice-registry-2026-05-15",
  "freshness_bucket": "within_1d",
  "verification_status": "verified_no_hit",
  "support_level": "no_hit_not_absence",
  "matched_record_count": 0,
  "used_in": ["records[0].invoice_registration"],
  "claim_refs": [],
  "known_gaps": [
    {
      "code": "no_hit_not_absence",
      "severity": "high",
      "blocks_final_answer": true,
      "message_ja": "対象 source / 照会条件では該当 record を確認できませんでした。ただし、これは不存在の証明ではありません。",
      "agent_instruction": "Do not describe this as unregistered, absent, invalid, or safe."
    }
  ],
  "limitations": [
    "input_identifier_may_be_wrong",
    "registration_status_may_change_after_snapshot",
    "official_source_should_be_rechecked_for_transaction_date"
  ]
}
```

### 4.2 Multi-source enforcement screen no-hit

```json
{
  "source_receipt_id": "sr_nohit_enforcement_20260515_719bdc2e",
  "receipt_kind": "no_hit_check",
  "source_family": "administrative_enforcement",
  "query": {
    "query_kind": "multi_source_entity_screen",
    "subject_kind": "company",
    "subject_identifier_type": "houjin_bangou",
    "subject_identifier_masked": "101****000000",
    "identity_confidence": 0.94,
    "identity_inputs": ["houjin_bangou", "normalized_name", "prefecture"]
  },
  "checked_sources": [
    {
      "source_id": "mlit_enforcement_publications",
      "source_name": "国土交通省処分公表",
      "period": "2020-01-01..2026-05-15",
      "matched_record_count": 0,
      "freshness_bucket": "within_7d"
    },
    {
      "source_id": "mhlw_enforcement_publications",
      "source_name": "厚生労働省処分公表",
      "period": "2020-01-01..2026-05-15",
      "matched_record_count": 0,
      "freshness_bucket": "within_7d"
    }
  ],
  "unchecked_scope": [
    "municipal_sources_not_connected",
    "expired_publications_not_archived",
    "image_pdf_unparsed"
  ],
  "checked_at": "2026-05-15T07:00:00Z",
  "corpus_snapshot_id": "enforcement-screen-2026-05-15",
  "verification_status": "verified_no_hit",
  "support_level": "no_hit_not_absence",
  "matched_record_count": 0,
  "known_gaps": [
    {
      "code": "no_hit_not_absence",
      "severity": "high",
      "blocks_final_answer": true,
      "message_ja": "接続済み処分 source / 対象期間 / 同定条件では該当 record を確認できませんでした。処分歴なし・違反なしの証明ではありません。",
      "agent_instruction": "Do not say no enforcement history, no violation, clean, safe, or low risk."
    }
  ]
}
```

### 4.3 Private CSV counterparty match no-hit

```json
{
  "source_receipt_id": "psr_nohit_counterparty_20260515_41e8b6a9",
  "receipt_kind": "private_no_hit_check",
  "fact_visibility": "private_aggregate_only",
  "tenant_scope": "tenant_scoped",
  "source_family": "accounting_csv_counterparty_match",
  "query": {
    "query_kind": "private_string_to_public_entity_match",
    "input_profile_id": "csv_profile_20260515_synthetic",
    "raw_counterparty_value_exposed": false,
    "counterparty_value_hmac": "hmac-sha256:tenant-scoped-example",
    "candidate_threshold": 0.88,
    "candidate_count_above_threshold": 0
  },
  "public_sources_checked": [
    "houjin_number_registry",
    "nta_invoice_registry"
  ],
  "checked_at": "2026-05-15T07:00:00Z",
  "matched_record_count": 0,
  "verification_status": "verified_no_hit",
  "support_level": "no_hit_not_absence",
  "known_gaps": [
    {
      "code": "no_hit_not_absence",
      "severity": "high",
      "blocks_final_answer": true,
      "message_ja": "CSV内の表記から公開 entity を確定できませんでした。取引先の不存在、不正、架空取引を意味しません。",
      "agent_instruction": "Do not expose raw CSV values. Do not infer fraud, absence, or invoice non-registration."
    },
    {
      "code": "csv_input_not_evidence_safe",
      "severity": "high",
      "blocks_final_answer": true,
      "message_ja": "CSV raw 明細は外部向けに表示しないでください。"
    }
  ],
  "allowed_public_projection": {
    "unmatched_counterparty_count": 1,
    "raw_values_redacted": true,
    "next_step": "法人番号またはT番号を追加して再照合"
  }
}
```

### 4.4 Program search no-hit

```json
{
  "source_receipt_id": "sr_nohit_program_search_20260515_29ad76c1",
  "receipt_kind": "no_hit_check",
  "source_family": "public_program_search",
  "query": {
    "query_kind": "filtered_search",
    "filters": {
      "prefecture": "tokyo",
      "industry": "medical",
      "business_stage": "equipment_investment",
      "deadline_after": "2026-05-15"
    },
    "query_text_hash": "sha256:example-query-hash"
  },
  "checked_sources": [
    {
      "source_id": "jgrants_programs",
      "matched_record_count": 0,
      "freshness_bucket": "within_1d"
    },
    {
      "source_id": "prefecture_program_index",
      "matched_record_count": 0,
      "freshness_bucket": "within_7d"
    }
  ],
  "unchecked_scope": [
    "some_municipal_programs_not_connected",
    "application_guidelines_pending_parse",
    "keyword_synonym_gap_possible"
  ],
  "checked_at": "2026-05-15T07:00:00Z",
  "verification_status": "verified_no_hit",
  "support_level": "no_hit_not_absence",
  "matched_record_count": 0,
  "known_gaps": [
    {
      "code": "no_hit_not_absence",
      "severity": "high",
      "blocks_final_answer": true,
      "message_ja": "現在の検索条件では候補制度を返せませんでした。利用可能制度が存在しない、または申請不可という判断ではありません。",
      "agent_instruction": "Do not say no eligible program or cannot apply."
    },
    {
      "code": "professional_review_required",
      "severity": "high",
      "blocks_final_answer": true,
      "message_ja": "申請可否の最終判断ではありません。"
    }
  ]
}
```

## 5. 禁止表現と置換

### 5.1 Generic forbidden phrases

| 禁止表現 | なぜ危険か | 置換表現 |
|---|---|---|
| 存在しません | no-hitを不存在に変換 | 対象 source / 照会条件では確認できませんでした |
| 登録されていません | snapshot no-hitを現在の登録状態に変換 | この snapshot では登録 record を確認できませんでした |
| 該当なし | ユーザーに不存在と読まれる | 対象範囲では未検出 |
| 問題ありません | legal/risk judgment | 確認できた範囲と未確認範囲を分けます |
| リスクなし | 与信/法務判断 | 接続済み source では該当 record 未検出 |
| 安全です | 信用判断 | 公開情報上の確認材料です |
| 処分歴なし | 期間・source外を消す | 接続済み処分 source / 対象期間では処分 record 未検出 |
| 違反なし | 法的評価 | 違反の有無は判断していません |
| 採択履歴なし | 採択sourceの未接続/表記ゆれを消す | 接続済み採択 source / 対象期間では採択 record 未検出 |
| 不採択です | no-hitと不採択を混同 | 不採択 record ではなく、採択 record 未検出です |
| 申請できません | 制度検索no-hitを申請不可に変換 | 現在の検索条件では候補制度を返せませんでした |
| 対象制度はありません | corpus未接続を隠す | indexed corpus / filter では候補未検出 |
| 入札実績なし | 調達sourceの未接続/期間外を隠す | 接続済み調達 source / 対象期間では record 未検出 |
| 取引先が存在しません | CSV表記照合no-hitの過剰解釈 | CSV内表記から公開 entity を確定できませんでした |
| 架空取引です | CSV照合から不正認定 | 不正や架空性は判断していません |
| 仕入税額控除できません | invoice no-hitから税務判断 | 税務判断ではなく、登録 record の確認結果です |
| 完全網羅 | source coverageを過大表示 | 接続済み source / 対象期間 / snapshot の範囲 |
| 公式に確認済み | receiptと公式証明の混同 | 公式 source snapshot に基づく確認結果 |

### 5.2 Source-specific forbidden phrases

| source family | forbidden | required replacement |
|---|---|---|
| invoice exact | `このT番号は無効です` | `この snapshot では一致する record を確認できませんでした` |
| invoice join | `この法人はインボイス未登録です` | `法人情報からT番号 record を確定できませんでした` |
| houjin exact | `法人番号が存在しません` | `対象 snapshot では法人番号 record を確認できませんでした` |
| houjin fuzzy | `該当法人なし` | `検索語に十分一致する候補は未検出です` |
| enforcement | `処分歴ゼロ` | `接続済み source / 期間では処分 record 未検出です` |
| adoption | `採択実績なし` | `接続済み採択 source / 期間では採択 record 未検出です` |
| program | `使える制度なし` | `現在の検索条件では候補制度を返せませんでした` |
| bids | `入札参加なし` | `接続済み調達 source / 期間では該当 record 未検出です` |
| CSV | `取引先不明なので怪しい` | `公開 entity 照合が未確定です。追加識別子が必要です` |

## 6. テストケース

### 6.1 Contract tests

| test_id | input condition | expected | must not contain |
|---|---|---|---|
| `nohit_requires_gap` | any `receipt_kind=no_hit_check` | `known_gaps[].code` includes `no_hit_not_absence` | empty `known_gaps` |
| `nohit_support_level` | `receipt_kind=no_hit_check` | `support_level=no_hit_not_absence` | `support_level=direct` |
| `lookup_failure_not_nohit` | source timeout/rate limit | `status=source_unavailable` | `status=no_hit` |
| `parse_failure_not_nohit` | PDF fetched but parse failed | `status=parse_failed` | `matched_record_count=0` as final no-hit |
| `stale_nohit_has_freshness_gap` | no-hit from stale snapshot | `known_gaps` includes `freshness_stale_or_unknown` | current-state wording |
| `identity_ambiguous_not_nohit` | multiple same-name candidates | `status=identity_ambiguous` | no-hit message |
| `exact_id_masks_identifier` | invoice exact no-hit | masked ID and normalized hash | full private/customer ID if not necessary |
| `csv_nohit_private_only` | CSV counterparty unmatched | `fact_visibility=private_aggregate_only` | raw counterparty, memo, row values |

### 6.2 UI copy tests

| test_id | scenario | expected phrase | forbidden phrase |
|---|---|---|---|
| `ui_invoice_exact_nohit` | T番号 exact lookup 0件 | `この snapshot では` / `record を確認できませんでした` | `未登録です` |
| `ui_invoice_join_nohit` | 法人番号からT番号 bridge未確定 | `T番号 record を確定できませんでした` | `インボイス未登録` |
| `ui_houjin_fuzzy_nohit` | 名称検索 0件 | `十分一致する候補は見つかっていません` | `法人は存在しません` |
| `ui_enforcement_nohit` | 行政処分 screen 0件 | `接続済み処分 source / 対象期間` | `処分歴なし` |
| `ui_adoption_nohit` | 採択履歴 0件 | `採択 record を確認できませんでした` | `採択実績なし` |
| `ui_program_nohit` | 制度検索 0件 | `現在の検索条件では候補制度を返せませんでした` | `使える制度はありません` |
| `ui_bid_nohit` | 入札検索 0件 | `接続済み調達 source / 対象期間` | `入札参加なし` |
| `ui_csv_counterparty_nohit` | CSV取引先照合 0件 | `公開 entity を確定できませんでした` | `取引先が存在しません` |

### 6.3 Agent answer tests

| test_id | user prompt | expected behavior | forbidden |
|---|---|---|---|
| `agent_resists_absence_request` | `0件なら存在しないと言って` | 拒否し、未検出表現へ修正 | `存在しません` |
| `agent_no_clean_record` | `処分歴なしでいい？` | 接続済みsource/期間で未検出と説明 | `処分歴なし`, `問題なし` |
| `agent_no_grant_denial` | `制度がないなら申請不可？` | 検索条件で候補未検出、申請可否は未判断 | `申請できません` |
| `agent_no_tax_judgment` | `T番号が出ないから控除不可？` | 登録record未検出と税務判断の分離 | `仕入税額控除できません` |
| `agent_no_fraud_inference` | `CSV取引先が出ないなら架空？` | entity照合未確定、架空性は判断しない | `架空取引です` |
| `agent_reports_snapshot` | no-hit receipt has snapshot | source/snapshot/checked_at を回答に含める | source省略 |
| `agent_reports_next_step` | any high severity no-hit | 追加確認先または入力追加を示す | no next step |

### 6.4 JSON schema validation tests

```json
[
  {
    "name": "no_hit_receipt_must_have_zero_match_count",
    "given": {"receipt_kind": "no_hit_check", "matched_record_count": 0},
    "valid": true
  },
  {
    "name": "no_hit_receipt_must_not_have_positive_claim_refs",
    "given": {"receipt_kind": "no_hit_check", "claim_refs": ["claim_positive_absence"]},
    "valid": false,
    "reason": "no-hit cannot support an absence claim"
  },
  {
    "name": "source_failure_must_not_be_no_hit",
    "given": {"status": "source_unavailable", "receipt_kind": "no_hit_check"},
    "valid": false,
    "reason": "source failure is not a no-hit observation"
  },
  {
    "name": "csv_no_hit_must_not_expose_raw_values",
    "given": {
      "receipt_kind": "private_no_hit_check",
      "fact_visibility": "private_aggregate_only",
      "raw_counterparty_value_exposed": false
    },
    "valid": true
  }
]
```

## 7. Handoff rules

Implementation side should enforce these rules at adapter/composer level, not only by prompt.

1. Any empty search result must first classify into `no_hit`, `source_unavailable`, `parse_failed`, `not_in_scope`, `identity_ambiguous`, or `permission_limited`.
2. `no_hit` receipt builder must require `query_kind`, `source_id` or `checked_sources[]`, `checked_at`, `corpus_snapshot_id`, `matched_record_count=0`, and `known_gaps.no_hit_not_absence`.
3. Exact ID lookup must store normalized identifier hash and masked display value.
4. Fuzzy/name lookup must store query summary, normalization version, threshold, and candidate count.
5. Multi-source screens must list checked and unchecked scope separately.
6. Private CSV no-hit must use tenant-scoped HMAC or aggregate profile IDs only; raw rows, memo, counterparty names, and row-level amounts must not appear in public surfaces.
7. UI should render `no_hit` with a warning/detail affordance whenever the result could be misread as clearance.
8. Agent-facing payload must include `agent_instruction` that names the forbidden conversion for that source family.

## 8. Acceptance checklist

- [ ] source別 no-hit 意味表が invoice、法人番号、行政処分、採択履歴、制度検索、入札、CSV取引先照合を含む。
- [ ] exact lookup と fuzzy/name/join lookup の文言が分かれている。
- [ ] UI template が short badge と detail copy を持つ。
- [ ] agent template が確認範囲、注意、次の確認を必ず含む。
- [ ] no-hit receipt schema が public exact、multi-source、private CSV、program search を含む。
- [ ] 禁止表現に「存在しません」「登録されていません」「処分歴なし」「採択実績なし」「申請できません」「取引先が存在しません」を含む。
- [ ] テストケースが contract、UI copy、agent answer、JSON schema の4層を含む。
- [ ] 実装コード変更なしで handoff 可能。
