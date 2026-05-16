# AWS smart methods round2 02: data, source, and knowledge graph

作成日: 2026-05-15
担当: 追加スマート方法検証 2/6 / Data, source, knowledge graph
対象: jpcite AWS credit run, Source OS, output_gap_map, source_candidate_registry, public official evidence graph
制約: AWS CLI/API実行なし。AWSリソース作成なし。既存コード変更なし。
出力: `/Users/shigetoumeda/jpcite/docs/_internal/aws_smart_methods_round2_02_data_knowledge_graph.md` のみ。

---

## 0. 結論

判定: **追加価値あり。既存の Source OS は正しいが、まだ「取得制御」寄りであり、データ資産化の中核をもう一段スマートにできる。**

既存案はすでに以下を持っている。

- `output_gap_map`
- `source_candidate_registry`
- `capture_method_router`
- `artifact_yield_meter`
- `expand_suppress_controller`
- `packet_to_source_backcaster`
- `source_freshness_monitor`
- `source_terms_classifier`
- `Playwright canary router`
- `failed_source_ledger`

今回の追加検証で採用すべきなのは、これらと重複しない次の機能である。

1. `Official Evidence Knowledge Graph`: 真実グラフではなく、公的一次情報の証跡グラフにする。
2. `Bitemporal Claim Graph`: 観測時点と制度/事実の有効時点を分離する。
3. `Source Twin Registry`: sourceごとの構造、失敗癖、更新癖、取得レシピを学習する。
4. `Semantic Delta Compressor`: HTML/PDF/API差分を成果物に効くclaim差分へ圧縮する。
5. `Update Frontier Planner`: 固定cronではなく、鮮度価値、売上価値、変化確率、取得コストで次の取得を決める。
6. `Claim Derivation DAG`: 取得物からclaimまでの変換を全てDAG化し、後から再検証できるようにする。
7. `Conflict-Aware Truth Maintenance`: 矛盾を多数決で潰さず、矛盾状態そのものを成果物化する。
8. `Schema Evolution Firewall`: 公式CSV/API/PDFの列・構造変更を本番packetに直撃させない。
9. `Reversible Entity Resolution Graph`: 法人、許認可、制度、自治体、業種の同定を可逆にする。
10. `Source Quality Learning Engine`: sourceごとの品質をaccepted artifact率だけでなく、矛盾率、schema drift率、再利用率で学習する。
11. `No-Hit Lease Ledger`: no-hitを永久事実にせず、検査範囲と失効期限付きの貸出証跡にする。
12. `Two-Layer Archive`: zero-bill後にも使える `public packet asset bundle` と、再生成用の `evidence replay bundle` を分ける。

最重要の修正はこれである。

> jpciteは「公的情報を集めたデータベース」ではなく、「公的一次情報から、どのclaimを、どの時点で、どの根拠から、どの範囲で言えるかを管理する証跡グラフ」にする。

これにより、AWSクレジットで一度作った資産が、単なるスクレイプ結果ではなく、本番後もpacket生成、差分検知、GEO proof、価格化、再検証に使い回せる。

---

## 1. 既存案との重複確認

### 1.1 既存案がすでに解いていること

既存の Source OS は、source候補をどう見つけ、どう取得し、どこで止めるかを十分に設計している。

既にあるため、今回の追加案では主目的にしないもの:

- source familyをさらに列挙すること
- API/bulk/HTML/PDF/Playwright/OCRの取得順を再定義すること
- accepted artifact率でexpand/suppressすること
- terms/robots gateを再説明すること
- broad crawlを禁止すること
- no-hitを不存在証明にしないこと

これらは既に正しい。

### 1.2 まだ弱いこと

弱いのは、取得後のデータ資産化である。

具体的には次が不足しやすい。

- 同じclaimが時点違いでどう変わったか。
- 取得日時と制度上の有効日時が混ざらないか。
- source同士が矛盾したとき、どちらをどう表示するか。
- 公式CSV/APIのschema変更で本番packetが壊れないか。
- PlaywrightやPDF由来のclaimが、後で再現できるか。
- no-hitが古くなっても残り続けないか。
- sourceの品質学習が「成功率」だけにならないか。
- AWS終了後に、何を残せば再生成・再検証できるか。

今回の提案はここを埋める。

---

## 2. 採用すべき中核アーキテクチャ

### 2.1 `Official Evidence Knowledge Graph`

名前はknowledge graphだが、設計上は「真実グラフ」にしない。

正しい定義:

```text
official source observation -> source receipt -> candidate claim -> compiled claim
-> packet claim view -> agent-facing evidence graph
```

禁止する定義:

```text
all sources -> one normalized truth database -> answer
```

理由:

- 公的情報同士でも矛盾する。
- 古いページ、PDF、告示、更新前APIが並存する。
- no-hitは不存在証明ではない。
- OCR/Playwrightは根拠力に差がある。
- 制度情報は有効日、公布日、施行日、更新日がずれる。

したがって、グラフは「何が真実か」ではなく、「どの根拠からどの範囲で何が言えるか」を表す。

### 2.2 graphの主要node

```text
source_profile
source_candidate
source_twin
source_document
source_receipt
capture_run
claim_candidate
claim_ref
subject_entity
schema_version
derivation_step
known_gap
no_hit_lease
conflict_case
packet_blueprint
packet_asset
proof_asset
```

### 2.3 graphの主要edge

```text
DISCOVERED_FROM
CAPTURED_BY
OBSERVED_IN
DERIVED_BY
SUPPORTS_CLAIM
CONFLICTS_WITH
SUPERSEDES
HAS_VALID_TIME
HAS_OBSERVED_TIME
HAS_SCHEMA_VERSION
MERGED_AS
ALIAS_OF
BLOCKED_BY_TERMS
EXPIRES_AT
USED_IN_PACKET
REDUCES_GAP
```

### 2.4 必須ルール

- `claim_ref` は必ず `source_receipt` へ戻れる。
- `source_receipt` は必ず `source_profile` と `capture_run` へ戻れる。
- `claim_ref` は `observed_time` と `valid_time` を混ぜない。
- entity mergeは可逆にする。
- conflictは隠さない。
- old packetはold schemaで再生できるようにする。
- no-hitには必ずscopeとexpiryを付ける。

---

## 3. `Bitemporal Claim Graph`

### 3.1 目的

公的一次情報では、時点が少なくとも2種類ある。

| time | 意味 | 例 |
|---|---|---|
| `observed_time` | jpciteがその情報を観測した時刻 | 2026-05-15にPDFを取得 |
| `valid_time` | 制度、登録、許認可、募集、法令上の効力時点 | 2026-06-01施行、2026-07-31締切 |

これを混ぜると、AIエージェントが誤った成果物を推薦する。

悪い例:

```text
2026-05-15にページを取得したので、補助金は2026-05-15時点で有効です。
```

良い例:

```text
2026-05-15に募集要領PDFを観測しました。PDF内の締切候補は2026-07-31です。
ただし募集状態の継続確認はsource TTLの範囲内です。
```

### 3.2 schema案

```json
{
  "schema_id": "jpcite.claim_temporality.v1",
  "claim_id": "claim_...",
  "observed_time": {
    "first_observed_at": "2026-05-15T10:00:00+09:00",
    "last_observed_at": "2026-05-15T10:00:00+09:00",
    "source_receipt_ids": ["sr_..."]
  },
  "valid_time": {
    "kind": "valid_until",
    "start_date": null,
    "end_date": "2026-07-31",
    "date_role": "application_deadline",
    "source_text_anchor_hash": "sha256:..."
  },
  "publication_time": {
    "published_at": "2026-04-20",
    "updated_at": "2026-05-01",
    "confidence": "source_declared"
  },
  "staleness_policy": {
    "ttl_days": 7,
    "expires_for_packet_use_at": "2026-05-22T10:00:00+09:00",
    "after_expiry_action": "known_gap_requires_refresh"
  }
}
```

### 3.3 採用効果

- 「いつ観測した情報か」と「いつ有効な情報か」を分離できる。
- 補助金、法令改正、許認可、入札、税労務イベントで誤表現が減る。
- stale情報を自動で `known_gap` に落とせる。
- 差分検知が「ページが変わった」ではなく「claimの有効時点が変わった」に圧縮される。

---

## 4. `Source Twin Registry`

### 4.1 目的

`source_profile` は契約・利用条件・基本entrypointを持つ。

追加で必要なのは、sourceごとの運用的な「癖」を持つ `source_twin` である。

`source_twin` は以下を学習する。

- DOM構造
- PDFの文字層有無
- 更新されやすい曜日/時間
- URL pattern
- ページング方式
- 429/403/timeout傾向
- OCRが必要になりやすいページ種
- cookie bannerや告知overlayの発生
- no-hit画面の表示パターン
- schema drift頻度
- accepted artifactへの変換率
- conflict発生率

### 4.2 `source_profile` との違い

| object | 役割 | 本番判断 |
|---|---|---|
| `source_profile` | 出典の契約、所有者、利用許諾、更新方針 | public claim利用可否 |
| `source_twin` | 取得と正規化の運用モデル | 取得方法、再試行、更新タイミング、schema adapter選択 |

### 4.3 schema案

```json
{
  "schema_id": "jpcite.source_twin.v1",
  "source_profile_id": "sp_...",
  "source_twin_id": "stw_...",
  "capture_shape": {
    "primary_method": "html_table",
    "fallback_methods": ["playwright_visible_text", "metadata_only"],
    "pagination_pattern": "query_param_page",
    "stable_selectors": ["table.result", "a.detail-link"],
    "fragile_selectors": [".notice-banner"]
  },
  "update_behavior": {
    "observed_change_rate": "weekly",
    "high_change_windows": ["Mon 09:00-12:00 JST"],
    "last_change_observed_at": "2026-05-15T00:00:00+09:00"
  },
  "failure_modes": {
    "timeout_rate": 0.02,
    "blocked_state_rate": 0.00,
    "schema_drift_rate": 0.05,
    "manual_review_required_rate": 0.03
  },
  "artifact_yield": {
    "accepted_receipt_rate": 0.82,
    "accepted_claim_rate": 0.56,
    "packet_fixture_contribution_rate": 0.18,
    "conflict_rate": 0.04
  },
  "recommended_capture_policy": {
    "mode": "expand",
    "max_parallelism": 20,
    "retry_policy": "low_retry_checkpoint_first",
    "next_review_reason": "schema_drift_above_baseline"
  }
}
```

### 4.4 採用効果

- sourceごとに毎回同じ探索をしなくてよい。
- schema driftやfailureの予兆を拾える。
- Playwright投入先をより絞れる。
- `Budget Token Market v2` の `artifact_value_density` に高品質な入力を渡せる。
- AWS終了後も、再取得設計や非AWS更新に使える。

---

## 5. `Semantic Delta Compressor`

### 5.1 目的

公的ページは、HTMLの微修正、PDF差し替え、ヘッダ変更、注記追加など、成果物に関係ない差分が多い。

差分をそのまま保存・処理すると、AWS費用もreview負荷も増える。

必要なのは、document差分をclaim差分へ圧縮すること。

```text
raw document diff
-> structural diff
-> field diff
-> claim diff
-> packet impact diff
```

### 5.2 diff level

| level | 内容 | packet影響 |
|---|---|---|
| L0 raw hash diff | byte/hashが変わった | まだ不明 |
| L1 structure diff | DOM/PDF table/sectionが変わった | 低から中 |
| L2 field diff | deadline/status/amount/article/dateが変わった | 高 |
| L3 claim diff | `claim_ref` が追加/変更/消滅 | 高 |
| L4 packet impact diff | paid packetの結果/known_gap/価格に影響 | 最重要 |

### 5.3 schema案

```json
{
  "schema_id": "jpcite.semantic_delta.v1",
  "source_profile_id": "sp_...",
  "previous_receipt_id": "sr_prev",
  "current_receipt_id": "sr_curr",
  "raw_hash_changed": true,
  "structural_delta": {
    "changed_sections": ["application_requirements", "deadline"],
    "ignored_sections": ["header_navigation", "footer"]
  },
  "field_delta": [
    {
      "field_name": "application_deadline",
      "old_value_hash": "sha256:old",
      "new_value_hash": "sha256:new",
      "delta_kind": "date_changed"
    }
  ],
  "claim_delta": {
    "added_claim_ids": ["claim_new"],
    "superseded_claim_ids": ["claim_old"],
    "unchanged_claim_stable_keys": ["csk_..."]
  },
  "packet_impact": [
    {
      "packet_type": "grant_candidate_shortlist",
      "impact_level": "material",
      "reason": "deadline changed"
    }
  ]
}
```

### 5.4 採用効果

- 差分監視が安くなる。
- 変わっていないclaimを再生成しなくてよい。
- packetに効く変化だけを優先できる。
- proof pageで「何が変わったか」を説明しやすい。
- AWS終了後のasset bundleが軽くなる。

---

## 6. `Update Frontier Planner`

### 6.1 目的

固定cronは単純だが、今回のサービスには最適ではない。

更新すべきsourceは、次の組み合わせで決めるべきである。

- そのsourceが支える有料packetの価値
- sourceの変化しやすさ
- stalenessの危険度
- no-hit leaseの期限
- schema driftの可能性
- 取得コスト
- accepted artifact化の確率
- 最近のagent需要
- source conflictの解消価値

### 6.2 scoring案

```text
next_fetch_value =
  packet_value_weight
  * gap_reduction_potential
  * freshness_urgency
  * change_probability
  * accepted_artifact_probability
  * agent_demand_signal
  * conflict_resolution_value
  / max(expected_cost_usd, minimum_cost_floor)
```

ただし、以下の場合は強制的に止める。

```text
if terms_status in blocked: stop
if robots_status in blocked: stop
if source_twin.blocked_state_rate above threshold: suppress
if packet_value_weight is zero and no compliance need: suppress
if no_hit lease still valid and low volatility: skip
```

### 6.3 既存 `source_freshness_monitor` との差分

`source_freshness_monitor` は鮮度を測る。

`Update Frontier Planner` は、鮮度に加えて「今取りに行く価値」を決める。

これはAWS credit run中にも、zero-bill後の非AWS更新設計にも使える。

---

## 7. `Claim Derivation DAG`

### 7.1 目的

sourceからclaimまでの変換をブラックボックスにしない。

すべての変換をDAGとして残す。

```text
source_document
-> extraction_step
-> normalization_step
-> entity_resolution_step
-> claim_candidate_step
-> claim_compile_step
-> packet_projection_step
```

### 7.2 なぜ必要か

- 公式sourceのschema変更時に、どのclaimが影響を受けたか分かる。
- OCRやPlaywright由来のclaimを後から隔離できる。
- 間違った正規化ルールを修正して再生成できる。
- evidence graphをAIエージェントへ説明しやすい。
- AWS終了後も、replay bundleから再検証できる。

### 7.3 schema案

```json
{
  "schema_id": "jpcite.claim_derivation_step.v1",
  "derivation_step_id": "drv_...",
  "run_id": "run_...",
  "input_object_ids": ["sr_...", "doc_..."],
  "output_object_ids": ["claim_candidate_..."],
  "operation": "normalize_japanese_date",
  "operation_version": "2026-05-15.1",
  "deterministic": true,
  "request_time_llm_call_performed": false,
  "parameters_hash": "sha256:...",
  "quality_checks": [
    {
      "check_id": "date_parse_roundtrip",
      "status": "pass"
    }
  ],
  "known_gap_ids": []
}
```

### 7.4 LLM候補の扱い

LLMを使う場合でも、claimを直接作らせない。

許可される用途:

- schema adapter候補の提案
- field mapping候補の提案
- document section分類候補
- conflict explanation draft
- human review queueの要約

禁止:

- source receiptなしでclaimを作る
- OCR単独で重要fieldを確定する
- no-hitを安全/不存在へ変換する
- `eligible` や `permission not required` を外部表示する

LLM候補は必ず以下に落とす。

```text
llm_candidate -> quarantine -> deterministic validator -> human_review or discard
```

---

## 8. `Conflict-Aware Truth Maintenance`

### 8.1 目的

source同士の矛盾は欠陥ではない。公的一次情報サービスでは、矛盾を隠さず扱えることが価値になる。

例:

- 法人所在地が法人番号と別sourceで違う。
- 補助金締切が一覧ページとPDFで違う。
- 法令ページと省庁ガイドラインの更新日が違う。
- 事業者登録の状態がsource間でずれる。
- 行政処分の公表名と法人番号同定が曖昧。

### 8.2 conflict object

```json
{
  "schema_id": "jpcite.conflict_case.v1",
  "conflict_id": "conf_...",
  "subject_entity_id": "ent_...",
  "field_name": "application_deadline",
  "conflict_kind": "value_mismatch",
  "claim_ids": ["claim_a", "claim_b"],
  "source_receipt_ids": ["sr_a", "sr_b"],
  "detected_at": "2026-05-15T00:00:00+09:00",
  "severity": "material_for_packet",
  "display_policy": "show_conflict_with_known_gap",
  "resolution_policy": {
    "auto_resolution_allowed": false,
    "precedence_rule": "none",
    "requires_human_review": true
  },
  "packet_impact": [
    {
      "packet_type": "grant_candidate_shortlist",
      "impact": "cannot_show_single_deadline"
    }
  ]
}
```

### 8.3 conflict handling policy

```text
if conflict is immaterial:
  attach known_gap and preserve both receipts

if conflict affects paid packet action:
  show conflict, do not collapse
  set human_review_required when needed

if one source has explicit legal precedence:
  show primary value plus conflicting source note

if precedence is unknown:
  do not choose winner
```

### 8.4 採用効果

- 「AIが勝手に丸めた」事故を避けられる。
- source-backedサービスとして信頼が増す。
- 矛盾そのものを有料価値にできる。
- 例: 「補助金締切が一覧とPDFで違うため、申請前に公式窓口確認が必要」。

---

## 9. `Schema Evolution Firewall`

### 9.1 目的

公式CSV、API、PDF、HTML tableは変わる。

schema変更がそのまま本番packetに入ると、誤claimや欠損が起きる。

そこで、sourceごとのschemaを本番packetから分離する。

```text
source native schema
-> source adapter
-> canonical intermediate schema
-> packet schema
```

### 9.2 compatibility levels

| level | 意味 | 処理 |
|---|---|---|
| `compatible` | 既存adapterで処理可 | 自動 |
| `additive` | 新列/新field追加 | 既存claimは維持、新fieldは候補 |
| `renamed_or_reordered` | 列名/順序変更 | adapter candidate + canary |
| `semantic_change` | field意味変更 | manual review |
| `breaking` | 必須field欠落 | quarantine |
| `unknown` | 判定不能 | manual_review_required |

### 9.3 schema drift object

```json
{
  "schema_id": "jpcite.source_schema_drift.v1",
  "source_profile_id": "sp_...",
  "detected_at": "2026-05-15T00:00:00+09:00",
  "previous_schema_hash": "sha256:old",
  "current_schema_hash": "sha256:new",
  "drift_level": "renamed_or_reordered",
  "affected_fields": ["address", "status"],
  "affected_packet_types": ["company_public_baseline"],
  "adapter_action": "candidate_adapter_required",
  "public_claim_allowed": false,
  "manual_review_required": true
}
```

### 9.4 採用効果

- 公式source変更で本番が壊れにくい。
- old packetをold schemaで再生できる。
- schema変更そのものを `known_gap` として出せる。
- AWSで大量取得した後のasset化が安定する。

---

## 10. `Reversible Entity Resolution Graph`

### 10.1 目的

法人、許認可、制度、自治体、業種は同定が難しい。

特にAIエージェント経由では、入力が曖昧になりやすい。

例:

- 会社名だけ
- 屋号だけ
- T番号だけ
- 住所の一部だけ
- 自治体名の旧称
- 業種の俗称

これを一度mergeしてしまうと、誤同定が大事故になる。

したがって、entity resolutionは可逆グラフにする。

### 10.2 design

```text
entity_candidate
-> match_evidence
-> merge_decision
-> canonical_entity_view
```

mergeは事実ではなく判断である。

### 10.3 schema案

```json
{
  "schema_id": "jpcite.entity_resolution_edge.v1",
  "edge_id": "ere_...",
  "left_entity_candidate_id": "entcand_a",
  "right_entity_candidate_id": "entcand_b",
  "match_basis": [
    "houjin_bangou_exact",
    "normalized_name_match",
    "address_similarity"
  ],
  "match_strength": "strong_id_match",
  "merge_allowed": true,
  "merge_reversible": true,
  "negative_evidence": [],
  "supporting_receipt_ids": ["sr_..."],
  "decision": {
    "status": "merged_for_packet_view",
    "decided_by": "deterministic_rule",
    "rule_version": "entity_match_2026-05-15.1"
  }
}
```

### 10.4 merge禁止例

- 会社名だけ一致。
- 住所だけ近い。
- OCRで読んだ法人名だけ一致。
- 古い自治体名と現自治体名の対応が未確認。
- 許認可番号と法人番号のリンクがsource-backedでない。

### 10.5 採用効果

- 誤同定リスクを下げる。
- AIが「この会社で合っていますか」と聞ける。
- packet previewで追加質問を生成しやすい。
- 後でmergeを戻せる。

---

## 11. `Source Quality Learning Engine`

### 11.1 目的

既存案の `artifact_yield_meter` は重要だが、品質学習をもう少し広げるべきである。

source品質は「accepted artifact率」だけではない。

### 11.2 quality dimensions

| dimension | 意味 |
|---|---|
| `officialness` | 公的sourceとしての強さ |
| `terms_clarity` | 利用条件の明確さ |
| `capture_reliability` | 取得安定性 |
| `schema_stability` | schema driftの少なさ |
| `claim_support_strength` | direct claimに使える割合 |
| `conflict_rate` | 他sourceと矛盾する率 |
| `freshness_observability` | 更新日/施行日/締切などの時点を取れるか |
| `packet_reuse_rate` | 複数packetで使い回せるか |
| `no_hit_scope_clarity` | no-hit範囲を明示できるか |
| `review_burden` | human reviewへ落ちる率 |

### 11.3 typed score_set

generic `score` は使わない。

```json
{
  "schema_id": "jpcite.source_quality_assessment.v1",
  "source_profile_id": "sp_...",
  "assessment_window": "2026-05-15/run-001",
  "score_set": {
    "officialness_score": 0.95,
    "terms_clarity_score": 0.80,
    "capture_reliability_score": 0.74,
    "schema_stability_score": 0.68,
    "claim_support_strength_score": 0.82,
    "freshness_observability_score": 0.77,
    "packet_reuse_score": 0.61,
    "review_burden_score": 0.35
  },
  "risk_indicators": {
    "conflict_rate": 0.06,
    "schema_drift_events": 2,
    "blocked_state_rate": 0.01,
    "ocr_only_material_field_rate": 0.00
  },
  "recommended_use": "public_claim_allowed_with_known_gaps",
  "recommended_budget_action": "expand_carefully"
}
```

### 11.4 採用効果

- AWS費用配分が賢くなる。
- 本番packetに入れるsourceが安定する。
- sourceの品質をGEO proofへ説明できる。
- 低品質sourceを「取っただけ」で価値扱いしなくなる。

---

## 12. `No-Hit Lease Ledger`

### 12.1 目的

no-hitは「ある範囲で、ある時点に、見つからなかった検査結果」である。

これを永久claimのように扱うと危険である。

そこで no-hit をleaseにする。

### 12.2 schema案

```json
{
  "schema_id": "jpcite.no_hit_lease.v1",
  "no_hit_lease_id": "nhl_...",
  "source_profile_id": "sp_...",
  "checked_subject": {
    "subject_kind": "company",
    "subject_id": "houjin:..."
  },
  "query_scope": {
    "source_entrypoint": "https://...",
    "query_parameters_hash": "sha256:...",
    "jurisdiction": "JP",
    "date_range_checked": null,
    "record_types_checked": ["administrative_disposition"]
  },
  "observed_at": "2026-05-15T00:00:00+09:00",
  "lease_expires_at": "2026-05-22T00:00:00+09:00",
  "allowed_statement": "no matching record was found in the checked corpus and scope",
  "forbidden_statement": "no record exists or the company is safe",
  "renewal_policy": "refresh_before_paid_packet_reuse",
  "known_gap_ids": ["gap_no_hit_not_absence"]
}
```

### 12.3 採用効果

- no-hitの古さを管理できる。
- packet再利用時に自動refresh判断できる。
- AIエージェントが安全な言い方をしやすい。
- no-hitを売り物にする場合も、範囲と期限を明確にできる。

---

## 13. `Two-Layer Archive`

### 13.1 目的

zero-bill後はAWSにS3も残さない。

それでも成果物を維持するには、残すarchiveを2層に分けるべきである。

### 13.2 layer A: `public packet asset bundle`

本番で直接使う軽量bundle。

含める:

- packet catalog
- static DB manifest
- compiled public claims
- source receipt summaries
- known gaps
- no-hit leases
- proof page assets
- agent decision pages
- schema version manifest
- checksum manifest

含めない:

- raw full screenshot
- raw DOM
- raw HAR body
- full OCR text
- private CSV-derived facts
- terms不明sourceの本文

### 13.3 layer B: `evidence replay bundle`

再検証・再生成用の内部bundle。

含める:

- canonical source receipt records
- document hashes
- text anchors
- bounded screenshot metadata
- derivation DAG
- schema adapter versions
- conflict cases
- rejected/quarantined reason
- quality assessments

注意:

- 実体ファイルをどこまで含めるかはlicense boundaryで決める。
- raw redistribution不可のsourceはhash/anchor/metadata-onlyに落とす。
- 本番公開面へは出さない。

### 13.4 採用効果

- zero-billと資産保持を両立しやすい。
- 本番は軽く、再検証は内部bundleで可能。
- rollbackや再生成がしやすい。
- source termsに応じて公開/内部を分離できる。

---

## 14. 追加すべきcompiler境界

### 14.1 `Evidence Graph Compiler`

`Public Packet Compiler` の前段に、`Evidence Graph Compiler` を置く。

役割:

- source receiptsをpacketで使える形へ射影する。
- claim候補をpublic/private/metadata-onlyに分ける。
- conflictとknown_gapを付与する。
- no-hit leaseの期限を確認する。
- schema adapterの互換性を確認する。
- entity resolutionのmerge状態を確認する。

出力:

```text
evidence_graph_view
packet_claim_candidates
blocked_claim_candidates
known_gap_matrix
conflict_case_refs
no_hit_lease_refs
```

### 14.2 `Public Packet Compiler` との境界

```text
Evidence Graph Compiler:
  can prepare claim candidates and evidence views
  cannot expose paid/public claims by itself

Public Packet Compiler:
  can emit public packet claims
  must require receipt, gap, conflict, no-hit, schema, and visibility checks
```

### 14.3 採用効果

- データ基盤と商品生成の境界がきれいになる。
- source graphの変更がpacket APIへ直撃しにくい。
- testしやすい。

---

## 15. packetから見た追加価値

### 15.1 `company_public_baseline`

追加価値:

- 法人同定を可逆entity graphで扱える。
- sourceごとの所在地/名称差分を conflict として出せる。
- no-hit leaseにより、古いno-hitを使い回さない。
- source qualityを表示できる。

### 15.2 `grant_candidate_shortlist`

追加価値:

- 募集期間の `valid_time` と観測日時を分けられる。
- PDF差し替えをsemantic deltaで締切変更へ圧縮できる。
- 一覧ページと募集要領PDFの矛盾を隠さない。
- no-hitを「対象補助金なし」ではなく、検査範囲付きで出せる。

### 15.3 `permit_rule_check`

追加価値:

- 法令、告示、自治体ページ、申請窓口の階層をgraph化できる。
- source conflictを「判断不能」ではなく「確認論点」として成果物化できる。
- 条文改正や自治体ページ変更を差分claimとして扱える。

### 15.4 `tax_labor_event_radar`

追加価値:

- 制度上の有効時点、届出期限、納付期限を分離できる。
- 更新が多いsourceをUpdate Frontierで優先できる。
- CSV-derived private factsとはpublic evidence graphを混ぜずにjoinできる。

### 15.5 `vendor_public_risk_attention`

追加価値:

- `risk score` ではなく、public evidence attentionとして構成できる。
- 行政処分sourceのno-hitを安全証明にしない。
- source conflictや同名法人リスクを前面に出せる。

---

## 16. 実装前に正本計画へマージすべき項目

正本計画へ追加すべきもの:

1. `Official Evidence Knowledge Graph` をSource OSの下位/中核データモデルとして追加。
2. `Bitemporal Claim Graph` をclaim schema必須項目へ追加。
3. `Source Twin Registry` を `source_profile` とは別objectとして追加。
4. `Semantic Delta Compressor` を更新・差分・再取得計画へ追加。
5. `Update Frontier Planner` をfixed cronの代替または上位制御として追加。
6. `Claim Derivation DAG` をartifact manifest必須項目へ追加。
7. `Conflict-Aware Truth Maintenance` をrelease gateへ追加。
8. `Schema Evolution Firewall` をsource adapter実装の前提へ追加。
9. `Reversible Entity Resolution Graph` を会社/制度/許認可/自治体同定へ追加。
10. `Source Quality Learning Engine` をAWS schedulerとproduct gateの入力へ追加。
11. `No-Hit Lease Ledger` をno-hit ledgerの正式形へ変更。
12. `Two-Layer Archive` をzero-bill export gateへ追加。

---

## 17. 採用しない方がよい案

### 17.1 one global truth graph

不採用。

理由:

- 公的sourceは矛盾する。
- 時点が違う。
- no-hitを誤って強い事実にしやすい。
- jpciteの価値は「断定」ではなく「根拠と限界の明示」。

### 17.2 ML/LLMでsource信頼度を直接決める

不採用。

source qualityは学習してよいが、public claim可否はterms、receipt、support level、schema、known gapで決める。

ML/LLMは候補生成やpriority補助に限定する。

### 17.3 schema変更を自動で本番反映

不採用。

自動adapter候補はよいが、本番packetへ入れる前にcompatibility gateが必要。

### 17.4 no-hit永久キャッシュ

不採用。

no-hitはleaseにする。期限切れ後はrefreshまたはknown gap。

### 17.5 screenshot-first corpus

不採用。

スクリーンショットはreceipt補助であり、API/bulk/text layerがあるならそちらを優先する。

---

## 18. 矛盾チェック

### 18.1 AWS zero-billとの整合

整合する。

`Two-Layer Archive` により、AWS上にS3を残さず、外部export後に削除できる。

注意:

- replay bundleの保管先はAWS外にする。
- AWS上のDynamoDB/S3/OpenSearch/Glue/Athenaを最終保持先にしない。
- checksumとmanifestをexport gateで検証してから削除する。

### 18.2 request-time LLMなしとの整合

整合する。

LLM候補は `quarantine` に落とし、public claimはdeterministic compilerで作る。

### 18.3 Source OSとの整合

整合する。

今回の提案はSource OSの置き換えではなく、Source OSが取得したものを成果物資産へ変える内部グラフである。

### 18.4 Output Composerとの整合

整合する。

Output Composerは購入判断と実行計画を作る。Evidence Graph Compiler / Public Packet Compilerがclaimを作る。

### 18.5 CSV privacyとの整合

整合する。

public evidence graphとprivate CSV overlayはnamespaceを分ける。

raw CSV、row-level CSV、実CSV由来のpublic proof流出は引き続き禁止。

### 18.6 Playwright方針との整合

整合する。

Playwrightはpublic rendered observationであり、Source TwinとCapture Method Routerの管理下に置く。

アクセス制限突破、CAPTCHA回避、403/429反復突破は行わない。

---

## 19. 最終提案

次の一文を正本計画へ追加するのがよい。

> Source OSで発見・取得した公的一次情報は、真実DBへ直接統合せず、`Official Evidence Knowledge Graph` に入り、`Bitemporal Claim Graph`、`Claim Derivation DAG`、`Conflict-Aware Truth Maintenance`、`Schema Evolution Firewall`、`No-Hit Lease Ledger` を通ってから、`Evidence Graph Compiler` と `Public Packet Compiler` によりpacket化される。

この追加により、jpciteはさらにスマートになる。

理由:

- 取得したsourceを長期資産にしやすい。
- 時点、矛盾、schema変化、no-hitの危険を抑えられる。
- AWSで大量に作ったartifactを、本番後も再利用・再検証できる。
- AIエージェントが「安く、根拠付きで、限界も説明できる成果物」を推薦しやすくなる。

---

## 20. Final verdict

既存計画は成立している。

ただし、よりスマートな方法として、データ基盤は単なるsource collectionやcacheではなく、以下へ進化させるべきである。

```text
Source OS
-> Official Evidence Knowledge Graph
-> Bitemporal Claim Graph
-> Claim Derivation DAG
-> Conflict / Schema / No-Hit gates
-> Evidence Graph Compiler
-> Public Packet Compiler
-> agent-facing packet and proof assets
```

これは既存案の重複ではなく、AWS credit runの成果を「取ったデータ」から「売れる証跡資産」に変換するための追加機能である。
