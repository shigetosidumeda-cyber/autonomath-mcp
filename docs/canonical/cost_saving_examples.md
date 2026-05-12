# jpcite Cost Saving Examples (per audience)

**Status**: canonical SOT (Wave 46 tick#4)
**Last updated**: 2026-05-12
**Brand**: jpcite (Bookyou株式会社)
**Pricing model**: ¥3/billable unit 完全従量、anonymous 3 req/日 free per IP

## Background — why "cost saving" not ROI/ARR

旧来の audience page は ROI / ARR / 年¥X / 年商 等の SaaS 系 metric を多用していた。 これは
- (1) AutoNoMath 系の SaaS 月額モデル時代の名残で、本来 jpcite は per-request 従量 ¥3 のみ
- (2) ROI 計算には「顧客の機会損失」を絡める必要があり、業種別の前提が透明性を欠く
- (3) ARR / 年¥ は AI agent 時代の per-call 経済性とは合わない

→ Wave 46 tick#3 で `cpa_firm` / `shindanshi` / `ma_advisor` の 3 page を「per-case cost saving table (純 LLM vs jpcite ¥3/req)」に置換済。 本 doc は残 14 page で利用する **業種別 persona × realistic frequency × 純 LLM vs jpcite ¥3/req** の cost saving 試算を canonical 化する。

## Method — per-case cost saving 算出式

```
case_cost_saving = LLM_only_manual_cost − jpcite_request_cost
LLM_only_manual_cost = manual_hours × hourly_rate (¥10,000/h 標準)
jpcite_request_cost = num_requests × ¥3
```

- `manual_hours`: 純粋に AI を補助無しで使い、 hallucination 裏取り + 一次 URL 手動探索 + 法令引用整形まで含めた工数
- `hourly_rate`: 業種別標準 (士業 ¥10,000/h、 金融機関職員 ¥6,000/h、 建設業コンサル ¥8,000/h、 中央会 ¥5,000/h 等)
- `num_requests`: jpcite MCP / REST 経由の 1 case あたり典型 request 数 (1-6 程度)

## 14 page 業種別 cost saving 表

| audience | persona | case | manual cost (純 LLM) | jpcite cost | per-case saving |
|---|---|---|---|---|---|
| **admin-scrivener** | 行政書士 / 事務所 5 案件/月 | 許認可 案件 1 件 prep | 3.5h × ¥10,000 = ¥35,000 | 1.5 req × ¥3 = ¥4.5 | **¥34,995** |
| **construction** | 建設業特化コンサル / 顧問 10 社 | 工事 1 案件 補助金抽出 | 4.0h × ¥8,000 = ¥32,000 | 2 req × ¥3 = ¥6 | **¥31,994** |
| **dev** | AI 開発者 / Claude Desktop 個人 | 試作 1 endpoint 検証 | 2.0h × ¥10,000 = ¥20,000 | 5 req × ¥3 = ¥15 | **¥19,985** |
| **index** | 全 audience アグリゲータ | 平均 case (全 page 加重) | 3.0h × ¥9,000 = ¥27,000 | 3 req × ¥3 = ¥9 | **¥26,991** |
| **journalist** | 記者・調査会社 / 1 取材先 | 法人裏取り 1 件 | 1.5h × ¥8,000 = ¥12,000 | 3 req × ¥3 = ¥9 | **¥11,991** |
| **manufacturing** | 製造業特化コンサル / 顧問 10 社 | 設備投資 1 案件抽出 | 4.0h × ¥8,000 = ¥32,000 | 2 req × ¥3 = ¥6 | **¥31,994** |
| **real_estate** | 不動産業特化コンサル / 顧問 8 社 | 賃貸事業 1 案件抽出 | 3.5h × ¥8,000 = ¥28,000 | 2 req × ¥3 = ¥6 | **¥27,994** |
| **shihoshoshi** | 司法書士 / 商業登記 1 件 | houjin 360° + jurisdiction | 3.0h × ¥10,000 = ¥30,000 | 2 req × ¥3 = ¥6 | **¥29,994** |
| **shinkin** | 信用金庫 取引先担当 / 月 100 取引先 | 1 取引先 補助金 + マル経 | 1.2h × ¥6,000 = ¥7,200 | 2 req × ¥3 = ¥6 | **¥7,194** |
| **shokokai** | 商工会 経営指導員 / 月 200 巡回先 | 1 巡回先 持続化補助金 案内 | 0.8h × ¥5,000 = ¥4,000 | 2 req × ¥3 = ¥6 | **¥3,994** |
| **smb** | 中小企業経営者 / 自社案件 | 自社の補助金候補 1 件相談前準備 | 2.0h × ¥5,000 = ¥10,000 | 3 req × ¥3 = ¥9 | **¥9,991** |
| **subsidy-consultant** | 補助金コンサル / 顧問 30 社 | 1 顧問先 月次スクリーニング | 1.5h × ¥8,000 = ¥12,000 | 3 req × ¥3 = ¥9 | **¥11,991** |
| **tax-advisor** | 税理士 / 顧問先 50 社 | 1 顧問先 措置法確認 | 1.0h × ¥10,000 = ¥10,000 | 2 req × ¥3 = ¥6 | **¥9,994** |
| **vc** | VC / M&A / 1 投資先 DD | 法人 1 社 行政処分 + 採択 + 適格 | 4.0h × ¥10,000 = ¥40,000 | 4 req × ¥3 = ¥12 | **¥39,988** |

### Saving range summary

- **最小**: ¥3,994/case (shokokai 経営指導員 — 巡回 frequency 高 / hourly rate 低)
- **最大**: ¥39,988/case (vc 法人 DD — 高 hourly + 多 endpoint 横断)
- **中央値**: ¥19,985/case (dev 試作 1 endpoint 検証)

## Disclaimers — 透明性 fence

1. **推定値**: 全数値は典型 case の参考値。実 case は工数 / hourly rate / req 数で変動する。
2. **AI 単体 baseline**: 「外部公的制度根拠なしの汎用 LLM 出力」を前提。 hallucination 裏取り工数を含む。
3. **誇大広告意図なし**: jpcite は事実検索 + scaffold 提供のみ。 専門家業務 (税理士業 / 行政書士業 / 司法書士業 / 監査意見 / 法律判断) は資格者本人の専権事項。
4. **¥3/req 完全従量**: anonymous 3 req/日 free per IP は API key なしで利用可 (JST 翌日 00:00 reset)。
5. **税抜表記**: ¥3/req は税抜 (qualified invoice T8010001213708)。

## Related pages

- `/audiences/cpa_firm.html` (tick#3 landed)
- `/audiences/shindanshi.html` (tick#3 landed)
- `/audiences/ma_advisor.html` (tick#3 landed)
- `/pricing.html` (¥3/req 完全従量)

## References

- pricing model: AutonoMath EC v4 改訂 (2026-04-30、¥3/req × Free 3 req/日)
- agent KPI 8: Cost-to-Serve / ASR / ARC / Spending Variance (Wave 16)
- agent funnel 6: Justifiability (Wave 43.5)

---

# v2 — 「普通に AI を使う」vs jpcite MCP の **token 単価ベース** 定量比較 (Wave 48 tick#1)

**Status**: canonical v2 quantify (Wave 48, 2026-05-12)
**目的**: § 14 page 表は「専門家工数 × 時給」ベースで強力だが、AI agent 利用者には「token 価格 + web search 課金」の世界観で語った方が即理解できる。 v2 では Anthropic 公式 + OpenAI 公式の **2026-05 時点公開単価** を使い、6 use case で side-by-side 計算する。

## § A. 「素の Claude/GPT で同じ作業を試す」のコスト構造

AI agent が公的制度 (補助金 / 法令 / 採択 / 行政処分 / 適格事業者) を **jpcite 無し** で扱う場合、 3 種のコストが積み上がる。

1. **入力 token cost** — system + user prompt + (web search 経由で取り込んだ) HTML / PDF chunk
2. **出力 token cost** — 回答テキスト (引用整形 + 業法 fence の代替を文章で書くため長い)
3. **web search tool cost** — Anthropic web search ($10 / 1,000 search) or OpenAI web search ($25-30 / 1,000 search、 search context = low/medium/high)

加えて hallucination 裏取り工数が乗るが、本 v2 では **時給を一切持ち込まず**、 純粋に API 料金だけで比較する (時給ベースは § 14 page 表で網羅済)。

### Anthropic 公式 token pricing — Claude Sonnet 4.5 / Opus 4 (一次参照: https://www.anthropic.com/pricing)

| model | input ($/MTok) | output ($/MTok) | cache write ($/MTok) | cache read ($/MTok) |
|---|---|---|---|---|
| Claude Opus 4 | $15.00 | $75.00 | $18.75 | $1.50 |
| Claude Sonnet 4.5 | $3.00 | $15.00 | $3.75 | $0.30 |
| Claude Haiku 4 | $0.80 | $4.00 | $1.00 | $0.08 |

**web search tool**: $10 / 1,000 search (Anthropic Messages API `web_search_20250305`).

### OpenAI 公式 token pricing — GPT-5 / GPT-4.1 (一次参照: https://openai.com/api/pricing/)

| model | input ($/MTok) | cached input ($/MTok) | output ($/MTok) |
|---|---|---|---|
| GPT-5 | $1.25 | $0.125 | $10.00 |
| GPT-5 mini | $0.25 | $0.025 | $2.00 |
| GPT-4.1 | $2.00 | $0.50 | $8.00 |

**web search tool** (Responses API built-in): $10 (low) / $25 (medium) / $30 (high) per 1,000 searches。 medium が公的制度の調査で実用標準。

### 換算 (本 v2 は ¥150/USD で固定、 2026-05-12 RBA spot 近傍)

```
¥/MTok = USD/MTok × 150
例: Claude Sonnet 4.5 input → $3.00 × 150 = ¥450/MTok = ¥0.00045/token
```

## § B. jpcite MCP 経由のコスト構造

```
jpcite_cost_per_req = ¥3 (税別) = ¥3.30 (税込)
anonymous free tier = 3 req/日 per IP (JST 翌日 00:00 reset)
```

**重要**: jpcite 1 req に対して、 顧客 agent 側の **追加 token 課金は微少**。 jpcite が返す JSON envelope は ~1-3 KB (≈ 300-900 token) で、 これを agent が読むだけの input token しか発生しない。 web search tool は **不要** (jpcite 側で一次出典は decode 済み)。

→ jpcite 1 req の **実質的な fully-loaded cost** は:
```
fully_loaded ≈ ¥3 (jpcite) + (300〜900 token × Claude Sonnet input ¥0.00045/token) ≈ ¥3.14〜3.41
```

## § C. 6 use case side-by-side calculator

各 use case で「純 Claude/GPT で同じ調査を **web search + LLM 推論のみ** で行う」場合と「jpcite MCP 1-N 回呼ぶ」場合を比較。 純 LLM 列は **業務品質 (公的制度の正確な抽出 + 一次出典提示 + 排他ルール照合 + 業法 fence) を保つために必要な multi-turn 検証ループ込み** の token 数を実測 baseline 化した推定値。 単発 1 ターンの token 数ではなく、 hallucination 裏取り 3-5 周 + 引用整形 + 通達 cross-reference まで含む。

**前提**: model = Claude Sonnet 4.5 (input $3 / output $15 per MTok)、 web search = Anthropic $10/1k、 USD = ¥150。 GPT-5 baseline は § E で別計算。

| # | use case | 純 LLM input tokens | 純 LLM output tokens | web search 回数 | 純 LLM 合計 | jpcite req | jpcite 合計 | 1 case 節約額 |
|---|---|---|---|---|---|---|---|---|
| **1** | 法人 1 社の許認可 + 採択 + 行政処分 (M&A DD 同等、 multi-turn 検証込) | 120,000 | 20,000 | 25 | ¥54.00 + ¥45.00 + ¥37.50 = **¥136.50** | 4 | **¥12** | **¥124.50** |
| **2** | 補助金 1 件の要件 + 一次 URL + 排他ルール抽出 (multi-program 比較込) | 80,000 | 15,000 | 18 | ¥36.00 + ¥33.75 + ¥27.00 = **¥96.75** | 2 | **¥6** | **¥90.75** |
| **3** | 税理士: 1 顧問先 措置法該当チェック + 通達 cross-reference | 60,000 | 12,000 | 15 | ¥27.00 + ¥27.00 + ¥22.50 = **¥76.50** | 2 | **¥6** | **¥70.50** |
| **4** | 行政書士: 許認可 1 件 根拠条文 + 通達 + 様式 walk | 90,000 | 15,000 | 20 | ¥40.50 + ¥33.75 + ¥30.00 = **¥104.25** | 2 | **¥6** | **¥98.25** |
| **5** | 信金: 1 取引先 マル経 + 補助金候補 + 排他 verify | 40,000 | 8,000 | 10 | ¥18.00 + ¥18.00 + ¥15.00 = **¥51.00** | 2 | **¥6** | **¥45.00** |
| **6** | dev/AI 開発者: 試作 endpoint 検証 (programs/laws/cases 3-5 endpoint 走査) | 50,000 | 10,000 | 12 | ¥22.50 + ¥22.50 + ¥18.00 = **¥63.00** | 5 | **¥15** | **¥48.00** |

**6 case 合計**: 純 LLM **¥528.00** vs jpcite **¥51** → 合計節約 **¥477.00** (1 セット走らせるだけで ~10x 安い)

### 計算式 (検算用)

```
input_cost  = input_tokens  × (3.00 / 1_000_000) × 150     // Claude Sonnet 4.5 input
output_cost = output_tokens × (15.00 / 1_000_000) × 150    // Claude Sonnet 4.5 output
search_cost = web_search    × (10.00 / 1_000)     × 150    // Anthropic web search
pure_llm    = input_cost + output_cost + search_cost

jpcite_cost = jpcite_req × ¥3
saving      = pure_llm - jpcite_cost
```

### 月次 / 年次 スケール: N use case 走らせた時の節約額

中央値 use case (#3 税理士措置法) は 1 case 純 LLM ¥76.50 vs jpcite ¥6 = **¥70.50/case 節約**。 税理士 / 信金 / 商工会 / VC が顧問先別に毎月 1 case 走らせる場合:

| 月次 case 数 | 純 LLM 合計 (#3 単価) | jpcite 合計 | 月節約額 | 年節約額 (×12) |
|---|---|---|---|---|
| 50 (税理士 50 顧問) | ¥3,825 | ¥300 | **¥3,525** | ¥42,300 |
| 100 (税理士 100 顧問) | ¥7,650 | ¥600 | **¥7,050** | ¥84,600 |
| 200 (信金 200 取引先) | ¥15,300 | ¥1,200 | **¥14,100** | ¥169,200 |
| 1,800 (BPO 月次 triage) | ¥137,700 | ¥10,800 | **¥126,900** | ¥1,522,800 |

**重要 (誇大表記回避)**: § C の節約額は **token cost + web search cost のみの差分**。 jpcite が回避する hallucination 起因の取りこぼし損失や顧問契約解除リスクは含まない (これは § 14 page 表の「工数 × 時給」軸が担当)。 §52 / §72 / 業法 fence の価値は **金額化していない**。

## § D. 公式 pricing inline (一次参照)

### Anthropic Messages API (2026-05-12 取得)

```
# https://www.anthropic.com/pricing#api
Claude Opus 4:    $15.00 input / $75.00 output per million tokens
Claude Sonnet 4.5: $3.00 input / $15.00 output per million tokens
Claude Haiku 4:   $0.80 input / $4.00  output per million tokens

# Web search tool (web_search_20250305)
$10 per 1,000 searches
```

### OpenAI API (2026-05-12 取得)

```
# https://openai.com/api/pricing/ + https://platform.openai.com/docs/pricing
GPT-5:        $1.25 input / $10.00 output per million tokens (cached $0.125)
GPT-5 mini:   $0.25 input / $2.00  output per million tokens
GPT-4.1:      $2.00 input / $8.00  output per million tokens

# Built-in tools (Responses API)
Web search (context=low):    $10 per 1,000 calls
Web search (context=medium): $25 per 1,000 calls
Web search (context=high):   $30 per 1,000 calls
```

## § E. 再現可能な計算スクリプト

```python
# tools/cost_saving_calculator.py-equiv (canonical reference)
USD_JPY = 150
JPCITE_PER_REQ_JPY = 3

MODELS = {
    "claude_sonnet_4_5": {"in_per_mtok": 3.00, "out_per_mtok": 15.00},
    "claude_opus_4":     {"in_per_mtok": 15.00, "out_per_mtok": 75.00},
    "claude_haiku_4":    {"in_per_mtok": 0.80, "out_per_mtok": 4.00},
    "gpt_5":             {"in_per_mtok": 1.25, "out_per_mtok": 10.00},
    "gpt_4_1":           {"in_per_mtok": 2.00, "out_per_mtok": 8.00},
}

WEB_SEARCH = {
    "anthropic":           10.00,  # $/1k searches
    "openai_low":          10.00,
    "openai_medium":       25.00,
    "openai_high":         30.00,
}

def pure_llm_cost_jpy(in_tok, out_tok, searches, model="claude_sonnet_4_5", search="anthropic"):
    m = MODELS[model]
    in_cost  = in_tok  * m["in_per_mtok"]  / 1_000_000 * USD_JPY
    out_cost = out_tok * m["out_per_mtok"] / 1_000_000 * USD_JPY
    sr_cost  = searches * WEB_SEARCH[search] / 1_000 * USD_JPY
    return in_cost + out_cost + sr_cost

def jpcite_cost_jpy(req):
    return req * JPCITE_PER_REQ_JPY

def saving_jpy(in_tok, out_tok, searches, req, **kw):
    return pure_llm_cost_jpy(in_tok, out_tok, searches, **kw) - jpcite_cost_jpy(req)

# 6 use case 検算
USE_CASES = [
    ("1. M&A DD",       120000, 20000, 25, 4),
    ("2. 補助金抽出",     80000, 15000, 18, 2),
    ("3. 税理士措置法",    60000, 12000, 15, 2),
    ("4. 行政書士許認可", 90000, 15000, 20, 2),
    ("5. 信金マル経",     40000,  8000, 10, 2),
    ("6. dev 試作",      50000, 10000, 12, 5),
]
for name, i, o, s, r in USE_CASES:
    print(f"{name}: pure=¥{pure_llm_cost_jpy(i, o, s):.2f}, jpcite=¥{jpcite_cost_jpy(r)}, saving=¥{saving_jpy(i, o, s, r):.2f}")
```

期待出力 (検算済):
```
1. M&A DD:       pure=¥136.50, jpcite=¥12, saving=¥124.50
2. 補助金抽出:    pure=¥96.75,  jpcite=¥6,  saving=¥90.75
3. 税理士措置法:  pure=¥76.50,  jpcite=¥6,  saving=¥70.50
4. 行政書士許認可: pure=¥104.25, jpcite=¥6,  saving=¥98.25
5. 信金マル経:    pure=¥51.00,  jpcite=¥6,  saving=¥45.00
6. dev 試作:     pure=¥63.00,  jpcite=¥15, saving=¥48.00
```

### Web 静的版 calculator

ブラウザで req 数を入力して即時試算できる静的 HTML を `/tools/cost_saving_calculator.html` に配置 (Wave 48 tick#1)。 全数値は本 doc § C と完全一致。

## § F. v2 disclaimers (v1 disclaimer 5 本に加え、 v2 固有 4 本)

1. **2026-05-12 時点公式単価**: Anthropic / OpenAI の API 料金は予告なく改訂される。 本 doc は 2026-05-12 公開単価で固定し、 半年後 (2026-11) に再 verify する。
2. **token 数 baseline**: 「純 LLM 同等品質」を保つための token 数は jpcite チーム実測 + 業界 dev community の中央値推定。 ±30% 程度の変動は許容範囲。
3. **JPY 為替**: 本 doc は USD/JPY = 150 で固定。 実料金は支払い時の Anthropic/OpenAI 課金為替 + クレジットカード手数料に依存。
4. **節約 ≠ 顧客機会損失**: § C 表は API 料金差分のみ。 業務上の取りこぼし損失や顧問解除リスクは含まない (これは § 14 page 表が担当)。


