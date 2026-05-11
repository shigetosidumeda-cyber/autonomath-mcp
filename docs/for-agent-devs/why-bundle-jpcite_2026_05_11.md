# Why bundle jpcite into your agent — a 30-second pitch for 5 dev personas

> 対象: AI agent dev (OpenAI Plugin builder / Anthropic MCP server author / Cursor MCP author / Custom GPT 作者 / Gemini Extensions dev / Perplexity Spaces dev / Anthropic API direct integrator / B2B 業務 SaaS の AI 機能担当)
> Snapshot: 2026-05-11 (facts_registry.json `snapshot_at: 2026-05-11T00:00:00Z`, snapshot_git_sha `d4216ffb`)
> 通貨: JPY (¥3 ex-tax / ¥3.30 inc-tax per billable unit, 100% metered, tier なし)
> 編集方針: ¥0/req tier や Pro plan、広告、フェーズ提案、工数の話、旧 brand (jpintel/AutonoMath/税務会計AI/zeimu-kaikei.ai) を本文に出さない。

---

## 共通の前提 (全 persona に効く 30 秒概要)

- **jpcite は evidence prefetch API + MCP server**。LLM 推論は一切しない (CLAUDE.md `Never put LLM API imports … anywhere under src/, scripts/cron/, scripts/etl/, or tests/`)。Caller の agent が推論し、jpcite は `source_url` / `source_fetched_at` / `corpus_snapshot_id` / `known_gaps` / `identity_confidence` / 併用ルール付きの evidence packet を返す。
- **規模感**: 11,601 searchable programs (S=114 / A=1,340 / B=4,186 / C=5,961) + 6,493 laws full-text + 9,484 law catalog stubs + 2,286 採択事例 + 108 融資 + 1,185 行政処分 + 50 tax_rulesets + 2,065 court_decisions + 362 bids + 13,801 invoice_registrants + 503,930 entities + 6.12M facts + 378,342 relations + 335,605 aliases + 181 排他/前提 rules + 33 am_tax_treaty rows。
- **配信面**: MCP 139 tools (default gate, protocol 2025-06-18) + REST 220 paths (full OpenAPI, `openapi.agent.json` は 34 paths agent-safe subset)。
- **業法 fence**: 8 canonical (税理士§52 / 弁護士§72 / 公認会計士§47の2 / 司法書士§73 / 行政書士§19 / 社労士§27 / 中小企業診断士登録規則 / 弁理士§75)。agent 側に `_disclaimer` 付き envelope が自動で乗る → agent dev は独占業務踏み込みを設計時に意識する手間が無くなる。
- **課金**: ¥3 ex-tax / 約 ¥3.30 inc-tax per billable unit, Stripe metered, tier なし、anonymous 3 req/IP/日 (JST 翌日 00:00 リセット)、API key 発行は Stripe Checkout 1 分でメール認証不要。
- **header**: `X-API-Key` (必須) / `X-Client-Tag: <顧問先 ID>` (任意・原価集計) / `Idempotency-Key: <uuid>` (POST 再送安全) / `X-Cost-Cap-JPY: <整数>` (batch 上限) → agent dev は user / project 単位で margin を計算しやすい。
- **install (全 surface 共通)**: `uvx autonomath-mcp` (legacy package name 維持、user-facing brand は jpcite)。Hosted MCP endpoint `https://api.jpcite.com/mcp` も別途利用可。

---

## Persona 1 — Custom GPT 作者 (日本市場向け補助金 / 税務系 GPT 作る個人)

### 30 秒 elevator pitch

ChatGPT Custom GPT で「日本の補助金教えて」「インボイス番号確認して」と聞かれた瞬間、web browsing だけだと PDF を丸読みして context を食い切るか、聞いた制度名が架空で hallucinate するかのどちらか。jpcite Action を 1 import すると、`/v1/programs/search` で実在 `unified_id` を返し、`/v1/evidence/packets/query` で出典 URL + fetched_at + known_gaps を渡してくれる。¥3.30/req inc-tax で fence (税理士法§52) も自動付与され、GPT は「申告書は作らない、専門家に相談」と user に正しく案内できる。

### bundle 後の agent 品質差 (before / after)

| 軸 | before (web browsing + GPT 単体) | after (jpcite Action import) |
|---|---|---|
| hallucinate 率 | 制度名・要件・締切を平気で捏造、program_id 架空 | `search_programs` 経由で実在 `unified_id` のみ参照、catalog 11,601 件 / 採択 2,286 件で照合 |
| coverage | 検索結果 top-10 PDF だけ、地方/業種狭め取りこぼし大 | 47 都道府県 × JSIC majors × tier S/A/B/C 全件横断、`upcoming_deadlines` で締切 30/60/90 日順 |
| 出典 verifiable | URL 出るが fetched_at 不明、リンク切れ多発 | `source_url` + `source_fetched_at` 必ず返却、`/v1/citations/verify` で到達性確認可 |
| 業法侵犯 risk | 「節税対策はこう」と GPT が断定 → 税理士法§52 抵触 | 8 fence の `_disclaimer` が envelope に同梱、user に専門家相談を自動案内 |

### ¥3/req の経済性

- 1 query = 約 1 unit (¥3.30 inc-tax)。GPT の monthly ARPU が ¥1,000 の有料 GPT なら、303 query/月まで margin 確保 (実際は web browsing 削減で OpenAI 側 token もむしろ減る)。
- 1 GPT user が月 10 query なら ¥33 inc-tax / 月、100 query で ¥330 inc-tax / 月。Custom GPT 単発の有料化テンプレ (note / Boothで ¥980 売り) でも 30 user で月 ¥970 のコスト負担、評判だけで回収可能。
- ChatGPT Custom GPT の anonymous は 3 req/共有 OpenAI IP/日 (実質 1 GPT で頻繁に枯れる) → 有料公開する GPT には必ず agent dev 自前の `sk_...` を Action header に固定推奨。

### install (3 step 以内)

```text
1. ChatGPT → Explore GPTs → Create → Configure → Actions
2. Import from URL: https://api.jpcite.com/v1/openapi.agent.json  (34 paths agent-safe subset)
   または 30 paths slim を使う場合: https://jpcite.com/openapi.agent.gpt30.json
3. Authentication → API Key → Bearer → sk_xxxxx (発行は https://jpcite.com/pricing.html#api-paid)
```

### first call output サンプル (実 response 抜粋)

```json
GET /v1/intelligence/precomputed/query?q=ものづくり補助金&prefecture=東京都&include_compression=true
{
  "results": [
    {
      "unified_id": "P-monozukuri-2026",
      "title": "ものづくり・商業・サービス生産性向上促進補助金 第18次",
      "source_url": "https://portal.monodukuri-hojo.jp/...",
      "source_fetched_at": "2026-05-10T03:14:22Z",
      "corpus_snapshot_id": "2026-05-11T00:00:00Z",
      "tier": "S",
      "amount_max_jpy": 50000000,
      "application_window": {"start": "2026-04-15", "end": "2026-07-10"},
      "known_gaps": ["application_form_url is the portal index, per-round PDF requires login"]
    }
  ],
  "_disclaimer": "本回答は税務助言ではありません。申告は税理士にご確認ください。 // fence: 税理士法§52"
}
```

---

## Persona 2 — Anthropic MCP server author (Claude Project に組み込む業界特化 server 作る人)

### 30 秒 elevator pitch

Claude Project で「税理士 / 会計士 / M&A」向けの業界特化 MCP server を自分で書くなら、まず公的制度コーパスは jpcite に bundle して、自分の server は「業界固有の差別化レイヤ」だけ書け。139 tool が `uvx autonomath-mcp` 1 行で 30 秒解禁、protocol 2025-06-18、Claude Desktop / Cursor / Cline と互換。`evidence/packets/query` / `prescreen_programs` / `check_exclusions` / `search_invoice_registrants` / `search_laws` / `search_court_decisions` を再実装する工数が消える。

### bundle 後の agent 品質差 (before / after)

| 軸 | before (自前 server に DB 抱える) | after (jpcite MCP を bundle) |
|---|---|---|
| hallucinate 率 | Claude が `program_id` を捏造して `get_program` 404 連発 | `search_programs` で実在 `unified_id` を取ってから `get_program` の運用 rule 確立、`facts_registry.json` の `forbidden_modifiers` で番号架空も guard |
| coverage | 自前で 50 制度集めて運用、地方補助金は虫食い | 11,601 programs × 47 都道府県 × tier S/A/B/C 全件、6,493 法令 full-text + 2,065 判例 + 1,185 行政処分 + 13,801 invoice registrants |
| 出典 verifiable | source URL なし、Claude が「公式サイトより」と曖昧引用 | 全 record `source_url` + `source_fetched_at` + `corpus_snapshot_id`、`/v1/citations/verify` で到達性 / 本文一致確認可 |
| 業法侵犯 risk | Claude が個別税額計算して税理士法§52 抵触判定リスクは自分持ち | 8 fence の `_disclaimer` envelope と `// fence: <業法>` コメント規約で agent 側に責任分担を委ねられる |

### ¥3/req の経済性

- 自前 server で「税理士向け Claude Project」を売る場合、典型 1 顧問先月次レビュー = `previewCost` + `company_public_baseline` + `prescreenPrograms` + `evidence/packets/query` × 3 = 約 18 unit / ¥60 inc-tax。
- 顧問先 100 社月次 = 18 × 100 = 1,800 unit / ¥6,000 inc-tax / 月。MCP server 自体を ¥9,800/月 で売っても粗利 ¥3,800 残る。
- `X-Client-Tag: <顧問先 ID>` で顧問先別原価集計、`X-Cost-Cap-JPY` で月次予算上限を SDK 側で hardcap 可能。
- agent dev 自身が Anthropic API を呼ぶ場合の token cost と完全独立 (jpcite は自前 LLM 呼ばないので jpcite 側請求は固定式)。

### install (3 step 以内)

```text
1. uvx をインストール: curl -LsSf https://astral.sh/uv/install.sh | sh
2. 自分の MCP server の install instruction に追加: uvx autonomath-mcp
   または ~/.claude.json / .cursor/mcp.json に
   { "mcpServers": { "jpcite": { "command": "uvx", "args": ["autonomath-mcp"],
     "env": { "JPCITE_API_KEY": "sk_xxxxx" } } } }
3. 動作確認: claude mcp list | grep jpcite  (Connected, 139 tools)
```

### first call output サンプル (実 response 抜粋)

```json
search_programs (MCP tool call)
{
  "q": "事業再構築",
  "prefecture": "東京都",
  "tier": ["S", "A"],
  "limit": 5
}
→
{
  "total": 17,
  "limit": 5,
  "offset": 0,
  "results": [
    {
      "unified_id": "P-jigyou-saikouchiku-2026",
      "title": "事業再構築補助金 第13回",
      "tier": "S",
      "source_url": "https://jigyou-saikouchiku.go.jp/...",
      "source_fetched_at": "2026-05-09T12:42:08Z",
      "corpus_snapshot_id": "2026-05-11T00:00:00Z",
      "compatibility_rules": ["exclusive_with: P-monozukuri-2026"],
      "known_gaps": []
    }
  ]
}
```

---

## Persona 3 — Cursor / Codex MCP author (developer-focused 業務 agent)

### 30 秒 elevator pitch

Cursor / Codex で「日本企業向け SaaS の AI 機能」を書くと、必ず「補助金 / 法令 / 適格請求書 / 行政処分」のどれかに触れる。`.cursor/mcp.json` に jpcite を bundle すると、Cursor agent が `dd_profile_am` 1 call で法人番号 → 採択履歴 + invoice 登録 + enforcement + 関連法令を束ねた public DD packet を返してくる。`pack_construction` / `pack_manufacturing` / `pack_real_estate` の業種別 1-call wrapper で 5-7 call が 1 SQL に潰れ、Cursor の latency と token 両方が落ちる。

### bundle 後の agent 品質差 (before / after)

| 軸 | before (Cursor agent が web fetch + LLM 推論で組み立て) | after (jpcite MCP bundle) |
|---|---|---|
| hallucinate 率 | 法人番号 13 桁 checksum も検証せず、agent が架空 invoice 番号生成 | `search_invoice_registrants(houjin_bangou=…)` で NTA 一次データに直接当たる (PDL v1.0 attribution 同梱) |
| coverage | 1 query で 1-3 source しか cover できない、業種 × 地域 cohort 弱い | `dd_profile_am` で法人番号 1 本 → 採択 + invoice + enforcement bundle、`graph_traverse` で 1-3 hop 知識グラフ walk (177,381 edges) を 1 SQL |
| 出典 verifiable | LLM が「公式サイトより」と generic 引用、user が確認に行くと 404 | `source_url` + `source_fetched_at` 必須、`compatibility_rules` も `am_compat_matrix` (4,300 sourced pairs) から machine-readable |
| 業法侵犯 risk | Cursor agent が登記 / 監査意見を generate して司法書士法§73 / 公認会計士法§47の2 抵触 | `// fence: 司法書士法§73` / `// fence: 公認会計士法§47の2` を出力 code block に必須付与する規約 (CLAUDE.md `Fence-aware quote 規約`) |

### ¥3/req の経済性

- B2B SaaS の AI 機能として bundle する場合、典型 1 取引先 DD = `company_public_baseline` + `search_invoice_registrants` + `search_enforcement_cases` + `company_public_audit_pack` = 約 24 unit / ¥80 inc-tax。
- BPO 1,000 案件 triage = 16,000 unit / ¥52,800 inc-tax。1 案件あたり ¥52.8 で公的 DD layer が組める。
- agent dev の SaaS が ¥980/月 / user の subscription で、user 1 人月平均 30 query なら ¥99 jpcite コスト / user、粗利 ¥881。
- `Idempotency-Key` で POST 再送安全、Cursor の chat session で agent が同じ tool を再 fire しても二重課金しない。

### install (3 step 以内)

```text
1. mkdir -p .cursor
2. curl -o .cursor/mcp.json https://jpcite.com/.cursor/mcp.example.json
   (内容: { "mcpServers": { "jpcite": { "command": "uvx",
     "args": ["autonomath-mcp"], "env": { "JPCITE_API_KEY": "sk_xxxxx" } } } })
3. Cursor 再起動 → Settings → MCP → jpcite が緑 dot で表示、tools count 139
```

### first call output サンプル (実 response 抜粋)

```json
@jpcite dd_profile_am houjin_bangou=8010001213708
→
{
  "houjin": {
    "houjin_bangou": "8010001213708",
    "legal_name": "Bookyou株式会社",
    "address": "東京都文京区小日向2-22-1",
    "invoice_registration": {"number": "T8010001213708", "registered_at": "2025-05-12"},
    "identity_confidence": 0.98,
    "source_url": "https://www.invoice-kohyo.nta.go.jp/...",
    "source_fetched_at": "2026-05-10T03:14:22Z"
  },
  "adoption_history": [],
  "enforcement_history": [],
  "known_gaps": [
    "民間決算情報 (TDB/TSR) は jpcite では扱わない、与信判断は対応外"
  ],
  "_disclaimer": "本回答は与信判断ではありません。 // fence: 公認会計士法§47の2"
}
```

---

## Persona 4 — Perplexity Spaces / Anthropic API direct integrator (RAG + LLM 自前実装)

### 30 秒 elevator pitch

Perplexity Spaces や Anthropic API + 自前 RAG で日本市場向けプロダクトを作るなら、retrieval 層を全部自前で集めるのは経済合理性ゼロ。jpcite REST 220 paths (`https://api.jpcite.com/v1/*`) を Perplexity Spaces source / 自前 RAG の前段に置けば、token 効率の良い evidence packet (median 566 tokens) が `compression.cost_savings_estimate.break_even_met` 付きで返ってくる。`/v1/evidence/packets/batch` (最大 100 lookup) で massive parallel fetch、`/v1/audit/proof/{evidence_packet_id}` で Merkle 監査チェーン (税理士・監査法人向け差別化)。

### bundle 後の agent 品質差 (before / after)

| 軸 | before (自前 scraping + RAG embedding) | after (jpcite REST/MCP を RAG 前段) |
|---|---|---|
| hallucinate 率 | LLM が embedding 検索結果の chunk から「公式」と称して捏造、原文 lost | evidence packet が `source_url` + `source_fetched_at` + `corpus_snapshot_id` を保持、Perplexity citation と互換 |
| coverage | scraping 漏れ多発 (METI / MAFF / 公庫 / 47 都道府県 全部対応するのは sustaining 不可能) | jpcite が継続 update、e-Gov 法令 CC-BY / NTA PDL v1.0 / gBizINFO 政府標準利用規約 のライセンス整理済み |
| 出典 verifiable | embedding similarity でしか chunk 出てこない、source URL が原典かわからない | `compatibility_rules` / `known_gaps` / `decision_insights` が AI 向け補助 field として届く、`/v1/citations/verify` で到達性 / 本文一致確認可 |
| 業法侵犯 risk | RAG が「節税スキーム」「契約書 template」を直接 chunk として返却 → 業法抵触 | 8 fence の `_disclaimer` envelope と evidence-to-expert handoff rule (`GET /v1/advisors/match`) で agent 側が責任分担しやすい |

### ¥3/req の経済性

- Perplexity Spaces / Anthropic API は token / search で課金される。jpcite は 1 query = 約 1 unit (¥3.30 inc-tax) で、自前 RAG の embedding コスト + chunk token + LLM token を 1 evidence packet (median 566 tokens) に圧縮できる。
- M&A 1 社 public DD = 47 unit / ¥155.10 inc-tax。Perplexity Spaces で ¥9,800/月 subscription の M&A Space を売る場合、user 1 人月 5 社 DD = ¥775.50 コスト / user で margin ¥9,024。
- `/v1/evidence/packets/batch` で 100 lookup → 1 HTTP req、Idempotency-Key で再送安全 → orchestrator 側の retry loop が単純化。
- `/v1/audit/proof/{evidence_packet_id}` で Merkle proof が返り、税理士 / 監査法人 / 金融機関の audit trail 要件に外形的に応えられる。

### install (3 step 以内)

```text
1. (Perplexity Spaces) Sources → Web → URL allowlist に https://api.jpcite.com を追加
   (Anthropic API direct) HTTP client で X-API-Key header を固定
2. curl -H "X-API-Key: sk_xxxxx" \
       "https://api.jpcite.com/v1/intelligence/precomputed/query?q=ものづくり&include_compression=true"
3. 自前 prompt template に
   "Cite source_url and source_fetched_at from jpcite evidence packets verbatim.
    Do not invent program_id. Use 'unified_id' from search_programs response."
   を入れて RAG / Space prompt を仕上げる
```

### first call output サンプル (実 response 抜粋)

```json
POST /v1/evidence/packets/query
Headers: X-API-Key: sk_xxxxx, X-Client-Tag: client_abc
Body: { "subject_kind": "program", "subject_id": "P-monozukuri-2026",
        "include_compression": true,
        "source_tokens_basis": "token_count", "source_token_count": 12400,
        "input_token_price_jpy_per_1m": 300 }
→
{
  "evidence_packet": {
    "subject_kind": "program",
    "subject_id": "P-monozukuri-2026",
    "title": "ものづくり・商業・サービス生産性向上促進補助金 第18次",
    "facts": [...],
    "source_url": "https://portal.monodukuri-hojo.jp/...",
    "source_fetched_at": "2026-05-10T03:14:22Z",
    "corpus_snapshot_id": "2026-05-11T00:00:00Z",
    "known_gaps": ["per-round PDF requires login"],
    "decision_insights": {
      "why_review": "公募要領 v2 で要件改定あり (申請書類追加)",
      "next_checks": ["新様式の入力済確認", "経営革新等支援機関との事前相談"],
      "evidence_gaps": ["事後実績報告 sample 未収録"]
    }
  },
  "compression": {
    "packet_tokens_estimate": 566,
    "input_context_reduction_rate": 0.954,
    "cost_savings_estimate": {
      "break_even_met": true,
      "savings_claim": "estimate_not_guarantee"
    }
  },
  "_disclaimer": "本回答は税務助言ではありません。 // fence: 税理士法§52"
}
```

---

## Persona 5 — B2B 業務 SaaS の AI 機能担当 (freee / マネーフォワード / 弥生 / SmartHR 等の API 担当)

### 30 秒 elevator pitch

freee / マネーフォワード / 弥生 / SmartHR で「補助金・融資・税制・行政処分・適格請求書」の AI 機能を企画した瞬間、内部に「補助金 DB を持つかどうか」の議論が始まる。持つのは 11,601 制度 + 47 都道府県 × 業種 × 締切のクロスを sustaining する人月が永続発生する。jpcite を `https://api.jpcite.com/v1/*` で bundle すれば、SaaS 自身の core domain (会計 / 給与 / 労務) に集中したまま「補助金 AI tab」「適格事業者確認」「監査 DD pack」を ¥3/req 単純従量で SaaS user に流せる。

### bundle 後の agent 品質差 (before / after)

| 軸 | before (SaaS 内で補助金 DB を自前管理) | after (jpcite を API として bundle) |
|---|---|---|
| hallucinate 率 | SaaS が顧客向けに「この補助金が使えます」と generate、要件外 / 期限切れで顧客クレーム | `prescreen_programs(prefecture, industry_jsic, employee_count)` で fit_score + match_reasons + caveats、`known_gaps` で誠実に未確認 gap を出す |
| coverage | 自社で 50-100 制度しか管理できず、地方は虫食い | 11,601 programs + 50 tax_rulesets + 2,065 court_decisions + 1,185 enforcements + 181 排他/前提 ルール |
| 出典 verifiable | SaaS dashboard で「補助金一覧」を出すが source URL なし、顧客が再確認できない | 全 record `source_url` + `source_fetched_at`、SaaS 顧客が監査 / 税務調査時にそのまま引用可能 |
| 業法侵犯 risk | 弥生 / freee が「節税アドバイス」 generate して税理士法§52 抵触リスクは SaaS 側がフル責任 | jpcite が 8 fence の `_disclaimer` を envelope に同梱 → SaaS 側 UI 設計時に「この出力は専門家相談を推奨」と standardized に flow through 可能 |

### ¥3/req の経済性

- SaaS が ¥30,000/月 の business plan で「補助金 AI tab」を有料化する場合、user 1 人月 300 query = ¥990 jpcite コスト / user、粗利 ¥29,010。
- 信金 / 商工会連合会 / 税理士法人向けの fan-out SaaS なら、`X-Client-Tag` で顧問先別原価集計 → 顧問先 100 件月次レビュー = 1,800 unit / ¥6,000 inc-tax で SaaS が再販。
- 業界 cohort (M&A / 税理士 / 会計士 / FDI / 補助金 consultant / LINE / 信金商工会 / industry packs) ごとに `pack_construction` / `pack_manufacturing` / `pack_real_estate` の 1-call wrapper が用意済み → SaaS 側 UI を industry tab で分けても backend 統一 1 endpoint。
- `audit_seal` (migration 089) + `/v1/audit/proof/{evidence_packet_id}` (Merkle proof) で監査証跡を SaaS 機能として再販可能。
- 法人購買 reviewer 向けに `/.well-known/trust.json` (operator T8010001213708 / SLA / data provenance / legal fences / privacy / security / AI use) を 1 fetch で提示 → SaaS 内部購買稟議の答えが詰まらない。

### install (3 step 以内)

```text
1. SaaS backend (Node.js / Python / Go) の HTTP client に X-API-Key header を固定
   (Stripe Checkout で sk_... 発行: https://jpcite.com/pricing.html#api-paid)
2. SaaS UI の「補助金 AI tab」「適格事業者確認」「監査 DD pack」から
   curl -H "X-API-Key: sk_xxxxx" \
        -H "X-Client-Tag: customer_id_${SaaS_user_id}" \
        "https://api.jpcite.com/v1/programs/search?q=..."
3. SaaS の billing dashboard で X-Client-Tag 集計 → 顧客別原価 / 再販 margin 可視化
```

### first call output サンプル (実 response 抜粋)

```json
GET /v1/programs/search?q=賃上げ促進&prefecture=東京都&industry_jsic=E&limit=3
Headers: X-API-Key: sk_xxxxx, X-Client-Tag: customer_id_42
→
{
  "total": 8,
  "limit": 3,
  "offset": 0,
  "results": [
    {
      "unified_id": "T-chinage-2026",
      "title": "賃上げ促進税制 (中小企業向け)",
      "program_kind": "tax_incentive",
      "tier": "S",
      "amount_max_jpy": null,
      "source_url": "https://www.chusho.meti.go.jp/...",
      "source_fetched_at": "2026-05-09T11:18:00Z",
      "corpus_snapshot_id": "2026-05-11T00:00:00Z",
      "static_url": "https://jpcite.com/programs/T-chinage-2026.html",
      "known_gaps": []
    }
  ],
  "_disclaimer": "本回答は税務助言ではありません。申告は税理士にご確認ください。 // fence: 税理士法§52"
}
```

---

## 全 persona 共通の technical selling point (再掲)

- **vs web search**: jpcite は `source_url` + `source_fetched_at` + `corpus_snapshot_id` + `known_gaps` を必ず返す。web search は出典が generic に劣化し、404 / 改訂前 cache / 同名法人混入のリスクがそのまま LLM に流れる。
- **7 (実 8) 業法 fence**: 8 canonical fence (税理士§52 / 弁護士§72 / 公認会計士§47の2 / 司法書士§73 / 行政書士§19 / 社労士§27 / 中小企業診断士登録規則 / 弁理士§75)。agent dev が「個別税額計算」「契約書 drafting」「登記代理」「監査意見」を踏まない安全装置として envelope に `_disclaimer` 同梱。
- **8 cohort revenue model** (M&A / 税理士 / 会計士 / FDI / 補助金 consultant / 中小企業 LINE / 信金商工会 / industry packs): agent dev が自分の bundling 先 user 群を 8 cohort のどれにマッピングするか即決可能、各 cohort に dedicated table / cron / route が存在 (CLAUDE.md `Cohort revenue model`)。
- **139 MCP tools (default gate) + 220 REST paths**: MCP も REST も同 corpus に hit、Custom GPT 30-path 上限向けに `openapi.agent.gpt30.json` slim も別途配信 (34 paths は agent-safe subset)。
- **数値の規模感**: 11,601 programs + 6,493 laws full-text (+ 9,484 catalog stubs) + 2,286 case studies + 1,185 enforcements + 13,801 invoice_registrants + 503,930 entities + 6.12M facts + 378,342 relations + 335,605 aliases + 181 排他/前提 rules + 33 tax treaty rows。
- **Stripe metered, agent dev の credit flow-through**: agent dev の Stripe 残高に余剰を貯めず、user 単位で `X-Client-Tag` 付与 → user から SaaS / GPT subscription fee を取り、jpcite ¥3/req コストを SaaS side で hardcap (`X-Cost-Cap-JPY`) しつつ flow through 可能。SaaS 側で credit 余剰負担をしなくて良い設計。

---

## Honest caveats (agent dev 向け)

- **anonymous 3 req/IP/日 は共有 IP で枯れやすい**。Custom GPT のように OpenAI 側 IP 共有がある surface では、有料配布する瞬間 sk_... を Action header に固定する設計が必須。
- **`am_amount_condition` 250,946 rows は majority template-default ¥500K/¥2M (broken ETL pass の名残)** → agent 側で aggregate 表示する場合は注意 (facts_registry `data_quality_publishable_false`)。`am_compat_matrix` 43,966 rows のうち 4,300 のみ sourced、残りは heuristic。`am_amendment_snapshot` 14,596 row のうち 144 のみ effective_from 確定 → time-series は 144 だけ高信頼。
- **PyPI package name は `autonomath-mcp` (legacy 維持)**、user-facing brand は jpcite。`uvx autonomath-mcp` の install string は変えない (CLAUDE.md `Never rename src/jpintel_mcp/`)。
- **fence は安全装置であって免責ではない**。agent dev 側でも `// fence: <業法>` コメント差し込み規約を agent prompt に書き、最終的に user が専門家へ handoff する経路を必ず設計する。`/v1/advisors/match` は候補 reviewer 検索であり referral 完了ではない。
- **jpcite は LLM 推論を一切しない**。agent dev 側の LLM (Claude / GPT / Gemini) が推論する設計が前提。jpcite 側 token / search / cache / tool 料金は jpcite ¥3/req の billing と完全独立。

---

> 連絡先: info@bookyou.net / Bookyou株式会社 (T8010001213708) / 東京都文京区小日向2-22-1 / SLA support 24h.
> Canonical surfaces: https://jpcite.com/llms.txt / https://jpcite.com/.well-known/mcp.json / https://jpcite.com/.well-known/trust.json
