# Artifact API Contract 設計 2026-05-06

担当範囲: artifact API contract 設計。コード変更なし。

## 前提

- 外部 CLI-B の市場・完成物調査が戻った後、最初に売る persona / artifact を 1 つに絞って最小実装する。
- 既存 API shape は壊さない。`/v1/funding_stack/check`, `/v1/intel/houjin/{houjin_id}/full`, `/v1/intel/program/{program_id}/full` は現行レスポンスを維持し、artifact は追加 endpoint または optional wrapper として重ねる。
- Evidence Packet composer は現状 `NO writes` なので、artifact contract は `packet_id` を必須にするが、初期実装では非永続の packet id でもよい。永続化は別 slice。
- 監査再現性の最低セットは `corpus_snapshot_id` + `audit_seal`。既存 `attach_corpus_snapshot()` / `attach_seal_to_body()` を再利用する。

## 既存 API 観察

### `/v1/funding_stack/check`

- 入力: `program_ids` 2..5 件。実評価・課金は重複排除後の pair 数。
- 出力: `program_ids`, `all_pairs_status`, `pairs`, `blockers`, `warnings`, `next_actions`, `_disclaimer`, `total_pairs`。
- pair ごとに `verdict`, `confidence`, `rule_chain`, `next_actions` がある。
- `audit_seal` は付与済み。`corpus_snapshot_id` は top-level に直接は付いていない。
- artifact 化する場合、既存 body は `sections[].content` に包むか、`summary.compatibility` と `sections: [{section_type:"pairs"}]` へ写像できる。

### `/v1/intel/houjin/{houjin_id}/full`

- 出力: `houjin_bangou`, `sections_returned`, `max_per_section`, `houjin_meta`, `adoption_history`, `enforcement_records`, `invoice_status`, `peer_summary`, `jurisdiction_breakdown`, `watch_status`, `data_quality`, `decision_support`, `_disclaimer`, `_billing_unit`。
- `corpus_snapshot_id`, `corpus_checksum`, `audit_seal` が付与される。
- `decision_support.known_gaps` と `next_actions` が既に artifact 共通項目へ写像しやすい。
- compact mode があるので、artifact endpoint では初期は compact 非対応、または共通必須 field を落とさない compact rule が必要。

### `/v1/intel/program/{program_id}/full`

- 出力: `program_id`, `include_sections`, `max_per_section`, `program_meta`, `eligibility_predicate`, `amendments_recent`, `adoptions_top`, `similar_programs`, `citations`, `audit_proof`, `data_quality`, `_disclaimer`, `_billing_unit`。
- `corpus_snapshot_id`, `corpus_checksum`, `audit_seal` が付与される。
- `known_gaps` / `next_actions` は houjin/full より弱いので、artifact 化するなら wrapper 側で `data_quality.missing_tables` と predicate coverage から補う。

## Artifact 優先順位

| 優先 | artifact_type | 最初の買い手仮説 | 既存 substrate | 実装難度 | 理由 |
|---:|---|---|---|---|---|
| P0 | `compatibility_table` | 補助金コンサル、税理士、信金・地銀の補助金相談窓口 | `/v1/funding_stack/check`, `am_compat_matrix`, `exclusion_rules` | 低 | 既存 endpoint がほぼ完成物。併用可否 + 出典 + next actions が GPT/Claude 単体との差分として説明しやすい。新規収集待ちが少ない。 |
| P1 | `houjin_dd_pack` | 金融機関、M&A/与信前さばき、税理士事務所の顧問先確認 | `/v1/intel/houjin/{id}/full`, `houjin_master`, invoice, enforcement, peer, watch | 中 | 既に composite があり、DD pack として価値が伝わる。リスクが高いので disclaimer / human review の厳格化が必要。 |
| P2 | `application_kit` | 補助金申請支援者、士業、社内バックオフィス | `/v1/intel/program/{id}/full`, eligibility, documents, adoptions | 中-高 | 価値は強いが、申請代理・断定に近づくため `human_review_required=true` が基本。必要書類 substrate の完全性確認後がよい。 |
| P3 | `monitoring_digest` | 継続監視ユーザー、顧問契約先、金融機関ポートフォリオ | watch_status, amendment diff, narrative/customer reports | 中 | 継続課金に向くが、初回価値のデモは compatibility より説明に時間がかかる。 |
| P4 | `tax_client_impact_memo` | 税理士事務所、会計事務所 | tax rulesets, regulatory context, houjin facts | 高 | 単価は高いが税務助言境界が最も重い。CLI-A/CLI-B のソース・市場確認と review workflow が揃ってから。 |

結論: 最初に実装する artifact は `compatibility_table`。既存 `/v1/funding_stack/check` の pair verdict をほぼそのまま完成物化でき、CLI-B の結果待ちなしに P0 contract を固定できる。

## 共通 JSON Envelope

全 artifact endpoint は top-level に以下を必ず返す。既存 API の `_disclaimer` / `_billing_unit` / `corpus_checksum` は追加で残してよい。

```json
{
  "artifact_id": "art_01HX...",
  "artifact_type": "compatibility_table",
  "artifact_version": "artifact.v1",
  "generated_at": "2026-05-06T12:34:56+09:00",
  "corpus_snapshot_id": "2026-05-06T00:00:00Z",
  "corpus_checksum": "sha256:0123456789abcdef",
  "packet_id": "evp_01HX...",
  "request": {
    "input_hash": "sha256:...",
    "params": {}
  },
  "summary": {},
  "sections": [],
  "sources": [],
  "known_gaps": [],
  "next_actions": [],
  "human_review_required": false,
  "billing_metadata": {
    "billing_unit": "pair",
    "result_count": 1,
    "value_basis": "source_backed_artifact_no_llm"
  },
  "audit_seal": {}
}
```

### Required field semantics

- `artifact_id`: `art_` prefixの安定 ID。初期は response-time UUID/ULID でよい。永続化後は `artifact.id` と一致させる。
- `artifact_type`: enum。初期許可値は `compatibility_table`, `houjin_dd_pack`, `application_kit`, `tax_client_impact_memo`, `monitoring_digest`。
- `corpus_snapshot_id`: artifact 生成に使った corpus 版。既存 `attach_corpus_snapshot()` の値を優先する。`funding_stack/check` wrapper では必ず付与する。
- `packet_id`: artifact の根拠 packet。初期は `evp_...` を生成し、永続化前でも返す。将来 `evidence_packet` table と接続する。
- `sources`: 正規化された出典配列。`audit_seal.source_urls` だけに依存せず、section ごとの source を明示する。
- `known_gaps`: 欠落・未確認・coverage 限界。空配列は「既知 gap なし」であり、「安全証明」ではない。
- `next_actions`: 人間または agent が次に行う作業。既存 `FundingStackNextAction` / `decision_support.next_actions` を流用する。
- `human_review_required`: boolean。キュー例では配列になっているが、既存 Evidence Packet は boolean なので artifact も boolean に寄せる。review 理由は `known_gaps` または `next_actions[].reason` に載せる。
- `billing_metadata`: artifact 課金の明示メタデータ。`billing_unit` は課金単位、`result_count` は課金対象件数、`value_basis` は LLM 生成ではなく出典付き完成物・監査再現性・次アクションを価値根拠にすることを示す。`audit_seal.response_hash` はこの field を含む artifact envelope 全体を対象にする。
- `audit_seal`: 既存 `attach_seal_to_body()` の customer-facing seal。匿名・無料枠でも artifact endpoint では原則付与し、付与不能時は 5xx ではなく `known_gaps` に `audit_seal_unavailable` を追加するか、課金対象 endpoint では fail closed を検討する。

### 推奨 sub-schema

`sources[]`:

```json
{
  "source_id": "src_...",
  "url": "https://example.go.jp/koubo.pdf",
  "title": "公募要領",
  "publisher": "経済産業省",
  "source_type": "primary",
  "fetched_at": "2026-05-01T00:00:00+09:00",
  "checksum": "sha256:...",
  "used_in": ["sections.compatibility_pairs[0].rule_chain[0]"]
}
```

`known_gaps[]`:

```json
{
  "gap_id": "round_specific_rules",
  "severity": "review",
  "message_ja": "公募回ごとの併用条件は一次資料で再確認が必要です。",
  "source_fields": ["pairs[].rule_chain", "warnings[]"]
}
```

`next_actions[]`:

```json
{
  "action_id": "contact_program_office",
  "label_ja": "制度事務局へ併用条件を照会する",
  "detail_ja": "対象経費、申請年度、交付決定順序を示して確認してください。",
  "reason": "requires_review 判定は機械判定だけで許可扱いにできないためです。",
  "source_fields": ["sections.compatibility_pairs[].verdict"]
}
```

## Artifact 別 Contract

### `compatibility_table`

Endpoint 案:

- 新規: `POST /v1/artifacts/compatibility_table`
- 後方互換 optional: `POST /v1/funding_stack/check?as_artifact=true`

新規 endpoint を推奨する。既存 `funding_stack/check` のレスポンス shape を変えず、OpenAPI / SDK の破壊を避けられる。

`summary`:

```json
{
  "program_count": 3,
  "total_pairs": 3,
  "all_pairs_status": "requires_review",
  "blocker_count": 0,
  "requires_review_count": 1,
  "unknown_count": 0
}
```

`sections`:

```json
[
  {
    "section_id": "compatibility_pairs",
    "section_type": "table",
    "title_ja": "制度併用可否表",
    "columns": ["program_a", "program_b", "verdict", "confidence", "rationale", "source"],
    "rows": []
  },
  {
    "section_id": "blockers",
    "section_type": "list",
    "title_ja": "阻害条件",
    "items": []
  },
  {
    "section_id": "warnings",
    "section_type": "list",
    "title_ja": "確認事項",
    "items": []
  }
]
```

写像:

- `FundingStackCheckResponse.pairs` -> `sections[compatibility_pairs].rows`
- `all_pairs_status`, `total_pairs`, `blockers`, `warnings` -> `summary`
- `pairs[].rule_chain[].source_url` / `source_urls` -> `sources`
- `warnings` + `unknown` verdict + `requires_review` verdict -> `known_gaps`
- `next_actions` -> top-level `next_actions`
- `human_review_required` -> `all_pairs_status != "compatible"` または `known_gaps` 非空

### `houjin_dd_pack`

Endpoint 案:

- `POST /v1/artifacts/houjin_dd_pack`
- body: `{ "houjin_id": "...", "include_sections": [...], "max_per_section": 10 }`

写像:

- 既存 `houjin/full` を内部 composer として呼ぶのではなく、同じ builder を service 化して wrapper から使うのが望ましい。
- `summary`: 法人名、所在地、invoice status、enforcement count、watch status、peer percentile。
- `sections`: `houjin_meta`, `adoption_history`, `enforcement_records`, `invoice_status`, `peer_summary`, `jurisdiction_breakdown`, `watch_status`。
- `known_gaps`: `decision_support.known_gaps` + `data_quality.missing_tables`。
- `human_review_required`: enforcement detected、invoice not active/not found、jurisdiction mismatch、known gaps 非空のいずれか。

### `application_kit`

Endpoint 案:

- `POST /v1/artifacts/application_kit`
- body: `{ "program_id": "...", "houjin_id": "...?", "applicant_profile": {...}? }`

写像:

- `program/full` の `program_meta`, `eligibility_predicate`, `amendments_recent`, `adoptions_top`, `citations`, `audit_proof` を sections にする。
- `required_documents` substrate が利用可能なら `sections.required_documents` を追加する。
- `human_review_required`: 常に true。申請代理・適格性断定ではなく、準備チェックリストとして返す。
- `known_gaps`: missing predicate axis、missing documents、application window 不明、source freshness 不明。

### `tax_client_impact_memo`

Endpoint 案:

- `POST /v1/artifacts/tax_client_impact_memo`

初期は contract のみ。税務判断に見えるため、`summary` は「影響候補」までに限定し、`human_review_required=true` 固定。税理士レビュー前提の `next_actions` を必須にする。

### `monitoring_digest`

Endpoint 案:

- `POST /v1/artifacts/monitoring_digest`

対象: houjin / program / law watch の変更 digest。`sections` は `new_changes`, `risk_flags`, `watched_entities`, `source_updates`。初期は `houjin/full.watch_status` と amendment diff から開始可能。

## 既存 API を壊さない統合案

1. 新規 router `src/jpintel_mcp/api/artifacts.py` を追加し、`/v1/artifacts/{artifact_type}` を提供する。
2. 既存 `/v1/funding_stack/check`, `/v1/intel/houjin/{id}/full`, `/v1/intel/program/{id}/full` のレスポンスは変更しない。
3. artifact endpoint は既存 builder / service を呼び、返却直前に共通 envelope を組み立てる。
4. `_response_models.py` には `ArtifactEnvelope`, `ArtifactSource`, `ArtifactKnownGap`, `ArtifactNextAction`, artifact-specific summary model を追加するが、既存 response model は変更しない。
5. `attach_corpus_snapshot()` と `attach_seal_to_body()` を artifact envelope に適用する。既存 API から artifact endpoint へ移行する利用者だけが新 shape を受け取る。
6. OpenAPI では artifact endpoint を `tags=["artifacts"]` に分離する。既存 SDK の generated type churn を最小化する。
7. 将来 `persist=true` を導入する場合、既存 endpoint ではなく artifact endpoint にだけ付ける。Evidence Packet composer 自体は read-only のまま維持する。

## 最初に実装するもの

`compatibility_table` を最初に実装する。

理由:

- 既存 `FundingStackChecker` と REST endpoint があり、データ取得・判定ロジックの新規リスクが低い。
- `next_actions` が既に pair / top-level にあるため、完成物としての「次に何をするか」を即表示できる。
- pair 数課金という既存 billing posture と artifact 価値が一致する。
- `am_compat_matrix` と `exclusion_rules` の source / rule chain を `sources` と `known_gaps` に写像しやすい。
- `houjin_dd_pack` や `application_kit` より専門職法境界の危険が低く、ただし `requires_review` で人間確認を促せる。

初期実装の最小仕様:

- `POST /v1/artifacts/compatibility_table`
- request は `FundingStackCheckRequest` と同じ `program_ids`。
- response は artifact 共通 envelope。
- 内部で `FundingStackChecker.check_stack()` を呼ぶ。
- `log_usage()` は既存 funding stack と同じ 1 pair = 1 unit。
- `corpus_snapshot_id` を必ず top-level に付ける。
- `audit_seal` を artifact envelope 全体に対して付ける。

## テスト観点

### Contract invariants

- 2xx artifact response は必ず `artifact_id`, `artifact_type`, `corpus_snapshot_id`, `packet_id`, `sources`, `known_gaps`, `next_actions`, `human_review_required`, `audit_seal` を持つ。
- `artifact_type` は enum 外を返さない。
- `artifact_id` は `art_` prefix、`packet_id` は `evp_` prefix。
- `audit_seal.response_hash` は artifact envelope の内容に対して生成される。
- `corpus_snapshot_id` は compact / field filter が入っても落ちない。

### `compatibility_table`

- 2 programs -> 1 pair、5 programs -> 10 pairs、6 programs -> 422。
- 既存 `funding_stack/check` と同じ verdict / confidence / rule_chain が artifact rows に保存される。
- `all_pairs_status=incompatible` または `requires_review` なら `human_review_required=true`。
- `unknown` verdict は `known_gaps` に入る。
- `next_actions` は既存 checker の action id を保持し、重複排除される。
- source URL がある rule は `sources[]` に正規化され、`used_in` が該当 row を指す。
- 既存 `/v1/funding_stack/check` の snapshot test / OpenAPI schema は変化しない。

### `houjin_dd_pack`

- 既存 `test_intel_houjin_full.py` と同じ seed で artifact sections が埋まる。
- sparse 法人では空 section を安全証明にせず `known_gaps` に出す。
- enforcement / invoice inactive / jurisdiction mismatch / watch detected の時に `human_review_required=true`。
- `include_sections` を絞っても共通 required fields は残る。

### `application_kit`

- unknown program は 404 のまま。
- predicate table 欠落は 500 ではなく `known_gaps`。
- `human_review_required=true` 固定。
- law / tsutatsu citations の source URL が `sources[]` に入る。

### Regression

- 既存 endpoint の response shape を変えないことを OpenAPI schema test で確認する。
- `tests/test_funding_stack_checker.py`, `tests/test_intel_houjin_full.py`, `tests/test_intel_program_full.py` は artifact 実装後も既存期待値のまま通る。
- anonymous / paid key で audit_seal の扱いが既存 policy と矛盾しないことを確認する。
- compact envelope が artifact に適用される場合、required fields の短縮キー仕様を別途テストする。初期は compact 非対応でよい。

## 未決事項

- `human_review_required` はキュー例では配列だが、既存 Evidence Packet と整合させ boolean にする。レビュー理由は `known_gaps` / `next_actions` に分離する。
- `packet_id` を初期から DB 永続化するか、`persist=true` slice まで非永続 ID にするか。
- `audit_seal` を無料3回枠にも必須にするか。完成物 artifact としては必須にしたいが、既存匿名 policy との整合確認が必要。
- CLI-B の persona 調査結果により、P1/P2 の順序は変わり得る。ただし P0 `compatibility_table` は queue の Slice 3 と既存実装適合性から先行可能。
