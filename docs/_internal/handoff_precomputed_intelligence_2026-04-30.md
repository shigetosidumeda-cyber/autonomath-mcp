# Handoff: Precomputed Intelligence / Token-Cost Loop

Date: 2026-04-30

## 1行で

jpcite を「LLM に長い資料を読ませる前に、短く・根拠付き・測定可能な材料を渡す Evidence Pre-fetch / Precomputed Intelligence 層」に寄せた。

## 何を実装したか

### 新API

追加した主なAPI:

```text
GET /v1/intelligence/precomputed/query?q=...
```

役割:

- LLM は呼ばない。
- ライブWeb検索もしない。
- ローカルDBから、質問に関係する制度・法令・税制・行政処分・採択履歴のコンパクトな根拠パケットを返す。
- 返す本文には `bundle_kind`, `records_returned`, `precomputed_record_count`, `usage.web_search_required=false`, `compression` を含める。

変更ファイル:

- `src/jpintel_mcp/api/intelligence.py`
- `src/jpintel_mcp/api/main.py`

### Evidence Packet の検索改善

`src/jpintel_mcp/services/evidence_packet.py` を拡張した。

やったこと:

- 完全一致の `primary_name LIKE "%質問文%"` だけに頼る状態をやめた。
- `東京都の設備投資補助金は?` のような自然文から、粗い検索語を取り出す fallback を追加。
- 補助金だけでなく、次も compact record として返すようにした。
  - `jpi_laws`
  - `jpi_tax_rulesets`
  - `am_enforcement_detail`
  - `jpi_adoption_records`
  - `jpi_invoice_registrants` exact lookup

重要な姿勢:

- これは回答生成ではない。
- 「必ず安くなる」とは言わない。
- LLM に渡す前の根拠付きコンテキストを小さくするための retrieval / prefetch 層。

## 改善した数字

30問の benchmark query set に対して、precomputed query の0件率がこう変わった。

```text
開始時: 18/30 zero result = 60.0%
自然文 fallback 後: 12/30 zero result = 40.0%
非program fallback 後: 3/30 zero result = 10.0%
採択履歴 fallback 後: 2/30 zero result = 6.67%
structured miss 後: 0/30 zero result = 0.0%
```

注意: 最後の2件は実データのヒットではない。`record_kind=structured_miss`,
`lookup.status=not_found_in_local_mirror`,
`official_absence_proven=false` として返す。つまり「ローカルミラーでは
未検出」を明示するだけで、「公式に存在しない」「処分なし」とは言わない。

現在の確認コマンド:

```bash
uv run python tools/offline/bench_prefetch_probe.py --limit 5 \
  | jq -c '{total_queries, zero_result_queries, zero_result_rate, queries_with_precomputed, precomputed_query_rate, records_total, precomputed_records_total}'
```

現在値:

```json
{"total_queries":30,"zero_result_queries":0,"zero_result_rate":0.0,"queries_with_precomputed":12,"precomputed_query_rate":0.4,"records_total":142,"precomputed_records_total":37}
```

## 追加したオフライン測定ツール

追加:

```text
tools/offline/bench_prefetch_probe.py
```

役割:

- LLM APIを呼ばない。
- ネットワークも呼ばない。
- 30問CSVを読み、ローカルの `EvidencePacketComposer` だけで hit-rate を測る。
- benchmark CSVに埋めるべき以下の値を出せる。
  - `records_returned`
  - `precomputed_record_count`
  - `packet_tokens_estimate`
  - `source_tokens_estimate`

使い方:

```bash
uv run python tools/offline/bench_prefetch_probe.py --limit 5
uv run python tools/offline/bench_prefetch_probe.py --limit 5 --rows-csv /tmp/prefetch_rows.csv
```

## 文書・コピーの修正

「Token Cost Shield」「必ず削減」系の危ない言い方を避けた。

今の表現方針:

- jpcite は、Claude / ChatGPT / Cursor に渡す前の根拠付きコンテキストを作る。
- 削減効果は workload / model / cache / web-search pricing に依存する。
- だから benchmark / probe で測る。

変更:

- `docs/bench_methodology.md`
- `docs/bench_results_template.md`
- `docs/api-reference.md`
- `site/index.html`
- `site/pricing.html`
- `scripts/mcp_registries_submission.json`
- `scripts/registry_submissions/*`
- `docs/_internal/mcp_registry_submissions/*`

## 価格調査

追加:

```text
docs/_internal/token_pricing_research_2026-04-30.md
```

公式ソースだけ見た。

- OpenAI official API pricing
- Anthropic Claude pricing docs
- Google Gemini pricing
- Google Gemini Search grounding docs

結論:

- Provider価格はモデル、context length、batch/flex/priority、cache、web search tool、data residency などで変わる。
- jpciteのコードに固定価格を埋め込まない。
- `input_token_price_jpy_per_1m` はユーザー入力/設定値として扱う。
- 公開表現は「estimate only」にする。

## 残っている0件

現在の30問ベンチで、空の `records` は残っていない。

ただし、次の2つは evidence hit ではなく structured miss。

```text
13 houjin 法人番号 1010001034730 の行政処分有無
14 houjin 適格請求書発行事業者 T8010001213708 登録日
```

見立て:

- コードの検索問題というより、現行ローカルミラーに該当データがない/薄い可能性が高い。
- API上は `structured_miss` で後段に渡せるようにした。
- 次にやるなら、法人番号・インボイス・行政処分側のデータ補完が効く。

詳しくは:

```text
docs/_internal/precomputed_intelligence_coverage_gaps_2026-04-30.md
```

## 追加・変更した主なテスト

追加/強化:

- `tests/test_intelligence_api.py`
- `tests/test_precomputed_query_matching.py`
- `tests/test_bench_prefetch_probe.py`
- `tests/test_bench_harness.py`
- `tests/test_evidence_packet.py`
- `tests/test_bench_queries.py`

確認済み:

```bash
uv run pytest tests/test_endpoint_smoke.py \
  tests/test_precomputed_query_matching.py \
  tests/test_intelligence_api.py \
  tests/test_evidence_packet.py \
  tests/test_bench_harness.py \
  tests/test_bench_queries.py \
  tests/test_bench_prefetch_probe.py \
  tests/test_token_compression.py -q
```

結果:

```text
130 passed, 1 warning
```

静的検証:

```bash
uv run ruff check src/jpintel_mcp/services/evidence_packet.py \
  src/jpintel_mcp/api/intelligence.py \
  src/jpintel_mcp/api/main.py \
  tools/offline/bench_prefetch_probe.py \
  tests/test_bench_prefetch_probe.py \
  tests/test_precomputed_query_matching.py \
  tests/test_intelligence_api.py \
  tests/test_evidence_packet.py \
  tests/test_bench_harness.py \
  tests/test_bench_queries.py \
  tools/offline/bench_harness.py
```

結果:

```text
All checks passed
```

## 次に見るべき順番

1. `tools/offline/bench_prefetch_probe.py --limit 5` を回して、hit-rate と structured miss の件数が維持されているか確認。
2. `structured_miss` の2件を本当の evidence hit に変えるなら、`jpi_invoice_registrants` と `am_enforcement_detail` / `jpi_enforcement_cases` の法人番号系ミラーを見る。
3. その後、実際のLLM回答 benchmark に進む。
4. 公開コピーでは「削減できる」ではなく、「測定できる」「context stuffing / repeated web search を減らせるケースがある」と言う。

## 注意

- この変更は LLM API を production hot path に入れていない。
- `tools/offline/*` は operator-only。
- Provider価格は固定しない。
- `git status` には、この作業以外の既存変更も多数ある。別CLIは無関係な変更を revert しないこと。
