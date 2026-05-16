# jpcite prebuilt deliverable packet strategy

Date: 2026-05-15

Status: internal source of truth

## 0. 結論

jpcite は「日本の制度・法令・法人・インボイス・行政処分を検索できる API」だけだと弱い。ユーザーから見ると「自分でキャッシュしておけばよい」「RAG に入れればよい」と判断されやすい。

強い価値は、AI agent が毎回 PDF・検索結果・制度ページを大量に読む前に、jpcite 側で次の 3 つを済ませた `成果物パケット` を返すこと。

1. 必要な公開情報を制度・法人・地域・期限・除外条件・併用ルールで突き合わせる。
2. 専門判断に踏み込まず、実務者が次に確認する表・質問・注意点・根拠 URL に整える。
3. AI agent に渡す入力を小さくし、`jpcite_cost_jpy`、`estimated_tokens_saved`、`source_count`、`known_gaps` で費用対効果を測れるようにする。

表現は「RAG の代替」ではなく、以下に統一する。

> jpcite は、AI が読む前の制度データ圧縮レイヤーです。毎回 PDF と検索結果を AI に投げる代わりに、根拠付きの小さい成果物パケットへ変換します。

## 1. 共通パケット契約

すべての完成成果物は、個別の表や文章ではなく同じ envelope で返す。これにより、Claude Agent SDK、claude -p、Codex、Cursor、GitHub Actions、独自 SaaS agent が同じ作法で扱える。

```json
{
  "package_id": "pkg_...",
  "package_kind": "evidence_packet | artifact_pack | precomputed_intelligence | watch_digest",
  "template_id": "application_strategy_v1",
  "template_version": "2026-05-15",
  "subject": {
    "kind": "program | houjin | invoice | cohort | watchlist | query",
    "id": "..."
  },
  "generated_at": "2026-05-15T12:00:00+09:00",
  "corpus_snapshot_id": "snap_...",
  "corpus_checksum": "sha256:...",
  "bundle_sha256": "sha256:...",
  "jpcite_cost_jpy": 3,
  "estimated_tokens_saved": 17680,
  "source_count": 12,
  "known_gaps": [],
  "human_review_required": true,
  "records": [],
  "sections": [],
  "sources": [
    {
      "source_url": "https://...",
      "source_fetched_at": "2026-05-15T09:00:00+09:00",
      "source_checksum": "sha256:...",
      "publisher": "official_primary | official_secondary | aggregator",
      "license": "..."
    }
  ],
  "source_receipts": [],
  "coverage": {
    "coverage_score": 0.86,
    "coverage_grade": "A",
    "critical_unknown_count": 0
  },
  "compression": {
    "source_tokens_estimate": 22000,
    "packet_tokens_estimate": 1800,
    "input_context_reduction_rate": 0.918
  },
  "copy_paste_parts": {},
  "agent_handoff": {
    "answer_outline": [],
    "must_cite_fields": ["source_url", "source_fetched_at", "known_gaps"],
    "do_not_claim": [
      "legal_advice",
      "tax_advice",
      "application代理",
      "grant_award",
      "audit_opinion",
      "credit_approval"
    ]
  },
  "disclaimer": "jpcite は情報検索・根拠確認の補助に徹し、個別具体的な税務・法律・申請・監査・登記・労務・知財・労基の判断は行いません。"
}
```

### 必須ルール

- `known_gaps` はトップレベルと該当 section の両方に出す。
- `unknown` は安全ではない。`unknown != safe` を API レスポンス・ドキュメント・画面コピーで一貫させる。
- 出典 URL がない claim は、AI が外部向け回答で使える claim にしない。
- stale source は「過去時点の証跡」として扱い、現時点の状態確認には使わない。
- `jpcite_cost_jpy`、`estimated_tokens_saved`、`source_count`、`known_gaps` は全 artifact に入れる。
- 専門家の最終判断が必要な成果物は `human_review_required: true` を固定する。
- 「使える」「申請できます」「法的に問題ありません」「税務上有利です」「融資可」ではなく、「候補」「確認質問」「要専門家確認」「公開情報上の一致/不一致」「根拠未接続」を返す。

## 2. 数学モデル

成果物パケットは「それっぽい要約」ではなく、どこまで根拠付きで圧縮できたかを数値化する。

### 2.1 coverage score

```text
fact_coverage_r =
  sourced_fact_count_r / max(required_fact_count_r, observed_fact_count_r, 1)

claim_coverage_r =
  source_linked_claim_count_r / max(claim_count_r, 1)

citation_coverage_r =
  (verified + 0.7*inferred + 0.3*stale + 0*unknown) / max(citation_count, 1)

freshness_coverage_r =
  exp(-age_days / stale_half_life_days)

gap_penalty =
  min(0.30, 0.08*high_gap_count + 0.04*medium_gap_count + 0.02*low_gap_count)

coverage_score =
  0.35 * mean(fact_coverage)
+ 0.25 * claim_coverage
+ 0.20 * citation_coverage
+ 0.15 * freshness_coverage
+ 0.05 * receipt_completion
- gap_penalty
```

Grade:

- `S`: `coverage_score >= 0.92` かつ critical unknown が 0
- `A`: `coverage_score >= 0.80`
- `B`: `coverage_score >= 0.65`
- `C`: `coverage_score >= 0.45`
- `D`: それ未満

`S/A` でも専門判断はしない。意味は「AI に渡せる根拠付き入力としての完成度が高い」だけ。

### 2.2 source confidence

```text
source_confidence_s =
  license_weight
* verification_weight
* source_type_weight
* freshness_weight
* checksum_weight
* corroboration_weight

verification_weight:
  verified=1.00, inferred=0.70, stale=0.40, unknown=0.25

source_type_weight:
  official_primary=1.00, official_secondary=0.85, aggregator=0.55, modeled=0.35

freshness_weight:
  exp(-age_days / 180)

corroboration_weight:
  min(1.00, 0.65 + 0.15*confirming_source_count)
```

集計は平均だけだと弱い。極端に低い根拠を拾うため、以下にする。

```text
aggregate_source_confidence =
  0.70 * weighted_mean(source_confidence_s)
+ 0.30 * p10(source_confidence_s)
```

### 2.3 compression / cost

```text
estimated_tokens_saved =
  max(0, source_tokens_estimate - packet_tokens_estimate)

input_context_reduction_rate =
  estimated_tokens_saved / max(source_tokens_estimate, 1)

break_even_source_tokens_estimate =
  packet_tokens_estimate + ceil(jpcite_cost_jpy / model_input_price_jpy_per_token)
```

外部 LLM の請求削減は保証しない。表示は必ず「caller baseline 条件下の入力文脈比較」にする。

### 2.4 precompute priority

大量に先回り生成すべき成果物は、単純な検索回数ではなく、繰り返し価値・実務単価・根拠複雑性・更新頻度で決める。

```text
precompute_priority =
  0.25 * repeat_frequency_score
+ 0.20 * willingness_to_pay_score
+ 0.18 * join_complexity_score
+ 0.15 * token_savings_score
+ 0.10 * freshness_volatility_score
+ 0.07 * legal_fence_safety_score
+ 0.05 * sales_demo_clarity_score
```

初期優先は、月次顧問先レビュー、申請戦略 pack、併用可否 matrix、法人 public DD、インボイス取引先確認、公開資金 traceback。

## 3. 成果物カタログ

### 3.1 税理士・会計事務所・診断士・補助金コンサル

#### 1. client_monthly_review_packet

50-200 社を毎月回す事務所向け。顧問先ごとに「今月見る制度・税制・補助金・期限・確認質問」を返す。

Inputs:

- 法人番号、所在地、業種、従業員数、資本金、売上規模、投資予定、過去採択、認定、顧問先メモ

Joined data:

- 法人基本情報、補助金/助成金、税制特例、融資制度、自治体制度、採択履歴、期限、除外条件、認定制度、法令根拠

Output sections:

- `this_month_watch_items`
- `deadline_risks`
- `program_candidates`
- `tax_or_system_change_notes`
- `questions_for_client`
- `known_gaps`
- `source_receipts`

AI agent が作れる次工程:

- 顧問先面談メモ
- 月次メール下書き
- 所内タスク
- 顧問先別 Notion/CRM 更新

Why paid:

- 毎月繰り返すため、都度 PDF と検索を agent に読ませるより差が出る。
- `known_gaps` があるので、未確認事項をそのまま顧問先質問にできる。

#### 2. application_strategy_pack

補助金・融資・税制の候補を、地域・業種・投資額・認定・除外条件で突き合わせる。

Output sections:

- `normalized_applicant_profile`
- `ranked_candidates`
- `amount_rate_deadline_table`
- `eligibility_signals`
- `exclusion_or_caution_points`
- `required_documents_hint`
- `questions_for_window_or_professional`
- `copy_paste_summary`

禁止:

- 「採択されます」
- 「申請可能です」
- 「この制度を使うべきです」

返すべき表現:

- 「候補」
- 「要確認」
- 「除外条件の確認が必要」
- 「窓口確認事項」

#### 3. funding_stack_compatibility_matrix

複数制度の併用可否、排他、同一経費リスク、case_by_case、unknown を表にする。

Verdicts:

- `compatible`
- `incompatible`
- `requires_review`
- `case_by_case`
- `unknown`

Output sections:

- `pairwise_matrix`
- `hard_blockers`
- `same_expense_risks`
- `sequence_or_timing_constraints`
- `rule_clauses`
- `office_confirmation_questions`

Key rule:

- `unknown` は「安全」ではなく「根拠未接続」。

#### 4. subsidy_application_checklist_packet

申請書を書く前に必要資料と不足事実を洗い出す。申請代行ではなく、準備チェックリスト。

Output sections:

- `document_checklist`
- `facts_needed`
- `evidence_to_keep`
- `source_clauses`
- `client_questions`

#### 5. adoption_case_benchmark_packet

過去採択事例を業種・地域・投資テーマでまとめ、AI が提案書の論点整理に使う。

Output sections:

- `similar_cases`
- `project_theme_patterns`
- `investment_keywords`
- `publicly_visible_limits`
- `known_gaps`

#### 6. enforcement_clawback_risk_packet

補助金返還・行政処分・不正受給・取消情報を時系列で確認し、公開情報上の注意点を出す。

Output sections:

- `timeline`
- `red_flags`
- `yellow_flags`
- `entity_match_confidence`
- `source_receipts`
- `dd_questions`

#### 7. invoice_compliance_evidence_packet

インボイス制度の登録・取消・失効・名称住所一致・経過措置論点を AI が誤らないように小さくまとめる。

Output sections:

- `invoice_registration_status`
- `name_address_match`
- `status_history`
- `caution_windows`
- `accounting_questions`

#### 8. tax_cliff_calendar_packet

制度変更・特例期限・経過措置期限を顧問先セグメント別にカレンダー化する。

Output sections:

- `upcoming_cliffs`
- `affected_client_segments`
- `action_window`
- `source_confidence`
- `questions_to_confirm`

#### 9. certification_leverage_packet

経営革新計画、先端設備等導入計画、各種認定の有無と、使える可能性がある制度をつなぐ。

Output sections:

- `certification_status`
- `programs_referencing_certification`
- `missing_certifications`
- `timing_dependencies`

#### 10. ai_answer_guard_packet

税理士・診断士・補助金コンサルが作る GPT/Claude agent に同梱する「言ってよいこと/言ってはいけないこと」の guard。

Output sections:

- `allowed_claims`
- `must_not_claim`
- `required_disclaimer`
- `citation_rules`
- `handoff_to_professional`

### 3.2 行政書士・社労士・弁理士・商工会・士業隣接

#### 11. client_evidence_pack

相談前に公開情報を揃える evidence pack。専門判断ではなく、面談準備。

Output sections:

- `client_profile`
- `candidate_programs_or_rules`
- `source_receipts`
- `known_gaps`
- `human_review_required`

Use cases:

- 行政書士の許認可/補助金相談準備
- 商工会の会員相談
- 士業チームの一次ヒアリング

#### 12. eligibility_question_list

「該当/非該当」を断定せず、実務者が聞くべき質問に変換する。

Question fields:

- `question`
- `category`
- `why_asked`
- `source_url`
- `source_fetched_at`
- `answer_type`
- `required_for_screening`

#### 13. deadline_matrix

制度や手続の期限を、確度付きで表にする。

Deadline confidence:

- `structured`
- `text_only`
- `unknown`

注意:

- 「随時」「通年」「期限空欄」は安全ではない。確認対象として出す。

#### 14. labor_grant_question_packet

社労士向け。助成金候補そのものより、労務・雇用・就業規則・賃金台帳などの確認質問を出す。

Output sections:

- `grant_candidate_outline`
- `labor_facts_needed`
- `document_questions`
- `risk_words_to_avoid`
- `professional_review_required`

#### 15. ip_subsidy_evidence_pack

弁理士・知財支援向け。知財取得・海外展開・研究開発関連の制度と必要確認事項をまとめる。

Output sections:

- `ip_or_rd_program_candidates`
- `eligible_expense_questions`
- `publication_or_application_timing_risks`
- `source_receipts`

#### 16. member_program_watchlist

商工会・団体向け。会員企業リストを毎月見て、関係しそうな制度・期限・確認質問を出す。

Output sections:

- `member_segments`
- `new_or_changed_programs`
- `deadline_alerts`
- `recommended_outreach_copy`
- `known_gaps`

### 3.3 信金・銀行・融資・M&A・VC・監査・記者

#### 17. counterparty_public_dd_packet

取引先・投資先・融資先候補の公開情報 DD。正式 DD の代替ではなく初期スクリーニング。

Inputs:

- 法人番号、T番号、名称、住所ヒント、業種、as_of

Joined data:

- 法人基本、インボイス、行政処分、補助金採択、返還/取消、入札/委託、関連制度、source receipts

Output sections:

- `identity_resolution`
- `invoice_status`
- `public_funding_history`
- `enforcement_or_sanction_hits`
- `red_flags`
- `yellow_flags`
- `unknowns`
- `dd_questions`

#### 18. loan_portfolio_watchlist_delta

信金・銀行向け。融資先や見込み先リストを定期監視し、差分だけ返す。

Output sections:

- `changed_entities`
- `new_public_funding_hits`
- `new_enforcement_hits`
- `invoice_status_changes`
- `program_opportunities`
- `relationship_manager_actions`

Why paid:

- 1 回限りの検索ではなく、毎月の営業/リスク管理オペレーションになる。

#### 19. ma_target_public_risk_memo

M&A/VC 向け。公開情報上の初期論点を memo 化する。

Output sections:

- `entity_baseline`
- `public_money_exposure`
- `compliance_history`
- `invoice_and_registry_check`
- `source_coverage`
- `known_gaps`
- `diligence_questions`

#### 20. auditor_evidence_binder

監査・内部統制・稟議向け。根拠 URL と取得時刻を束ねる binder。

Output sections:

- `binder_index`
- `evidence_items`
- `receipts`
- `hashes`
- `coverage_score`
- `review_queue`

#### 21. public_funding_traceback

補助金・委託・入札・返還・処分を時系列で並べる。記者、監査、M&A、行政調査向け。

Output sections:

- `timeline`
- `program_or_contract_links`
- `money_flow_notes`
- `same_entity_confidence`
- `open_questions`
- `source_receipts`

#### 22. supplier_invoice_enforcement_screen

経理・仕入先登録・BPO 向け。T番号/法人番号から登録・取消・失効・名称住所一致・行政処分ヒットを返す。

Output sections:

- `identity_match`
- `invoice_registration`
- `status_history`
- `enforcement_hits`
- `procurement_questions`

#### 23. journalist_public_interest_brief

記者向け。公開情報の事実関係、時系列、未確認点を整理する。断定記事の生成ではない。

Output sections:

- `known_public_facts`
- `timeline`
- `documents_to_request`
- `unknowns`
- `right_of_reply_questions`

### 3.4 AI 開発者・SaaS・エージェント開発者

#### 24. program_opportunity_brief

自社 SaaS の中で「このユーザーに関係しそうな制度」を出すための agent 入力。

Output sections:

- `program_summary`
- `fit_signals`
- `missing_profile_fields`
- `source_receipts`
- `ui_safe_copy`

#### 25. reviewer_handoff_packet

AI が作った回答や申請前メモを、人間レビュアーに渡すための根拠 bundle。

Output sections:

- `answer_claims`
- `supporting_sources`
- `unsupported_claims`
- `known_gaps`
- `reviewer_questions`

#### 26. saved_search_delta_packet

GitHub Actions、cron、社内 agent が毎日/毎週見る差分パケット。

Output sections:

- `new_records`
- `changed_records`
- `expired_or_removed_candidates`
- `impact_summary`
- `agent_next_actions`

#### 27. citation_pack

AI agent が回答に差し込む出典だけを小さく返す。

Output sections:

- `citation_items`
- `preferred_citation_text`
- `source_url`
- `source_fetched_at`
- `license`
- `known_gaps`

#### 28. ui_copy_safety_packet

SaaS に表示してよい文言と避けるべき文言を返す。

Output sections:

- `safe_labels`
- `unsafe_labels`
- `required_disclaimer`
- `known_gaps_display_rules`
- `seo_geo_terms`

#### 29. agent_system_prompt_guard

Claude Project、Custom GPT、Codex agent、Cursor agent に貼る system/developer prompt 用 guard。

Output sections:

- `role`
- `allowed_tasks`
- `forbidden_tasks`
- `citation_policy`
- `professional_handoff_policy`
- `examples`

#### 30. cost_and_token_roi_packet

開発者が「jpcite を呼ぶ方が安いか」を agent 内で判断するための見積パケット。

Output sections:

- `baseline_assumptions`
- `source_tokens_estimate`
- `packet_tokens_estimate`
- `break_even`
- `recommendation`
- `limitations`

## 4. API / MCP 形

既存の `/v1/evidence/packets/*` と `/v1/artifacts/*` を生かし、上に catalog/preview を足す。

### REST

- `GET /v1/packets/catalog`
- `POST /v1/packets/preview`
- `POST /v1/packets/client_monthly_review`
- `POST /v1/packets/application_strategy`
- `POST /v1/packets/compatibility_matrix`
- `POST /v1/packets/company_public_baseline`
- `POST /v1/packets/counterparty_public_dd`
- `POST /v1/packets/public_funding_traceback`
- `POST /v1/packets/invoice_counterparty_check`
- `POST /v1/packets/saved_search_delta`
- `POST /v1/packets/reviewer_handoff`
- `POST /v1/packets/cost_and_token_roi`

### MCP tools

- `listPrebuiltPackets`
- `previewPacketCost`
- `createClientMonthlyReviewPacket`
- `createApplicationStrategyPack`
- `createFundingStackCompatibilityMatrix`
- `createCounterpartyPublicDDPacket`
- `createPublicFundingTraceback`
- `createInvoiceCounterpartyCheckPack`
- `createSavedSearchDeltaPacket`
- `createReviewerHandoffPacket`

Tool descriptions should say:

- “prepares evidence and questions”
- “does not make legal/tax/application/audit/labor/IP decisions”
- “returns known_gaps and source receipts”
- “unknown is not safe”

## 5. 初期実装順位

### P0: すぐ商品価値を出す

1. `application_strategy_pack`
2. `funding_stack_compatibility_matrix`
3. `company_public_baseline`
4. `counterparty_public_dd_packet`
5. `invoice_counterparty_check_pack`
6. `cost_and_token_roi_packet`

理由:

- 既存データと既存 API の延長で作りやすい。
- デモが分かりやすい。
- AI agent からの token 節約を説明しやすい。
- 士業・金融・SaaS の複数市場に横展開できる。

### P1: 継続課金に効く

1. `client_monthly_review_packet`
2. `loan_portfolio_watchlist_delta`
3. `member_program_watchlist`
4. `saved_search_delta_packet`
5. `tax_cliff_calendar_packet`

理由:

- 単発検索から月次/週次の業務ループへ変わる。
- 「AI だけで毎回調べる」より、反復運用で明確に差が出る。

### P2: 専門領域別に刺す

1. `labor_grant_question_packet`
2. `ip_subsidy_evidence_pack`
3. `auditor_evidence_binder`
4. `journalist_public_interest_brief`
5. `ui_copy_safety_packet`

理由:

- 専門判断への距離が近いので legal fence とセットで慎重に出す。
- public copy と QA が固まってから展開する。

## 6. UI / SEO / GEO 表現

画面や LP では、内部実装名をそのまま見せすぎない。

Good:

- 「AI が読む前の制度データ圧縮レイヤー」
- 「根拠付きの小さい入力に変換」
- 「申請前に確認すべき質問と出典」
- 「unknown を安全扱いしない」
- 「source_url / source_fetched_at / known_gaps 付き」
- 「Claude Agent SDK / claude -p / GitHub Actions で使える」

Avoid:

- 「RAG の代替」
- 「AI だけより安い」
- 「申請できます」
- 「法律判断できます」
- 「税務判断できます」
- 「監査できます」
- 「融資判断できます」

SEO/GEO target phrases:

- 日本 制度 API
- 補助金 AI agent
- Claude Agent SDK 日本 制度
- 法人番号 公開情報 DD
- インボイス番号 API 確認
- 補助金 併用可否 matrix
- Evidence Packet API
- AI agent source_url source_fetched_at known_gaps

## 7. 実装ガード

### Tests

- すべての artifact response に `jpcite_cost_jpy`, `estimated_tokens_saved`, `source_count`, `known_gaps` がある。
- `known_gaps` がある時、`human_review_required` は true。
- compatibility matrix で `unknown` を safe/compatible に丸めない。
- `source_url` なしの claim を `copy_paste_parts` に入れない。
- OpenAPI / MCP schema に legal fence が残る。
- public site の wording に「申請できます」「法律判断」「税務判断」などが出ない。
- pricing/case study に「外部 LLM 請求削減保証」と読める表現がない。

### Deployment

- packet template を追加するだけで OpenAPI、MCP tool registry、public docs、pricing example が自動検査されるようにする。
- template catalog を単一 JSON/YAML に寄せ、API schema と docs をそこから生成する。
- generated public HTML に古い文言が復活しないよう、static reachability/wording guard に禁止語と必須語を持たせる。

## 8. 一言で売るなら

AI agent に日本の制度・法人・インボイス・行政処分を毎回読ませるのではなく、jpcite が先に突き合わせて、根拠付きの完成成果物パケットにして渡す。ユーザーは、そのパケットを顧問先レビュー、申請前確認、公開情報 DD、取引先確認、監査 binder、SaaS の AI 機能にそのまま使える。

価値は「検索できること」ではなく、「AI が次に作る実務アウトプットの 70-90% を、判断手前まで根拠付きで済ませること」。
