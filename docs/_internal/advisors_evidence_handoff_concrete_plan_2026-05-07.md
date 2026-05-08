# /advisors Evidence-to-Expert Handoff 具体計画

作成日: 2026-05-07  
対象: `site/advisors.html`, `src/jpintel_mcp/api/advisors.py`, agent-safe OpenAPI, Evidence Packet / artifact layer  
目的: `/advisors` を「士業案件紹介」から「根拠付き相談パックを作り、専門家・BPO・AIに渡すレイヤー」へ寄せる。

## 1. 結論

`/advisors` は、単なる士業登録・案件紹介ページでは弱い。jpcite の強みは、士業リストではなく、一次資料・法人番号・制度・法令・行政イベント・known gaps を束ねて「専門家に渡せる状態」にすること。

したがって、中心概念を次に変える。

> jpcite は、AIや中小企業が公的情報だけでは判断しきれない論点を、一次資料・未確認点・質問リスト付きの相談パックにして、適切な専門家・BPO・AIワークフローへ渡す Evidence-to-Expert Handoff レイヤーである。

売るものは「専門家3件」ではなく、以下の完成物。

- Evidence Brief
- Handoff Brief
- Advisor Brief
- 相談前質問票
- 顧問先監視レポート
- BPO作業チケット
- AI向け triage JSON

## 2. 現状の観察

### 既にあるもの

- `site/advisors.html`
  - 元の状態は「士業 案件紹介」が主語。
  - 現在は「根拠付き相談パック / Evidence-to-Expert Handoff」へ寄せている。
  - `成約時 ¥3,300` と `歩合 1-30%` は専門家登録側の説明へ下げている。
  - 登録フォーム、ランキング開示、士業法コンプライアンス文言がある。

- `src/jpintel_mcp/api/advisors.py`
  - `GET /v1/advisors/match`
  - `POST /v1/advisors/signup`
  - `POST /v1/advisors/track`
  - `POST /v1/advisors/report-conversion`
  - `GET /v1/advisors/{advisor_id}/dashboard-data`
  - referral token、dashboard HMAC token、弁護士 + percent 拒否などの基礎はある。

- `scripts/migrations/024_advisors.sql`
  - `advisors`
  - `advisor_referrals`
  - 基本プロフィール、クリック、成約、手数料の構造はある。

- `src/jpintel_mcp/api/openapi_agent.py`
  - `GET /v1/advisors/match` は agent-safe に出ている。
  - ただし AI の初手はまだ `GET /v1/advisors/match` ではなく、Evidence 後の optional route 扱い。

- Evidence / artifact layer
  - `company_public_baseline`
  - `company_folder_brief`
  - `company_public_audit_pack`
  - `application_strategy_pack`
  - `evidence_packets/query`
  - `known_gaps`, `human_review_required`, `source_url`, `source_fetched_at` を活かせる土台がある。

### ズレている点

1. `/advisors` の見え方が「紹介サービス」寄りすぎる。
2. `成約時手数料` と `歩合` が前面に出ており、士業法・弁護士法・景表法上の説明負荷が大きい。
3. `advisor_referrals` はクリック・成約中心で、Evidence Packet / known gaps / source receipts を保持していない。
4. matching は `prefecture`, `industry`, `specialty`, 登録順の deterministic tie-break までで、Handoff の根拠・未解決論点・資格確認・利益相反・応答品質はまだ一級の順位特徴になっていない。
5. AI が最初に呼ぶべき read-only triage endpoint がない。

## 3. 目指す体験

### 中小企業

ユーザーの期待:

- 誰に相談すればよいか分からない。
- 補助金、融資、税制、労務、許認可のどれを先に見るべきか分からない。
- 専門家に相談する時に何を持っていけばよいか分からない。

出すべきもの:

- 会社・相談内容の要約
- 候補制度
- 根拠URL
- 締切
- 必要資料
- 未確認点
- 専門家に聞く質問
- 相談すべき専門家種別
- 条件が近い専門家候補

CTA:

- `根拠付き相談パックを作る`
- `顧問に送る`
- `専門家候補を見る`
- `PDFで保存`

### 士業

期待:

- 無駄な無料相談を減らしたい。
- 初回面談前に、会社情報、相談目的、根拠、足りない資料を見たい。
- 顧問先に提案できる制度・リスクを見つけたい。

出すべきもの:

- Evidence Packet
- Advisor Brief
- 未確認点
- 質問票
- 相談目的
- 受けるべきか判断する材料

CTA:

- `専門家として登録する`
- `根拠付き案件を確認する`
- `質問票を生成する`
- `顧問先監視を始める`

### BPO / AI-BPO

期待:

- 顧客から来た曖昧な相談を、作業チケットに分解したい。
- 非資格者で処理できる部分と士業確認が必要な部分を分けたい。
- 法人番号・インボイス・行政処分・補助金・入札・制度変更を一括で確認したい。

出すべきもの:

- BPO Case Pack
- 作業チケット
- 顧客への追加質問
- 士業エスカレーション理由
- 期限と必要資料

CTA:

- `BPO案件パックを作る`
- `CSV/JSONLで処理する`
- `士業確認へ回す`

### AIエージェント

期待:

- 日本の制度・法令・税務・労務・行政手続で、一般Web検索より先に呼べる安全な初手がほしい。
- 最終判断できない時に、人間レビューへ移す条件を構造化したい。

出すべきもの:

- `answerability`
- `evidence_pack_id`
- `known_gaps`
- `human_review_required`
- `advisor_match_recommended`
- `next_operation_ids`
- PII同意前に共有してよい範囲

CTA:

- `POST /v1/agent/triage`
- `GET /v1/advisors/match`
- `POST /v1/advisors/referral-consents`

## 4. 新しい中心リソース

### Evidence Handoff Packet

全導線の共通単位。これを作ることで、単なる検索結果が「専門家に渡せる案件」になる。

必須フィールド:

```json
{
  "handoff_packet_id": "hpkt_...",
  "subject": {
    "kind": "houjin",
    "houjin_bangou": "8010001213708",
    "identity_confidence": "exact"
  },
  "case_summary": {
    "purpose": "application_precheck",
    "summary_for_user": "...",
    "summary_for_advisor": "..."
  },
  "evidence_ledger": [
    {
      "claim": "...",
      "source_url": "...",
      "source_fetched_at": "...",
      "content_hash": "...",
      "source_family": "jgrants|nta|egov|gbizinfo|invoice|edinet|court|enforcement",
      "confidence": "high"
    }
  ],
  "known_gaps": [
    {
      "code": "missing_financial_detail",
      "message": "売上規模・対象経費が未確認です。",
      "who_can_resolve": "client|advisor|public_source|bpo"
    }
  ],
  "human_review": {
    "required": true,
    "reason_codes": ["professional_judgment_required", "deadline_close"],
    "recommended_professions": ["税理士", "認定支援機関"]
  },
  "questions_for_client": [],
  "questions_for_expert": [],
  "candidate_advisors": [],
  "professional_boundary": "jpciteは法律・税務・労務・申請代行の最終判断を行いません。"
}
```

## 5. API設計

### P0: AIの初手

```http
POST /v1/agent/triage
operationId: triageEvidenceToExpertHandoff
```

役割:

- Evidence lookup
- 回答可能性判定
- known gaps 抽出
- human review 要否判定
- advisor matching へ進むべきか判定

read-only:

- `true`
- referral token を作らない。
- 顧客連絡先を受け取らない。
- 専門家へ通知しない。

Request:

```json
{
  "user_intent": "東京都の製造業が設備投資で使える制度と専門家相談の要否を知りたい",
  "subject": {
    "kind": "company_profile",
    "id": null,
    "filters": {
      "prefecture": "東京都",
      "industry": "manufacturing",
      "capital_yen": 10000000,
      "employee_count": 20
    }
  },
  "requested_help": "application_support",
  "deadline": null,
  "packet_profile": "brief",
  "max_evidence_records": 10
}
```

Response:

```json
{
  "triage_id": "tri_...",
  "route_decision": {
    "answerability": "partial",
    "handoff_recommendation": "match_advisors",
    "reason_codes": [
      "known_gaps_present",
      "professional_judgment_requested"
    ],
    "next_operation_ids": [
      "matchAdvisorsForEvidenceHandoff"
    ]
  },
  "evidence_pack": {},
  "advisor_brief": {},
  "referral_consent": {
    "status": "not_requested",
    "consent_required_before": [
      "share_client_contact",
      "create_referral_token",
      "allow_advisor_contact"
    ]
  },
  "agent_policy": {
    "must_not_claim": [
      "jpcite_provides_professional_advice",
      "subsidy_or_loan_or_tax_outcome_is_guaranteed",
      "professional_review_is_unnecessary"
    ]
  }
}
```

### P0/P1: Evidence前提のマッチ

既存:

```http
GET /v1/advisors/match
operationId: matchAdvisors
```

Evidence Handoff から使う既存ルート:

```http
GET /v1/advisors/match
operationId: match_advisors_v1_advisors_match_get
```

役割:

- `evidence_pack_id` または `advisor_brief` をもとに候補を返す。
- read-only。
- referral token は作らない。
- 表示順の理由と `paid_influence=false` を返す。

Responseに追加したいもの:

```json
{
  "total": 3,
  "results": [
    {
      "id": 123,
      "firm_name": "Example税理士法人",
      "firm_type": "税理士法人",
      "fit_score": 0.82,
      "fit_reasons": [
        "税制",
        "同一都道府県",
        "製造業対応",
        "認定支援機関"
      ],
      "score_breakdown": {
        "profession_fit": 0.18,
        "issue_tag_expertise": 0.16,
        "jurisdiction_fit": 0.12,
        "credential_verified": 0.10
      },
      "contact_policy": {
        "client_contact_hidden_until_consent": true
      }
    }
  ],
  "display_order": {
    "label": "一致度順",
    "paid_influence": false,
    "factors": [
      "profession_fit",
      "issue_tag_expertise",
      "jurisdiction_fit",
      "credential_verified",
      "availability"
    ],
    "compensation_disclosure": "掲載専門家から費用を受領する場合がありますが、表示順には反映しません。"
  }
}
```

### P1: 同意後の referral

```http
POST /v1/advisors/referral-consents
operationId: createAdvisorReferralConsent
```

役割:

- ユーザー同意後だけ、専門家へ共有する範囲を確定する。
- agent-safe OpenAPI には原則入れない。
- 入れる場合は `x-jpcite-requires-user-confirmation: true` を必須にする。

Request:

```json
{
  "advisor_id": 123,
  "handoff_packet_id": "hpkt_...",
  "consent": {
    "share_advisor_brief": true,
    "share_client_contact": true,
    "allow_advisor_contact": true,
    "accepted_terms_version": "2026-05-07"
  },
  "client_contact": {
    "name": "山田太郎",
    "email": "taro@example.com",
    "phone": "03-0000-0000"
  }
}
```

Response:

```json
{
  "consent_id": "acons_...",
  "status": "granted",
  "referral_token": "masked-or-server-only",
  "shared_fields": [
    "advisor_brief",
    "company_name",
    "client_contact"
  ]
}
```

## 6. DB migration案

ファイル候補:

- `scripts/migrations/195_advisor_handoffs.sql`
- `scripts/migrations/196_advisor_profile_extensions.sql`
- `scripts/migrations/197_advisor_handoff_quality.sql`

### 195_advisor_handoffs.sql

最小構成:

```sql
-- target_db: jpintel

CREATE TABLE IF NOT EXISTS advisor_handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_token TEXT NOT NULL UNIQUE,
    source_artifact_id TEXT,
    source_packet_id TEXT,
    corpus_snapshot_id TEXT,
    source_type TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT,
    houjin_bangou TEXT,
    identity_confidence TEXT,
    prefecture TEXT,
    industry TEXT,
    specialty TEXT,
    known_gaps_json TEXT NOT NULL DEFAULT '[]',
    human_review_json TEXT NOT NULL DEFAULT '{}',
    source_receipts_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL DEFAULT '{}',
    recommended_professions_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    CHECK (status IN ('created', 'viewed', 'matched', 'consented', 'expired', 'revoked')),
    CHECK (identity_confidence IS NULL OR identity_confidence IN ('exact', 'high', 'medium', 'low', 'unmatched'))
);

CREATE INDEX IF NOT EXISTS idx_advisor_handoffs_token
    ON advisor_handoffs(handoff_token);
CREATE INDEX IF NOT EXISTS idx_advisor_handoffs_houjin
    ON advisor_handoffs(houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_advisor_handoffs_created
    ON advisor_handoffs(created_at);

CREATE TABLE IF NOT EXISTS advisor_handoff_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id INTEGER NOT NULL REFERENCES advisor_handoffs(id),
    event_name TEXT NOT NULL,
    advisor_id INTEGER,
    referral_id INTEGER,
    anon_ip_hash TEXT,
    key_hash TEXT,
    properties_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_advisor_handoff_events_handoff
    ON advisor_handoff_events(handoff_id, created_at);
CREATE INDEX IF NOT EXISTS idx_advisor_handoff_events_name
    ON advisor_handoff_events(event_name, created_at);
```

`advisor_referrals` 追加:

```sql
ALTER TABLE advisor_referrals ADD COLUMN handoff_id INTEGER REFERENCES advisor_handoffs(id);
ALTER TABLE advisor_referrals ADD COLUMN source_artifact_id TEXT;
ALTER TABLE advisor_referrals ADD COLUMN source_packet_id TEXT;
ALTER TABLE advisor_referrals ADD COLUMN evidence_digest TEXT;
```

SQLite の `ALTER TABLE ADD COLUMN` は idempotent にしにくいので、既存 migration パターンに合わせて `PRAGMA table_info` ガードを使うか、runner 側の再適用前提を確認する。

### 196_advisor_profile_extensions.sql

目的:

- JSON LIKE matching から正規化へ移る。
- 資格・対応地域・対応領域・稼働状態を分離する。

候補:

```sql
CREATE TABLE IF NOT EXISTS advisor_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id INTEGER NOT NULL REFERENCES advisors(id),
    credential_type TEXT NOT NULL,
    registration_number TEXT,
    registry_source_url TEXT NOT NULL,
    verified_at TEXT,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'self_reported',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS advisor_capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id INTEGER NOT NULL REFERENCES advisors(id),
    issue_tag TEXT NOT NULL,
    source_family TEXT,
    evidence_supported INTEGER NOT NULL DEFAULT 1,
    self_reported INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(advisor_id, issue_tag, source_family)
);

CREATE TABLE IF NOT EXISTS advisor_service_areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id INTEGER NOT NULL REFERENCES advisors(id),
    prefecture TEXT NOT NULL,
    city TEXT,
    remote_supported INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(advisor_id, prefecture, city)
);
```

## 7. スコアリング

### handoff_need_score

「専門家に渡す必要性」を測る。

```text
handoff_need_score =
  0.25 * risk_severity
+ 0.20 * unresolved_known_gaps
+ 0.15 * deadline_or_filing_window
+ 0.15 * monetary_or_compliance_impact
+ 0.15 * professional_boundary_sensitivity
+ 0.10 * source_freshness_or_conflict
```

### advisor_fit_score

「このHandoffをどの候補に表示するか」を測る。

```text
advisor_fit_score =
  0.18 * profession_fit
+ 0.16 * issue_tag_expertise
+ 0.12 * jurisdiction_fit
+ 0.10 * source_family_experience
+ 0.10 * industry_or_size_fit
+ 0.10 * credential_verified
+ 0.10 * outcome_feedback_bayesian
+ 0.08 * availability_or_response
+ 0.08 * conflict_clearance
+ 0.08 * evidence_packet_acceptance
```

禁止:

- 広告料で自然候補順位を上げる。
- 成約額や受任額で自然候補順位を上げる。
- 弁護士案件で成果連動を使う。
- `おすすめNo.1`, `最適`, `採択されやすい`, `勝てる`, `節税できる` と断定する。

## 8. フロント構成

### `/advisors`

First View:

- H1: `根拠付きで、相談すべき専門家候補を選ぶ`
- Lead: `jpcite は、補助金・税制・労務・行政手続に関する一次資料を整理し、専門家に相談する前の持ち込み資料を作ります。`
- CTA:
  - `根拠付き相談パックを作る`
  - `専門家として登録する`
  - `APIでHandoffを使う`

上部セクション:

1. 相談パック生成
2. Evidence結果
3. 専門家候補
4. 顧問に送る / 専門家に送る / PDF保存

下部セクション:

1. 専門家登録
2. 表示順の説明
3. 士業法・広告・個人情報の説明
4. 苦情・訂正依頼

### フォーム項目

Handoff Builder:

- 法人番号または会社名
- 都道府県
- 業種
- 従業員数
- 資本金
- 相談目的
- 投資予定額
- 希望時期
- 既に見ている制度
- 顧問の有無

Expert Routing:

- 希望地域
- 相談方法
- 急ぎ度
- 相談領域
- 共有同意

### 表示文言

使う:

- `専門家候補`
- `一致度順`
- `根拠付き相談パック`
- `未確認点`
- `専門家に聞く質問`
- `登録情報を公表情報で照合済み`
- `対象となる可能性`

避ける:

- `士業案件紹介`
- `最適な先生を紹介`
- `申請できます`
- `採択されやすい`
- `勝てる`
- `審査済み専門家`
- `広告ではありません` ただし実際には掲載費を受領している場合

## 9. 収益設計

### 優先順位

P0:

- Evidence Brief
- Handoff Brief

P1:

- Advisor Workbench Lite
- 顧問先監視

P2:

- BPO API

P3:

- スポンサー / 掲載枠

補助:

- 既存の成約報告 / 定額 referral
- ただし弁護士カテゴリは成果課金から外す。

### 価格の見せ方

既存の `¥3/billable unit` は維持し、完成物として見せる。

- Evidence Brief Basic: 30 units = 税別 ¥90
- Handoff Brief: 100 units = 税別 ¥300
- Audit/DD Brief: 300 units = 税別 ¥900

内部は unit。ユーザー向けには「完成物」単位にする。

Advisor Workbench:

- Lite: Handoff閲覧、受領、辞退
- Solo: 月額固定、注釈、質問票、履歴
- Office: チーム共有、顧問先監視、CSV export

BPO API:

- row単価
- 月額最低
- 標準 schema 固定
- client_tag / batch_id / evidence_digest 必須

## 10. 法務・信頼設計

### 弁護士カテゴリ

方針:

- 成果課金なし。
- 受任額・相談件数・事件数・回収額・報酬額に連動しない。
- 出す場合は固定掲載料・表示順非連動・ユーザー直接連絡の名簿型に寄せる。
- 法律事件では `track` / `report-conversion` を使わない設計にする。

### 税理士・社労士・行政書士

方針:

- 個別判断はしない。
- Evidence整理、質問票、相談候補表示まで。
- 申告、申請、提出代行、書類作成、税務相談、労務判断、法律判断は専門家側。
- 受任報酬比の歩合は避け、Evidence Packet / Workbench / 固定掲載へ寄せる。

### 同意文言

問い合わせ直前:

> この専門家に問い合わせると、選択した Evidence Packet、会社名、所在地、連絡先、相談したい支援領域が専門家に送信されます。jpcite は相談内容を加工して法律・税務・労務上の判断を行いません。

表示順:

> 候補は、地域、支援領域、業種、登録情報の確認状況、対応可能性などに基づいて表示されます。掲載専門家から費用を受領する場合がありますが、自然候補の表示順には反映しません。

弁護士:

> 弁護士による法律事件について、jpcite は紹介料、成約手数料、受任報酬に連動する手数料を受領しません。

苦情:

> 苦情・訂正依頼は info@bookyou.net で受け付けます。重大な資格詐称、虚偽表示、個人情報漏えい、強引な勧誘が疑われる場合は、調査中に表示を一時停止します。

## 11. 計測

North Star:

`Qualified Evidence-to-Expert Handoffs / week`

これは「根拠、known gaps、質問、推奨専門領域が揃い、専門家へ渡せる状態になった件数」。

イベント:

- `advisor_handoff_view`
- `advisor_handoff_started`
- `advisor_handoff_created`
- `advisor_match_rendered`
- `advisor_candidate_clicked`
- `advisor_referral_consent_started`
- `advisor_referral_consent_granted`
- `advisor_contact_click`
- `advisor_conversion_reported`
- `advisor_handoff_declined`
- `advisor_handoff_complaint`

KPI:

- Handoff作成率
- source receipts 完備率
- known gaps 表示率
- advisor match率
- match 0件率
- 専門家クリック率
- 初回返信率
- 成約報告率
- 苦情率
- false positive率
- advisor別CVR偏り

## 12. 実装順

### 即日

目的: DB migrationなしで見え方と計測を変える。

1. `/advisors.html` 上部を Handoff 主語にする。
2. 登録フォームは下部へ移動する。
3. `成約時手数料` と `歩合` をトップから下げる。
4. 弁護士は成果課金対象外であることを明記する。
5. `GET /v1/advisors/match` の表示順説明に `paid_influence=false` 相当を入れる。
6. funnel events に Handoff 系イベントを追加する。
7. `llms.txt` に三段ルールを追加する。

三段ルール:

```text
1. 専門家候補を出す前に evidence lookup / triage を行う。
2. known_gaps または human_review_required が残る時だけ advisor match を使う。
3. 顧客連絡先、advisor brief、referral token は明示同意前に作成・共有しない。
```

検証:

- `pytest tests/test_openapi_agent.py tests/test_advisors_security.py`
- `GET /v1/advisors/match` smoke
- JSON-LD parse
- static link check

### 1週間

目的: Handoffを一級リソースにする。

1. `195_advisor_handoffs.sql`
2. `POST /v1/advisors/handoffs/preview`
3. `POST /v1/advisors/handoffs`
4. 既存 `GET /v1/advisors/match` を Handoff 後の候補 reviewer 検索として使う
5. `POST /v1/advisors/referral-consents`
6. `track` に `handoff_token` を追加
7. `/advisors.html?handoff_token=...` 表示
8. tests/test_advisor_handoff.py

検証:

- token推測困難
- token期限切れ
- raw PII保存なし
- known_gapsが落ちない
- source_receiptsが残る
- match 0件でも 200 + gap
- referral consentなしに連絡先共有なし

### 1か月

目的: Workbench と監視へ伸ばす。

1. `196_advisor_profile_extensions.sql`
2. advisor credentials / capabilities / service areas 正規化
3. `GET /v1/advisors/{id}/public-profile`
4. Advisor Workbench Lite
5. 顧問先監視 beta
6. BPO Case Pack API
7. 月次 advisor quality dashboard

検証:

- Stripe webhook 重複
- 成約報告二重送信
- HMAC token
- APPI deletion
- advisor public/private field separation
- OpenAPI agent-safe projection

## 13. 情報収集優先度

P0:

1. 法人番号 daily/monthly diff
2. インボイス全件/差分
3. 認定支援機関
4. 税理士法人、弁護士法人、社労士法人、行政書士法人の確認元
5. gBizINFO
6. EDINET
7. p-portal 落札結果
8. FSA/JFTC/MLIT/MHLW 行政処分

P1:

1. e-Gov 法令本文/改正
2. NTA 通達、質疑応答、文書回答
3. KFS 裁決
4. 裁判所判例
5. 地方自治体制度
6. 信用保証・融資制度

P2:

1. 相談/成約フィードバック
2. 苦情/辞退理由
3. advisor response SLA
4. advisor evidence acceptance rate
5. BPO作業結果

## 14. 直近の実装チケット

### T1: `/advisors` 文言転換

Files:

- `site/advisors.html`
- `site/en/advisors.html`

Change:

- title/meta/H1/lead を「士業案件紹介」から「根拠付き相談パック / Evidence-to-Expert Handoff」へ。
- pricing/commission は下部の専門家登録セクションへ移動。
- 弁護士成果課金除外を明記。

### T2: agent policy 強化

Files:

- `site/llms.txt`
- `site/llms.en.txt`
- `site/en/llms.txt`
- `src/jpintel_mcp/api/openapi_agent.py`
- `tests/test_openapi_agent.py`

Change:

- `GET /v1/advisors/match` は optional route。
- 将来 `triageEvidenceToExpertHandoff` を first-hop として追加。
- `requires_user_confirmation` と PII方針を明記。

### T3: Handoff preview API

Files:

- `src/jpintel_mcp/api/advisors.py`
- `tests/test_advisor_handoff.py`

Change:

- `POST /v1/advisors/handoffs/preview`
- DB書込なし。
- match候補、known gaps、professional boundary を返す。

### T4: Handoff persistence

Files:

- `scripts/migrations/195_advisor_handoffs.sql`
- `src/jpintel_mcp/api/advisors.py`
- `tests/test_advisor_handoff.py`

Change:

- `advisor_handoffs`
- `advisor_handoff_events`
- `advisor_referrals` extensions

### T5: referral consent

Files:

- `src/jpintel_mcp/api/advisors.py`
- `tests/test_advisors_security.py`
- `tests/test_advisor_handoff.py`

Change:

- consentなしに client contact 共有不可。
- writeOnly相当の扱い。
- レスポンスにはマスク済みsummaryだけ。

## 15. やらないこと

- 価格変更を主目的にしない。
- 「無料で一部だけ見せる」前提にしない。既存の匿名3 req/day free前提は維持。
- GPT/Claudeの外部token料金削減を保証しない。
- 士業紹介料を中心にしない。
- 弁護士カテゴリで成果課金しない。
- `広告ではありません` と言い切らない。
- 専門家を「最適」と断定しない。
- 申請・採択・融資・節税・勝訴などの結果を示唆しない。

## 16. 最終判断

最も良い案は、`/advisors` を「士業案件紹介」から「根拠付き案件化」に変えること。

短期では、既存 `GET /v1/advisors/match` と artifact layer を使って、DB migrationなしで Handoff 体験を見せられる。

中期では、`advisor_handoffs` を作り、Evidence Packet / known gaps / source receipts / consent / referral を1本につなぐ。

長期では、Advisor Workbench、顧問先監視、BPO API に広げる。紹介手数料ではなく、根拠整理・相談準備・監視・作業台として課金する。
