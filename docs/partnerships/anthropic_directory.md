# Partnership — Anthropic / Claude Desktop MCP Directory

> **要約 (summary):** Claude Desktop の **MCP server registry** に jpcite を登録。`mcp publish server.json` 1 コマンド + DXT bundle (`autonomath-mcp.mcpb`) で完結。Claude 利用者 (50,000+ active developers) が **直接** jpcite を叩く。referral fee なし — Anthropic は registry 運営者であり referral partner ではない。jpcite が直接従量課金。

## ターゲットと規模

- Claude Desktop アクティブユーザー: 約 50,000 (2026 Q1 推定、日本市場含む)
- 想定到達率: 5% (= 2,500 user) × 月平均 8,000 req × ¥3 = **月 ¥6,000,000 = 年 ¥72M 規模の流通額上限 (historical "年 ARR 上限" 表現)**、10-30% realized = ¥7.2M-21.6M / 年。per-user 節約額は [cost saving examples](../canonical/cost_saving_examples.md) 参照。
- 受注経路: registry listing (self-serve install) のみ。営業 NG

## 連携シナリオ

Claude Desktop ユーザー (AI 開発者 / 税理士 / 行政書士 / VC) が:

1. `Settings → Extensions → Browse Directory` で「jpcite」を検索
2. 1 click でインストール (`autonomath-mcp.mcpb` または PyPI `uvx autonomath-mcp`)
3. すぐに `「弊社の今期使える税制と補助金は?」`と Claude に聞ける
4. Claude が jpcite MCP の 151 tools  + 30 autonomath at default gates) を自動選択して呼出

API key 不要 (anonymous IP-based 3 req/日 free)、有料化は本人が Stripe portal でカード登録するだけ。

## 配布形式

| 形式 | エンドユーザー導線 | 実装 |
|------|------------------|------|
| MCP Official Registry | `Settings → Extensions → Browse → Install` 1 click | `mcp publish server.json` |
| DXT Bundle (`autonomath-mcp.mcpb`) | URL から `.mcpb` をダウンロード → ダブルクリック | `bash scripts/build_mcpb.sh` |
| PyPI | `uvx autonomath-mcp` で manual config | 既存 `autonomath-mcp` v0.3.0 |

`server.json` は既に整備済 (Schema `2025-12-11`、Protocol `2025-06-18`)。

## referral fee なし

- Anthropic は **registry 運営者** であり、referral partner ではない
- jpcite は **直接** ユーザーに ¥3/billable unit を課金
- Anthropic API / claude CLI / SDK は **jpcite サーバー側で呼ばない** (memory `feedback_autonomath_no_api_use`) — 推論はユーザー側 Claude Desktop の subagent が実行
- discount は永久 NG

## Directory listing copy 案

### Japanese (long, ≤500 chars)

```
jpcite — 日本の制度情報 MCP サーバー (151 tools, protocol 2025-06-18)。
14,472 プログラム (補助金 / 融資 / 税制 / 認定) + 2,286 採択事例 + 108 融資 (担保 /
個人保証人 / 第三者保証人 三軸分解) + 1,185 行政処分 + e-Gov 法令メタデータ・条文参照 (record により coverage は異なる) +
税制 ruleset (インボイス / 電帳法) 50 行 + 適格請求書事業者 13,801 行 (PDL v1.0) +
503,930 entity + 6.12M facts + 177,381 relations + 335k aliases。
181 件の排他ルール、cross-dataset glue (trace_program_to_law / find_cases_by_law /
combined_compliance_check)。major public rows: source_url + fetched_at where available、検出済み集約サイトは除外。
¥3/billable unit (税別、税込 ¥3.30) フル従量、IP ベース 3 req/日 無料 (JST 翌日 00:00 リセット、
key 不要)。Bookyou 株式会社 / info@bookyou.net。
```

### English (long, ≤500 chars)

```
jpcite — MCP server (151 tools, protocol 2025-06-18) over Japanese public-program
data: 14,472 programs (subsidy / loan / tax / certification) + 2,286 acceptance cases +
108 loans (3-axis: collateral / individual guarantor / third-party guarantor) +
1,185 enforcement actions + e-Gov law metadata and article references (coverage varies by record) + 50 tax rulesets
(invoice / electronic-bookkeeping) + 13,801 invoice registrants (NTA, PDL v1.0) +
503,930 entities + 6.12M facts + 177,381 relations + 335k aliases.
181 exclusion / prerequisite rules; cross-dataset glue: trace_program_to_law /
find_cases_by_law / combined_compliance_check. major public rows ship source_url +
fetched_at where available; known aggregator sources are excluded where detected.
¥3/billable unit fully metered (¥3.30 incl. tax); 3 req/day
per IP free (resets JST midnight, no key required). Bookyou Inc. / info@bookyou.net.
```

### Short (≤160 chars, registry summary)

JP:
```
日本の制度情報 (補助金 / 融資 / 税制 / 認定) を 151 ツールで横断検索。181 排他ルール、3 軸融資リスク、出典付き。¥3/billable unit、3 req/日 free。
```

EN:
```
151-tool MCP over Japanese public programs (subsidy/loan/tax) with 181 exclusion rules, 3-axis loan risk, source citations. ¥3/billable unit; 3 req/day free.
```

## 申請手順

```bash
# 1. 事前確認 (mcp_registries.md § 1 prerequisites)
.venv/bin/pytest --tb=short -q
.venv/bin/mkdocs build --strict
python -c "import json; print(json.load(open('server.json'))['version'])"
python -c "import re; print(re.search(r'version\s*=\s*\"(.+?)\"', open('pyproject.toml').read).group(1))"
# 両 version が一致

# 2. publish (launch day = 2026-05-06、それ以前は実行禁止)
export MCP_REGISTRY_TOKEN="ghp_..."   # GitHub PAT, repo:read on jpcite/autonomath-mcp
mcp publish server.json
# expected: "Published io.github.jpcite/autonomath-mcp@0.2.0 successfully"

# 3. DXT bundle 配布 (Claude Desktop 直接 install ルート)
bash scripts/build_mcpb.sh
# 出力 site/downloads/autonomath-mcp.mcpb を Cloudflare Pages で /downloads/autonomath-mcp.mcpb として配信
```

## Timeline (T+90d)

| T+ | アクション |
|----|-----------|
| T-7d (= 2026-04-29) | server.json + .mcpb の最終ビルド + 動作確認 |
| T+0d (= 2026-05-06) | `mcp publish` 実行、DXT 配信開始 |
| T+1d | registry listing 確認、PulseMCP / Glama 自動 ingest を確認 |
| T+30d | Anthropic Featured Directory 申請 (任意 — 法務 OK 取れたら) |
| T+90d | Claude Desktop の「Featured Extensions」selection を beg しない、organic 待ち (memory `feedback_organic_only_no_ads`) |

## 触れない

- Anthropic への営業電話 / 個別契約は **永久 NG** (memory `feedback_organic_only_no_ads`)
- Anthropic の logo / 商標は **法務 OK 受領後のみ** (memory `feedback_no_trademark_registration`)
- claude CLI / claude SDK は **jpcite サーバーから一切呼ばない** (memory `feedback_autonomath_no_api_use`、5,000 円損失で確立)
- "Anthropic Partner" / "Claude Certified" 表記は許諾あるまで禁止 (景表法)
- "Featured" 申請 → 落選 でフォローアップしない (organic only)

## 参考リンク

- MCP Official Registry: https://registry.modelcontextprotocol.io/
- DXT spec: https://github.com/anthropics/dxt
- Claude Desktop Extensions: Settings → Extensions → Browse Directory
- 内部参照: `scripts/mcp_registries.md` (registry submission runbook) / `server.json` (MCP manifest, version + tool count)
