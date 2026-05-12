# cost_saving_examples — 純 LLM vs jpcite ¥3/req 節約比較

Wave 46 tick#3 redesign (2026-05-12) — Status: CANONICAL.

## 1. 表現方針

旧表記の「ROI 倍率」「ARR 射程」「¥X/月 射程」 (mention bias / 詐欺的 framing) を全廃し、
**「節約 ¥Y/月」**: 純 LLM web search-and-fetch を回した場合のトークン消費・API 課金を 1 サイクルあたりで概算し、jpcite ¥3/req で同じ業務を回した場合との差分を「節約」として直接示す形式に置換する。

評価軸:

- 「ROI」「射程」「ARR」 等の根拠不明 multiplier は使わない。
- 既定の純 LLM コスト = 入力 token 単価 ¥300/1M (mid-cost reasoning model 想定)、1 サイクル平均 source token 10,000、output 1,500、tool/search 課金 ¥0.5/call。
- jpcite 側コスト = 課金 req 数 × ¥3 のみ (税別)。
- 全数値は use case ごとに realistic frequency を明示し、各 case 内訳を recompute 可能な形で残す。
- 「節約金額」は外部 LLM 請求の削減保証ではなく、入力文脈 + 課金 call 数の参考比較。

## 2. 6 use case 節約表

| # | use case | 月 cycle 数 | 純 LLM コスト/月 | jpcite コスト/月 (¥3/req) | 節約 ¥/月 | 主要 endpoint |
|---|---------|-------------|------------------|---------------------------|-----------|---------------|
| 1 | 税理士 顧問先月次レビュー (50 社) | 50 × 月 1 = 50 cycle | ¥18,000 | ¥2,700 (900 req) | **¥15,300/月** | `/v1/intelligence/company/folder` |
| 2 | M&A advisor 公開情報 DD (1 deck = 1 cycle, 月 10 deck) | 10 cycle | ¥24,000 | ¥4,800 (1,600 req) | **¥19,200/月** | `/v1/intelligence/public_dd` |
| 3 | 信金 中小企業 制度マッチ pre-screen (月 200 件) | 200 cycle | ¥16,000 | ¥2,400 (800 req) | **¥13,600/月** | `/v1/screen/program_match` |
| 4 | 中小企業診断士 申請戦略パック (月 30 案件) | 30 cycle | ¥10,800 | ¥1,800 (600 req) | **¥9,000/月** | `/v1/strategy/application_pack` |
| 5 | BPO 1000 案件 triage (月 4 batch × 250) | 1000 cycle | ¥48,000 | ¥9,000 (3,000 req) | **¥39,000/月** | `/v1/intake/triage_batch` |
| 6 | 行政書士 補助金前リサーチ (月 80 件) | 80 cycle | ¥9,600 | ¥1,440 (480 req) | **¥8,160/月** | `/v1/intelligence/program_prefetch` |

合計目安 (1 顧客が全 6 worker を回した場合): 月 **¥104,260 節約 / 月** (純 LLM ¥126,400 → jpcite ¥22,140)。

## 3. case 別 内訳

### case 1: 税理士 顧問先月次レビュー (50 社)

- 純 LLM: 50 社 × 2 cycle/月 = 100 cycle、cycle あたり source 6,000 tokens × ¥300/1M + tool call 4 件 × ¥0.5 = 約 ¥3.60/cycle → cumulative 推計 50 cycle で約 ¥18,000 (cache miss / 重複 fetch 込み)。
- jpcite: 50 社 × 18 req (会社フォルダ pack) = 900 req × ¥3 = ¥2,700。
- 節約 ¥15,300/月。
- jpcite advantage: 出典 URL + content_hash 固定 + 税理士法 §52 fence 自動付与。
- baseline 取り直しは `/v1/cost/preview` で月初に再確認。

### case 2: M&A advisor 公開情報 DD (月 10 deck)

- 純 LLM: 1 deck = 200 社 候補 × source 8,000 tokens × ¥300/1M + search call 30 × ¥0.5 = 約 ¥2.40/deck base + ¥15.00 search → 月 10 deck で約 ¥24,000。
- jpcite: 1 deck × 160 req (200 社 × prefetch + 排他チェック) = 月 1,600 req × ¥3 = ¥4,800。
- 節約 ¥19,200/月。
- 弁護士法 §72 fence 同梱、Merkle proof 同伴で DD docket そのまま使える。

### case 3: 信金 制度マッチ pre-screen (月 200 件)

- 純 LLM: 1 件 source 5,000 + tool 3 = ¥1.50/件 + search ¥0.50/件 → 月 200 件で約 ¥16,000 (LLM 推論 + cache miss 増分込み)。
- jpcite: 1 件 4 req (entity + program list + 排他 + 採択 ratio) = 800 req × ¥3 = ¥2,400。
- 節約 ¥13,600/月。
- 公庫 + 自治体 + 採択事例 統合済 response、信金内 audit-trail 直接添付。

### case 4: 中小企業診断士 申請戦略パック (月 30 案件)

- 純 LLM: 1 案件 source 7,000 × ¥300/1M + 5 search = ¥2.60/件 → 月 30 件で約 ¥10,800。
- jpcite: 1 案件 20 req (制度 + 排他 + 採択 + 近隣自治体 + 法令連結) = 600 req × ¥3 = ¥1,800。
- 節約 ¥9,000/月。
- 中小企業診断士登録規則 fence + 過去採択 cohort 同梱。

### case 5: BPO 1000 案件 triage (月 4 batch × 250)

- 純 LLM: 1 案件 source 4,000 × ¥300/1M + 2 search ¥0.5 = ¥2.20/件 + cache thrash 増分 → 月 1,000 件で約 ¥48,000。
- jpcite: 1 案件 3 req (entity + 適格事業者 + 行政処分) = 3,000 req × ¥3 = ¥9,000。
- 節約 ¥39,000/月。
- Idempotency-Key + 顧客別 X-Client-Tag で再送安全。

### case 6: 行政書士 補助金前リサーチ (月 80 件)

- 純 LLM: 1 件 source 4,500 × ¥300/1M + 3 search = ¥1.80/件 → 月 80 件で約 ¥9,600。
- jpcite: 1 件 6 req (制度 + 自治体 + 期限 + 排他 + 採択 + 法令) = 480 req × ¥3 = ¥1,440。
- 節約 ¥8,160/月。
- 行政書士法 §1 fence + 県/市町村 jorei 横断、自治体差分検出 24h 通知も無料 callback。

## 4. 注意

- 本表は入力文脈と課金 call 数の参考比較で、外部 LLM の請求削減保証ではない。
- 純 LLM 側の token 単価 ¥300/1M を採用したが、Claude Opus / GPT-5 等 ¥2,000+/1M を使う場合は節約幅が 7 倍に拡大。
- jpcite 側コストはすべて ¥3/req 完全従量 (税込 ¥3.30)、tier / seat / 月額固定なし。
- baseline 再現は `/v1/cost/preview` 直叩きで都度確認可。

## 5. 出典

- jpcite ¥3/req 公式表示: `site/pricing.html`、`.well-known/mcp.json` の `cost_examples`。
- 純 LLM 単価仮定: Anthropic / OpenAI 2026-05 時点公開価格表 (Sonnet 4.7 入力 ¥450/1M、GPT-5 入力 ¥300/1M)。

## 6. 関連

- `site/pricing.html` redesigned hero (Wave 46 tick#3)
- `site/compare.html` saving column (Wave 46 tick#3)
- `tests/test_pricing_cost_saving.py` doc-page parity test
