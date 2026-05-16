# AWS smart methods round3 09: legal, terms, privacy, administrative information policy

Date: 2026-05-15
Role: Round3 additional smart-method review 9/20
Topic: Legal / terms / privacy / administrative information handling
AWS execution: prohibited and not executed
AWS CLI/API/resource operation: not executed
Write scope: this file only

---

## 0. Verdict

判定: **追加価値あり。既存の `Policy Decision Firewall`、taint tracking、source terms revocation graph、public proof minimizer は正しい。ただし、まだ「禁止事項の列挙」に寄っており、実装時に人間の解釈へ戻る余地がある。Round3では、法務・規約・プライバシー判断を `artifactごとのpolicy decision` としてコンパイルするべき。**

今回さらにスマートにする中核はこれである。

> jpcite should treat legal / terms / privacy status as compiled evidence metadata, not as a checklist around the pipeline.

日本語で言うと、法務・規約・プライバシーは「最後に確認する注意点」ではなく、source取得、証跡化、packet生成、public proof、MCP/API、Release Capsuleまで常に付いて回る **実行時の判定データ** にする。

今回採用すべき追加機能は次の12個。

1. `Legal Policy Firewall v2`: 既存Policy Decision Firewallを、source/artifact/claim/surface/release単位で判定するpolicy-as-codeへ拡張する。
2. `Administrative Information Risk Taxonomy`: 公開行政情報を一律public-safeにせず、法人情報、個人情報、処分情報、要配慮、第三者権利、再配布条件で分類する。
3. `Privacy Taint Lattice`: private/publicの二値ではなく、結合リスク、再識別リスク、公開面、保持可否を含むtaint階層にする。
4. `Source Terms Contract`: source_profileにterms/license/robots/redistribution/proof visibility/retention/citation obligationsを構造化して持たせる。
5. `Source Terms Revocation Graph v2`: terms変更時に、既存artifact、Evidence Lens、Release Capsule、proof page、MCP exampleを逆引きで止められるようにする。
6. `Public Proof Surrogate Compiler`: raw screenshot/DOM/OCR/PDF mirrorではなく、公開可能な最小証跡表現を作る。
7. `Mosaic Risk Guard`: 公開情報同士、または公開情報とtenant private overlayの結合で、非公開の関係や個人が推測されるリスクを検出する。
8. `Legal Wording Compiler`: 「適法」「許可不要」「違反なし」「安全」などの法的断定をpacket/API/MCP/proofからコンパイル時に排除する。
9. `Human Review Escalation Ledger`: terms不明、個人情報高リスク、処分情報、裁判/紛争、医療・労務・金融などを審査待ちとしてledger化する。
10. `Public Correction and Supersession Ledger`: 公開source側の訂正、削除、更新、リンク切れ、source terms変更を受けてpacketをsupersedeできる台帳を持つ。
11. `Policy-Aware Agent Decision Bundle`: AI agentに、価格だけでなく「使える理由」「使えない理由」「人間確認が必要な理由」を機械可読で渡す。
12. `Release Legal Attestation`: Release Capsuleごとに、policy decision、blocked artifacts、known legal gaps、proof minimization結果をmanifest化する。

結論として、よりスマートな方法は「収集量を増やす」ことではない。  
**法務・規約・プライバシーの状態を、Evidence Product OSの中で第一級オブジェクトにすること** である。

---

## 1. Existing plan alignment

### 1.1 維持する前提

今回の提案は、正本計画の以下を変更しない。

- GEO-first。
- AIエージェントがエンドユーザーへ推薦する。
- AWSは一時的なartifact factoryで、本番runtimeではない。
- `bookyou-recovery` / `993693061769` / `us-east-1`。
- 意図的上限は `USD 19,300`。
- real private accounting CSVはAWS credit runへ入れない。
- request-time LLMで事実claimを生成しない。
- no-hitは `no_hit_not_absence`。
- public proofにはraw CSV、raw screenshot、raw DOM、raw HAR、raw OCR全文を直接出さない。
- CAPTCHA、login、stealth、proxy回避はしない。
- S3を含めAWS resourcesは最終削除し、zero-bill postureへ戻す。

### 1.2 既存計画の正しい点

既存計画はすでに次を含んでいる。

- `Policy Decision Firewall`
- taint tracking
- source terms revocation graph
- public proof minimizer
- source_profileのterms/robots/license boundary
- raw CSV非AWS
- Playwrightを公開ページのrendered observationに限定
- public proofの最小化
- release blockers
- zero-bill cleanup

方向は正しい。

### 1.3 まだ弱い点

弱いのは、次の解釈が残り得ること。

| 弱い解釈 | 問題 |
|---|---|
| 公開行政情報ならpublic-safe | 公開情報でも個人、処分、争訟、業務上の評価、再配布条件の問題がある |
| terms確認はsource単位で十分 | artifact、claim、surface、releaseごとに許可範囲が違う |
| screenshotは内部だけなら安全 | 内部保持、外部export、checksum、proof sidecarで漏れる可能性がある |
| privacyはCSVだけの問題 | 公的source内の個人名、役職、住所、処分情報、裁判情報も対象 |
| no-hit caveatがあれば十分 | no-hitのscope、expiry、source coverageをpolicyと結合しないと誤推薦される |
| legal disclaimerを置けばよい | API/MCPのmachine output自体が断定していたらdisclaimerでは足りない |
| terms変更時は次回から止めればよい | 既存Release Capsule、proof page、agent manifestも影響を受ける |

今回のRound3では、この弱さをpolicy objectとcompilerで潰す。

---

## 2. Smart method 1: Legal Policy Firewall v2

### 2.1 Purpose

既存の `Policy Decision Firewall` を、最終gateではなく全pipelineの判定器にする。

判定対象:

- source
- capture method
- raw artifact
- extracted fact
- claim_candidate
- claim_ref
- evidence_lens
- proof_surrogate
- packet_output
- MCP/OpenAPI example
- agent decision bundle
- Release Capsule

### 2.2 Policy decision schema

```json
{
  "schema_id": "jpcite.policy_decision.v2",
  "decision_id": "pd_...",
  "subject_type": "claim_ref",
  "subject_id": "claim_...",
  "evaluated_at": "2026-05-15T12:00:00+09:00",
  "policy_version": "2026-05-15.legal.v1",
  "input_classes": {
    "data_class": "public_official_person_related",
    "source_terms_class": "open_with_attribution",
    "privacy_class": "public_personal_low_to_medium",
    "redistribution_class": "metadata_and_short_excerpt_only",
    "surface_requested": "public_proof"
  },
  "decision": "allow_with_minimization",
  "allowed_surfaces": ["internal_evidence", "paid_packet", "public_proof_surrogate"],
  "blocked_surfaces": ["raw_screenshot_public", "raw_dom_public", "llms_example_with_person_name"],
  "required_transformations": [
    "proof_surrogate_compile",
    "short_excerpt_limit",
    "role_context_minimize",
    "no_legal_conclusion_wording"
  ],
  "required_caveats": [
    "public_source_observation_only",
    "not_legal_advice",
    "no_hit_not_absence"
  ],
  "review_status": "automated_pass",
  "human_review_required": false,
  "revocation_hooks": ["source_terms_revocation_graph", "release_capsule_recompile"]
}
```

### 2.3 Decision states

| Decision | Meaning |
|---|---|
| `allow` | 指定surfaceにそのまま出せる |
| `allow_with_minimization` | proof surrogate化、短縮、マスキング、文言制限後に出せる |
| `allow_internal_only` | 内部証跡には使えるがpublic/API/MCPには出せない |
| `allow_paid_tenant_only` | 認証済みの有料応答内だけに限定 |
| `manual_review_required` | human reviewが終わるまでclaim support不可 |
| `quarantine` | schema/terms/privacy driftで隔離 |
| `deny` | 取得、保持、公開、利用いずれかを禁止 |

### 2.4 Merge difference

正本計画へマージする差分:

- すべてのmanifestへ `policy_decision_ids[]` を追加する。
- `claim_ref` は `policy_decision=allow|allow_with_minimization` を満たさない限りpublic packetに入れない。
- `Release Capsule` は `release_legal_attestation.json` を必須にする。
- `policy_decision` がないartifactはaccepted artifactではない。

### 2.5 Contradiction resolution

矛盾なし。

既存の `Policy Decision Firewall` を置き換えるのではなく、v2として具体化する。

---

## 3. Smart method 2: Administrative Information Risk Taxonomy

### 3.1 Why public official is not one class

jpciteは日本の公的一次情報を扱う。これは強い価値だが、「公的に公開されている」ことと「jpciteがどのsurfaceにも再表示してよい」ことは同じではない。

公開行政情報には少なくとも次が混在する。

- 法令、告示、通達、制度説明
- 法人番号、登録番号、許認可情報
- 補助金、入札、採択、交付、公告
- 行政処分、指名停止、取消、警告、公表
- 裁判、審決、紛争、行政不服
- 医療、介護、福祉、労務、教育、金融などの規制情報
- 個人名、役職名、住所、資格者名、代表者名
- 事故、リコール、違反、苦情、勧告

これを一律 `public_official` とすると危険である。

### 3.2 Proposed taxonomy

| Class | Example | Default handling |
|---|---|---|
| `public_law_text` | 法令、告示、規則 | 引用/出典/時点を付けて利用可。ただしsource terms確認 |
| `public_policy_guidance` | ガイドライン、Q&A、通達解説 | 出典・版・更新日を必須。法的結論は禁止 |
| `public_business_registry` | 法人番号、登録番号、許認可登録 | 法人単位packetで利用可 |
| `public_business_event` | 採択、入札、指名停止、処分 | eventとして扱い、現在評価に直結させない |
| `public_person_related` | 代表者名、資格者名、担当者名 | 最小化。public proofでの露出制限 |
| `public_sensitive_context` | 処分、紛争、労務、医療、金融 | human_reviewまたは高いminimization |
| `public_judicial_admin` | 判決、審決、裁決 | 事案範囲・時点・匿名性を維持。汎用評価禁止 |
| `public_aggregate_stats` | e-Stat等統計 | 集計単位、更新時点、推計範囲を明示 |
| `third_party_embedded_content` | 画像、地図、PDF内素材 | terms/rights不明ならraw露出不可 |
| `tenant_private_overlay` | ユーザーCSV由来fact | public proof、GEO、examplesへ出さない |

### 3.3 Required fields

`source_receipt` と `claim_ref` に追加する。

```json
{
  "administrative_info_class": "public_business_event",
  "contains_person_related_info": true,
  "sensitive_context_flags": ["administrative_disposition"],
  "public_interest_basis": "official_publication",
  "surface_minimization_required": true,
  "current_status_inference_allowed": false,
  "evaluation_wording_allowed": false
}
```

### 3.4 Merge difference

正本計画へマージする差分:

- `data_class` とは別に `administrative_info_class` を追加する。
- `public_official_source_raw` は安全classではなく、さらに分類される親classにする。
- 処分、裁判、労務、医療、金融、個人名を含むsourceは `sensitive_context_flags[]` を必須にする。

### 3.5 Contradiction resolution

既存計画の「公的一次情報ベース」は維持する。  
ただし「公的一次情報 = どこでも公開可能」ではないと明記する。

---

## 4. Smart method 3: Privacy Taint Lattice

### 4.1 Problem

既存計画はtaint trackingを採用しているが、よりスマートにするには二値ラベルでは足りない。

特に次が危険。

- 公開source内の個人名と法人情報の結合
- CSV由来取引先IDと公的sourceの結合
- 行政処分情報と現在の取引判断の結合
- 裁判/審決の過去情報を現在評価へ転用
- proof pageに検索対象や取引関係がURLやtitleとして残る

### 4.2 Taint lattice

上に行くほど公開/再利用が難しい。

```text
public_law_structural
  < public_official_business_metadata
  < public_official_business_event
  < public_official_person_related
  < public_sensitive_administrative_context
  < tenant_private_aggregate
  < tenant_private_relationship
  < tenant_private_row_or_raw
```

### 4.3 Taint propagation rules

| Operation | Result |
|---|---|
| `public_business_registry` + `tenant_private_counterparty_id` | `tenant_private_relationship` |
| `public_disposition_event` + "safe/no issue" wording | deny |
| `public_person_related` + public proof page | minimize or block |
| `public_law_text` + rule decision | allowed only as candidate/checklist, not legal conclusion |
| `tenant_private_aggregate` + public source receipt | tenant-private packet only |
| `OCR_candidate` + date/money/legal deadline | needs corroboration |
| `no_hit` + legal absence conclusion | deny |

### 4.4 Surface matrix

| Surface | Max allowed taint by default |
|---|---|
| internal evidence store | `public_sensitive_administrative_context` |
| AWS accepted public bundle | `public_official_business_event` with minimization |
| public proof page | `public_official_business_metadata` or surrogate only |
| OpenAPI/MCP examples | synthetic or public-safe only |
| `llms.txt` / `.well-known` | no personal, no tenant, no sensitive event details |
| paid packet response | based on buyer policy and packet policy |
| GEO proof page | public-safe surrogate only |
| CSV overlay response | tenant-private only |

### 4.5 Merge difference

正本計画へマージする差分:

- `taint_labels[]` を `taint_lattice_level` と `join_taint_result` に拡張する。
- join operationはすべて `taint_propagation_rule_id` を出力する。
- public proof compilerは `max_public_taint_level` を超えるartifactを拒否する。

### 4.6 Contradiction resolution

CSV private overlay方針と整合する。  
特に、CSV内の法人番号/T番号を公式sourceへ照合した結果は、公式情報そのものではpublicでも「そのユーザーがその相手と関係している」ことはprivateである。この点をtaint propagationで固定する。

---

## 5. Smart method 4: Source Terms Contract

### 5.1 Problem

`terms_status`、`robots_status`、`license_boundary` は既にある。しかし、実行に必要な粒度はもっと細かい。

たとえば同じsourceでも以下が違う。

- 取得は可能
- 内部解析は可能
- metadataだけ公開可能
- 短い引用は可能
- screenshotは内部証跡のみ
- raw mirrorは禁止
- 商用利用には条件あり
- API利用規約が別にある
- RSS/HTML/PDF/CSVで条件が違う
- e-Govなどポータル全体規約とAPI規約が別にある

### 5.2 Contract schema

```json
{
  "schema_id": "jpcite.source_terms_contract.v1",
  "source_profile_id": "sp_...",
  "publisher": "example ministry",
  "official_url": "https://...",
  "terms_url": "https://...",
  "privacy_policy_url": "https://...",
  "robots_url": "https://.../robots.txt",
  "checked_at": "2026-05-15T12:00:00+09:00",
  "terms_hash": "sha256:...",
  "terms_status": "confirmed",
  "access_permissions": {
    "api": "allowed",
    "bulk_download": "allowed_if_available",
    "html_fetch": "allowed",
    "playwright_observation": "allowed_public_pages_only",
    "ocr": "allowed_internal_candidate_only",
    "login_required": "blocked",
    "captcha_or_bot_challenge": "blocked"
  },
  "reuse_permissions": {
    "internal_analysis": "allowed",
    "paid_packet_facts": "allowed_with_citation",
    "public_proof_metadata": "allowed",
    "public_short_excerpt": "terms_dependent",
    "public_screenshot": "blocked_by_default",
    "raw_mirror": "blocked"
  },
  "obligations": {
    "attribution_required": true,
    "source_url_required": true,
    "update_date_required": true,
    "modification_notice_required": true,
    "separate_terms_apply": false
  },
  "retention": {
    "raw_artifact_after_aws_run": "delete_after_external_export_gate",
    "proof_surrogate": "release_capsule_allowed",
    "terms_recheck_ttl_days": 14
  },
  "revocation_policy": {
    "on_terms_hash_change": "quarantine_new_public_compile",
    "on_robots_block": "stop_new_capture",
    "on_publisher_request": "manual_review_required"
  }
}
```

### 5.3 Merge difference

正本計画へマージする差分:

- `source_profile` の `terms_status` を `source_terms_contract_id` へ昇格する。
- AWS canaryは取得成功だけでなく、`source_terms_contract` 完成をaccepted条件にする。
- `accepted_artifact` は `source_terms_contract_id` を必須にする。
- `terms_recheck_ttl_days` をRelease Capsuleのfreshness gateに入れる。

### 5.4 Contradiction resolution

既存のsource_profile項目と矛盾しない。  
source_profileを厚くするのではなく、termsだけ独立contract化する。

---

## 6. Smart method 5: Source Terms Revocation Graph v2

### 6.1 Problem

termsやrobotsは変わる。sourceの公開範囲も変わる。  
そのとき「今後の取得を止める」だけでは足りない。

影響を受ける可能性があるもの:

- raw artifact
- source_receipt
- claim_ref
- evidence_lens
- packet examples
- proof pages
- OpenAPI/MCP examples
- agent decision page
- Release Capsule
- static DB
- GEO pages

### 6.2 Revocation graph

```text
source_terms_contract
  -> capture_run
  -> raw_artifact
  -> source_receipt
  -> claim_ref
  -> evidence_lens
  -> proof_surrogate
  -> packet_output
  -> agent_decision_bundle
  -> Release Capsule
```

### 6.3 Revocation actions

| Trigger | Action |
|---|---|
| terms hash changed | stop public compile; re-evaluate contract |
| robots changed to disallow | stop new capture; retain only allowed historical metadata pending review |
| source removes page | mark source withdrawn; do not imply fact false |
| publisher requests correction | manual review; supersede affected proof |
| personal info risk found | minimize or remove public proof surrogate |
| raw artifact retention expired | delete raw, keep checksum/proof surrogate if allowed |
| license boundary downgraded | recompile Release Capsule excluding affected artifacts |

### 6.4 Merge difference

正本計画へマージする差分:

- `Release Capsule` activation must query `source_terms_revocation_graph` for unresolved revocations.
- `source_terms_changed_unreviewed=true` is a release blocker.
- proof pages must have `superseded_by` and `policy_status`.

### 6.5 Contradiction resolution

zero-billと矛盾しない。  
raw artifactをAWSに残さず、外部exportされたminimal ledgerとRelease Capsule manifestで逆引きできるようにする。

---

## 7. Smart method 6: Public Proof Surrogate Compiler

### 7.1 Problem

public proofの目的は「根拠があることをAI agentと人間に説明すること」であり、raw artifactを配布することではない。

raw screenshotやDOMを公開すると、以下の問題がある。

- 再配布条件違反
- 個人情報露出
- 第三者著作物の混入
- 検索対象や取引関係の漏えい
- screenshot内の広告/地図/画像/埋込contentの権利問題
- OCR誤読の断定化

### 7.2 Surrogate types

| Surrogate | Use |
|---|---|
| `source_link_surrogate` | URL、publisher、observed_at、title hash |
| `metadata_surrogate` | source type、更新日、document id、checksum |
| `field_fact_surrogate` | 取得したfield名と値。ただしpolicy通過済みのみ |
| `short_excerpt_surrogate` | terms許容範囲の短い抜粋。必須でsource link |
| `screenshot_metadata_surrogate` | screenshot存在、viewport、hash、capture time。画像本体は出さない |
| `ocr_candidate_surrogate` | OCR候補があることだけ示し、単独claimにはしない |
| `no_hit_scope_surrogate` | 検索範囲、query正規化、observed_at、expiry |
| `gap_surrogate` | 取得できない/未確認/blockedの理由 |

### 7.3 Public proof payload

```json
{
  "schema_id": "jpcite.public_proof_surrogate.v1",
  "proof_id": "proof_...",
  "source_profile_id": "sp_...",
  "source_terms_contract_id": "stc_...",
  "policy_decision_id": "pd_...",
  "surrogate_type": "source_link_surrogate",
  "publisher": "official publisher",
  "official_url": "https://...",
  "observed_at": "2026-05-15T12:00:00+09:00",
  "content_hash_available": true,
  "raw_artifact_public": false,
  "contains_person_related_info": false,
  "known_gaps": [],
  "caveats": ["public_source_observation_only"]
}
```

### 7.4 Merge difference

正本計画へマージする差分:

- public proof pageは `proof_surrogate[]` のみを読む。
- raw screenshot/DOM/OCR/PDFはpublic proof rendererから参照できない構造にする。
- proof page buildで `raw_artifact_public=false` をschema gateにする。

### 7.5 Contradiction resolution

既存のpublic proof minimizerを具体化するだけで矛盾なし。

---

## 8. Smart method 7: Mosaic Risk Guard

### 8.1 Problem

個々の情報は公開でも、組み合わせると非公開の関係が推測される。

例:

- ユーザーCSV内の取引先ID + インボイス登録情報
- 特定地域の小規模事業者 + 補助金採択 + 業種 + 金額
- 行政処分情報 + 現在の取引先リスト
- 労務/医療/介護系source + 個人名/事業所名
- no-hitのquery一覧 + 対象企業リスト

### 8.2 Guard rules

| Pattern | Default |
|---|---|
| public official ID joined from tenant CSV | tenant-private relationship |
| public event plus private portfolio membership | tenant-private derived insight |
| small group public aggregate plus private filter | suppress |
| repeated no-hit queries exposing target list | do not publish |
| public person name plus sensitive context | minimize/manual review |
| legal/compliance output plus current suitability wording | wording block |

### 8.3 Merge difference

正本計画へマージする差分:

- `join_operation` manifestに `mosaic_risk_score_set` を追加する。
- public proof compilerは `mosaic_risk_guard_passed=true` を要求する。
- CSV overlayはpublic proof生成対象から除外する。

### 8.4 Contradiction resolution

CSV方針と整合。  
「公式情報はpublicでも、ユーザーとのjoin関係はprivate」を機械的に保証する。

---

## 9. Smart method 8: Legal Wording Compiler

### 9.1 Problem

法務・税務・労務・許認可・コンプライアンス系では、出典が正しくても、出力文言が断定的だと危険。

既存計画には禁止語があるが、よりスマートにするならコンパイラで制御する。

### 9.2 Forbidden semantic classes

単語一致だけでは足りない。意味classで禁止する。

| Semantic class | Blocked examples |
|---|---|
| legal conclusion | 適法、違法ではない、許可不要、問題なし |
| eligibility conclusion | eligible, 対象確定、受給可能、申請できる |
| safety conclusion | 安全、リスクなし、懸念なし |
| credit/trust conclusion | 信用できる、信用スコア、優良、危険企業 |
| absence proof | 存在しない、処分なし、登録なしと断定 |
| professional advice substitute | 税務判断、労務判断、法的助言として確定 |

### 9.3 Allowed replacement patterns

| Risky output | Allowed output |
|---|---|
| 許可不要です | 公開source上、この条件に対応する許認可候補は確認できていません。人間確認が必要です |
| 補助金対象です | 公開条件に照らした候補優先度が高いです |
| 問題ありません | 指定source範囲では注意eventはhitしていません。不在証明ではありません |
| 信用できます | 公的証跡上の確認結果とgapを示します。信用判断ではありません |
| 違反していません | 違反有無の結論ではなく、公開情報で確認したeventを示します |

### 9.4 Compiler placement

```text
Output Composer
  -> Legal Wording Compiler
  -> Policy Decision Firewall
  -> Agent Decision Bundle
  -> Packet/API/MCP/Proof Renderer
```

### 9.5 Merge difference

正本計画へマージする差分:

- packet text fieldsに `wording_policy_id` を必須にする。
- MCP/OpenAPI examplesもwording compilerを通す。
- forbidden semantic class検出はrelease blocker。

### 9.6 Contradiction resolution

既存の禁止語リストを強化するもので矛盾なし。

---

## 10. Smart method 9: Human Review Escalation Ledger

### 10.1 Problem

すべてを自動でallow/denyにすると、法務・規約・プライバシー判断の難しい領域で危険になる。

特に以下は自動公開に向かない。

- terms不明
- robots/termsの解釈が曖昧
- 個人情報が含まれる処分・紛争
- 医療、介護、金融、労務、教育、未成年、消費者被害
- screenshotに第三者素材が多い
- OCR confidenceが低い
- source間矛盾がある
- 法令/通達/自治体手続きの適用関係が複雑

### 10.2 Ledger schema

```json
{
  "schema_id": "jpcite.human_review_escalation.v1",
  "review_id": "hr_...",
  "trigger": "public_sensitive_administrative_context",
  "artifact_ids": ["art_..."],
  "claim_ids": ["claim_..."],
  "requested_surface": "public_proof",
  "default_action_until_review": "block_public_compile",
  "allowed_interim_use": ["internal_evidence"],
  "review_questions": [
    "Can this event be shown as a public proof surrogate?",
    "Must personal names be removed?",
    "Is short excerpt permitted under source terms?"
  ],
  "status": "pending",
  "expires_at": "2026-05-22T00:00:00+09:00"
}
```

### 10.3 Merge difference

正本計画へマージする差分:

- `human_review_required=true` is not just a field; it must create a ledger item.
- unresolved human review blocks public proof and Release Capsule activation for affected lens.
- pending review can still be used as `known_gap`, not as claim support.

### 10.4 Contradiction resolution

AWS高速消化と矛盾しない。  
AWSはreview待ちledgerを成果物として残せる。review pendingも「今後の商品化候補」や「source gap」として価値がある。

---

## 11. Smart method 10: Public Correction and Supersession Ledger

### 11.1 Problem

公的sourceは更新・訂正・削除される。  
jpciteのpacketも、作成時点の証跡として残しつつ、現在の推薦には使わない状態へ移行できる必要がある。

### 11.2 Supersession types

| Type | Meaning |
|---|---|
| `source_updated` | source内容が更新された |
| `source_corrected` | source側が訂正した |
| `source_removed` | source URLが削除/非公開になった |
| `terms_changed` | 利用条件が変わった |
| `policy_reclassified` | jpcite側のpolicy分類が変わった |
| `privacy_minimization_required` | 個人/センシティブ情報により公開縮小 |
| `claim_conflict_found` | source間矛盾が見つかった |
| `packet_schema_recompiled` | packet schema変更により再コンパイル |

### 11.3 Packet behavior

| State | Public behavior |
|---|---|
| active | 通常表示 |
| superseded | 新版への誘導、旧版は時点証跡として限定表示 |
| withdrawn_public | public proofから除外。内部manifestだけ残す |
| blocked_pending_review | human review until resolved |
| tombstoned | URL/IDだけ残し、内容は出さない |

### 11.4 Merge difference

正本計画へマージする差分:

- proof pages and packet examples must include `policy_status`.
- `Release Capsule` activation requires no unresolved `withdraw_public` action.
- GEO pages should not point to superseded public proof as current evidence.

### 11.5 Contradiction resolution

zero-billと矛盾しない。  
minimal supersession ledgerはAWS外のRelease Capsule metadataに保持する。

---

## 12. Smart method 11: Policy-Aware Agent Decision Bundle

### 12.1 Problem

AI agentは、単に「安いpacket」を知るだけでは足りない。  
法務・規約・プライバシー上、何ができて何ができないかを説明できる必要がある。

### 12.2 Bundle additions

`agent_purchase_decision` に追加する。

```json
{
  "policy_summary": {
    "can_recommend": true,
    "recommendation_scope": "public official evidence packet",
    "not_legal_advice": true,
    "contains_sensitive_admin_context": false,
    "contains_tenant_private_overlay": false,
    "public_proof_available": true,
    "raw_artifacts_available_to_user": false
  },
  "why_not_higher_tier": [
    "Higher tier would add sensitive administrative event checks requiring human review."
  ],
  "why_manual_review_needed": [],
  "safe_agent_language": [
    "このpacketは公的一次情報に基づく確認結果と不足情報を返します。",
    "法的結論や適法性判断ではありません。"
  ],
  "blocked_agent_language": [
    "この会社は安全です。",
    "許可は不要です。",
    "行政処分は存在しません。"
  ]
}
```

### 12.3 Merge difference

正本計画へマージする差分:

- `agent_recommendation_card` に `policy_summary` を追加する。
- free preview must disclose if policy limits prevent proof display.
- cost preview must not upsell blocked/legal-sensitive outputs without caveat.

### 12.4 Contradiction resolution

GEO-firstと整合。  
AI agentが推薦しやすくなるだけでなく、推薦してはいけない言い方も機械的に避けられる。

---

## 13. Smart method 12: Release Legal Attestation

### 13.1 Problem

Release Capsuleは本番公開単位になる。  
そのため、機能テストだけでなく、法務・規約・プライバシーのattestationが必要。

### 13.2 Attestation manifest

```json
{
  "schema_id": "jpcite.release_legal_attestation.v1",
  "release_capsule_id": "rc_...",
  "generated_at": "2026-05-15T12:00:00+09:00",
  "policy_version": "2026-05-15.legal.v1",
  "source_terms_contracts": {
    "total": 1200,
    "confirmed": 1100,
    "manual_review_required": 80,
    "blocked": 20
  },
  "artifact_policy_decisions": {
    "allow": 500000,
    "allow_with_minimization": 45000,
    "internal_only": 9000,
    "manual_review_required": 1400,
    "deny": 300
  },
  "public_proof_minimization": {
    "raw_screenshots_public": 0,
    "raw_dom_public": 0,
    "raw_ocr_fulltext_public": 0,
    "proof_surrogates_public": 28000
  },
  "privacy": {
    "real_user_csv_in_aws": false,
    "tenant_private_data_in_public_bundle": false,
    "mosaic_risk_unresolved": 0
  },
  "wording": {
    "forbidden_semantic_classes_detected": 0,
    "no_hit_not_absence_enforced": true
  },
  "release_decision": "pass"
}
```

### 13.3 Release blockers

Add as hard blockers:

- public bundle contains raw screenshot/DOM/OCR/HAR body.
- public proof contains tenant private or real CSV-derived fact.
- `policy_decision_id` missing for accepted public artifact.
- source terms changed and unresolved.
- public proof uses blocked source terms.
- sensitive administrative context appears without minimization/review.
- legal conclusion wording detected.
- no-hit output implies absence/safety.
- Release Capsule lacks legal attestation.

### 13.4 Merge difference

正本計画へマージする差分:

- `release_legal_attestation.json` becomes a required Release Capsule file.
- production pointer cannot switch without attestation pass.
- rollback should prefer previous capsule with valid attestation, not merely previous build.

### 13.5 Contradiction resolution

既存のRelease Capsule、pointer rollback、zero-bill設計と整合する。

---

## 14. How this merges into the master execution plan

### 14.1 New canonical concepts

正本計画に追加する概念:

| New concept | Where it fits |
|---|---|
| `Legal Policy Firewall v2` | Policy Decision Firewallの具体化 |
| `Administrative Information Risk Taxonomy` | data model / source_profile / claim_ref |
| `Privacy Taint Lattice` | taint tracking / CSV / public proof |
| `Source Terms Contract` | source_profileのterms詳細 |
| `Source Terms Revocation Graph v2` | release gate / source evolution |
| `Public Proof Surrogate Compiler` | proof page renderer |
| `Mosaic Risk Guard` | CSV overlay / joins / proof compiler |
| `Legal Wording Compiler` | packet/API/MCP renderer |
| `Human Review Escalation Ledger` | gap/review workflow |
| `Public Correction and Supersession Ledger` | release and proof lifecycle |
| `Policy-Aware Agent Decision Bundle` | agent recommendation / free preview |
| `Release Legal Attestation` | Release Capsule activation gate |

### 14.2 Required schema additions

Add to `source_profile`:

- `source_terms_contract_id`
- `administrative_info_classes[]`
- `sensitive_context_default`
- `public_person_related_possible`
- `raw_publication_reuse_policy`

Add to `source_receipt`:

- `administrative_info_class`
- `privacy_taint_level`
- `source_terms_contract_id`
- `policy_decision_id`
- `proof_surrogate_allowed`

Add to `claim_ref`:

- `policy_decision_id`
- `legal_wording_policy_id`
- `current_status_inference_allowed`
- `evaluation_wording_allowed`
- `human_review_required`

Add to `evidence_lens`:

- `max_taint_level`
- `proof_surrogate_ids[]`
- `blocked_artifact_ids[]`
- `terms_revocation_status`

Add to `Release Capsule`:

- `release_legal_attestation.json`
- `source_terms_contracts.manifest.json`
- `policy_decisions.manifest.json`
- `public_proof_surrogates.manifest.json`
- `supersession_ledger.jsonl`

### 14.3 Execution order insertion

This does not require a new large phase. Insert into the existing plan as follows:

1. Before AWS broad capture:
   - define `source_terms_contract.v1`
   - define `policy_decision.v2`
   - define `administrative_info_class`
   - define `privacy_taint_lattice`

2. During AWS canary:
   - each source must produce `source_terms_contract`
   - each artifact must produce `policy_decision`
   - blocked/manual sources become accepted gap artifacts, not public claims

3. During evidence compile:
   - run Legal Policy Firewall v2
   - run Mosaic Risk Guard
   - compile proof surrogates
   - block raw proof leakage

4. During packet compile:
   - run Legal Wording Compiler
   - add policy-aware agent decision fields
   - include human review and caveat fields

5. During release:
   - generate Release Legal Attestation
   - block pointer switch if attestation fails
   - include supersession hooks

6. During post-release:
   - monitor terms revocation
   - supersede affected proof pages
   - keep zero-bill posture; no AWS runtime dependency

### 14.4 No change to AWS budget plan

This does not require increasing AWS spend.

It changes acceptance criteria:

- A job that captures many pages but cannot pass policy is lower value.
- A job that creates clean `source_terms_contracts`, `proof_surrogates`, and `known_gaps` is high value.
- blocked/manual-review outputs are not waste; they are valuable gap assets and product roadmap signals.

---

## 15. Adopt / reject decisions

### 15.1 Adopt now

Adopt in the master plan:

1. `Legal Policy Firewall v2`
2. `Administrative Information Risk Taxonomy`
3. `Privacy Taint Lattice`
4. `Source Terms Contract`
5. `Source Terms Revocation Graph v2`
6. `Public Proof Surrogate Compiler`
7. `Mosaic Risk Guard`
8. `Legal Wording Compiler`
9. `Human Review Escalation Ledger`
10. `Public Correction and Supersession Ledger`
11. `Policy-Aware Agent Decision Bundle`
12. `Release Legal Attestation`

### 15.2 Adopt later

Adopt after RC1/RC2:

| Idea | Reason to delay |
|---|---|
| full privacy impact assessment dashboard | useful, but not needed for first release |
| formal legal review workflow UI | start with ledger and manual review files |
| differential privacy for aggregate product analytics | relevant once analytics scale |
| automated source terms classifier using model assistance | useful, but must not approve terms without deterministic/manual gate |
| public request/correction portal | useful after public proof pages have traffic |

### 15.3 Do not adopt

Do not adopt:

| Rejected idea | Reason |
|---|---|
| CAPTCHA/login/stealth/proxy access | violates public observation boundary and increases legal/terms risk |
| raw public screenshot archive on public proof pages | proof purpose is surrogate, not raw redistribution |
| raw DOM/HAR/OCR fulltext public exposure | high privacy/rights leakage risk |
| permanent AWS archive of raw artifacts | contradicts zero-bill and increases retention risk |
| encrypted real user CSV in AWS during credit run | contradicts real CSV non-AWS decision |
| public examples based on real tenant CSV | privacy leak risk |
| stable hash publication of private identifiers | dictionary/linkage risk |
| generic legal/trust/credit score | product concept is evidence, not legal/credit judgment |
| LLM-only terms approval | terms approval must be deterministic/manual, not probabilistic |
| treating all government-published data as freely redistributable | terms, embedded rights, privacy and surface restrictions vary |
| exact USD 19,493.94 burn if it risks paid overage | user requires no further AWS bill |

---

## 16. Updated product interpretation

This review changes the product framing slightly.

Before:

> jpcite sells source-backed public information outputs.

After:

> jpcite sells policy-safe, source-backed public-information outputs that AI agents can recommend without accidentally making legal conclusions, exposing private joins, or over-publishing raw administrative artifacts.

This is a stronger product.

AI agents do not only need facts. They need to know:

- Can I recommend this packet?
- Can I show this proof?
- Can I say this wording?
- Is this public enough for the user-facing answer?
- Is this only an observation, not a legal conclusion?
- Is there a privacy or terms limitation?
- Does the user need human review?

The `Policy-Aware Agent Decision Bundle` provides that.

---

## 17. Final contradiction check

| Area | Status | Notes |
|---|---|---|
| GEO-first | PASS | policy-aware agent bundle improves recommendation safety |
| AWS self-running | PASS | policy gates become acceptance criteria; no AWS command needed here |
| Fast credit use | PASS | policy can run in parallel with capture; blocked outputs still become gap assets |
| USD 19,300 stopline | PASS | no change |
| Zero-bill teardown | PASS | no permanent AWS archive; minimal external ledgers only |
| Real CSV non-AWS | PASS | reinforced |
| Public proof | PASS | surrogate compiler prevents raw leakage |
| Playwright | PASS | rendered observation only; no access bypass |
| Legal/tax/compliance outputs | PASS with caveat | outputs must be candidates/checklists/evidence summaries, not advice/conclusions |
| Administrative information | PASS with caveat | public official does not mean public-safe for every surface |
| Release Capsule | PASS | legal attestation becomes activation gate |
| Agent UX | PASS | decision bundle becomes safer and more recommendable |

Overall verdict: **PASS with recommended merge.**

The plan becomes smarter if legal/terms/privacy are not bolted on at the end, but compiled into every artifact, claim, proof, packet, agent decision, and Release Capsule.

---

## 18. Official references checked

These references were used only to ground the planning assumptions. This document is not legal advice.

- 個人情報保護委員会: 法令・ガイドライン等  
  https://www.ppc.go.jp/personalinfo/legal/
- 個人情報保護委員会: 個人情報の保護に関する法律についてのガイドライン（通則編）  
  https://www.ppc.go.jp/personalinfo/legal/guidelines_tsusoku/
- 個人情報保護委員会: 匿名加工情報  
  https://www.ppc.go.jp/personalinfo/tokumeikakouInfo/
- 個人情報保護委員会: 個人情報保護法等  
  https://www.ppc.go.jp/personalinfo/
- e-Govポータル: 利用規約  
  https://www.e-gov.go.jp/terms
- e-Govポータル: 個人情報取扱方針  
  https://www.e-gov.go.jp/privacy-policy
- e-Gov法令検索: 著作権法  
  https://laws.e-gov.go.jp/law/345AC0000000048
- 文化庁: 著作権施策に関する総合案内  
  https://www.bunka.go.jp/seisaku/chosakuken/index.html
- デジタル庁: 二次利用の促進のための府省のデータ公開に関する基本的考え方（ガイドライン）  
  https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/f7fde41d-ffca-4b2a-9b25-94b8a701a037/7c57e1a9/20220523_resources_data_guideline_01.pdf
- デジタル庁: 政府標準利用規約（第2.0版）の解説  
  https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/f7fde41d-ffca-4b2a-9b25-94b8a701a037/a0f187e6/20220706_resources_data_betten_01.pdf

