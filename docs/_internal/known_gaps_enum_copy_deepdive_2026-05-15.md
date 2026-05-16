# known_gaps enum / Japanese copy / agent instructions finalization

作成日: 2026-05-15  
担当: known_gaps enum / Japanese copy / agent instructions finalization  
制約: 実装コードには触れない。docs/_internal 専用の設計メモ。  
状態: P0 final proposal for implementation handoff

## 0. 結論

P0 の `known_gaps` は、AI が誤断定しやすい失敗面を 7 個の閉じた enum に固定する。

```text
csv_input_not_evidence_safe
source_receipt_incomplete
pricing_or_cap_unconfirmed
no_hit_not_absence
professional_review_required
freshness_stale_or_unknown
identity_ambiguity_unresolved
```

この 7 個以外を public / agent-facing の `known_gaps[].code` として出さない。既存実装や内部検査の細かい gap は、`raw_code` / `legacy_code` / `details.reason_codes[]` に退避し、UI と agent prompt は上記 7 個だけを見る。

## 1. 設計原則

- `known_gaps` は品質の言い訳ではなく、AI が断定してはいけない境界を機械可読にするための契約である。
- UI は「何が未確認か」と「次に誰が確認するか」を表示し、ユーザーに判断済みの印象を与えない。
- agent は gap がある claim を、結論ではなく候補、確認材料、追加確認点として扱う。
- `blocks_final_answer=true` は「回答不能」ではなく「断定形・最終判断・保証表現を禁止する」という意味で使う。
- `no_hit`、stale、identity ambiguity、professional review は、特に断定事故につながるため P0 では high severity とする。

## 2. P0 enum final

| code | scope | severity | blocks_final_answer | agent_instruction | 人間向け文言 |
|---|---|---:|---:|---|---|
| `csv_input_not_evidence_safe` | CSV / accounting / private input | high | true | raw CSV の摘要、取引先、個人名、金額明細を回答へ転記しない。列構成、期間、件数、入力品質、要レビュー理由などの派生情報だけを使い、会計・税務判断はしない。 | CSV に機微情報や未確認の取引情報が含まれる可能性があります。外部向け回答では raw 明細を出さず、入力品質と確認点だけを扱ってください。 |
| `source_receipt_incomplete` | source / citation / receipt | high | true | source URL、取得日時、hash、license、引用位置のいずれかが不足する claim は断定しない。出典が足りない事実は「未確認」として分け、根拠付き claim と混ぜない。 | 出典情報が不足しています。根拠付きで言えることと、追加確認が必要なことを分けてください。 |
| `pricing_or_cap_unconfirmed` | pricing / billing / cost preview | medium | false | 料金、cap、従量課金、外部 LLM コスト削減について保証しない。cost preview やプラン条件が未確認なら「見積もり前提」と明示する。 | 料金または利用上限の前提が未確認です。実行前に cost preview、月次上限、プラン条件を確認してください。 |
| `no_hit_not_absence` | no-hit / zero result / empty result | high | true | 0 件、未検出、照会失敗を「存在しない」「登録なし」「リスクなし」に変換しない。照会条件、対象 source、snapshot、名称揺れ、未接続 source を併記する。 | 対象範囲では該当 record を確認できませんでした。ただし、これは不存在の証明ではありません。 |
| `professional_review_required` | tax / legal / audit / finance / grant application | high | true | 税務、法務、監査、融資、与信、補助金採択、申請可否を最終判断しない。回答は根拠整理、候補、確認質問、専門家/公式窓口への引き継ぎに限定する。 | この結果は根拠整理です。最終判断は専門家、社内担当者、または公式窓口で確認してください。 |
| `freshness_stale_or_unknown` | freshness / source age / snapshot | high | true | stale または freshness unknown の source から、現在有効な制度、締切、金額、登録状態、処分状態を断定しない。確認時点と再確認先を示す。 | 出典の取得時点または鮮度が古い/不明です。最終利用前に公式 source で再確認してください。 |
| `identity_ambiguity_unresolved` | identity resolution / same-name / identifier bridge | high | true | 同名法人、旧商号、所在地揺れ、法人番号/T番号/EDINET/gBiz の bridge 不足がある場合、同一 entity と断定しない。match confidence と未解決の識別子を示す。 | 対象の同定に不確実性があります。同名・旧商号・識別子の照合を確認してから利用してください。 |

## 3. UI copy

UI は短文を badge / row title に、詳細文を expandable detail / tooltip / export footnote に使う。

| code | short label | detail copy |
|---|---|---|
| `csv_input_not_evidence_safe` | CSV入力は要注意 | CSV に摘要、取引先、個人情報、金額明細などの機微情報が含まれる可能性があります。外部向けには raw 明細を出さず、構造、件数、期間、入力品質、要レビュー理由だけを表示してください。 |
| `source_receipt_incomplete` | 出典情報が不足 | source URL、取得日時、hash、license、引用位置などが不足しています。この項目は根拠付き claim として断定せず、追加確認が必要な情報として扱ってください。 |
| `pricing_or_cap_unconfirmed` | 料金前提が未確認 | この実行または説明の料金、cap、従量課金、外部 LLM コスト前提が未確認です。cost preview と現在のプラン条件を確認してから実行・案内してください。 |
| `no_hit_not_absence` | 未検出は不存在ではない | 対象 source / 照会条件では該当 record を確認できませんでした。ただし、名称揺れ、更新遅延、未接続 source、非公開範囲の可能性があります。 |
| `professional_review_required` | 専門家確認が必要 | 税務・法務・監査・融資・与信・補助金採択・申請可否の最終判断ではありません。確認材料として扱い、必要に応じて資格者、社内担当者、公式窓口で確認してください。 |
| `freshness_stale_or_unknown` | 鮮度確認が必要 | 出典の取得/確認時点が古い、または不明です。現在の制度、締切、金額、登録状態、処分状態として使う前に公式 source で再確認してください。 |
| `identity_ambiguity_unresolved` | 同定が未確定 | 同名法人、旧商号、所在地揺れ、識別子不足などにより対象の同定が未確定です。法人番号、T番号、EDINET、gBiz などの照合を確認してください。 |

## 4. Agent instruction finalization

System / developer / tool instruction に入れる最小文言:

```text
When jpcite output contains known_gaps, treat each gap as a boundary on what may be asserted. Do not hide known_gaps. Do not convert no-hit into absence, stale source into current truth, identity ambiguity into entity match, or professional-review material into tax/legal/audit/finance/grant decisions. If a gap blocks the final answer, answer with supported facts, uncertainty, and the next verification step.
```

日本語 agent prompt:

```text
jpcite の known_gaps は、AI が断定してはいけない境界です。known_gaps を隠さず、根拠付きで言えること、未確認のこと、次に人間または公式窓口で確認することを分けてください。no-hit を不存在、stale を現時点の真実、identity ambiguity を同一法人確定、professional review required を専門判断に変換してはいけません。
```

回答生成時の順序:

1. `known_gaps[].code` を読む。
2. `blocks_final_answer=true` の gap がある claim は、断定形、保証、最終判断にしない。
3. まず根拠付きで言えることを書く。
4. 次に「未確認/要確認」として gap を短く表示する。
5. 最後に公式 source、専門家、社内担当者、または cost preview などの次アクションを書く。

## 5. Forbidden phrase mapping

| forbidden / risky phrase | blocked by code | required replacement direction |
|---|---|---|
| 存在しません | `no_hit_not_absence` | 対象 source / 照会条件では確認できませんでした |
| 登録されていません | `no_hit_not_absence`, `freshness_stale_or_unknown` | 照会範囲では登録情報を確認できませんでした |
| 処分歴なし | `no_hit_not_absence`, `identity_ambiguity_unresolved` | 接続済み source / 期間 / 同定条件では該当 record を確認できませんでした |
| 違反なし | `no_hit_not_absence`, `professional_review_required` | 対象 source では該当 record が見つかっていません |
| リスクなし | `no_hit_not_absence`, `professional_review_required`, `identity_ambiguity_unresolved` | 未確認範囲を残した確認材料です |
| 法的に問題ありません | `professional_review_required` | 法務レビューで確認すべき根拠を示します |
| 税務判断できます | `professional_review_required` | 税務確認のための根拠を整理します |
| 監査済み / 監査完了 | `professional_review_required`, `source_receipt_incomplete` | 監査調書の前段資料として使える公開根拠を整理します |
| 融資可能 / 与信OK | `professional_review_required` | 公開情報ベースの確認材料を整理します |
| 採択されます / 採択確実 | `professional_review_required`, `freshness_stale_or_unknown` | 申請前に確認すべき候補条件を示します |
| 申請できます | `professional_review_required`, `freshness_stale_or_unknown` | 公開要件に照らした候補/要確認点を示します |
| 併用可能です | `professional_review_required`, `source_receipt_incomplete` | 根拠付きで確認できた範囲と未確認条件を分けます |
| 完全網羅 | `source_receipt_incomplete`, `no_hit_not_absence` | 対象 source と known gaps を明示します |
| リアルタイム正本 | `freshness_stale_or_unknown` | 取得時点付きの source-linked snapshot |
| 100% 正確 | `source_receipt_incomplete`, `professional_review_required` | 出典・取得時点・hash により検証可能 |
| 幻覚ゼロ | `source_receipt_incomplete` | unsupported claim を減らすための receipts を返します |
| 必ず安くなります | `pricing_or_cap_unconfirmed` | 長文資料の再読込を減らせる場合があります |
| LLM費用を保証削減 | `pricing_or_cap_unconfirmed` | jpcite 課金と外部 LLM / agent runtime cost は別です |
| 取引明細を安全に共有 | `csv_input_not_evidence_safe` | raw 明細を出さず、構造/件数/期間/品質だけ共有します |
| 摘要から取引先を推定 | `csv_input_not_evidence_safe` | 摘要は presence / hash / 分類に留めます |
| この仕訳は正しい | `csv_input_not_evidence_safe`, `professional_review_required` | CSV品質上の要レビュー項目を示します |
| 経費にできます | `csv_input_not_evidence_safe`, `professional_review_required` | 税務確認に必要な候補科目と根拠を整理します |
| 同じ会社です | `identity_ambiguity_unresolved` | 同定候補、根拠、未解決の識別子を示します |

## 6. Legacy / internal code mapping

既存や深掘り案の細かい code は P0 UI に直接出さず、以下へ集約する。

| legacy / raw code examples | P0 code |
|---|---|
| `missing_source_id`, `source_unverified`, `source_url_quality`, `source_receipt_missing_fields`, `license_unknown`, `license_blocked`, `source_license_high_risk`, `citation_unverified` | `source_receipt_incomplete` |
| `source_stale`, `latest_news_not_checked`, `lookup_status_unknown`, `freshness_unknown`, `deadline_stale`, `form_version_stale` | `freshness_stale_or_unknown` |
| `not_found_in_local_mirror`, `structured_miss`, `no_public_event_found_not_clean_record`, `zero_result`, `empty_result` | `no_hit_not_absence` |
| `identity_confidence_below_floor`, `identifier_bridge_missing`, `houjin_bangou_unverified`, `edinet_unresolved`, `enforcement_match_low_confidence`, `same_name_collision` | `identity_ambiguity_unresolved` |
| `requires_tax_review`, `requires_legal_review`, `requires_audit_review`, `requires_grant_review`, `requires_credit_review`, `private_context_not_covered` | `professional_review_required` |
| `cost_preview_missing`, `monthly_cap_unknown`, `plan_unknown`, `external_llm_cost_not_estimated`, `pricing_surface_stale` | `pricing_or_cap_unconfirmed` |
| `csv_contains_sensitive_columns`, `csv_raw_rows_present`, `csv_pii_possible`, `csv_accounting_judgment_required`, `csv_export_not_safe` | `csv_input_not_evidence_safe` |

## 7. Output contract recommendation

P0 の wire shape は既存互換を保ちながら、次のフィールドを推奨する。

```json
{
  "known_gaps": [
    {
      "code": "no_hit_not_absence",
      "severity": "high",
      "blocks_final_answer": true,
      "subject": "houjin",
      "short_message_ja": "未検出は不存在ではない",
      "message_ja": "対象範囲では該当 record を確認できませんでした。ただし、これは不存在の証明ではありません。",
      "agent_instruction": "Do not convert this no-hit into absence or clean record.",
      "raw_code": "not_found_in_local_mirror",
      "affected_records": []
    }
  ]
}
```

`code` は P0 enum のみ。`raw_code` は任意で、互換・監査・改善ループ用に残す。UI は `short_message_ja` と `message_ja` を表示し、agent は `agent_instruction` と `blocks_final_answer` を読む。

## 8. Severity and blocking policy

| severity | meaning | UI behavior | agent behavior |
|---|---|---|---|
| high | 誤断定が法務・税務・信用・安全・同定事故に直結しやすい | 常時表示。export footnote にも出す | 対象 claim を断定しない。確認範囲と次アクションを必ず書く |
| medium | 課金、運用、説明前提のずれが起きる | 実行前または設定欄に表示 | 保証表現を避け、前提確認として書く |
| low | P0 では未使用 | 将来拡張 | 将来拡張 |

P0 では `pricing_or_cap_unconfirmed` だけ `blocks_final_answer=false` を許容する。ただし「必ず安くなる」「料金確定」「cap内で実行可能」のような料金断定はブロックする。他の 6 個は `blocks_final_answer=true` とする。

## 9. Copy rules

使う語:

- 確認できた範囲
- 対象 source / 照会条件
- 取得時点
- 未確認
- 要確認
- 確認材料
- 根拠整理
- 追加確認先
- 専門家または公式窓口

避ける語:

- 確実
- 保証
- 公式認定
- 合法 / 違法
- 安全
- 問題なし
- 採択確実
- 融資可能
- 節税できます
- 監査済み
- 反社ではない
- 不正です

否定文として許可される例:

- 採択判断ではありません。
- 安全性を判定しません。
- 不存在の証明ではありません。
- 税務・法務・監査・融資・与信の最終判断ではありません。

## 10. Acceptance checklist

- [ ] Public / agent-facing `known_gaps[].code` は 7 enum のみ。
- [ ] `no_hit_not_absence` が「存在しない」「登録なし」「リスクなし」に変換されない。
- [ ] `freshness_stale_or_unknown` がある制度、締切、金額、登録状態を現時点の真実として断定しない。
- [ ] `identity_ambiguity_unresolved` がある record を同一法人・同一制度として断定しない。
- [ ] `professional_review_required` がある回答で、税務・法務・監査・融資・与信・採択・申請可否を断定しない。
- [ ] `csv_input_not_evidence_safe` がある出力で raw CSV 明細、摘要、取引先、個人情報を外部向けに再掲しない。
- [ ] `pricing_or_cap_unconfirmed` がある説明で、料金確定、cap内保証、外部 LLM 費用削減保証をしない。
- [ ] UI は short label と detail copy を表示できる。
- [ ] Agent instruction は known_gaps を隠さず、根拠付き claim / 未確認 / 次アクションを分ける。
