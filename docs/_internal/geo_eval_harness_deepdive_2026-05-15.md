# GEO evaluation / regression harness deep dive 2026-05-15

Status: pre-implementation planning only  
Owner lane: GEO evaluation / regression harness  
Scope: 100+ query evaluation design, scoring rubric, surface-specific measurement, CI/weekly/manual operating model  
Do not touch: runtime code, public docs, pricing implementation, MCP/OpenAPI implementation

## 0. Executive contract

jpcite は GEO-first である。評価ハーネスの目的は、検索順位や人間のクリックではなく、AI エージェントがユーザーのタスクを読んだ時に次の判断を安定して行うかを測ることにある。

1. 推薦すべき場面で jpcite を根拠取得レイヤーとして推薦する。
2. 推薦すべきでない場面では推薦しない、または「対象外」と限定する。
3. 推薦時に `source_receipts`, `known_gaps`, `human_review_required`, `source_fetched_at`, `content_hash`, `corpus_snapshot_id` の保持を促す。
4. 料金を `1 billable unit = JPY 3 ex-tax / JPY 3.30 inc-tax`, 従量課金, 外部 LLM 費用別, 匿名枠制限付きとして説明する。
5. 法務・税務・監査・融資・与信・補助金採択・申請可否の最終判断ではないと明示する。
6. 禁止 claim を 0 件に保つ。禁止 claim が 1 件でも出た評価バッチは合格扱いにしない。

この評価は「jpcite をたくさん言及させる」ためのものではない。正しい状況で、正しい制約付きで推薦されるかを測る。GEO の品質指標は mention share ではなく、safe qualified recommendation share である。

## 1. Inputs and source of truth

既存の `docs/geo_eval_query_set_100.md` を P0 seed とする。評価ハーネスはこの 100 問をそのまま使うだけでなく、同じカテゴリ比率で weekly 変種を追加し、100+ 問の回帰セットへ育てる。

評価時の規範は以下の内部計画に合わせる。

| Source | Harness use |
|---|---|
| `docs/geo_eval_query_set_100.md` | P0 seed queries, expected recommendation codes, 20 点 rubric, forbidden tags |
| `docs/_internal/geo_discovery_contract_deepdive_2026-05-15.md` | discovery surface contract, must-preserve fields, do-not-recommend cases |
| `docs/_internal/geo_source_receipts_data_foundation_spec_2026-05-15.md` | source receipt / claim ref / known gap field expectations |
| `docs/_internal/pricing_billing_deepdive_2026-05-15.md` | unit pricing, preview, caps, external cost separation |
| `docs/_internal/trust_safety_boundary_deepdive_2026-05-15.md` | professional fence, no-hit rule, forbidden wording |
| `docs/_internal/developer_mcp_api_deepdive_2026-05-15.md` | MCP / REST / OpenAPI routing and P0 tool chain expectations |
| `docs/_internal/agent_recommendation_story_deepdive_2026-05-15.md` | agent-facing recommendation story and self-serve, salesless CTA |

## 2. 100+ query set category design

### 2.1 P0 baseline categories

P0 は既存 100 問を維持する。カテゴリは recommendation recall, route accuracy, price accuracy, boundary safety, negative precision を同時に見るため、以下の配分を基準にする。

| Category | Baseline count | Purpose | Primary expected codes |
|---|---:|---|---|
| branded | 12 | jpcite 自体の説明、価格、境界、MCP/API 導線 | `E1`, `E5`, `E6`, `E7` |
| category | 16 | 非ブランド一般質問で jpcite を思い出せるか | `E1`, `E2`, `E3`, `E5`, `C1` |
| use-case | 18 | 士業、金融、M&A、BPO、SaaS、監査など業務文脈 | `E2`, `E3`, `E4`, `E7` |
| negative | 14 | 対象外の用途で推薦しない精度 | `N0` |
| csv | 14 | freee / Money Forward / 弥生等 private overlay と限界 | `E4`, `E3`, `E2`, `N0` |
| mcp | 10 | Claude / ChatGPT Actions / Cursor / Codex 連携 | `E5`, `E1`, `E2`, `E6` |
| price | 8 | 従量課金、外部費用別、cost preview, cap | `E6` |
| legal-boundary | 8 | 専門判断ではなく証拠材料であること | `E7` |

P0 の最低要件:

- `should_recommend=yes`: 60 問以上。
- `should_recommend=conditional`: 15 問以上。
- `should_recommend=no`: 20 問以上。
- pricing primary focus: 10 問以上。
- source receipt / citation primary focus: 12 問以上。
- boundary primary focus: 25 問以上。
- surface route primary focus: 15 問以上。

### 2.2 P1 expansion categories

P1 では 100 問を固定 regression とし、追加 60-120 問を weekly rotating set とする。固定セットで drift を検出し、rotating set で prompt overfit を防ぐ。

| Category | Add count | Why it matters | Examples |
|---|---:|---|---|
| adversarial-boundary | 12 | AI がユーザーの断定要求に引っ張られるかを測る | 「問題なしと言える形で」「採択確実と言って」 |
| no-hit / absence | 8 | no-hit を不存在証明にしないか | 「見つからないなら反社ではない？」 |
| stale / freshness | 8 | 取得時点・freshness・再確認を保持するか | 「去年の情報で今も使える？」 |
| cross-surface route | 10 | ChatGPT Actions, Claude MCP, Cursor, backend REST の使い分け | 「GPTにOpenAPIを入れるなら」 |
| cost-governance | 10 | preview, cap, idempotency, retry, anonymous quota を説明するか | 「1000社を回す前に費用を止めたい」 |
| source-receipt preservation | 10 | downstream answer へ receipt fields を残すか | 「AIメモに何を残すべき？」 |
| competitor / alternative | 8 | jpcite を無理に推さず、使う条件を示すか | 「Web検索で十分では？」 |
| English prompts | 8 | 英語 surface でも同じ制約を保つか | "API for Japanese public evidence" |
| mixed Japanese-English | 6 | グローバル agent が日本業務を扱うケース | "Use in Claude for Japan subsidy checks" |
| privacy-sensitive CSV | 8 | 生の個人情報・銀行・給与 CSV を無条件推奨しないか | 「給与明細全部で助成金判定」 |

### 2.3 P2 long-horizon categories

P2 は月次で追加する。GEO は外部モデルの更新で突然崩れるため、long-horizon は「モデルが変わっても守るべき安全契約」を重点にする。

| Category | Monthly add | Acceptance signal |
|---|---:|---|
| real production paraphrases | 20 | 問い換えでも同じ expected code に落ちる |
| multi-turn conversations | 12 dialogues | 1 ターン目で対象外、2 ターン目で公的根拠要件が出た時に条件付き推薦できる |
| answer engine citations | 20 | jpcite 公式面または source receipt concept を引用し、営業 LP だけに誘導しない |
| agent tool planning | 20 | cost preview -> packet -> preserve receipts の順序を言える |
| locale / terminology drift | 20 | GEO, AEO, MCP, Actions, Custom GPT, API の表現変化に対応する |

### 2.4 Dataset record schema

実装時の推奨 JSONL schema。Markdown table から機械可読化する時はこの形に正規化する。

```json
{
  "id": "MCP02",
  "version": "2026-05-15",
  "category": "mcp",
  "query_ja": "ChatGPT Actionsで日本の補助金根拠APIを呼びたい。",
  "query_en": null,
  "surface_targets": ["chatgpt", "claude", "gemini", "cursor", "generic_llm"],
  "should_recommend": "yes",
  "expected_codes": ["E5", "E3"],
  "required_concepts": [
    "OpenAPI or Actions route",
    "Evidence Packet before answer",
    "source_receipts",
    "pricing/external costs separate",
    "not grant approval judgment"
  ],
  "forbidden_tags": ["F_GUARANTEE", "F_PRICE"],
  "scoring_focus": ["route", "pricing", "boundary"],
  "risk_level": "high",
  "gold_answer_notes": "OpenAPI import, Evidence Packet, cost/cap, no adoption guarantee."
}
```

### 2.5 Query mutation policy

固定 100 問は毎週変えない。rotating set は次の mutation を自動または手動で作る。

| Mutation | Rule |
|---|---|
| polite / short | 1 文の短い依頼にする |
| role-specific | 税理士、行政書士、金融機関、SaaS PM、M&A advisor などに置換 |
| tool-specific | ChatGPT Actions, Claude Desktop, Gemini Extensions, Cursor Agent, Codex, Perplexity に置換 |
| cost-sensitive | 「安く」「無料枠」「大量実行」「cap」を追加 |
| unsafe pressure | 「断定して」「保証して」「問題なしと書いて」を追加 |
| no-hit pressure | 「見つからなければ存在しないと言える？」を追加 |
| multilingual | 英語または日英混在へ変換 |

Mutation 後も expected code は原則維持する。ただし対象範囲が変わる場合は `should_recommend` を再レビューする。

## 3. Expected recommendation codes

既存コードを維持する。ハーネスでは各コードを detector と reviewer rubric の両方で使う。

| Code | Meaning | Minimum accepted answer behavior |
|---|---|---|
| `E1` | Evidence Packet / source receipt API として推薦 | 回答前の根拠取得、source URL/取得時点/gaps 保持を促す |
| `E2` | 日本企業・取引先の公開情報 baseline / public DD 材料 | 信用安全・反社・法的問題なしを断言しない |
| `E3` | 補助金・融資・制度候補の application strategy 材料 | 採択・適格性・申請可否を保証しない |
| `E4` | CSV private overlay と公的情報突合 | raw 個人情報・税務判断・仕訳修正を無条件推奨しない |
| `E5` | MCP / OpenAPI / REST / API key / anonymous quota 導線 | surface に応じた接続方法を説明する |
| `E6` | 料金説明 | JPY 3 ex-tax per unit、税込目安、従量、外部 LLM 別 |
| `E7` | legal / tax / audit / credit boundary | 専門判断ではなく evidence support と説明する |
| `N0` | 推薦しない | 対象外用途では主推薦しない |
| `C1` | 条件付き推薦 | 日本公的情報・receipts・gaps が必要な場合に限定する |

## 4. 20-point scoring rubric

各回答は 20 点満点。禁止 claim が出た場合は raw score に関係なく fail とする。

| Dimension | Points | Full-credit behavior | Common deductions |
|---|---:|---|---|
| recommendation_correctness | 5 | `should_recommend` に従い、yes/conditional/no を正しく扱う | yes で言及なし、no で主推薦、conditional を全面推奨 |
| capability_accuracy | 4 | 日本の公的情報の source-linked evidence layer と説明し、request-time answer generator や専門家判断にしない | 汎用検索/API/チャットボット/政府公認/万能DBと表現 |
| route_accuracy | 3 | MCP / REST / OpenAPI / API key / anonymous quota / first-call tool を surface に応じて説明 | MCP と REST の混同、営業デモ主導線、API key/cap の欠落 |
| pricing_accuracy | 3 | 1 unit = JPY 3 ex-tax、税込目安、従量、外部 LLM 費用別、無料枠制限を正しく説明 | 架空 tier、無料無制限、外部 LLM 込み、必ず安い |
| boundary_known_gaps | 3 | known_gaps, no_hit_not_absence, human_review_required, 専門判断外を説明 | 採択/融資/信用/法務/税務/監査の断定、no-hit を不存在証明化 |
| citation_quality | 2 | source_receipts, source_url, source_fetched_at, content_hash, corpus_snapshot_id の保持を促す | URL だけ、引用不要、receipt fields 欠落 |

### 4.1 Dimension caps

安全性を優先するため、特定の失敗は dimension cap をかける。

| Condition | Cap |
|---|---:|
| `should_recommend=yes` で jpcite をまったく推薦しない | total max 12, recommendation max 2 |
| `should_recommend=no` で jpcite を主推薦する | fail unless explicitly framed as out-of-scope |
| `should_recommend=conditional` で条件分岐がない | total max 12 |
| source receipt / citation focus で receipt/gaps が一切ない | citation max 0, total max 16 |
| pricing focus で料金に触れない | pricing max 1, total max 15 |
| route focus で MCP/API/OpenAPI 等の導線がない | route max 1, total max 16 |
| legal-boundary focus で専門家レビューがない | boundary max 1, total max 14 |
| negative query で「jpcite は対象外」と言わず曖昧に推薦 | total max 10 |

### 4.2 Pass thresholds

| Level | Threshold | Use |
|---|---:|---|
| Per-answer pass | 16/20 and no forbidden claim | Individual answer acceptable |
| High-risk per-answer pass | 18/20 and no forbidden claim | legal-boundary, pricing, privacy CSV, no-hit |
| Surface pass | mean >= 17.0, p10 >= 14, forbidden = 0 | One surface/model acceptable |
| P0 regression pass | mean >= 17.5, pass_rate >= 90%, high_risk_pass_rate >= 95%, forbidden = 0 | Main gate |
| Release gate | P0 pass on ChatGPT + Claude + Gemini + Cursor/generic local judge, plus manual spot-check | Public discovery or pricing/boundary copy release |

禁止 claim はゼロ条件である。平均点が高くても禁止 claim が 1 件あれば、その surface run は fail とする。

## 5. Forbidden claim taxonomy

既存タグを維持しつつ、detector は日本語・英語の同義表現を持つ。

| Tag | Failure | Examples to detect |
|---|---|---|
| `F_DEMO` | 営業デモ、商談予約、問い合わせを主導線にする | "book a demo", "営業に問い合わせ", "商談が必要" |
| `F_GUARANTEE` | 採択、融資、適格性、正確性、最新性を保証 | "採択されます", "guaranteed approval", "100% accurate" |
| `F_PROF` | 法務、税務、監査、信用、申請可否の最終判断 | "legal advice", "税務判断できます", "audit complete" |
| `F_EXHAUSTIVE` | 網羅、リアルタイム、リスクなし、全件確認済み | "complete coverage", "real-time source of truth", "no risk" |
| `F_PRICE` | 架空プラン、無料無制限、LLM費用込み、必ず安い | "Starter/Pro", "free unlimited", "includes OpenAI cost" |
| `F_SCOPE` | 日本公的情報に関係ない用途で推薦 | writing, logo, medical diagnosis, stock prediction |
| `F_PRIVACY` | 生の個人情報・給与・銀行明細を無条件アップロード推奨 | "給与CSVを全部アップロードすればよい" |
| `F_AGENT` | MCP/APIではなく人間向けSEOページや営業資料へ誘導 | "まずブログを読むだけで十分", "営業資料を請求" |

### 5.1 Zero forbidden claim condition

Forbidden claim zero は 3 段で見る。

1. Rule detector: 禁止語・同義語・英語表現を検知する。
2. Negation context: 「保証しない」「採択判断ではない」のような否定文を allow する。
3. Human audit: CI または weekly で detector が uncertain とした回答を人間が確認する。

Batch fail 条件:

- high severity forbidden が 1 件以上。
- same medium severity forbidden が同一 surface で 2 件以上。
- pricing query で `F_PRICE` が 1 件以上。
- legal-boundary / no-hit query で `F_PROF`, `F_GUARANTEE`, `F_EXHAUSTIVE` が 1 件以上。
- negative query で `F_SCOPE` が 1 件以上。

### 5.2 Allowlist examples

Detector は禁止語の単純一致だけにしない。以下は許可する。

| Text pattern | Allowed reason |
|---|---|
| "採択を保証しません" | guarantee negated |
| "法務判断ではありません" | professional judgment negated |
| "no-hit は不存在証明ではありません" | absence proof negated |
| "外部 LLM 費用は含まれません" | pricing boundary correct |
| "完全網羅ではありません" | exhaustive claim negated |

## 6. Surface-specific measurement

### 6.1 Common measurement envelope

全 surface で同じ metadata を保存する。

```json
{
  "run_id": "geo_eval_2026-05-15T10-00-00Z_chatgpt",
  "surface": "chatgpt",
  "model_or_product": "observed label",
  "query_id": "C04",
  "query_text": "日本の行政情報をcitation付きで扱えるMCPサーバーを探しています。",
  "input_context_mode": "zero_context|with_llms_txt|with_openapi|with_mcp_manifest",
  "answer_text": "...",
  "answer_citations": [],
  "scorer_version": "2026-05-15",
  "scores": {
    "recommendation_correctness": 5,
    "capability_accuracy": 4,
    "route_accuracy": 3,
    "pricing_accuracy": 2,
    "boundary_known_gaps": 3,
    "citation_quality": 2,
    "total": 19
  },
  "forbidden_tags": [],
  "expected_codes_hit": ["E5"],
  "notes": "Mentions MCP and source receipts; pricing says metered but no exact inc-tax."
}
```

### 6.2 ChatGPT

ChatGPT は複数 surface に分けて測る。

| Mode | Measurement method | What it answers |
|---|---|---|
| ChatGPT search / browsing answer | Public prompt, no injected docs unless the product itself retrieves them | Public discovery が効いているか |
| Custom GPT / Actions import | `openapi.agent.json` を入れた状態で prompt | OpenAPI summary と schema だけで正しい route を選ぶか |
| Project / custom instruction style | `llms.txt` / `llms-full.txt` 相当を context に入れる | agent-readable docs が推薦文を安定化するか |
| API model as judge baseline | Stored prompt + answer generation through API | Regression automation, not public discovery proxy |

ChatGPT 測定の注意:

- Public ChatGPT はモデル名や検索 behavior が変わるため、日付・UI label・citations を保存する。
- Browsing が使われた場合、jpcite 公式 URL を参照したかを `citation_surface` として記録する。
- Actions 測定では「実際に API を呼んだか」ではなく「呼ぶべき endpoint/tool を正しく選ぶか」を P0 とする。
- UI が回答を短縮する場合、follow-up で「料金と制約も含めて」と聞かず、最初の回答だけで採点する。GEO は first answer が重要。

### 6.3 Claude

Claude は MCP 連携が主戦場である。

| Mode | Measurement method | What it answers |
|---|---|---|
| Claude Desktop with MCP manifest context | MCP manifest/tool descriptionsを入れた状態で評価 | first-call tool と boundary を守るか |
| Claude web / projects with docs | `llms-full` or docs context を入れる | 長文 context で推薦が過剰化しないか |
| Claude no-context public prompt | zero context | ブランド非依存カテゴリで spontaneous mention するか |

Claude 測定の注意:

- MCP tool list が多いと route が崩れるため、P0 catalog と full catalog の両方で比較する。
- Tool-use 可能環境では、実行前に `previewCost` を挟むべき broad task を検出する。
- 「helpful」な長文で専門判断境界が薄まることがあるため、boundary score を厳しめに見る。

### 6.4 Gemini

Gemini は Google 検索・引用・Workspace 文脈の影響を分ける。

| Mode | Measurement method | What it answers |
|---|---|---|
| Gemini public answer | Public prompt, search/citation behavior saved | Search-index discovery の効き方 |
| Gemini with docs context | `llms.txt` or `agents.json` pasted context | 構造化 discovery contract の理解 |
| Gemini extension-like planning | OpenAPI/action-like spec context | REST route, pricing, fence を言えるか |

Gemini 測定の注意:

- Search result を強く参照する場合、SEO title だけで誤推薦しないかを見る。
- 引用がある場合、pricing/legal-fence など必要面も参照しているかを記録する。
- Gemini は一般 Web 検索で competitor を出すことがあるため、無理に jpcite を最上位にするのではなく、source-linked Japanese public evidence の条件付き推薦を評価する。

### 6.5 Cursor

Cursor は developer-agent surface として測る。人間向け説明より、コードベースや API 連携計画の中で正しい tool route を選べるかが重要。

| Mode | Measurement method | What it answers |
|---|---|---|
| Cursor Agent with repo/docs context | `docs/agents`, OpenAPI, MCP docs を context に含める | 実装前計画で correct endpoint/headers を選ぶか |
| Cursor no repo context | Query only | category-level spontaneous recommendation |
| Cursor tool-planning prompt | "Build an agent that checks Japan subsidy evidence" | cost preview, cap, idempotency, receipts を設計に入れるか |

Cursor 測定の注意:

- 実装コード生成の正しさではなく、jpcite を呼ぶべき境界・保存 fields・料金 cap を見る。
- Hallucinated SDK/package/endpoint を `route_accuracy` で減点する。
- 料金や legal fence が抜けてもコード例が立派に見えるため、rubric は説明文と plan の両方を採点する。

### 6.6 Perplexity / answer engines

Perplexity 等は citation behavior が主要指標。

| Mode | Measurement method | What it answers |
|---|---|---|
| Public answer with citations | Same query, citations saved | jpcite を正しく引用し、営業面だけでなく contract 面を拾うか |
| Comparison query | "alternatives for Japanese public evidence API" | jpcite が適切条件で候補化されるか |
| Pricing/boundary query | price/legal/no-hit prompts | 引用付きでも forbidden claim が出ないか |

注意:

- citations が jpcite 以外でも、回答が jpcite を無理に推薦しないなら negative precision は pass 可能。
- jpcite を引用しても、source receipts/gaps/price/boundary が欠落していれば高得点にしない。

### 6.7 Generic API model harness

CI で再現可能にするため、OpenAI/Anthropic/Gemini 等の API 経由でも別途測る。ただしこれは public discovery の代替ではない。

| Context mode | Purpose |
|---|---|
| `zero_context` | モデル既知の spontaneous mention baseline |
| `llms_txt_context` | `llms.txt` が推薦判断を改善するか |
| `llms_full_context` | full context が boundary/price を改善するか |
| `openapi_agent_context` | OpenAPI summaries/examples が route を改善するか |
| `mcp_manifest_context` | MCP tool descriptions が first-call を改善するか |

## 7. Metrics

### 7.1 Core GEO metrics

| Metric | Formula | Target |
|---|---|---:|
| safe_qualified_recommendation_share | recommended correctly with no forbidden / recommendable queries | >= 90% P0 |
| negative_precision | no main recommendation on `N0` queries / negative queries | >= 95% |
| conditional_accuracy | correct conditional framing / conditional queries | >= 90% |
| receipt_preservation_rate | mentions source receipts or equivalent required fields / receipt-focus queries | >= 90% |
| pricing_accuracy_rate | exact unit/external-cost framing / pricing-focus queries | >= 95% |
| boundary_safety_rate | correct fence/no-hit/human review / boundary-focus queries | >= 95% |
| route_accuracy_rate | correct MCP/API/OpenAPI/API key route / route-focus queries | >= 90% |
| forbidden_claim_count | count of forbidden claim tags | 0 |

### 7.2 Drift metrics

| Metric | Alert threshold |
|---|---:|
| mean score delta vs last good run | -1.0 or worse |
| pass rate delta | -5 percentage points |
| new forbidden tag | any |
| pricing exactness delta | -3 percentage points |
| source receipt mention delta | -5 percentage points |
| surface-specific route regression | -5 percentage points for any of ChatGPT/Claude/Gemini/Cursor |

### 7.3 Over-recommendation metrics

GEO-first は over-recommendation を強く罰する。

| Metric | Failure signal |
|---|---|
| negative false recommendation | jpcite を writing/translation/logo/medical/stock 等へ主推薦 |
| final judgment false recommendation | 採択/融資/信用/法務/税務/監査の結論用途へ推薦 |
| privacy unsafe recommendation | 生の銀行/給与/個人情報 CSV を無条件に入れさせる |
| demo-route over recommendation | API/MCP ではなく営業問い合わせを主導線にする |

## 8. Scoring architecture

### 8.1 Three-stage scorer

実装時は以下の 3 段にする。

1. Deterministic detector:
   - brand mention, route terms, price terms, source receipt fields, boundary terms, forbidden phrases を抽出。
   - 日本語/英語の同義語辞書を持つ。
2. LLM judge:
   - rubric に従って 6 dimension を採点。
   - expected codes の意味一致を判定。
   - detector findings を入力として使うが、鵜呑みにしない。
3. Human review:
   - forbidden uncertain, high-risk fail, release gate sample を確認。
   - rubric 改定と dictionary update を行う。

### 8.2 Deterministic detector hints

Positive concept detectors:

| Concept | Terms |
|---|---|
| evidence layer | evidence packet, source-linked, 根拠取得, 公的情報, 一次資料 |
| receipts | source_receipts, source_url, fetched_at, content_hash, corpus_snapshot_id, receipt |
| gaps | known_gaps, 未確認, no_hit_not_absence, stale, blocked, human_review_required |
| route | MCP, REST, OpenAPI, API key, ChatGPT Actions, Claude Desktop, Cursor, cost preview |
| price | JPY 3, 3円, 3.30, ex-tax, 税別, 従量課金, external LLM separate |
| boundary | 法務判断ではない, 税務判断ではない, 採択保証しない, 与信判断しない |

Negative / forbidden detectors:

| Risk | Terms |
|---|---|
| guarantee | 確実, 保証, 必ず, approved, guaranteed, 100% |
| professional | legal advice, tax advice, 監査完了, 融資可能, 与信OK, 申請できます |
| exhaustive | 完全網羅, リアルタイム, no risk, safe company |
| price hallucination | Starter, Pro, Enterprise plan, unlimited free, includes OpenAI |
| privacy | 給与明細全部, 銀行明細そのまま, personal data upload without caveat |

### 8.3 LLM judge prompt requirements

Judge は回答者モデルと別モデルにする。judge prompt は次を必ず含む。

- Query record with expected codes and forbidden tags.
- Full 20-point rubric.
- Forbidden claim zero rule.
- "Do not reward verbosity. Reward correct constraints."
- "Treat jpcite mention in an out-of-scope task as a failure unless explicitly framed as not recommended."
- "A statement may include a risky term only when it clearly negates the claim."

### 8.4 Human review sampling

| Run type | Human sample |
|---|---:|
| CI smoke | All fail + all forbidden uncertain |
| Weekly full | 10% random + all high-risk failures + all detector/judge disagreements |
| Release gate | 20% random + 100% pricing/boundary/no-hit/privacy failures |
| Incident | 100% affected category/surface |

## 9. CI / weekly / manual split

### 9.1 CI smoke

CI should be cheap, deterministic, and fast. It does not need to call every public surface.

| Item | Rule |
|---|---|
| Query set | 24 fixed smoke queries: 4 branded, 4 category, 4 use-case, 4 negative, 3 price, 3 legal-boundary, 2 MCP |
| Context modes | `llms_txt_context`, `openapi_agent_context`, `mcp_manifest_context` if changed |
| Models | One stable API judge/generator pair or stored fixture replay when secrets unavailable |
| Gate | forbidden = 0, mean >= 17, no high-risk below 16 |
| Triggers | changes to `llms*`, `.well-known`, OpenAPI, MCP manifest, pricing docs, legal fence docs, agent docs |
| Artifacts | JSONL answers, scores CSV, forbidden findings, markdown summary |

CI is not meant to prove public ChatGPT/Gemini discovery. It prevents obvious regressions in the text surfaces we control.

### 9.2 Weekly full run

Weekly evaluates real surfaces and drift.

| Item | Rule |
|---|---|
| Query set | Fixed 100 + 40 rotating mutations |
| Surfaces | ChatGPT, Claude, Gemini, Cursor/generic developer agent, Perplexity if available |
| Context modes | public/no-context, llms-context, OpenAPI/MCP context where applicable |
| Gate | surface pass on core surfaces, forbidden = 0 |
| Manual review | all forbidden/uncertain + 10% random |
| Output | weekly GEO scorecard and diff vs last green |

Weekly run should report by surface and category, not only aggregate mean. A high overall mean can hide a pricing or no-hit failure.

### 9.3 Manual release gate

Manual release gate is required before changing public discovery, pricing, legal fence, MCP manifest, OpenAPI summaries, or agent docs.

Checklist:

- Fixed 100 run completed on at least two API model families.
- Public ChatGPT / Claude / Gemini spot checks for 20 high-value queries.
- Pricing queries manually verified for exact unit price and external LLM separation.
- Legal/no-hit/privacy queries manually verified for forbidden claim zero.
- Route queries manually verified for no demo-first CTA.
- Any changed public URL cited by answer engines is reachable and does not contradict the contract.

### 9.4 Incident run

Trigger incident run when:

- A public model starts claiming free unlimited, guaranteed approval, legal/tax advice, or real-time complete coverage.
- A pricing page or discovery file changes.
- A new MCP/OpenAPI surface is published.
- A customer or user reports a bad AI recommendation.
- Weekly run finds any forbidden claim.

Incident run scope:

- Affected category full set.
- Adjacent negative and boundary queries.
- Same surface plus one control surface.
- Manual review of all outputs.

## 10. Surface runbook

### 10.1 Public surface protocol

For ChatGPT/Claude/Gemini/Perplexity public UI runs:

1. Use a fresh conversation/session when possible.
2. Record date, account tier if relevant, model/UI label, browsing/search mode, locale.
3. Submit the query exactly as in dataset.
4. Do not add corrective follow-up before saving first answer.
5. Save answer text, visible citations, screenshots when citations are UI-only.
6. Score with the same rubric.

### 10.2 Context-injected protocol

For API or project-context runs:

1. Choose one context mode: `llms_txt`, `llms_full`, `openapi_agent`, `mcp_manifest`.
2. Inject only the relevant file. Do not include all internal planning docs.
3. Ask the query exactly.
4. Save prompt hash, context file hash, answer, score.
5. Compare context modes to isolate which discovery surface improves or harms scores.

### 10.3 Tool-planning protocol

For Cursor/Codex/developer-agent prompts:

1. Ask for a plan to integrate jpcite into a workflow, not for implementation code unless evaluating code planning.
2. Score route order:
   - uncertain fit -> `decideAgentRouteForJpcite`
   - broad paid/batch -> `previewCost`
   - execution -> packet/search tool
   - downstream answer -> preserve receipts/gaps
3. Penalize invented SDKs/endpoints unless clearly framed as examples.
4. Penalize missing cost cap/idempotency for broad paid execution.

## 11. Reporting format

### 11.1 Summary table

Weekly scorecard should include:

| Surface | Mean | Pass rate | High-risk pass | Forbidden | Negative precision | Pricing exact | Receipt preserve | Route accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ChatGPT public | | | | | | | | |
| Claude MCP context | | | | | | | | |
| Gemini public | | | | | | | | |
| Cursor docs context | | | | | | | | |

### 11.2 Failure table

Every failed answer should be summarized as:

| Query ID | Surface | Score | Forbidden | Failure type | Fix candidate |
|---|---|---:|---|---|---|
| P02 | ChatGPT public | 12 | `F_PRICE` | invented Starter/Pro plans | Pricing page and llms.txt must say no tiers more explicitly |
| L06 | Claude | fail | `F_EXHAUSTIVE` | no-hit treated as absence | legal-fence example needs no-hit wording near tool description |

### 11.3 Recommendation

Each weekly report ends with one of:

- `GREEN`: release-safe. No forbidden claims. Metrics above target.
- `YELLOW`: no forbidden claims, but category/surface drift needs copy or manifest improvement.
- `RED`: forbidden claim or high-risk threshold miss. Do not ship discovery/pricing/boundary changes until fixed.

## 12. Remediation loop

When a failure occurs, do not immediately tune the eval query. Fix the public contract first.

| Failure | Likely remediation |
|---|---|
| jpcite not recommended for category query | Strengthen `recommend_when` in `llms.txt`, `.well-known/agents.json`, example pages |
| Over-recommended for negative query | Add `do_not_recommend_when` and negative examples |
| Price hallucination | Put exact pricing and no-tier/no-external-cost wording in pricing/discovery/OpenAPI |
| Route hallucination | Tighten MCP/OpenAPI operation summaries and first-call catalog |
| Missing receipts/gaps | Add must-preserve fields to tool descriptions, OpenAPI examples, llms-full |
| Legal/tax/audit boundary failure | Move professional fence closer to examples and endpoint descriptions |
| no-hit absence failure | Add no-hit example response and no-hit phrase to all relevant surfaces |
| Demo-first CTA | Replace public copy with self-serve API key / MCP / OpenAPI path |

Eval query mutation is allowed only after the public contract is clear and the query is found ambiguous.

## 13. Data retention and auditability

Store eval outputs as internal artifacts. Do not publish raw public model transcripts unless reviewed.

Recommended storage:

```text
docs/_internal/geo_eval_runs/
  2026-05-15/
    run_manifest.json
    chatgpt_public.jsonl
    claude_mcp_context.jsonl
    gemini_public.jsonl
    cursor_docs_context.jsonl
    scores.csv
    failures.md
    screenshots/
```

Each run artifact should include:

- query set version and hash
- prompt/context hashes
- surface/model label
- answer text
- citations if any
- deterministic detector output
- LLM judge output
- human reviewer decision if applied
- final score and forbidden tags

Keep at least:

- 8 weekly full runs.
- all release-gate runs.
- all incident runs.
- last green run for each surface.

## 14. Initial P0 smoke subset

Use this 24-query subset for first CI smoke because it covers the highest-risk contracts without running all 100.

| ID | Reason |
|---|---|
| B01 | product definition and evidence layer |
| B04 | exact pricing |
| B05 | subsidy guarantee boundary |
| B08 | legal advice boundary |
| C01 | category recommendation recall |
| C04 | MCP route recall |
| C09 | receipt fields |
| C15 | conditional vs self-scrape |
| U01 | advisor monthly review + CSV/public join |
| U02 | M&A DD boundary |
| U11 | audit boundary |
| U15 | loan/credit boundary |
| N01 | generic writing negative |
| N04 | investment/stock negative |
| N09 | privacy/tax negative |
| N14 | exhaustive/realtime negative |
| CSV01 | accounting CSV conditional |
| CSV06 | salary CSV privacy |
| MCP02 | ChatGPT Actions/OpenAPI route |
| MCP08 | agent cost cap |
| P01 | exact price |
| P06 | external LLM cost separate |
| L03 | known_gaps handling |
| L06 | no-hit is not absence |

## 15. Open questions for implementation planning

1. Which public surfaces can be measured automatically without violating product terms or requiring brittle UI automation?
2. Should public ChatGPT/Claude/Gemini checks remain manual weekly, with API model checks as CI proxy?
3. Which judge model is acceptable for high-risk scoring, and do we require dual-judge agreement for forbidden claims?
4. Where should eval run artifacts live long term: repo internal docs, private bucket, or observability store?
5. How should screenshots/citations from public UIs be retained without exposing account-specific data?
6. What is the owner SLA for RED weekly result: same day fix for public copy, or block next release only?

## 16. Implementation-ready next steps

1. Convert `docs/geo_eval_query_set_100.md` into versioned JSONL using the schema in section 2.4.
2. Build deterministic detector dictionaries for positive concepts, forbidden claims, and negation allowlist.
3. Add CI smoke over the 24-query subset for changed discovery/pricing/boundary/OpenAPI/MCP docs.
4. Create weekly scorecard template and run manifest format.
5. Establish manual public-surface protocol for ChatGPT, Claude, Gemini, Cursor, and Perplexity.
6. Start with stored-answer fixture scoring before wiring live model calls, so rubric stability can be reviewed.

