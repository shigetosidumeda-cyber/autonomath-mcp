# Integrations Implementation Loop Log

更新日: 2026-05-06  
Owner: Wave2 Worker F / Wave7 Worker D / Wave8 Worker C / Wave10 Worker C / Wave12 Worker C  
Scope: `docs/integrations` の索引と実装ループ記録。Wave 12 Worker C は `output-satisfaction-spec.md`, `artifact-catalog.md`, `implementation-loop-log.md`, `README.md`, `site/llms.txt`, `site/llms.en.txt`, `site/en/llms.txt` のみを編集対象にした。

## Guiding Focus

このループの焦点は価格変更ではない。

| Focus | Meaning |
|---|---|
| アウトプット満足度 | 検索結果ではなく、顧問先メモ、申請キット、DDパック、稟議シート、監視ダイジェストとして使える形にする |
| 無料3回通常品質 | Free 3/day は低品質サンプルではなく、通常品質の成功体験にする |
| 派生データ | ranking、勝ち筋、不足質問、source freshness、差分、確認範囲を構造化して返す |
| CTA実装 | Evidence Packet 後に、業務単位の完成物へ自然につなげる |

## Wave 1 Outcomes

Wave 1 では、実装前に必要な方針と仕様を docs として分解した。

| Outcome | Doc | Implementation Value |
|---|---|---|
| 深い有料アウトプットとデータ基盤の全体方針を定義 | [`deep-paid-output-and-data-foundation-plan.md`](./deep-paid-output-and-data-foundation-plan.md) | artifact中心、Evidence Packet、audit-ready output、無料3回通常品質、派生レイヤーの方向を統合した |
| 無料3回/通常利用の出力満足度 contract を定義 | [`output-satisfaction-spec.md`](./output-satisfaction-spec.md) | `source_url`, `source_fetched_at`, `known_gaps`, 確認事項、免責境界を無料でも落とさない方針を固定した |
| artifact type ごとの完成物仕様を定義 | [`artifact-catalog.md`](./artifact-catalog.md) | 顧問先メモ、申請キット、補助金戦略、法人DD、稟議シート、監視などの出力セクションと品質ゲートを整理した |
| 派生データレイヤー仕様を定義 | [`derived-data-layer-spec.md`](./derived-data-layer-spec.md) | `program_decision_layer`, `corporate_risk_layer`, `source_quality_layer`, `document_requirement_layer`, `monitoring_delta_layer` を実装候補に落とした |
| AI agent routing と CTA 文言を定義 | [`agent-routing-and-cta-spec.md`](./agent-routing-and-cta-spec.md) | use/skip 条件、無料枠表示、429、Evidence Packet 後の完成物 CTA、0件時応答を統一した |
| AI agent への推薦・配布計画を定義 | [`ai-agent-recommendation-plan.md`](./ai-agent-recommendation-plan.md) | Claude / ChatGPT / Cursor などに jpcite を Evidence pre-fetch layer として理解させる説明軸を整理した |

Wave 1 の結論:

1. Free 3/day は品質を下げない。
2. 課金価値は「検索回数」ではなく、再利用できる完成物と監視に置く。
3. `known_gaps` は内部エラーではなく、ユーザーに見せる確認範囲にする。
4. AI agent には、jpcite を「日本の公的 evidence の前処理」として使う/使わない条件を明確に渡す。

## Wave 2 Implementation Targets

Wave 2 では、Wave 1 docs を実装可能な単位に分解する。

| Target | Source Spec | Expected Implementation |
|---|---|---|
| Free 3/day response contract | `output-satisfaction-spec.md`, `agent-routing-and-cta-spec.md` | 無料枠でも通常品質の envelope を返し、quota 表示は `used`, `remaining`, `reset_at`, `quality` で表す |
| Evidence Packet footer CTA | `agent-routing-and-cta-spec.md`, `artifact-catalog.md` | packet 後に文脈別 CTA を 1-3 件返す。例: 顧問先メモ、申請前チェックリスト、法人DD、月次監視 |
| Artifact minimum sections | `artifact-catalog.md`, `output-satisfaction-spec.md` | `結論サマリ`, `なぜ今か`, `次にやること`, `根拠カード`, `NG/不明条件`, `顧客向け文面`, `確認範囲`, `監視提案` を artifact 出力の標準にする |
| Derived data layer backlog | `derived-data-layer-spec.md` | `program_decision_layer` と `corporate_risk_layer` を優先候補にし、source quality と document requirement を品質 gate に接続する |
| Zero result handling | `output-satisfaction-spec.md`, `agent-routing-and-cta-spec.md` | 0件時に「存在しない」と断定せず、収録範囲、条件拡張、一次確認先、0件 CTA を返す |
| Agent distribution copy | `ai-agent-recommendation-plan.md`, `agent-routing-and-cta-spec.md` | README、llms.txt、OpenAPI、MCP tool description、Actions operation description の文言を同じ意味に揃える |
| Conversion event hooks | `agent-routing-and-cta-spec.md`, `deep-paid-output-and-data-foundation-plan.md` | `free_call_1/2/3`, `free_quota_exhausted`, `api_key_cta_clicked`, `artifact_cta_shown`, `artifact_cta_clicked` を計測候補にする |

## Implementation Guardrails

| Guardrail | Rule |
|---|---|
| No pricing rewrite | unit単価、税表示、課金体系の変更を主目的にしない |
| No degraded free sample | 無料枠で根拠URL、候補名、known_gaps、確認事項を隠さない |
| No final professional judgment | 税務、法律、申請可否、融資可否を断定しない |
| No silent coverage gap | corpus外、stale、未取得PDF、引用未検証を `known_gaps` として表示する |
| No raw-search-only finish | Evidence Packet や検索結果の後に、完成物 CTA を提示する |

## Worker F Notes

2026-05-05:

- `docs/integrations/README.md` を新規作成し、Wave 1 で追加された6本の主要docsを索引化した。
- `docs/integrations/implementation-loop-log.md` を新規作成し、Wave 1成果とWave 2実装対象を記録した。
- 編集は指定された2ファイルのみに限定した。

## Wave 3 Worker E Notes

2026-05-05:

- `python3 scripts/check_distribution_manifest_drift.py` の静的チェックで、残driftは18件、対象surfaceは5件だった。
- このWaveでは配布surfaceの大規模同期は行わず、次Waveで安全に直す順序だけを計画化した。
- 既存未コミット変更が多数あるため、次Waveでも `git status --short` で先行差分を確認し、他Workerの変更を戻さず、対象行だけを最小編集する。
- 価格変更、free-tier変更、課金unit変更には触れない。`pricing_unit_jpy_ex_tax`, `pricing_unit_jpy_tax_included`, `free_tier_requests_per_day`, unit文言はこのdrift解消の対象外とする。

### Distribution Drift Remaining Plan

Canonical source: `scripts/distribution_manifest.yml`

| Order | Drift | Count | Safe next action |
|---|---:|---:|---|
| 1 | `dxt/manifest.json` version `0.3.3 -> 0.3.4` | 1 | `version` だけを `pyproject_version` に合わせる。description、tools配列、価格/free-tier文言は同時に触らない。 |
| 2 | README tool count `96 -> 139` | 5 | `README.md` の該当5行だけを更新する。表現差分は最小にし、MCP protocol、program件数、価格/free-tier文言は変えない。 |
| 3 | pyproject tool count `96 -> 139` | 1 | `pyproject.toml` の description 内のtool countだけを更新する。package metadataやversionは同時に変更しない。 |
| 4 | DXT text tool count `96 -> 139` | 1 | `dxt/manifest.json` の description 内のtool countだけを更新する。version修正とは別diffにしてレビューしやすくする。 |
| 5 | OpenAPI description tool count `96 -> 139` | 1 | `docs/openapi/v1.json` の `info.description` 相当の文言だけを更新する。OpenAPI全体の再生成やpaths並べ替えはしない。 |
| 6 | site/llms tool count `96 -> 139` | 6 | `site/llms.txt` の該当6行だけを更新する。integration link、URL、pricing/free-tier文言、周辺説明は保持する。 |
| 7 | `dxt/manifest.json` tools array `96 entries -> 139 expected` | 1 | 最後に実施する。canonical tool listからの再生成が必要なため、他WorkerのDXT変更を確認してから専用diffで同期する。手編集で43件を足す場合も、順序・schema・operation名の検証を必須にする。 |
| 8 | site/llms public paths `221` | 2 | `site/llms.txt` のOpenAPI public paths表記2箇所だけを `221` に更新する。`docs/openapi/v1.json` のpaths本体は別担当の再生成結果を参照し、ここでは再生成しない。 |

Verification after each small batch:

1. `python3 scripts/check_distribution_manifest_drift.py --fix` で対象行の残driftとsuggestionを確認する。
2. 価格、free-tier、unitのdiffが混ざっていないことを `git diff -- README.md pyproject.toml dxt/manifest.json docs/openapi/v1.json site/llms.txt` で確認する。
3. DXT tools配列同期後だけ、JSON parseとtool countを別途確認してからdrift checkerを再実行する。

## Wave 4 Worker F Notes

2026-05-06:

- Wave 4 は価格変更を行わない。既存の単価、税表示、課金unit、pricing copy はこのWaveの変更対象外とする。
- 無料枠は匿名ユーザー3回/日の既存仕様を維持する。free-tierの回数、認証条件、quota semantics は変更しない。
- 無料枠で一部情報を隠す方針ではない。根拠URL、候補名、`known_gaps`、確認事項、免責境界は無料枠でも落とさない。
- 作業の主眼は、アウトプット内容の改善とAI向け価値訴求の改善に置く。検索結果だけで終わらせず、Evidence Packet、artifact CTA、agent routing copy を実装面に接続する。
- Wave 3 で残った distribution manifest drift を解消する。ただし未確定または未実施の項目を完了扱いにしない。
- unrelated dirty changes は戻さない。他Workerの変更をrevertせず、対象surfaceごとに最小diffで進める。

### Wave 4 Execution Frame

| Item | Status | Notes |
|---|---|---|
| 価格変更なし | fixed | unit単価、税表示、課金体系、pricing copy は変更しない。 |
| 匿名無料枠3回/日の維持 | fixed | `free_tier_requests_per_day` の意味と回数は既存仕様のまま扱う。 |
| 無料枠の情報非表示化をしない | fixed | 無料で一部だけ隠す話ではなく、通常品質の成功体験を維持する。 |
| アウトプット内容の改善 | planned | Evidence Packet、artifact最小セクション、0件時応答、確認範囲、CTAの実装接続を優先する。 |
| AI向け価値訴求の改善 | planned | README、llms.txt、OpenAPI、MCP/DXT description の意味を揃え、AI agentが使う/使わない条件を判断しやすくする。 |
| distribution manifest drift解消 | planned | `scripts/distribution_manifest.yml` をcanonical sourceとして、対象surfaceのdriftを小分けに解消する。 |
| `tools[]` 139化 | pending | DXT tools配列 `96 entries -> 139 expected` は未確定。実施前にcanonical tool list、schema、operation名、他WorkerのDXT変更を確認する。 |

### Wave 4 Constraints To Preserve

1. 価格、free-tier、unitのdiffをWave 4のdrift解消に混ぜない。
2. 無料枠は低品質サンプルではなく、匿名3回/日の通常品質利用として扱う。
3. 「無料なので一部だけ隠す」設計にはしない。価値差分は隠蔽ではなく、再利用できる完成物、監視、業務単位のartifact、派生データで作る。
4. 完了していないdistribution driftは `planned` または `pending` として記録し、実施済みのように書かない。
5. `tools[]` 139化は未確定のため、Wave 4開始時点では `pending` とする。

## Wave 7 Worker D Notes

2026-05-06:

- Wave 7 Worker D は価格、unit、税表示、無料回数、pricing copy を変更しない。
- 無料3回/日は通常品質体験のまま扱う。根拠URL、取得日時、候補名、`known_gaps`、確認事項、免責境界を無料枠でも隠さない。
- 「無料では一部を隠す」設計、価格変更、外部LLM料金保証を主訴求にする説明はこのWaveの対象外かつ禁止とした。
- 実際の出力改善として、Evidence Packet と AI 向け回答に `decision_insights`, `cross_source_signals`, `next_actions`, `known_gaps` をどう載せるかを docs に追加した。
- 既存データ基盤を付き合わせて価値発見を返すため、`program_decision_layer`, `corporate_risk_layer`, `source_quality_layer`, `document_requirement_layer`, `monitoring_delta_layer` を回答ブロックの生成元として明示した。
- 編集は指定された3ファイルのみに限定した。unrelated dirty changes は戻していない。

### Wave 7 Implementation Targets

| Target | Source Doc | Expected Implementation | Status |
|---|---|---|---|
| Evidence Packet intelligence block | `output-satisfaction-spec.md`, `artifact-catalog.md` | packet に `answer_intelligence.decision_insights[]`, `answer_intelligence.cross_source_signals[]`, `answer_intelligence.next_actions[]` を載せ、各itemから `evidence_item_ids` / `source_fact_ids` / `source_refs` へ戻れるようにする | planned |
| AI answer rendering | `output-satisfaction-spec.md` | AI 向け回答では「結論 -> 判断材料 -> 複数データの手掛かり -> 完成物 -> 次にやること -> 確認範囲 -> 判断境界」の順で短く表示する | planned |
| Cross-source signal assembly | `artifact-catalog.md`, `derived-data-layer-spec.md` | 締切 x 決算月、対象経費 x 様式、法人番号 x invoice、処分 x 制度推薦、採択事例 x 地域/業種密度などを `cross_source_signals[]` に変換する | planned |
| Known gaps gating | `output-satisfaction-spec.md` | `conflict`, `source_stale`, `citation_unverified`, `human_review_required` があるclaimは断定せず、`defer`, `watch`, `ask_human`, `needs_confirmation` に落とす | planned |
| Actionable next actions | `artifact-catalog.md` | CTAだけでなく、顧客質問、窓口確認、書類収集、監視追加、artifact生成を `next_actions[]` として返す | planned |
| Artifact-specific mapping | `artifact-catalog.md` | 10種類のartifactで、`decision_insights`, `cross_source_signals`, `next_actions` の生成例を実装タスクへ分解できる状態にする | documented |

### Wave 7 Acceptance Notes

| Check | Expected |
|---|---|
| Free 3/day quality | 無料枠でも通常品質の schema と根拠表示を維持する |
| No masking | 「有料なら根拠を表示」のような文言を入れない |
| No pricing rewrite | 価格、unit、税表示、free-tier回数を変更しない |
| Evidence-linked insights | `decision_insights` と `cross_source_signals` は根拠IDへ戻れる |
| Actionable output | `next_actions` は業務行動であり、単なるアップグレード誘導ではない |
| Visible gaps | `known_gaps` は欠陥ではなく確認範囲として表示する |

## Wave 8 Worker C Notes

2026-05-06:

- Wave 8 Worker C は価格、unit、税表示、無料回数、pricing copy を変更しない。
- Evidence Packet の実レスポンス改善として、JSON 出力時の top-level `decision_insights` を公開docsに反映した。
- `decision_insights` は `schema_version`, `generated_from`, `why_review`, `next_checks`, `evidence_gaps` を持ち、`records`, `quality`, `verification`, `evidence_value`, `corpus_snapshot_id` から作る補助ブロックとして扱う。
- `/v1/intel/bundle/optimal` には top-level `decision_support` を追加する方針を公開docsに追記した。生成元は既存レスポンスの `bundle`, `bundle_total`, `conflict_avoidance`, `optimization_log`, `runner_up_bundles`, `data_quality` に限定し、採択保証、受給保証、併用安全保証にはしない。
- `docs/openapi/v1.json` では Evidence Packet schema/example に `decision_insights` を追加した。現在のOpenAPI `paths` には `/v1/intel/bundle/optimal` が存在しないため、同endpointのpath追加やdescription新設は行っていない。
- 外部LLM料金保証を前面に出す表現は追加していない。compression/cost系の既存文言は変更しない。
- unrelated dirty changes は戻していない。他Workerの変更をrevertしていない。

### Wave 8 Implementation Targets

| Target | Source Doc | Expected Implementation | Status |
|---|---|---|---|
| Evidence Packet `decision_insights` public contract | `output-satisfaction-spec.md`, `artifact-catalog.md`, `docs/openapi/v1.json` | top-level `decision_insights` を JSON Evidence Packet の回答補助として説明し、why/next/gap の3分類を例示する | documented |
| bundle/optimal `decision_support` public contract | `output-satisfaction-spec.md`, `artifact-catalog.md` | top-level `decision_support` で primary bundle の理由、runner-up tradeoff、next actions、known gaps を返す | documented |
| OpenAPI bundle/optimal description | `docs/openapi/v1.json` | 既存 `/v1/intel/bundle/optimal` description がある場合のみ、top-level `decision_support` を説明する | not_applicable_current_snapshot |
| Boundary preservation | all touched docs | 価格、無料枠、課金体系、外部LLM料金保証、専門判断の断定を変更しない | documented |

## Wave 10 Worker C Notes

2026-05-06:

- Wave 10 Worker C は価格、無料枠、課金体系、pricing copy を変更しない。
- `/v1/intel/match` の新フィールド `next_questions`, `eligibility_gaps`, `document_readiness` を、AI agent が顧客ヒアリングと申請前チェックへそのまま使う補助フィールドとして docs と llms surfaces に反映した。
- `next_questions` は顧客へ聞く不足情報、`eligibility_gaps` は要件未解消・unknown条件、`document_readiness` は必要書類の準備状態と最新版確認の説明に限定した。
- これらのフィールドは採択、申請可否、書類完備、外部LLM料金の保証ではなく、公開情報と入力profileに基づく業務補助として扱う。
- unrelated dirty changes は戻していない。他Workerの変更をrevertしていない。

## Wave 11 Worker C Notes

2026-05-06:

- Wave 11 Worker C は価格、無料枠、課金体系、pricing copy を変更しない。
- `/v1/intel/houjin/{houjin_id}/full` の `decision_support` を、法人360レスポンスを AI agent が法人DD、与信前確認、監視提案へ変換する補助フィールドとして docs と llms surfaces に反映した。
- 法人360 `decision_support` は、公的リスクの見るべき点、追加DD質問、与信前の照合メモ、監視対象を短く示す用途に限定し、融資可否、取引安全、公的リスクなし、監視検知を保証しない。
- 外部LLM料金保証を前面に出す表現は追加していない。compression/cost系の既存文言は変更しない。
- unrelated dirty changes は戻していない。他Workerの変更をrevertしていない。

## Wave 12 Worker C Notes

2026-05-06:

- Wave 12 Worker C は価格、無料枠、課金体系、pricing copy を変更しない。
- funding stack/compat の `next_actions` を、AI agent が併用/排他表、申請前チェック、代替bundle提案へ使う確認行動として docs と llms surfaces に反映した。
- `next_actions` は pair verdict、conflict edge、`runner_up_bundles[]`、`exclude_program_ids` 再実行条件を説明する補助であり、採択、受給、併用安全性の保証として扱わない。
- 外部LLM料金保証を前面に出す表現は追加していない。compression/cost系の既存文言は変更しない。
- unrelated dirty changes は戻していない。他Workerの変更をrevertしていない。
