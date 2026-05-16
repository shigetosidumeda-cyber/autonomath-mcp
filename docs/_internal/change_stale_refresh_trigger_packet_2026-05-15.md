# #29 Change / Stale Refresh Trigger Pack

Date: 2026-05-15

Status: internal product packet analysis

Template ID: `change_stale_refresh_trigger_pack_v1`

## 0. 結論

`Change / Stale Refresh Trigger Pack` は、制度・法令・公募要領・FAQ・PDF の更新を検知した時に、既存の Evidence Packet、保存済み成果物、AI 回答、顧客向け表示コピーを「現時点の回答に使ってよいか」で判定する成果物 packet である。

この packet の価値は、単なる変更通知ではない。以下を同じ envelope で返す。

1. どの一次情報源が、いつ、どの粒度で変わったか。
2. どの既存 packet / AI 回答 / UI 表示が影響を受けるか。
3. stale 判定を `safe / caution / stale / blocked` で明示する。
4. 再生成、自動差分通知、人手確認、非表示化の次アクションを返す。

基本方針は次の通り。

- `stale` は「内容が誤り」と同義ではない。「現時点の根拠として再確認が必要」という状態である。
- `fresh` は「法的・制度的に正しい」と同義ではない。「登録済みソースとの差分が検出されていない」という状態である。
- AI 回答は、出典 URL だけでなく `source_checksum`、`source_fetched_at`、`claim_refs` に紐づけていない限り、精密な stale 判定はできない。
- 制度・法令・公募要領では `unknown != safe` を固定する。取得失敗、PDF 差し替え不明、FAQ 構造崩れは `known_gaps` として返す。

## 1. 対象ユーザー

### 1.1 AI エージェント / SaaS 開発者

目的:

- ユーザーへ表示済みの制度候補、申請メモ、AI 回答、FAQ 回答が古くなった時に自動で警告したい。
- 保存済み回答を再利用する前に、根拠の鮮度と差分を API で確認したい。
- GitHub Actions、cron、社内 worker、Claude/Codex agent から安全に再生成キューを作りたい。

購入理由:

- 自前 crawler + diff + impact graph + reviewer workflow を作るより安い。
- LLM に毎回 PDF 全文を読ませず、影響範囲だけを小さく渡せる。

### 1.2 税理士・会計事務所・診断士・補助金コンサル

目的:

- 顧問先に送った月次制度レビューや申請候補リストについて、公募要領・FAQ・期限・補助率が変わった時だけ確認したい。
- 過去に作った packet のうち、再提案・再説明が必要なものだけ拾いたい。
- 人手レビュー対象を「全部」ではなく「期限、対象者、金額、提出書類、併用可否が変わったもの」に絞りたい。

購入理由:

- 公募情報の見落としリスクを減らしつつ、専門判断は人間に残せる。

### 1.3 金融機関・M&A・調査会社

目的:

- 公的 DD、補助金採択、行政処分、法令根拠を含む packet が更新で使えなくなったかを監査ログに残したい。
- 提出済み資料や社内メモに「再確認が必要」と差分付きで通知したい。

購入理由:

- 監査・審査の再利用時に、古い根拠をそのまま使う事故を減らせる。

## 2. 入力

### 2.1 最小入力

```json
{
  "watch_scope": {
    "source_urls": ["https://example.go.jp/program/abc.html"],
    "packet_ids": ["evp_1234abcd"],
    "answer_ids": ["ans_20260515_001"]
  },
  "policy": {
    "stale_profile": "subsidy_default",
    "auto_regenerate": true,
    "notify_on": ["stale", "blocked", "material_change"],
    "human_review_threshold": "medium"
  }
}
```

### 2.2 推奨入力

```json
{
  "watch_scope": {
    "subject": {
      "kind": "program",
      "id": "program_...",
      "jurisdiction": "meti | prefecture | municipality | e_gov"
    },
    "source_urls": [
      {
        "url": "https://...",
        "source_kind": "program_page | call_guideline_pdf | faq_page | law_page | form_pdf",
        "importance": "critical | high | medium | low"
      }
    ],
    "packet_ids": ["evp_..."],
    "answer_ids": ["ans_..."],
    "client_tags": ["client_a"]
  },
  "stored_artifacts": [
    {
      "artifact_id": "ans_...",
      "artifact_kind": "ai_answer | ui_copy | application_memo | reviewer_handoff",
      "claim_refs": [
        {
          "claim_id": "clm_001",
          "source_url": "https://...",
          "source_checksum": "sha256:...",
          "field_paths": ["records[0].deadline", "sections.eligibility"],
          "claim_severity": "critical"
        }
      ],
      "generated_at": "2026-05-14T10:00:00+09:00"
    }
  ],
  "policy": {
    "stale_profile": "subsidy_default",
    "max_source_age_days": 30,
    "require_checksum_match": true,
    "semantic_diff": true,
    "auto_regenerate": true,
    "human_review_threshold": "medium",
    "notification_channels": ["webhook", "email_digest", "slack"],
    "budget_cap_jpy": 3300
  }
}
```

### 2.3 入力で必須にしたいメタデータ

- `source_url`: 一次情報の URL。
- `source_kind`: `program_page`, `call_guideline_pdf`, `faq_page`, `law_page`, `law_xml`, `form_pdf`, `notice_page`, `rss_feed`, `api_json`。
- `source_checksum`: 前回取得時の正規化本文または PDF bytes の hash。
- `source_fetched_at`: jpcite が最後に取得・構造化した日時。
- `published_at` / `last_modified_at`: ソース側に明示されている公表日・更新日。なければ `null`。
- `valid_from` / `valid_until`: 制度・法令・公募の効力または受付期間。なければ `unknown`。
- `claim_refs`: AI 回答内の主張と根拠 source / field の対応。これがない回答は `answer_stale_confidence` を低くする。

## 3. 出力 packet

### 3.1 envelope

```json
{
  "package_id": "pkg_change_...",
  "package_kind": "watch_digest",
  "template_id": "change_stale_refresh_trigger_pack_v1",
  "template_version": "2026-05-15",
  "subject": {
    "kind": "program",
    "id": "program_..."
  },
  "generated_at": "2026-05-15T14:00:00+09:00",
  "corpus_snapshot_id": "snap_...",
  "corpus_checksum": "sha256:...",
  "bundle_sha256": "sha256:...",
  "jpcite_cost_jpy": 33,
  "estimated_tokens_saved": 14800,
  "source_count": 7,
  "known_gaps": [],
  "human_review_required": true,
  "sections": [
    {
      "section_id": "change_summary",
      "title": "変更概要",
      "items": []
    },
    {
      "section_id": "stale_decisions",
      "title": "stale 判定",
      "items": []
    },
    {
      "section_id": "impacted_packets",
      "title": "影響を受ける packet",
      "items": []
    },
    {
      "section_id": "impacted_answers",
      "title": "影響を受ける AI 回答",
      "items": []
    },
    {
      "section_id": "regeneration_plan",
      "title": "再生成計画",
      "items": []
    },
    {
      "section_id": "notifications",
      "title": "差分通知",
      "items": []
    },
    {
      "section_id": "human_review_queue",
      "title": "人手確認キュー",
      "items": []
    }
  ],
  "sources": [],
  "source_receipts": [],
  "agent_handoff": {
    "must_cite_fields": [
      "source_url",
      "previous_source_checksum",
      "current_source_checksum",
      "change_detected_at",
      "stale_decision",
      "known_gaps"
    ],
    "do_not_claim": [
      "legal_advice",
      "tax_advice",
      "application代理",
      "grant_award",
      "official_update_completeness"
    ]
  },
  "disclaimer": "jpcite は公開情報の変更検知・差分整理・根拠確認の補助に徹し、個別具体的な法律・税務・申請・監査判断は行いません。"
}
```

### 3.2 stale decision item

```json
{
  "artifact_id": "evp_1234abcd",
  "artifact_kind": "evidence_packet",
  "previous_status": "fresh",
  "stale_decision": "stale",
  "stale_reason_codes": [
    "critical_source_checksum_changed",
    "deadline_field_changed"
  ],
  "severity": "high",
  "confidence": 0.93,
  "affected_claim_refs": [
    {
      "claim_id": "clm_deadline_001",
      "field_path": "records[0].application_deadline",
      "previous_value": "2026-06-14",
      "current_value": "2026-05-31",
      "change_type": "deadline_moved_earlier"
    }
  ],
  "recommended_action": "regenerate_and_notify",
  "human_review_required": true,
  "safe_to_reuse": false
}
```

### 3.3 change summary item

```json
{
  "source_url": "https://...",
  "source_kind": "call_guideline_pdf",
  "publisher": "official_primary",
  "previous": {
    "source_fetched_at": "2026-05-10T09:00:00+09:00",
    "source_checksum": "sha256:old",
    "last_modified_at": null
  },
  "current": {
    "source_fetched_at": "2026-05-15T13:45:00+09:00",
    "source_checksum": "sha256:new",
    "last_modified_at": "2026-05-15T11:30:00+09:00"
  },
  "change_type": "pdf_replaced",
  "materiality": "high",
  "changed_fields": [
    {
      "field": "application_deadline",
      "previous_value": "2026-06-14",
      "current_value": "2026-05-31",
      "risk": "deadline_moved_earlier"
    }
  ],
  "diff_receipt_id": "diff_..."
}
```

## 4. stale 判定

### 4.1 判定ステータス

- `fresh`: 現在の保存 source と照合でき、重要フィールド差分なし。回答再利用は可能。ただし専門判断は別。
- `caution`: 軽微な変更、取得日時の古さ、FAQ の非重要項目変更、構造化 confidence 低下など。表示時に「再確認推奨」。
- `stale`: 重要フィールド、根拠 PDF、法令施行日、受付期限、対象者、金額、提出書類、併用可否に差分。再生成または人手確認まで外部向け回答に使わない。
- `blocked`: 一次情報に到達不能、PDF が消滅、robots / 403 / hash 不一致で検証不能、法令 status が廃止/未施行へ変化、または根拠 URL が別内容に置換。自動回答を止める。

### 4.2 stale reason codes

- `source_age_exceeded`: source_fetched_at が policy の freshness SLA を超過。
- `source_unreachable`: 取得失敗。404/410 は high、5xx/timeouts は medium から開始。
- `source_checksum_changed`: 正規化本文または PDF bytes の checksum が変化。
- `critical_source_checksum_changed`: importance=critical の source が変化。
- `last_modified_changed`: HTTP Last-Modified / ETag / ページ表示更新日が変化。
- `pdf_replaced`: PDF bytes hash が変化。
- `pdf_attachment_added`: 新しい要領・様式 PDF が追加。
- `pdf_attachment_removed`: 既存 PDF が消滅。
- `deadline_field_changed`: 締切・受付期間が変化。
- `deadline_moved_earlier`: 締切が早まった。
- `amount_field_changed`: 補助上限、補助率、対象経費が変化。
- `eligibility_field_changed`: 対象者、地域、業種、認定要件が変化。
- `exclusion_or_compatibility_changed`: 併用不可、排他、前提条件が変化。
- `required_document_changed`: 提出書類、様式、添付資料が変化。
- `faq_answer_changed`: FAQ 回答が変化。
- `law_effective_date_changed`: 施行日・改正日・廃止日が変化。
- `law_text_changed`: 条文または引用根拠が変化。
- `source_redirect_changed`: canonical URL または redirect 先が変化。
- `claim_source_missing`: AI 回答の claim_ref が現行 source に接続できない。
- `answer_claim_unanchored`: AI 回答に claim_refs がなく、差分影響を特定できない。

### 4.3 重要度

`materiality` は差分の大きさではなく、回答・業務判断に与える影響で決める。

- `critical`: 締切前倒し、募集停止、対象者除外、法令廃止/施行日変更、上限額/補助率変更、提出必須書類変更、URL 消滅。
- `high`: FAQ の実務回答変更、様式差し替え、併用可否変更、審査基準変更。
- `medium`: 受付窓口、提出先、問い合わせ先、軽微な対象経費説明、表現変更。
- `low`: 誤字、レイアウト、見出し、問い合わせ電話番号の表記揺れ。ただし source_receipt には残す。

### 4.4 鮮度 SLA の初期値

| source_kind | freshness SLA | stale 判定 |
| --- | ---: | --- |
| `call_guideline_pdf` | 24 時間 | checksum 差分または 24h 超過で `caution`、重要 field 差分で `stale` |
| `program_page` | 72 時間 | 72h 超過で `caution`、期限・金額・対象者差分で `stale` |
| `faq_page` | 7 日 | FAQ 回答差分で `caution` 以上、申請可否に関わる回答なら `stale` |
| `law_page` / `law_xml` | 7 日 | 改正日・施行日・条文差分で `stale`、廃止/未施行は `blocked` |
| `form_pdf` | 7 日 | 必須様式差し替えは `high`、任意様式は `medium` |
| `notice_page` | 24 時間 | 募集停止・採択結果・追加公募は `high` 以上 |
| `api_json` | 24 時間 | schema drift は `blocked`、value drift は field 重要度で判定 |

既存 `known_gaps.source_stale` の 90 日閾値は汎用 Evidence Packet の薄さ検出として残す。この packet では業務用途別に短い SLA を持つ。つまり `source_stale` は最低限の品質 gap、`Change / Stale Refresh` は実務運用の再確認 trigger である。

### 4.5 判定式

```text
artifact_stale_score =
  0.30 * source_change_score
+ 0.25 * critical_field_impact_score
+ 0.15 * answer_claim_impact_score
+ 0.10 * source_age_score
+ 0.10 * source_reachability_risk
+ 0.10 * extraction_confidence_drop

safe_to_reuse = (
  artifact_stale_score < 0.35
  AND no critical reason code
  AND all critical claim_refs are source-linked
)
```

ステータス変換:

- `< 0.20`: `fresh`
- `0.20 - 0.34`: `caution`
- `0.35 - 0.74`: `stale`
- `>= 0.75` または critical blocker: `blocked`

## 5. 再生成・通知・人手確認

### 5.1 action routing

| 状態 | 自動処理 | 通知 | 人手確認 |
| --- | --- | --- | --- |
| `fresh` | なし | なし、または週次 digest | 不要 |
| `caution` | 必要なら lightweight regenerate | digest | policy 次第 |
| `stale` | `regenerate_packet` を queue | 即時または日次 | high 以上は必要 |
| `blocked` | 外部向け再利用停止、fallback 表示 | 即時 | 必須 |

### 5.2 再生成キュー item

```json
{
  "job_id": "regen_...",
  "job_type": "regenerate_packet",
  "priority": "high",
  "artifact_id": "evp_...",
  "template_id": "application_strategy_pack_v1",
  "reason_codes": ["deadline_field_changed"],
  "cost_preview": {
    "estimated_billable_units": 4,
    "estimated_cost_jpy_excl_tax": 12,
    "cost_cap_jpy_excl_tax": 100
  },
  "idempotency_key": "regen:evp_...:sha256_new",
  "requires_human_review_before_publish": true
}
```

### 5.3 差分通知

通知本文は「変更があった」だけでは足りない。最低限、以下を含める。

- 対象制度・法令・公募名。
- 変更 source と取得時刻。
- 影響を受ける packet / AI 回答 / UI 表示。
- 変更前後の値。
- 推奨 action。
- `unknown != safe` の明示。
- 人手確認が必要な理由。

通知先:

- `webhook`: SaaS / agent workflow 向け。
- `email_digest`: 士業・顧問先レビュー向け。
- `slack`: 社内運用向け。
- `dashboard_inbox`: jpcite dashboard 上の再確認 queue。
- `api_polling`: `GET /v1/watch/events` による pull。

### 5.4 人手確認 queue

人手確認に回す条件:

- `deadline_moved_earlier`
- `amount_field_changed`
- `eligibility_field_changed`
- `exclusion_or_compatibility_changed`
- `law_text_changed`
- `law_effective_date_changed`
- `required_document_changed`
- `source_unreachable` が critical source で発生
- `answer_claim_unanchored` かつ外部送信済み回答

review item:

```json
{
  "review_id": "rev_...",
  "review_kind": "stale_refresh",
  "artifact_id": "ans_...",
  "severity": "high",
  "review_questions": [
    "締切が 2026-06-14 から 2026-05-31 に変わっています。顧客通知が必要ですか。",
    "旧回答の「申請準備は6月上旬まででよい」は撤回または修正が必要ですか。"
  ],
  "suggested_disposition": "revise_answer_and_notify_client",
  "blocked_until_reviewed": true
}
```

## 6. API

### 6.1 REST

Catalog:

- `GET /v1/packets/catalog`
- `GET /v1/packets/catalog/change_stale_refresh_trigger_pack_v1`

Create:

- `POST /v1/packets/change-stale-refresh`

Preview:

- `POST /v1/packets/change-stale-refresh/preview`

Watch registration:

- `POST /v1/watch/subscriptions`
- `GET /v1/watch/subscriptions`
- `PATCH /v1/watch/subscriptions/{subscription_id}`
- `DELETE /v1/watch/subscriptions/{subscription_id}`

Events:

- `GET /v1/watch/events?since=...&severity=...&cursor=...`
- `GET /v1/watch/events/{event_id}`
- `POST /v1/watch/events/{event_id}/ack`

Regeneration:

- `POST /v1/packets/{packet_id}/refresh-preview`
- `POST /v1/packets/{packet_id}/refresh`
- `GET /v1/packets/refresh-jobs/{job_id}`

Stored answer impact:

- `POST /v1/answer-artifacts`
- `GET /v1/answer-artifacts/{answer_id}/stale-status`
- `POST /v1/answer-artifacts/{answer_id}/stale-check`

### 6.2 MCP tools

- `createChangeStaleRefreshTriggerPack`
- `previewChangeStaleRefreshCost`
- `registerSourceWatch`
- `listWatchEvents`
- `ackWatchEvent`
- `refreshEvidencePacket`
- `checkAnswerStaleness`

Tool descriptions must include:

- “detects source changes and stale risk”
- “does not decide legal/tax/application correctness”
- “unknown is not safe”
- “returns recommended regeneration and human review actions”

### 6.3 Webhook event payload

```json
{
  "event_id": "evt_...",
  "event_type": "packet.stale",
  "occurred_at": "2026-05-15T14:10:00+09:00",
  "severity": "high",
  "subject": {
    "kind": "program",
    "id": "program_..."
  },
  "artifact": {
    "artifact_id": "evp_...",
    "artifact_kind": "evidence_packet"
  },
  "reason_codes": ["deadline_field_changed"],
  "source_receipts": [
    {
      "source_url": "https://...",
      "previous_checksum": "sha256:old",
      "current_checksum": "sha256:new",
      "source_fetched_at": "2026-05-15T13:45:00+09:00"
    }
  ],
  "recommended_action": "regenerate_and_notify",
  "human_review_required": true,
  "packet_url": "/v1/watch/events/evt_..."
}
```

## 7. イベント型

Source events:

- `source.created`
- `source.changed`
- `source.removed`
- `source.unreachable`
- `source.redirect_changed`
- `source.reachable_again`
- `source.metadata_changed`

Document events:

- `document.checksum_changed`
- `document.pdf_replaced`
- `document.pdf_attachment_added`
- `document.pdf_attachment_removed`
- `document.extraction_failed`
- `document.extraction_confidence_dropped`

Domain events:

- `program.deadline_changed`
- `program.deadline_moved_earlier`
- `program.amount_changed`
- `program.eligibility_changed`
- `program.required_documents_changed`
- `program.compatibility_changed`
- `program.closed_or_suspended`
- `program.reopened`
- `faq.answer_changed`
- `law.text_changed`
- `law.effective_date_changed`
- `law.status_changed`

Artifact events:

- `packet.caution`
- `packet.stale`
- `packet.blocked`
- `answer.caution`
- `answer.stale`
- `answer.blocked`
- `ui_copy.stale`

Workflow events:

- `regeneration.previewed`
- `regeneration.queued`
- `regeneration.completed`
- `regeneration.failed`
- `notification.sent`
- `notification.failed`
- `human_review.required`
- `human_review.completed`
- `watch_event.acknowledged`

## 8. known_gaps

この packet 固有の `known_gaps`:

- `source_unreachable`: 公式 source に到達できない。
- `source_timestamp_missing`: 公表日・更新日が source に明示されていない。
- `source_checksum_missing`: 旧 packet / answer に checksum がないため厳密比較できない。
- `answer_claim_refs_missing`: AI 回答と source field の対応がない。
- `pdf_text_extraction_low_confidence`: PDF 抽出品質が低い。
- `pdf_scanned_image`: OCR が必要で差分精度が落ちる。
- `javascript_render_required`: 静的取得では source 本文が得られない。
- `semantic_diff_unavailable`: checksum 差分はあるが field-level 差分を抽出できない。
- `law_mapping_incomplete`: 制度と根拠法令の link が不完全。
- `faq_structure_changed`: FAQ の質問単位対応が崩れた。
- `duplicate_source_candidates`: 同一制度に複数の canonical source 候補がある。
- `removed_source_not_confirmed`: source が消えたが、移転・終了・一時障害を判定できない。
- `notification_destination_missing`: 通知先が未設定。
- `regeneration_budget_cap_exceeded`: 再生成見積が上限を超えた。
- `human_review_queue_unconfigured`: 人手確認の受け皿が未設定。

`known_gaps` は packet top-level と該当 section に重複して出す。AI agent は `known_gaps` を隠して外部向け断定に使ってはいけない。

## 9. MVP

### 9.1 MVP スコープ

P0:

- 保存済み Evidence Packet の `sources[]`, `source_receipts[]`, `records[]` に対する stale check。
- source URL の HEAD/GET、ETag、Last-Modified、checksum 比較。
- HTML 正規化本文 hash、PDF bytes hash、PDF text hash の保存。
- 重要 field の deterministic diff。
- `packet.stale`, `packet.blocked`, `regeneration.queued`, `human_review.required` events。
- `POST /v1/packets/change-stale-refresh` と `GET /v1/watch/events`。
- webhook 1 種類。
- `known_gaps` と `safe_to_reuse` を返す。

P1:

- AI 回答 artifact 登録と `claim_refs` ベースの stale 判定。
- FAQ question-answer pair 単位の diff。
- 法令 XML / e-Gov mirror の改正日・施行日 diff。
- Slack / email digest。
- dashboard review queue。

P2:

- 自動再生成後の old/new packet 比較。
- 顧問先別・案件別 stale digest。
- UI copy safety packet との連携。
- semantic diff の精度改善。
- source canonicalization と duplicate source merge。

### 9.2 MVP でやらないこと

- 全官公庁サイトのリアルタイム監視保証。
- 公式発表と同時の push 配信保証。
- 法的・税務的に「正しい」変更解釈。
- AI 回答本文からの自由な claim 抽出。MVP では caller が `claim_refs` を渡す。
- PDF OCR の完全対応。
- 民間 aggregator の網羅監視。

## 10. 価格

公開価格の前提は既存 jpcite と同じ。

- 1 billable unit = 税別 ¥3、税込 ¥3.30。
- 匿名は 3 req/日 free。
- 通常の単発作成は最低 1 unit。
- batch / watch / refresh は実行前に `estimated_billable_units` と `X-Cost-Cap-JPY` で上限を明示する。

推奨 billing formula:

```text
change_stale_refresh_units =
  1
+ ceil(source_probe_count / 10)
+ ceil(pdf_diff_count / 3)
+ ceil(impacted_artifact_count / 25)
+ regeneration_units
```

例:

- 1 制度、HTML 1、PDF 1、既存 packet 1 件確認: `1 + 1 + 1 + 1 = 4 units`、税別 ¥12、税込 ¥13.20。
- 50 制度の週次 watch、source 120、PDF 30、artifact 500: `1 + 12 + 10 + 20 = 43 units`、税別 ¥129、税込 ¥141.90。
- 再生成込みの場合は、各 regenerated packet の既存 unit formula を加算する。

価格表示で言ってよいこと:

- 「長い PDF を毎回 LLM に読ませる前に、変更影響だけを packet 化する」
- 「再生成前に cost preview と budget cap を返す」
- 「LLM の出力 token / reasoning / cache / search 料金は含まない」

言ってはいけないこと:

- 「AI 費用を必ず削減する」
- 「制度変更を必ず即時検知する」
- 「古い回答の法的責任を自動で解消する」

## 11. 境界線

### 11.1 できること

- 公開 source の取得時点、checksum、差分、到達可能性を記録する。
- 既存 packet / answer が参照している source と現在 source を照合する。
- stale / blocked の機械判定を出す。
- 再生成 queue、通知、review queue を作る。
- known gaps を明示する。
- 監査用に old/new checksum、diff receipt、event id を残す。

### 11.2 できないこと

- 法令・制度の個別具体的な解釈を確定する。
- 申請可否、採択可能性、税務効果、法的適合性を断定する。
- 公式 source の完全性や即時性を保証する。
- source から削除された情報の意味を断定する。
- claim_refs のない過去 AI 回答について、全主張を高精度に stale 判定する。
- 顧客への法定通知や専門家レビューを代替する。

### 11.3 AI agent 向け禁止表現

- 「この制度は現在も使えます」
- 「申請できます」
- 「法的に問題ありません」
- 「変更はありません」
- 「この回答は最新です」

代替表現:

- 「登録済み source との差分は検出されていません」
- 「重要フィールドの変更は検出されていません」
- 「次の source は再確認が必要です」
- 「この回答は stale 判定のため再生成または人手確認が必要です」

## 12. 実装メモ

### 12.1 DB tables

新規 table 案:

- `source_snapshot`: URL、normalized checksum、raw checksum、fetched_at、HTTP metadata、extraction metadata。
- `source_diff`: old snapshot / new snapshot / field-level diff / receipt。
- `watch_subscription`: scope、policy、notification settings、budget cap。
- `watch_event`: event_type、severity、subject、artifact、reason_codes、ack status。
- `artifact_source_ref`: packet / answer / ui_copy と source / field / claim の対応。
- `refresh_job`: regeneration queue、idempotency key、cost preview、status。
- `human_review_item`: review queue。

既存 `evidence_packet` persistence がある場合、`artifact_source_ref` は `evidence_packet.sources[]` と `records[].citations[]` から派生生成する。

### 12.2 idempotency

同じ source checksum 変化で重複再生成しない。

```text
idempotency_key =
  "stale:" + artifact_id + ":" + current_source_checksum + ":" + template_version
```

### 12.3 false positive / false negative 方針

- 公募・法令・申請系では false negative を避ける。迷ったら `caution` 以上。
- `blocked` は UX 影響が大きいので、critical source の到達不能、source 消滅、schema drift、法令 status 変更に限定する。
- `caution` は安価に多めに出し、通知 policy で digest に逃がす。

## 13. カタログ差し込み案

既存の #29 `agent_system_prompt_guard` は #31 以降へ移動し、AI 開発者・SaaS・エージェント開発者向けの #29 を以下に差し替える。

#### 29. change_stale_refresh_trigger_pack

制度・法令・公募要領・FAQ・PDF の更新を検知し、既存 packet / AI 回答 / UI copy の stale 判定、再生成 queue、差分通知、人手確認 queue を返す。

Output sections:

- `change_summary`
- `stale_decisions`
- `impacted_packets`
- `impacted_answers`
- `regeneration_plan`
- `notifications`
- `human_review_queue`
- `known_gaps`

Primary buyer:

- AI SaaS、士業システム、顧問先レビュー運用、金融/M&A DD workflow。

MVP:

- packet-level stale 判定、source checksum diff、critical field diff、webhook、refresh queue。

Boundary:

- 変更検知と影響整理まで。法令解釈・申請判断・税務判断・公式即時性保証はしない。
