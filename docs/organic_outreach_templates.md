# Organic Outreach Templates (operator-only)

> **operator-only**: このページは運営者専用 outreach template 集です。mkdocs.yml の `exclude_docs` で公開除外しています。launch 時の手動 send 用。
>
> 制約 (memory `feedback_organic_only_no_ads`):
> - 営業 / 広告 / 紹介費用 = 永久 NG
> - 自然検索 + earned media + GitHub stars + AI agent registry のみ
> - prtimes.jp / 日経等 banned aggregator への直接 outreach NG (これらの媒体に earned coverage で取り上げてもらうこと自体は OK)
> - ¥3/req 完全従量、tier / seat / 営業電話 提案禁止

更新日: 2026-04-25 / Launch: 2026-05-06

---

## 0. 共通注意

- `[X]` は send 直前に手で埋める変数。template のまま送らないこと。
- 1 媒体あたり 1 回のみ送信。返信なければそれ以上 follow-up しない (organic = pull-based)。
- 全 template は AI 生成を経由せず、operator 本人が校正してから send。
- 法務確認: 企業名・固有名詞は CLAUDE.md の表記 (Bookyou株式会社 / jpcite) を厳守。

---

## 1. Hacker News — Show HN announcement (英語)

**Where**: https://news.ycombinator.com/submit
**When**: T+0 (2026-05-06) 09:00 JST = 20:00 ET 前日 / TG: 平日 PT morning

**Title** (max 80 chars):

```
Show HN: jpcite – MCP API for 11k Japanese government subsidy/loan/tax data
```

**URL**: `https://jpcite.com`

**Text (first comment)** — Show HN は本文に first comment 推奨:

```
Hi HN! I'm Shigetoshi (solo dev, Tokyo).

jpcite is a REST + MCP API that exposes Japanese public-program data —
subsidies, loans, tax incentives, certifications, laws, enforcement cases,
invoice registrants — to AI agents in a single call.

Coverage as of launch (2026-05-06):
- 14,472 programs (METI, MAFF, SME Agency, prefectures, JFC)
- 2,286 case studies (採択事例)
- 108 loans, decomposed across collateral / personal-guarantor / third-party-guarantor axes
- 1,185 enforcement cases
- 9,484 laws (e-Gov, CC-BY, continually loading)
- 13,801 invoice registrants (NTA, PDL v1.0, delta-only live mirror)
- 503,930 entities + 6.12M facts in entity-fact EAV layer
- 181 exclusion rules (35 hand-seeded + 146 auto-extracted from primary sources)
- major public rows have source_url + fetched_at lineage

What's interesting (to me, anyway):
- MCP-native (93 tools, protocol 2025-06-18, stdio). Plug into Claude
  Desktop / Cursor / ChatGPT with one Manifest line, no SDK.
- Cross-dataset glue: trace_program_to_law, find_cases_by_law,
  combined_compliance_check.
- Pricing: pure metered ¥3/request (~$0.02), no tiers, no seat fees,
  anonymous tier gets 3 req/day free per IP.
- Built solo + zero-touch: no sales calls, no DPA negotiation, no Slack
  Connect, no onboarding, 100% organic.

Where jGrants is the *application portal*, this is the *discovery +
compatibility + track-record + statute-trace* layer.

Happy to answer technical questions about 全文検索インデックス (3-gram) for Japanese,
the EAV layer for entity-fact (504k entities, 6.12M facts), or why I went
metered-only.

Repo: https://github.com/[USERNAME]/[REPO]
Docs: https://jpcite.com/docs/
PyPI: https://pypi.org/project/autonomath-mcp/
```

**Notes**:
- Show HN guidelines: tech audience が好む詳細 + first-person 適度に。誇張禁止。
- 自分で upvote/sockpuppet NG (HN ban worthy)。

---

## 2. 日経xTECH ピッチ template (日本語、tech 系記者)

**Where**: 日経xTECH 編集部 (記者個人窓口経由、bizit feedback / SNS DM 経由)
**Who**: 日経xTECH のサブスタック / SaaS / 開発者ツール担当記者 (個人 X / SNS で記事を書いている人)

**件名**:

```
[press] jpcite — 日本の公的制度 14,472 件を AI agent に直接接続する MCP API
```

**本文**:

```
[記者名] 様

突然のご連絡失礼します。Bookyou株式会社 (T8010001213708) の梅田です。
solo 開発で「jpcite」という、日本の公的制度データを AI エージェント
が 1 query で呼び出せる REST + MCP API を 2026-05-06 に launch します。

[記者名] 様が [SaaS / AI agent / 開発者ツール / etc.] 関連の記事を書いて
いらっしゃるのを拝見し、本サービスが該当領域に該当するため、内容を
お伝えしたくご連絡しました。掲載のご検討を頂ければ幸いです。

▼ 概要 (300 字)

jpcite は、日本の公的制度データ — 補助金・融資・税制優遇・認定制度・
法令・行政処分・税務ruleset・適格事業者 — を AI エージェントから 1 API で
呼び出せる REST + MCP サーバーです。経産省・農水省・中小企業庁・日本政策
金融公庫など一次情報源から 14,472 制度 + 2,286 採択事例 + 108 融資 +
1,185 行政処分 + 9,484 法令 + 13,801 適格事業者を正規化。Claude Desktop /
ChatGPT / Cursor / Gemini が stdio で直接呼び出せ、SDK 不要。料金は
完全従量 ¥3/req 税別、匿名 3 req/日 per IP 無料。

▼ 特徴 (記事化検討用)

1. MCP プロトコル 2025-06-18 ネイティブ実装、93 ツール
2. 一次情報源を優先し、主要な公開行に出典 URL を付与
3. 完全従量制 (tier SKU・seat 課金なし) で AI agent workflow に最適化
4. solo 開発 + zero-touch 運営、100% organic acquisition
5. Jグランツが「申請ポータル」なのに対し、jpcite は「発見 + 併用可否
   判定 + 実績確認 + 根拠法トレース」layer

▼ 取材対応

- メールでの書面取材歓迎 (electronic interview)
- 数値 / 出典 / 技術詳細は公開資料 (https://jpcite.com/press/) のとおり
- 引用自由、出典明記をお願いします

▼ プレスキット

- Press kit: https://jpcite.com/press/
- Fact sheet: https://jpcite.com/press/fact-sheet.md
- Quotes: https://jpcite.com/press/quotes.md

宜しくお願いします。

---
梅田茂利 (Shigetoshi Umeda)
Bookyou株式会社 (T8010001213708)
東京都文京区小日向2-22-1
info@bookyou.net
```

---

## 3. TechCrunch JP ピッチ template (日本語、SaaS 系)

**Where**: TechCrunch JP は廃刊 (2022)。代替 = ASCII / CNET Japan / BRIDGE / TechBlitz
**Who**: SaaS / API / 開発者ツール / GovTech 担当の個人記者 (公開窓口)

**件名**:

```
[press] jpcite — solo dev による MCP-first 制度データ API、5/6 launch
```

**本文**:

```
[記者名] 様

[媒体名] 編集部様

Bookyou株式会社 (T8010001213708)、代表の梅田茂利です。
2026-05-06 launch の jpcite について、内容のお伝えのご連絡を差し上げ
ます。

▼ 一行紹介
日本の公的制度データ (補助金・融資・税制・認定・法令・処分・適格事業者)
35,000+ 件を、AI エージェントが MCP プロトコル経由で 1 query で呼び出せる
REST + MCP API。

▼ 記事化に値しうる切り口 (※選択して下さい)

1. **GovTech × MCP**: 国内 MCP サーバー実装で、政府データを 1 行で AI agent
   に繋げる solo プロダクト。Claude Desktop の Manifest 1 行で 93 ツール
   が使える。

2. **完全従量 ¥3/req SaaS**: tier / seat / 年間最低額をすべて廃止し、無料枠
   は匿名 3 req/日 per IP のみ。AI agent 呼び出しのコスト構造に合わせた
   pricing 実験。

3. **Solo + Zero-touch SaaS**: 営業 / CS / 法務チームなし、100% organic で
   launch する個人 SaaS の事例 (info@bookyou.net 1 窓口のみ)。

4. **インボイス制度対応 API**: 適格事業者番号 13,801 件を NTA PDL v1.0 で
   ライブミラー。Stripe Tax 連携で B2B 課金完結。

▼ ピッチ補足

- 売上・MRR・ユーザー数: launch 前のため未公開 (T+7d に transparent
  dashboard 公開予定)
- 競合: Jグランツ (政府の申請ポータル、検索 layer ではない) /
  各 SaaS aggregator (規約上 LLM 投入 grayエリア)

▼ プレスキット

- https://jpcite.com/press/

書面 (メール) 取材歓迎。電話・対面取材は zero-touch 方針のため対応して
おりません。

宜しくお願い致します。

---
梅田茂利
Bookyou株式会社 / info@bookyou.net
```

---

## 4. Zenn / Qiita feature 投稿 template (日本語 dev)

**Where**: Zenn (https://zenn.dev) / Qiita (https://qiita.com) — 自分のアカウントで投稿
**When**: T-3d (2026-05-03) に Zenn 草稿 publish (memory: launch_announcement_calendar)

**Zenn タイトル** (max 70 chars):

```
日本の補助金 14,472 件を AI agent から 1 query で — jpcite を作った話
```

**Qiita タイトル**:

```
MCP プロトコル 2025-06-18 で日本の制度データ 35,000 件を AI agent に流す
```

**本文骨子** (~3000-5000 字):

```markdown
## 背景

日本の補助金・融資・税制・認定制度のデータは政府サイトに散らばっており、
個別の要綱を辿るコストが大きい。一方、Jグランツは「申請ポータル」であり、
事前の発見・併用可否判定・実績確認を担う API は存在しなかった。

## 作ったもの

jpcite — 日本の公的制度を AI エージェントが 1 query で呼び出せる
REST + MCP API。

- 制度: 14,472 件
- 採択事例: 2,286 件
- 融資: 108 件 (担保 / 個人保証人 / 第三者保証人 三軸分解)
- 行政処分: 1,185 件
- 法令: 9,484 件 (e-Gov, CC-BY)
- 適格事業者: 13,801 件 (NTA PDL v1.0)
- entity-fact: 503,930 entities + 6.12M facts

## 技術 stack

- Python + FastAPI (REST)
- FastMCP (stdio MCP server)
- SQLite 全文検索インデックス (3-gram, 日本語複合語検索)
- Fly.io Tokyo (nrt) ホスティング
- Stripe Metered + Stripe Tax (インボイス対応)
- Cloudflare Pages (静的サイト)

## はまった所 (技術記事の core)

1. **全文検索インデックス (3-gram) の偽 single-kanji 一致問題**
   `税額控除` で検索すると `ふるさと納税` も一致 → phrase query で対処

2. **MCP プロトコル 2025-06-18 の 93 ツール定義**
   FastMCP の register pattern + tool schema validation

3. **適格事業者の差分配信 (NTA PDL v1.0)**
   月次フルバルク + 日次 delta の二段同期、JST/UTC 境界処理

4. **完全従量課金 + Stripe Tax**
   `consent_collection={"terms_of_service": "required"}` で 500 を踏んだ事例
   と回避策 (`custom_text.submit.message`)

## 使い方

```json
// Claude Desktop の claude_desktop_config.json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

これで Claude Desktop から `search_programs` / `prescreen` / 他 50 ツール
が使える。

## Pricing

¥3/req 税別、匿名 3 req/日 per IP 無料。
tier / seat / 年間最低額なし。

## Launch

2026-05-06 launch。フィードバック歓迎: info@bookyou.net

GitHub: [URL]
PyPI: https://pypi.org/project/autonomath-mcp/
Docs: https://jpcite.com/docs/
```

**Tag**:
- Zenn: `python`, `mcp`, `claude`, `補助金`, `api`
- Qiita: `Python`, `MCP`, `Claude`, `FastAPI`, `SQLite`

---

## 5. Reddit post template (英語、r/Japan / r/MachineLearning / r/programming)

**Where**:
- r/MachineLearning (Self-Promotion Saturday のみ可)
- r/programming
- r/Japan (生活系のため、本サービス的中度低) - 投稿しなくて良い
- r/LocalLLaMA (MCP 文脈で適合)

**Title** (max 300 chars, but pithy):

```
[P] jpcite: MCP server for 36k Japanese government subsidy/law/tax data, $0.02/req metered
```

**Body**:

```
Solo dev (Tokyo) launching jpcite — REST + MCP API exposing Japanese
public-program data to AI agents (Claude Desktop / ChatGPT / Cursor / Gemini)
in a single call.

**What's in it (as of 2026-05-06 launch):**
- 14,472 subsidy/loan/tax/cert programs (METI, MAFF, JFC, prefectures)
- 2,286 case studies, 108 loans (3-axis collateral), 1,185 enforcement cases
- 9,484 laws (e-Gov, CC-BY) + 13,801 invoice registrants (NTA, PDL v1.0)
- 503,930 entities + 6.12M facts in entity-fact EAV layer
- 181 exclusion rules (program compatibility checks)
- major public rows with source_url + fetched_at lineage

**MCP-native, 93 tools, protocol 2025-06-18:**
- search_programs, prescreen, deadlines, exclusions
- 5 one-shot discovery (smb_starter_pack, subsidy_combo_finder, ...)
- cross-dataset glue: trace_program_to_law, find_cases_by_law,
  combined_compliance_check
- 16 autonomath tools backed by entity-fact DB

**Pricing:** ¥3/req (~$0.02), pure metered, no tiers, no seats, anonymous
gets 3/day free. No sales calls, no DPA negotiation, no onboarding.

**Tech:** Python + FastAPI + FastMCP + SQLite 全文検索インデックス (3-gram), hosted on
Fly.io Tokyo. Stripe metered + Stripe Tax for JP invoice system.

Repo: [GitHub URL]
Docs: https://jpcite.com/docs/
PyPI: https://pypi.org/project/autonomath-mcp/

Happy to discuss 全文検索インデックス (3-gram 分割) pitfalls for Japanese, MCP
tool design tradeoffs, or how the metered-only model holds up against
the inevitable "but we want a free tier" feedback.
```

**Notes**:
- r/MachineLearning は self-promotion 厳格、Saturday only
- 自演 upvote NG (Reddit shadowban worthy)

---

## 6. X (Twitter) thread template (日本語 + 英語)

### 日本語 thread (T+0 launch tweet)

```
1/ 🇯🇵 jpcite 本日 launch しました。
日本の公的制度データ (補助金・融資・税制・認定・法令・処分・適格事業者)
35,000+ 件を、AI エージェントが 1 query で呼び出せる REST + MCP API です。

https://jpcite.com

2/ 何が入ってるか
- 制度 14,472 件
- 採択事例 2,286 件
- 融資 108 件 (3軸分解: 担保/個人保証人/第三者保証人)
- 行政処分 1,185 件
- 法令 9,484 件 (e-Gov, CC-BY)
- 適格事業者 13,801 件 (NTA PDL v1.0)
- 排他ルール 181 本
- 主要な公開行に出典 URL を付与

3/ MCP プロトコル 2025-06-18 ネイティブ、93 ツール。
Claude Desktop / ChatGPT / Cursor の Manifest に 1 行追加するだけで AI
agent から日本の制度を直接 reasoning できます。SDK 不要。

4/ 料金は完全従量 ¥3/req 税別 (税込 ¥3.30)。
tier / seat / 年間最低額なし。匿名 3 req/日 per IP は無料 (JST 翌日 00:00 リセット)。
Stripe Tax 経由でインボイス対応。

5/ Jグランツが「申請ポータル」なのに対し、
jpcite は「発見 + 併用可否判定 + 実績確認 + 根拠法トレース + 判例・
入札・適格事業者横断」の layer。
データ収集と申請の橋渡しは AI agent に任せる新しい工法です。

6/ solo + zero-touch で運営。
営業 / 広告 / 紹介費なし、100% organic。zero-touch のため電話・対面取材は
対応していません。フィードバック大歓迎: info@bookyou.net

Press kit: https://jpcite.com/press/
Docs: https://jpcite.com/docs/

#MCP #ClaudeDesktop #補助金 #SaaS
```

### English thread (T+0 launch tweet)

```
1/ 🚀 jpcite launches today.
A REST + MCP API exposing 35,000+ Japanese public-program data points
(subsidies, loans, tax incentives, laws, enforcement, invoice registrants)
to AI agents in a single call.

https://jpcite.com

2/ Coverage as of launch:
- 14,472 programs (METI, MAFF, SME Agency, JFC)
- 2,286 case studies
- 108 loans (3-axis: collateral / personal-guarantor / 3rd-party-guarantor)
- 1,185 enforcement cases
- 9,484 laws (e-Gov, CC-BY)
- 13,801 invoice registrants (NTA, PDL v1.0)
- major public rows with source_url

3/ MCP-native, 93 tools, protocol 2025-06-18.
One Manifest line plugs Claude Desktop / ChatGPT / Cursor / Gemini
directly into Japanese government data. No SDK.

4/ Pricing: ¥3/req (~$0.02), pure metered.
No tiers, no seats, no annual minimums. Anonymous gets 3 req/day
free per IP. Stripe Tax for JP invoice system compliance.

5/ Where jGrants is the application portal, jpcite is the
discovery + compatibility + track-record + statute-trace layer.

Built solo + zero-touch, 100% organic acquisition. No sales calls,
no DPA negotiation, no Slack Connect.

Press kit: https://jpcite.com/press/
Docs: https://jpcite.com/docs/

#MCP #ClaudeDesktop #JapanTech #SaaS
```

---

## 7. LinkedIn post template (英語、dev / SaaS persona)

**Where**: 個人 LinkedIn account
**When**: T+0 (launch day)

```
Today I'm launching jpcite — a REST + MCP API that exposes 35,000+
Japanese public-program data points (subsidies, loans, tax incentives,
laws, enforcement cases, invoice registrants) to AI agents in a single
call.

The "why":

For 5+ years, anyone trying to find Japanese government subsidies via AI
agents has hit a wall. Government sites publish PDF-first. Aggregators
exist but are gray-area for LLM ingestion. There was no API for
"is this company eligible for this program, with primary-source URLs and
case-study evidence."

The "how":

- 14,472 programs from METI, MAFF, SME Agency, JFC, 47 prefectures
- 2,286 case studies, 108 loans (3-axis collateral decomposition)
- 9,484 laws (e-Gov, CC-BY), 13,801 invoice registrants (NTA, PDL v1.0)
- MCP-native, 93 tools, protocol 2025-06-18 — plugs into Claude Desktop /
  ChatGPT / Cursor / Gemini with a single Manifest line
- Pure metered ¥3/req (~$0.02), no tiers, no seat fees, anonymous tier
  gets 3/day free per IP
- Built solo + zero-touch — no sales calls, no DPA negotiation, no Slack
  Connect, no onboarding

The "tradeoffs":

I deliberately chose:
- Metered-only over tier SKUs (AI agent workflows don't have "Pro user"
  semantics)
- Solo ops over hiring (zero-touch is the only feasible distribution model
  at this scale)
- Organic only — no ads, no cold outreach, no paid placements
- Earned media over PR-news — banned aggregators avoided

Press kit: https://jpcite.com/press/
Docs: https://jpcite.com/docs/

If you build AI agents that touch Japanese SMBs, accountants, certified
support orgs, or anyone navigating Japan's public-program landscape —
I'd love to hear how it performs in your workflow.

#MCP #ClaudeDesktop #JapanTech #SaaS #AIagents
```

---

## 8. 投稿時 checklist

Before pressing send / publish:

- [ ] template の `[X]` placeholder すべて埋めた
- [ ] 数値 (制度数 / 採択数 / 融資数 / 法令数 / 適格事業者数) を fact-sheet.md と照合
- [ ] 主要導線の出典 URL 動作確認 (https://jpcite.com/press/, /docs/, /pricing.html)
- [ ] 商標表記 (jpcite / Bookyou株式会社 / T8010001213708) 統一
- [ ] 「jpintel」brand を user-facing strings から排除 (memory `project_jpintel_trademark_intel_risk`)
- [ ] tier / seat / 年間最低額の言及がない
- [ ] 営業 / cold call / 紹介費 の言及がない
- [ ] prtimes.jp / 日経への有料掲載提案がない
- [ ] 自演 upvote / sockpuppet 設計がない (HN / Reddit ban worthy)
- [ ] template の AI 生成箇所を operator 本人が校正

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
