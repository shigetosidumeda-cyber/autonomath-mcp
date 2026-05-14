# Claude Code から日本の補助金 DB を 1 行で呼べる時代 — jpcite MCP β 公開

2026 年 5 月 11 日、Bookyou株式会社 (T8010001213708) は「日本の公的制度を AI agent から横断照会する」ための API & MCP server「jpcite」のベータ版を公開しました。`uvx autonomath-mcp` の 1 行で Claude Code に統合できます。

## なぜ作ったか — 士業 → AI への evidence handoff の現状課題

中小企業の経営者が「うちの会社、何か使える補助金あります?」と税理士に聞く。税理士は中小企業庁 / 経産省 / 各府省 / gBizINFO / 国税庁 / e-Gov を 1 サイトずつ巡回し、エクセル一覧と PDF 募集要項を 30 〜 50 ファイル開いて条件照合する。これを 1 顧問先あたり月 1 回やる。100 社抱えていれば月 100 回。

AI に聞けば早いだろう、と思って Claude や ChatGPT に投げると、学習データの 2024 年カットオフで答えが返ってきて、出典 URL もなく、最新の採択結果や行政処分の反映もない。AI 出力をそのまま顧客に渡せば後で「あの補助金もう終わってるじゃない」と言われる。だから結局 AI を使わず手作業に戻る。

jpcite はこの「公開情報の snapshot を AI に根拠付きで渡す」一点を解決する API です。データ自体は政府が無料で出している公開情報なので、私たちが提供する価値は (a) 7 サイトの normalize、(b) `source_url + fetched_at + content_hash` の出典 Evidence 付与、(c) 法人番号での横断 join、(d) Stripe ¥3/billable unit metered billing、の 4 つに絞っています。DB/source freshness と caller 側 review は引き続き必要です。

## 何ができるか — 5 商品

1. **会社フォルダ Brief / Pack** — 法人番号 1 つで baseline / 採択履歴 / 行政処分 / インボイス登録 / 関連法令を 18 req (¥59.40 税込) で 1 PDF artifact に。M&A 前 DD / 新規取引 KYC / 内部監査用途の確認材料をまとめます。
2. **顧問先月次レビュー** — 100 社 × 月次 = ¥330/月の前提例。インボイス取消 / 行政処分新着 / 採択結果 monitor を月初 1 batch で fan-out。会計事務所の月次定例準備で使う確認材料をまとめます。
3. **受付前エビデンス整理パック** — 1000 案件 triage = ¥52,800/月。顧客問合せの法人名から baseline + 業種 + 規模を 3 req で fetch し、担当者振分に必要な根拠を Evidence Packet として揃えます。
4. **M&A M&A DD / 取引先公開情報チェック** — 1 社 = ¥155.10 (47 req)。法人 6 源泉 + 行政処分 5 年遡及 + 適格事業者推移 + 採択補助金履歴 + 関連法令 + 役員兼任を 1 通の DD report に。
5. **相談前プレ診断** — 50 件 = ¥1,320 (400 req)。士業の初回相談前に相談者の法人状態を 8 req で先回り fetch する前提例。面談前の確認材料として使えます。

## どう使うか — 5 min 接続、4 AI surface

### Claude Code (uvx 1 行)

```
claude mcp add jpcite -- uvx autonomath-mcp
```

これだけで Claude Desktop / Claude Code の tool picker に jpcite の 151 tool が即時 enumerate されます。`/mcp` で接続状況、`/tools` で全 tool 一覧。

### Cursor (.cursor/mcp.json 1 file)

`.cursor/mcp.json` に MCP server を 1 block 追加。プロジェクト root に置けばチーム共有、`~/.cursor/mcp.json` に置けば user 全体共有。Cursor の AI chat / Cmd+K / Composer から jpcite を直接呼べます。

### ChatGPT Custom GPT (Action URL import)

Custom GPT 設定の `Add actions` → `Import from URL` に `https://jpcite.com/openapi.agent.gpt30.json` を貼り付け。GPT Actions の 30 paths 上限に合わせた subset を別 OpenAPI で配信しています。

### OpenAI Codex / Agents SDK (hosted_mcp 1 import)

```python
from agents import Agent, hosted_mcp
mcp = hosted_mcp(server_url="https://api.jpcite.com/mcp")
agent = Agent(name="jp_subsidy", tools=mcp.list_tools())
```

remote MCP として hosted 経由で叩く構成です。SDK が tool discovery / call / response を cover、認証は header injection で完結。

## 業法フェンス — 8 業法は踏み越さない

jpcite は「公開情報の Evidence handoff」までで止まる設計です。AI が個別案件の税務・法律助言を出力しないよう、以下 8 業法に対応するフェンスを実装しています。

- 税理士法 §52 (税務代理・税務書類作成の独占業務)
- 弁護士法 §72 (個別法律相談・代理の独占業務)
- 公認会計士法 §47-2 (監査証明業務)
- 行政書士法 §1の2 (官公署提出書類等)
- 司法書士法 §3 (登記又は供託に関する手続代理)
- 社会保険労務士法 §27 (労務書類作成・社会保険申請代行の独占業務)
- 弁理士法 §75 (特許・商標出願代理・鑑定の独占業務)
- 労働基準法 §36 (36協定)

sensitive surface に該当する出力では「本情報は公開情報の集約であり、個別案件は有資格者にご相談ください」という disclaimer を表示対象にし、個別の税額計算 / 法的判断 / 適合性判定に踏み込まないガードレールを置いています。

## 価格 — ¥3/billable unit、無料 3 req/IP/日

- 完全従量 ¥3/billable unit (税込 ¥3.30)
- 無料 3 req/IP/日 (anon、API key 不要、playground 体験可)
- Stripe Checkout 1 分で API key 発行
- 月額固定費なし、解約は dashboard 1 click
- 法人 invoice / 適格請求書 (T8010001213708) は月次自動発行

「とりあえず触りたい」だけなら https://jpcite.com/playground で無料 3 req/IP/日。API key 取って本番に組み込むなら https://jpcite.com/pricing から Stripe Checkout 1 分です。

## 数字 (β 公開時点)

- 補助金: 11,601 件 (tier S=114 / A=1,340 / B=4,186 / C=5,961)
- 法令メタ: 9,484 件 (e-Gov CC-BY-4.0)
- 行政処分: 1,185 件
- 適格事業者: 13,801 件 (PDL v1.0 monthly bulk)
- 法人公開情報 entity: 503,930 件
- 関係 facts: 6.12M / relations: 378,342 / 改正 snapshot: 14,596
- MCP tool 数: 151 (industry packs / chain / composition 含む)

## 次の予定

- 法人番号横断 join の強化 (gBizINFO + 適格事業者 + 行政処分の 3 軸 simultaneous match)
- 自治体補助金 monitor (47 都道府県の独自補助金を順次 wire)
- 適格事業者取消 watch (月次 diff alert)
- 産業別 industry packs 拡張 (現在 9 業種、Wave 23 で追加分散中)

## 連絡

Bookyou株式会社 (T8010001213708)、代表取締役 梅田茂利、東京都文京区小日向 2-22-1、info@bookyou.net。法人 invoice / 適格請求書 / 個別契約はこのメール 1 本で 24h 以内に返信します。

https://jpcite.com で公開中です。
