# AWS credit review 18: cost / artifact ROI ledger

作成日: 2026-05-15  
レビュー枠: AWSクレジット統合計画 追加20エージェントレビュー 18/20  
担当: コスト対成果物ROI台帳、打ち切り数学、予算移管基準  
AWS前提: CLI profile `bookyou-recovery` / Account `993693061769` / default region `us-east-1`  
対象クレジット: USD 19,493.94  
状態: Markdown追加レビューのみ。AWS CLI/API実行、AWSリソース作成、ジョブ投入はしない。

## 0. 結論

USD 19,493.94 のクレジットは、Cost Explorer上の数字を大きくするためではなく、jpcite本体へ取り込める成果物を最大化するために使う。

最終方針:

1. ほぼ全額を使う前提で、意図的な使用上限は `USD 19,300` とする。残りはbilling lag、credit対象外、cleanup遅延、税/サポート/転送などの防波堤であり、無駄ではない。
2. すべてのジョブは `accepted artifact` を生む義務を持つ。raw file、未検証candidate、重複record、terms不明record、private/raw CSV由来recordはROIに数えない。
3. 支出速度は速くする。ただし30-60分単位で `marginal accepted value / USD` を見て、単価が悪いジョブは止め、高密度ジョブへ予算を移す。
4. Codex/Claude等の対話エージェントがrate limitに入っても、AWS側は事前に固定されたqueue、manifest、ledger、stopline、drain条件で自律的に進む。ただし `USD 18,900` 以降のmanual stretchは明示承認なしに始めない。
5. 本番デプロイに必要な成果物を優先する。大量source lakeだけで終わらせず、packet/proof/GEO/deploy artifactへ変換してからcredit runを閉じる。

この文書は、統合計画のJ01-J24を「いくら使って、何個の成果物が出れば継続か」に変換するROI運用台帳である。

## 1. ROIで数える成果物

### 1.1 Accepted artifact definition

ROIへ計上できるのは、以下を満たす成果物だけである。

- `artifact_manifest.jsonl` に登録済み
- checksumあり
- provenanceあり
- license/terms boundaryが `full_fact`、`metadata_only`、`link_only`、`review_required` のいずれかで明示済み
- private/raw CSV、摘要、口座、取引先、給与、個人識別子を含まない
- `source_receipt` または `known_gap` へ接続済み
- no-hitを不存在/安全/問題なし/適格確定へ変換していない
- `quality.gate_status` が `pass` または `review_required_nonblocking`
- repo importまたはpublic proof/discoveryへの使い道が明確

以下はROIに数えない。

- S3へ置いただけのraw dump
- parseできていないPDF/image
- source URLだけの未検証candidate
- LLM分類だけでsource receiptに接続されていないclaim candidate
- duplicate artifact
- terms不明でclaim supportに使えないartifact
- private/raw CSV由来の行やログ
- 本体P0計画に接続しない広いload testやCPU burn

### 1.2 Counted artifact kinds

| Kind | 説明 | ROI計上単位 |
|---|---|---|
| `source_receipt` | 公式/公開sourceから取得した根拠receipt。URL、取得時刻、checksum、source_profile、document locatorを持つ。 | accepted 1 record |
| `claim_ref` | receiptに接続されたatomic claim。金額、期限、資格、法令、企業属性、統計値など。 | accepted 1 atomic claim |
| `known_gap` | 取得不能、古い、曖昧、terms制約、no-hit限界などの明示的gap。 | accepted 1 actionable gap |
| `no_hit_check` | no-hitをabsenceではなく `no_hit_not_absence` として記録した確認結果。 | accepted 1 safe check |
| `packet` | P0 packet typeの入力/出力fixture。`request_time_llm_call_performed=false`。 | accepted 1 packet |
| `proof` | public proof page、proof ledger、sidecar JSON、source-backed public example。 | accepted 1 proof asset |
| `geo_eval` | GEO/answer-engine向けquery、expected behavior、actual output、scoring、failure reason。 | accepted 1 evaluated case |
| `deploy_artifact` | OpenAPI/MCP example、llms/.well-known、JSON-LD、release gate report、checksum/export/cleanup ledger。 | accepted 1 deployable artifact |

## 2. Weighted accepted value model

単純な件数だけでROIを見ると、NTA法人番号のような大量構造データがscoreを支配し、packet/proof/deploy readinessが過小評価される。したがって、運用判断は件数と重み付き価値の両方で行う。

### 2.1 Base weights

| Kind | Weight | 理由 |
|---|---:|---|
| `source_receipt` | 1 | jpciteの根拠土台。大量化しやすいため後述の飽和をかける。 |
| `claim_ref` | 2 | agentが回答や判断へ使えるatomic fact。 |
| `known_gap` | 3 | hallucination防止に直結する。actionable gapのみ加点。 |
| `no_hit_check` | 1.5 | no-hit誤用防止に効くが、absence証明ではない。 |
| `packet` | 250 | end userが価値を感じる直接成果物。 |
| `proof` | 80 | GEO-first discoveryと信頼形成に効く。 |
| `geo_eval` | 20 | AIエージェント推薦の改善に効く。 |
| `deploy_artifact` | 200 | 本番デプロイ、MCP/API課金導線、release gateに効く。 |

補助artifactの扱い:

| Kind | Weight | 計上先 |
|---|---:|---|
| `source_profile` | 50 | J01に限り補助scoreへ加算 |
| `quality_gate_report` | 200 | `deploy_artifact` として扱う |
| `cleanup_ledger` | 200 | `deploy_artifact` として扱う |
| `cost_ledger_snapshot` | 50 | `deploy_artifact` の補助。ただし1日6件まで |

### 2.2 Saturation

大量recordでscoreが歪まないよう、jobごとkindごとにcapを置く。

```text
effective_count(n, cap) = min(n, cap) + sqrt(max(n - cap, 0))
```

例:

- cap 50,000 のsource_receiptが1,000,000件あっても、score上は `50,000 + sqrt(950,000)` として扱う。
- raw件数は保持するが、予算判断では「大量であること」より「本体価値へ変換されること」を優先する。

### 2.3 Quality multiplier

各artifact kindの有効価値:

```text
accepted_value_jk =
  weight_k
  * effective_count(accepted_count_jk, cap_jk)
  * quality_multiplier_jk
  * product_multiplier_jk
  * freshness_multiplier_jk
```

品質係数:

| Signal | Multiplier |
|---|---:|
| gate pass, terms verified, receipt linked | 1.00 |
| human review required but nonblocking | 0.50 |
| metadata/link only, claim support不可 | 0.25 |
| stale but retained as known_gap | 0.30 |
| duplicate after canonicalization | 0.00 |
| terms unknown and not quarantined | 0.00 |
| private leak or raw CSV exposure | hard stop |
| no-hit misuse in publishable artifact | hard stop |

Product multiplier:

| Connection | Multiplier |
|---|---:|
| P0 packet/proof/API/MCP/release gateに直接使える | 1.50 |
| P0 composer fixtureに使える | 1.20 |
| source lakeとして将来利用のみ | 0.70 |
| 用途不明 | 0.00 |

Freshness multiplier:

| Freshness | Multiplier |
|---|---:|
| source updated within expected cadence | 1.00 |
| source stale but freshness gap recorded | 0.60 |
| source freshness unknown | 0.30 |
| source removed/unreachable and gapなし | 0.00 |

### 2.4 Job score

```text
WAV_j = sum(accepted_value_jk for all kinds k) - penalty_j

ROI_j = WAV_j / max(spend_j, 1)

MROI_j_delta = (WAV_j_now - WAV_j_prev) / max(spend_j_now - spend_j_prev, 1)
```

`WAV` は weighted accepted value。  
`MROI` は直近30-60分または直近USD 100-300消費あたりの限界ROI。

Penalty:

| Penalty source | Formula |
|---|---|
| duplicate rate | `WAV_j * min(duplicate_rate, 0.5)` |
| blocking quality issue | `500 * blocking_issue_count` |
| forbidden claim candidate not quarantined | hard stop |
| no-hit misuse candidate not quarantined | hard stop |
| private leak | hard stop |
| unexplained untagged spend | hard stop or no-new-work behavior |
| terms violation risk | artifact value set to 0 until resolved |

## 3. Global target by USD 19,000-19,300

最終的にcredit run全体で狙うaccepted artifactの目安。実際のsource件数が公式データの規模により上下するため、件数とcoverage率の両方で見る。

| Artifact | Minimum acceptable | Good target | Excellent target | Notes |
|---|---:|---:|---:|---|
| `source_profile` | 60 | 100 | 140 | terms/robots/license/freshness付き |
| `source_receipt` | 300,000 or P0 structured source 80% coverage | 1,000,000 or P0 structured source 95% coverage | 2,000,000+ with saturation cap | NTA等の大量構造recordはraw件数とeffective scoreを分ける |
| `claim_ref` | 150,000 | 400,000 | 800,000 | receipt接続済みのみ |
| `known_gap` | 8,000 | 20,000 | 40,000 | actionable gapのみ |
| `no_hit_check` | 20,000 | 80,000 | 200,000 | absence証明ではない |
| `packet` | 90 | 180 | 360 | 6 P0 packet typeで偏りなく |
| `proof` | 200 | 600 | 1,200 | public publish前にleak/terms gate必須 |
| `geo_eval` | 300 | 700 | 1,200 | agent推薦/誤推薦/拒否/価格導線を含む |
| `deploy_artifact` | 40 | 90 | 150 | OpenAPI/MCP/llms/.well-known/release/cleanup |

本番デプロイ前の最低条件:

- `packet >= 90`
- `proof >= 200`
- `geo_eval >= 300`
- `deploy_artifact >= 40`
- forbidden claim in publishable artifact = 0
- no-hit misuse in publishable artifact = 0
- private/raw CSV leakage = 0
- source receipts without provenance = 0
- zero-bill cleanup plan and export checksum ledger present

## 4. Per-job artifact targets

### 4.1 Base jobs J01-J16

`Min to continue` はpilotまたは最初のUSD 100-300消費後に満たすべき値。  
`Good completion target` は標準予算内で達成したい値。  
source全体の公式件数が小さい場合は、件数よりcoverage率を優先する。

| Job | Standard USD | Stretch USD | Min to continue | Good completion target | Stop / shift condition |
|---|---:|---:|---|---|---|
| J01 Official source profile sweep | 600 | 900 | `source_profile>=20`, `known_gap>=10`, `deploy_artifact>=2` | `source_profile 80-120`, `source_receipt 120-300`, `known_gap 60-150`, `deploy_artifact 8-15` | terms/robots/freshnessが埋まらないsourceが30%超ならsource familyを絞る |
| J02 NTA法人番号 mirror and diff | 900 | 1,300 | official bulk shapeが取れ、`source_receipt>=50,000` or 10% coverage | `source_receipt 500k-2M+` or 95% coverage, `claim_ref 500k-2M+`, `known_gap 20-100` | `accepted_receipt/USD < 200` が2窓続く、またはdiff/provenance欠落 |
| J03 NTA invoice registrants and no-hit | 700 | 1,100 | `source_receipt>=30,000`, safe no-hit sample >=1,000 | `source_receipt 300k-1M+` or 95% coverage, `claim_ref 300k-1M+`, `no_hit_check 10k-80k`, `known_gap 50-200` | no-hitが未登録/不存在へ変換されたら即停止 |
| J04 e-Gov law snapshot | 800 | 1,200 | `source_receipt>=2,000`, article/locator checksumあり | `source_receipt 20k-60k`, `claim_ref 40k-120k`, `known_gap 1k-3k`, `proof 20-80` | article locatorが不安定、法令改正freshnessが不明ならclaim生成停止 |
| J05 J-Grants/public program acquisition | 1,600 | 2,300 | `source_receipt>=1,000`, `claim_ref>=3,000`, deadlines/amounts/doc req抽出あり | `source_receipt 15k-60k`, `claim_ref 40k-120k`, `known_gap 2k-8k`, `packet 30-80`, `proof 80-200` | `claim_ref/USD < 20` かつpacketに接続しないならJ15/J16へ移管 |
| J06 Ministry/local PDF extraction | 2,000 | 3,200 | CPU/text-layerで`claim_ref>=1,000`、OCR候補がrank済み | `source_receipt 8k-25k`, `claim_ref 15k-60k`, `known_gap 5k-20k`, `proof 100-300` | PDF単価が悪い。`accepted_claim/USD < 8` が2窓続いたらJ17へ広げず停止 |
| J07 gBizINFO public business signal join | 1,000 | 1,600 | `source_receipt>=10,000`, identity join key quality >=95% | `source_receipt 50k-300k`, `claim_ref 50k-300k`, `known_gap 500-2k`, `packet 20-60` | join collision >1% or unmatched reason gapなしなら停止 |
| J08 EDINET metadata snapshot | 700 | 1,100 | `source_receipt>=5,000`, filing metadata normalized | `source_receipt 20k-100k`, `claim_ref 20k-100k`, `known_gap 300-1k`, `proof 20-80` | API/rate/termsによりclaim support不可ならmetadata-onlyへ縮小 |
| J09 Procurement/tender acquisition | 1,000 | 1,700 | `source_receipt>=1,000`, tender fields >=5 types | `source_receipt 10k-50k`, `claim_ref 20k-100k`, `known_gap 1k-5k`, `proof 80-200` | sourceごとterms不明が20%超ならsourceを止める |
| J10 Enforcement/sanction/public notice sweep | 1,100 | 1,800 | `source_receipt>=800`, safe caveat templateあり | `source_receipt 5k-25k`, `claim_ref 10k-60k`, `known_gap 2k-8k`, `no_hit_check 10k-50k`, `proof 50-150` | no-hitを「問題なし」へ寄せた表現が1件でもpublish側に出たら停止 |
| J11 e-Stat regional statistics enrichment | 600 | 1,000 | `source_receipt>=500`, table/series locatorあり | `source_receipt 2k-10k`, `claim_ref 20k-100k`, `known_gap 1k-5k`, `packet 20-60` | region/code/versionが不安定ならclaim化せずgap化 |
| J12 Source receipt completeness audit | 400 | 800 | missing required field report >=1 | `known_gap 5k-20k`, `deploy_artifact 10-25`, `quality_gate_report 10-30` | mandatory job。ROI低くても止めず、scopeを縮めて必ず完了 |
| J13 Claim graph dedupe/conflict analysis | 700 | 1,200 | duplicate/conflict report >=1、quarantine rulesあり | dedupe decisions `20k-150k`, `known_gap 2k-10k`, `deploy_artifact 10-25` | conflictが増えるだけで解消規則が増えないならJ12へ戻す |
| J14 CSV private overlay safety analysis | 600 | 1,000 | synthetic/header-only fixture >=100、leak scan pass | synthetic cases `300-800`, leak tests `500-1,500`, `known_gap 200-800`, `deploy_artifact 10-20` | raw/private CSVがS3/log/manifestに出たら即停止 |
| J15 Packet/proof fixture materialization | 1,200 | 2,000 | 6 packet typeのうち3 typeでfixture各5件 | `packet 180-360`, `proof 300-800`, `deploy_artifact 40-80` | `packet/USD < 0.08` か proofにsource_refs欠落が出たらsource側へ戻す |
| J16 GEO/no-hit/forbidden-claim evaluation | 600 | 1,000 | `geo_eval>=100`, forbidden/no-hit rules pass | `geo_eval 400-800`, `deploy_artifact 20-40`, failure taxonomy 50-150 | mandatory job。publishable forbidden/no-hit misuseが0になるまでrelease不可 |

### 4.2 Stretch jobs J17-J24

Stretchは「creditを使うため」ではなく、base jobsで高密度の成果物が出ているときだけ使う。

| Job | Target USD | Min to launch | Good completion target | Stop / shift condition |
|---|---:|---|---|---|
| J17 Local government PDF OCR expansion | 1,200-2,000 | J06の`accepted_claim/USD >= 12`、OCR対象rank済み | `source_receipt 5k-20k`, `claim_ref 10k-40k`, `known_gap 5k-15k`, `proof 100-300` | OCR cost per accepted claim > USD 0.12 なら停止 |
| J18 Public-only Bedrock batch classification | 700-1,400 | public-only、credit eligibility確認、candidateをreceiptで検証可能 | claim candidates `20k-80k`, accepted `claim_ref 8k-30k`, `known_gap 2k-8k` | LLM candidateがreceipt接続されないならROI=0として停止 |
| J19 Temporary OpenSearch retrieval benchmark | 700-1,200 | defined questions >=100、export/delete pathあり | `geo_eval 200-500`, deploy configs `3-10`, retrieval failure taxonomy `50-150` | indexを長期保持しない。qualityが静的検索で足りるなら起動しない |
| J20 GEO adversarial eval expansion | 500-900 | J16 core pass、release blockersが残る | `geo_eval 300-600`, `deploy_artifact 10-25` | 新しいfailure classが出なくなったら停止 |
| J21 Proof page scale generation | 600-1,000 | J15 proof gate pass、source refs完全 | `proof 500-1,500`, `packet 100-250`, `deploy_artifact 10-30` | proofが重複/薄い/terms不明ならJ15へ戻す |
| J22 Athena/Glue QA reruns and compaction | 400-700 | Parquet dataset exists、scan cap設定済み | QA reports `20-80`, corrected manifests `10-40`, `known_gap 1k-5k` | Athena scanが成果物修正に繋がらないなら停止 |
| J23 Static site crawl/render/load check | 300-700 | proof/discovery pages generated | checked URLs `500-2,000`, `geo_eval 100-300`, `deploy_artifact 20-60` | broad load testは禁止。render/evidence/link確認に限定 |
| J24 Final artifact packaging/checksum/export | 300-600 | drain開始、import candidateが存在 | `deploy_artifact 15-40`, checksum/export/cleanup ledger complete | mandatory job。ROI低くても止めず、zero-bill cleanupの前提として完了 |

## 5. Unit cost targets

### 5.1 Artifact unit cost bands

| Artifact | Excellent | Acceptable | Stop / investigate |
|---|---:|---:|---:|
| Structured `source_receipt` | <= USD 0.001 | <= USD 0.005 | > USD 0.01 |
| Document/PDF `source_receipt` | <= USD 0.05 | <= USD 0.15 | > USD 0.30 |
| Structured `claim_ref` | <= USD 0.002 | <= USD 0.01 | > USD 0.03 |
| Document/PDF `claim_ref` | <= USD 0.03 | <= USD 0.10 | > USD 0.20 |
| `known_gap` | <= USD 0.10 | <= USD 0.50 | > USD 1.00 |
| `no_hit_check` | <= USD 0.005 | <= USD 0.02 | > USD 0.05 |
| `packet` | <= USD 5 | <= USD 20 | > USD 50 |
| `proof` | <= USD 2 | <= USD 8 | > USD 20 |
| `geo_eval` | <= USD 0.75 | <= USD 2.50 | > USD 6 |
| `deploy_artifact` | <= USD 10 | <= USD 40 | > USD 100 |

Unit costだけで止めない例外:

- J12/J16/J24はrelease gateなので、単価が悪くてもscopeを縮めて完了させる。
- J01はsource boundaryが価値なので、件数が少なくてもterms/freshness/coverageを作れれば続ける。
- J13はconflictやduplicateを消すことで後段の価値を増やすため、直接artifact件数が少なくても品質改善があれば続ける。

### 5.2 Job-level ROI thresholds

| Lane | Jobs | Continue if | Stop if |
|---|---|---|---|
| Structured backbone | J02/J03/J07/J08 | `MROI >= 100 WAV/USD` or `accepted_receipt/USD >= 200` | 2 windows below threshold and no deploy blocker solved |
| Law/stat/program sources | J04/J05/J11 | `MROI >= 40 WAV/USD` or `accepted_claim/USD >= 20` | claim extraction cannot cite receipts |
| PDF/OCR/local documents | J06/J17 | `MROI >= 25 WAV/USD` or `accepted_claim/USD >= 8` | OCR/document spend rises but accepted claims flat |
| Product artifacts | J15/J21 | `MROI >= 20 WAV/USD` or packet/proof minimums unlock release | packet/proof lacks source_refs or duplicates dominate |
| GEO/eval/deploy | J16/J20/J23/J24 | release blocker count decreases, `geo_eval` or `deploy_artifact` rises | no new failure classes and no release blocker reduction |
| QA/graph/privacy | J12/J13/J14/J22 | blocking issues decrease or leak/conflict/gap ledgers improve | findings are not actionable after 2 windows |
| Conditional services | J18/J19 | accepted artifacts survive deterministic verification | candidates cannot be verified by source receipts |

Window definition:

- Active spend window: 30 minutes or USD 100 gross spend, whichever comes later.
- Fast burn window: 15 minutes or USD 300 gross spend when queues are intentionally scaled.
- Stretch window: 15 minutes or USD 100 gross spend after USD 18,300.

## 6. Budget transfer rules

### 6.1 Priority score

When a job underperforms, move remaining budget to the highest priority open job.

```text
priority_j =
  expected_mroi_j
  * confidence_j
  * deploy_unlock_multiplier_j
  * source_uniqueness_multiplier_j
  / risk_multiplier_j
```

Where:

| Term | Values |
|---|---|
| `expected_mroi_j` | last good window, pilot estimate, or comparable job estimate |
| `confidence_j` | 0.3 unknown, 0.6 pilot pass, 0.9 stable |
| `deploy_unlock_multiplier_j` | 2.0 if blocks production deploy, 1.5 if blocks packet/proof, 1.0 otherwise |
| `source_uniqueness_multiplier_j` | 1.5 if unique official source family, 1.0 normal, 0.5 duplicate coverage |
| `risk_multiplier_j` | 1.0 low, 1.5 terms/rate uncertainty, 2.0 service cost lag, 3.0 privacy/managed-service risk |

### 6.2 Transfer matrix

| Underperforming spend | First transfer target | Second target | Reason |
|---|---|---|---|
| J06/J17 PDF extraction | J15 proof/packet if receipts enough | J12/J13 quality cleanup | PDF has high variable cost; convert existing evidence first |
| J18 Bedrock candidates | J13 deterministic claim graph | J16/J20 eval | unverifiable candidates do not count |
| J19 OpenSearch benchmark | J20 GEO eval | J23 static crawl/render | deploy learning may be cheaper without managed search |
| J05 program acquisition | J04/J11 law/stat support | J15 application_strategy packets | program facts need legal/stat context |
| J09 procurement | J10 public notices | J15 company_public_baseline packets | buyer/supplier signal can be substituted by notices/baseline |
| J02/J03 structured backbone | J12 completeness | J15 packet fixture | if bulk fetch complete, stop rerunning and productize |
| J15 packet generation | J12/J13 missing refs/conflicts | J05/J06 source expansion | packet failure usually means source/claim inputs are weak |
| J16 eval | J15/J21 proof repair | P0 code fix outside AWS | repeated failures should feed implementation, not burn AWS |

### 6.3 Mandatory preservation budget

Before entering USD 18,300, reserve:

| Reserve | Amount | Purpose |
|---|---:|---|
| J12/J13/J16 quality reserve | USD 700-1,200 | completeness/conflict/no-hit/forbidden gates |
| J15/J21 productization reserve | USD 900-1,500 | packets/proof pages |
| J23/J24 deploy/export reserve | USD 600-1,000 | crawl/render/checksum/export/cleanup |

If gross spend reaches USD 17,000 and these reserves are not funded, stop all stretch and low-yield jobs immediately.

## 7. Fast credit consumption without blind burn

The user wants the credit consumed quickly to accelerate production deployment. The safe way to do that is not one giant queue; it is many capped queues with frequent ledger updates and automatic demotion of low-yield work.

### 7.1 Spend pace target

| Phase | Cumulative spend | Duration target | Main work | Required ROI check |
|---|---:|---|---|---|
| Wave 0 preflight | USD 0-50 | same day | contract, ledgers, dry-run | no spend-heavy jobs |
| Wave 1 smoke | USD 100-300 | 2-4 hours | J01/J02/J12/J15/J16 small | all schemas and stop drill pass |
| Wave 2 backbone | USD 2,500-4,500 | day 1 | J01-J04/J11/J12 | structured receipt density |
| Wave 3 expansion | USD 7,000-11,000 | day 1-3 | J05-J10/J06 text/J13 | claim/proof connection |
| Wave 4 product bridge | USD 12,000-15,500 | day 2-5 | J14-J16/J15 | packets/proof/eval unlock |
| Wave 5 selective stretch | USD 17,000-18,900 | day 3-7 | J17-J23 only if high yield | MROI and blocker reduction |
| Wave 6 drain/stretch | USD 18,900-19,300 | day 5-10 | J24, final checks, export, cleanup | manual approval only |

This pace can consume most of the credit within one week if jobs are productive, while preserving a path to production and zero ongoing bill.

### 7.2 Agent rate-limit independence

AWS jobs should not require Codex/Claude to keep issuing commands.

Required design:

- All job definitions, input shards, caps, stoplines, output prefixes, and accepted artifact definitions exist before scale-up.
- Batch/Step Functions/SQS or equivalent orchestration can continue from manifests.
- A small control job writes `cost_artifact_ledger.jsonl` and `job_decision_ledger.jsonl` on a schedule.
- Queues have max vCPU caps and timeout caps.
- Every job has checkpointing and can stop after current shard.
- Budget/action/deny policies can disable new work even if the local terminal is idle.
- `USD 18,900` manual stretch is not auto-entered; it requires recorded approval.

If the local AI agent is unavailable:

1. Continue already approved work until its job cap, timeout, or stopline.
2. Do not create new service families.
3. Do not enter manual stretch.
4. Always leave control/drain/export/cleanup jobs available.

## 8. Ledger templates

### 8.1 `cost_artifact_ledger.jsonl`

One row per job per window.

```json
{
  "schema_id": "jpcite.aws_credit.cost_artifact_ledger",
  "schema_version": "2026-05-15",
  "run_id": "aws-credit-2026-05-15-r001",
  "window_id": "2026-05-15T10:00:00+09:00/PT30M",
  "profile": "bookyou-recovery",
  "account_id": "993693061769",
  "region": "us-east-1",
  "job_id": "J05",
  "job_name": "J-Grants/public program acquisition",
  "queue": "jpcite-source-expand-q",
  "phase": "Wave 3",
  "gross_spend_usd_window": 180.25,
  "gross_spend_usd_cumulative": 8240.75,
  "estimated_running_exposure_usd": 220.0,
  "paid_exposure_usd": 0.0,
  "untagged_spend_usd": 0.0,
  "accepted_counts": {
    "source_receipt": 2400,
    "claim_ref": 7400,
    "known_gap": 520,
    "no_hit_check": 0,
    "packet": 8,
    "proof": 18,
    "geo_eval": 0,
    "deploy_artifact": 2
  },
  "candidate_counts": {
    "source_receipt": 2600,
    "claim_ref": 9800
  },
  "rejected_counts": {
    "duplicate": 300,
    "terms_unknown": 0,
    "private_leak": 0,
    "no_hit_misuse": 0,
    "forbidden_claim": 0
  },
  "weighted_accepted_value_window": 21560.0,
  "weighted_accepted_value_cumulative": 79050.0,
  "roi_wav_per_usd_cumulative": 9.59,
  "mroi_wav_per_usd_window": 119.61,
  "unit_costs": {
    "source_receipt_usd": 0.075,
    "claim_ref_usd": 0.024,
    "packet_usd": 22.53,
    "proof_usd": 10.01
  },
  "quality": {
    "gate_status": "pass",
    "blocking_issue_count": 0,
    "warning_count": 4,
    "receipt_link_rate": 0.94,
    "duplicate_rate": 0.031,
    "private_leak_count": 0,
    "no_hit_misuse_count": 0,
    "forbidden_claim_count": 0
  },
  "decision": {
    "action": "continue",
    "reason": "marginal ROI above threshold and packet/proof conversion is active",
    "next_window_budget_usd": 250,
    "next_cap_change": "hold",
    "transfer_target_if_fail": "J15"
  }
}
```

### 8.2 `job_decision_ledger.jsonl`

One row whenever a job is continued, slowed, stopped, or budget is transferred.

```json
{
  "schema_id": "jpcite.aws_credit.job_decision_ledger",
  "schema_version": "2026-05-15",
  "run_id": "aws-credit-2026-05-15-r001",
  "decided_at": "2026-05-15T10:30:00+09:00",
  "line": "watch",
  "control_spend_usd": 17080.25,
  "job_id": "J06",
  "previous_action": "continue",
  "new_action": "stop_and_transfer",
  "reason_codes": [
    "accepted_claim_per_usd_below_threshold_2_windows",
    "ocr_cost_per_accepted_claim_above_0_12",
    "packet_inputs_sufficient"
  ],
  "math": {
    "mroi_wav_per_usd_last_window": 11.4,
    "required_mroi_wav_per_usd": 25.0,
    "accepted_claim_per_usd_last_window": 3.7,
    "required_accepted_claim_per_usd": 8.0
  },
  "remaining_budget_usd_reassigned": 850.0,
  "reassigned_to": "J15",
  "operator_or_policy": "auto_policy_before_18900",
  "requires_manual_approval": false
}
```

### 8.3 `artifact_roi_summary.md`

Human-readable daily summary.

```markdown
# AWS credit run ROI summary

Time JST: <timestamp>
Control spend: USD <amount>
Stopline: <watch|slowdown|no-new-work|stretch|absolute>
Paid exposure: USD <amount>
Untagged spend: USD <amount>

## Accepted artifacts

| Kind | Accepted | Good target | Unit cost | Status |
|---|---:|---:|---:|---|
| source_receipt |  | 1,000,000 |  |  |
| claim_ref |  | 400,000 |  |  |
| known_gap |  | 20,000 |  |  |
| packet |  | 180 |  |  |
| proof |  | 600 |  |  |
| geo_eval |  | 700 |  |  |
| deploy_artifact |  | 90 |  |  |

## Decisions

| Job | Action | Reason | Budget change |
|---|---|---|---:|
|  |  |  |  |

## Release readiness

- packet minimum:
- proof minimum:
- GEO minimum:
- deploy artifacts:
- forbidden claim:
- no-hit misuse:
- private leak:
- cleanup/export:
```

### 8.4 `job_roi_config.yaml`

Static config checked into the run package before AWS execution.

```yaml
schema_id: jpcite.aws_credit.job_roi_config
schema_version: "2026-05-15"
run_id: aws-credit-2026-05-15-r001
credit:
  face_value_usd: 19493.94
  watch_usd: 17000
  slowdown_usd: 18300
  no_new_work_usd: 18900
  absolute_stop_usd: 19300
artifact_weights:
  source_receipt: 1
  claim_ref: 2
  known_gap: 3
  no_hit_check: 1.5
  packet: 250
  proof: 80
  geo_eval: 20
  deploy_artifact: 200
hard_stops:
  private_leak_count_gt: 0
  publishable_no_hit_misuse_count_gt: 0
  publishable_forbidden_claim_count_gt: 0
  unexplained_paid_exposure_usd_gte: 100
  absolute_control_spend_usd_gte: 19300
window:
  normal_minutes: 30
  normal_min_spend_usd: 100
  fast_minutes: 15
  fast_min_spend_usd: 300
mandatory_jobs:
  - J12
  - J16
  - J24
```

## 9. Cutoff rules

### 9.1 Hard stop

即停止。ROI計算を待たない。

| Trigger | Action |
|---|---|
| `private_leak_count > 0` in artifact/log/manifest | stop job family, quarantine outputs, run leak audit |
| publishable `no_hit_misuse_count > 0` | stop publish/proof/packet generation, repair templates |
| publishable `forbidden_claim_count > 0` | stop release path, repair claim filters |
| paid exposure >= USD 100 | account-wide no-new-work behavior |
| control_spend >= USD 19,300 | emergency stop |
| untagged spend unexplained within 30 min | no-new-work behavior |
| Marketplace/Support/commitment/domain/NAT drift | emergency investigation |

### 9.2 Soft stop

2 windows連続で発火したら止めるか縮小する。

| Trigger | Default action |
|---|---|
| `MROI_j_delta` below lane threshold | reduce cap 50%, one more window only |
| accepted artifact count flat while spend rises | stop and transfer |
| duplicate rate > 30% | canonicalization fix or stop |
| receipt link rate < 90% for claim jobs | stop claim generation, run J12/J13 |
| terms unknown > 10% for source family | metadata/link-only or stop |
| retry spend > 20% of job spend | fix shard/rate/backoff or stop |
| proof missing source_refs > 0 | stop proof publish, repair J15 |

### 9.3 Completion stop

高ROIでも、一定の目的を達したら止めてproductizationへ移る。

| Condition | Action |
|---|---|
| source coverage >= 95% and freshness/gap reports done | stop mirroring, run J12/J15 |
| packet target >= 360 and proof target >= 1,200 | stop generation, run J16/J23 |
| GEO eval produces no new failure class for 2 windows | stop eval expansion |
| deploy artifacts complete and cleanup ready | enter drain/export |

## 10. 本体計画と本番デプロイへのマージ順

ROI台帳はAWS単体の運用ではなく、本体P0実装を本番へ通すための順序制御である。

| Order | 本体側 | AWS ROI gate | Exit criteria |
|---:|---|---|---|
| 1 | Packet contract/catalog freeze | J01/J08 schema and ROI config fixed | artifact kinds, weights, manifests, gates fixed |
| 2 | Source receipts/claim refs/known gaps | J01-J04/J11/J12 meet minimums | source backbone accepted, no-hit safe |
| 3 | Composers | J05/J07/J10/J11/J15 conversion active | first 90 packet fixtures possible |
| 4 | CSV private overlay | J14 leak tests pass | raw CSV never leaves local/private boundary |
| 5 | REST/MCP | J15 deploy examples and J16 eval | examples cite receipts, billing metadata present |
| 6 | Proof/discovery | J15/J21/J23 | proof pages render, JSON-LD/llms/.well-known ready |
| 7 | Release gates | J12/J13/J16/J23/J24 | forbidden/no-hit/private leakage zero |
| 8 | Production deploy | non-AWS deployment path | import selected artifacts, deploy, run smoke |
| 9 | AWS drain | J24 and cleanup ledger | export verified, AWS resources deleted for zero ongoing bill |

Do not wait until AWS credit is fully consumed to start production preparation. As soon as J15/J16 produce minimum deployable fixtures, begin non-AWS production release work in parallel. AWS then continues producing additional receipts/proofs/evals until slowdown/no-new-work lines.

## 11. Operator dashboard requirements

During the run, the operator dashboard should show these fields at all times.

| Field | Purpose |
|---|---|
| control spend | stopline decision |
| paid exposure | cash billing risk |
| untagged spend | attribution failure |
| running exposure | lag-adjusted stop decision |
| accepted artifacts by kind | product value |
| WAV and MROI by job | continue/stop/transfer |
| packet/proof/GEO/deploy counts | production readiness |
| hard stop counters | safety |
| J12/J16/J24 reserve remaining | release/cleanup safety |
| queue caps by lane | burn speed control |

Minimum dashboard table:

| Job | Spend | Running exposure | WAV | MROI | Key unit cost | Hard stop count | Action |
|---|---:|---:|---:|---:|---:|---:|---|
| J01 |  |  |  |  |  |  |  |
| J02 |  |  |  |  |  |  |  |
| J03 |  |  |  |  |  |  |  |
| J04 |  |  |  |  |  |  |  |
| J05 |  |  |  |  |  |  |  |
| J06 |  |  |  |  |  |  |  |
| J07 |  |  |  |  |  |  |  |
| J08 |  |  |  |  |  |  |  |
| J09 |  |  |  |  |  |  |  |
| J10 |  |  |  |  |  |  |  |
| J11 |  |  |  |  |  |  |  |
| J12 |  |  |  |  |  |  |  |
| J13 |  |  |  |  |  |  |  |
| J14 |  |  |  |  |  |  |  |
| J15 |  |  |  |  |  |  |  |
| J16 |  |  |  |  |  |  |  |
| J17-J24 |  |  |  |  |  |  |  |

## 12. Final run acceptance

Credit run is successful only if all are true:

- Gross intended spend is near the target band without crossing the absolute safety line.
- Paid exposure is zero or explicitly explained below the configured threshold.
- Accepted artifact counts meet at least minimum global targets.
- J12/J13/J16/J24 completed.
- `source_receipts`, `claim_refs`, `known_gaps`, packets, proofs, GEO evals, deploy artifacts all appear in manifests.
- No private/raw CSV leakage.
- No publishable forbidden claims.
- No no-hit misuse.
- Production deploy path has concrete import artifacts and release gates.
- Final export checksum ledger exists.
- Zero-bill cleanup ledger exists and all AWS-side spend-heavy resources are deleted or scheduled for deletion according to the cleanup plan.

The intended behavior is: burn fast where artifact density is high, stop quickly where artifact density collapses, convert evidence into packet/proof/deploy assets early, and leave AWS with no ongoing bill after the run.
