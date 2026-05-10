# 日本公的制度 AI 横断 API「jpcite」β 公開

**Bookyou株式会社 (代表取締役 梅田茂利、本社 東京都文京区) は、AI agent (Claude / ChatGPT / Cursor / Codex) から日本の公的制度を横断照会できる Evidence API「jpcite」のベータ版を 2026 年 5 月 11 日に公開しました。**

## 背景

日本の公的制度情報 (補助金・許認可・行政処分・適格事業者・法令) は 7+ の政府サイトに分散しており、士業や中小企業の担当者は毎月の制度 monitor / 顧問先別 fit 判定 / DD 用 evidence 収集を手作業で巡回しています。AI に聞いても学習データのみで出典 URL も最新性も保証されず、結局手作業に戻る現状があります。

jpcite は「公開情報の最新 snapshot を AI に正確に渡す」一点に絞った API です。データは政府が無料公開している情報をそのまま normalize し、`source_url + fetched_at + content_hash` を必須付与することで、AI の出力を再検証可能にしています。

## jpcite の特徴 5 つ

1. **法人番号 1 つで 6 源泉を横断照会** — 法人公開 baseline + 採択履歴 + 行政処分 + インボイス登録 + 許認可 + 関連法令を 1 API で取得
2. **5 商品の Artifact 出力** — 会社フォルダ / 顧問先月次レビュー / BPO 受付 / M&A DD / 相談前プレ診断
3. **Evidence Packet 必須** — `source_url + fetched_at + content_hash` を payload に同梱、AI 出力の検証可能性確保
4. **7 業法 fence** — 税理士法 §52 / 弁護士法 §72 / 社労士法 §27 / 行政書士法 §19 / 司法書士法 §73 / 弁理士法 §75 / 公認会計士法 §47-2 の独占業務には踏み込まない設計
5. **¥3/req 完全従量、月額固定費なし** — Stripe metered billing、無料 3 req/IP/日 (API key 不要)

## 数字 (β 公開時点)

- 補助金: 11,601 件 (tier S=114 / A=1,340 / B=4,186 / C=5,961)
- 法令メタ: 9,484 件 (e-Gov CC-BY-4.0)
- 行政処分: 1,185 件 (各府省公開情報)
- 適格事業者: 13,801 件 (PDL v1.0 monthly bulk wired)
- 法人公開情報 entity: 503,930 件
- 関係 facts: 6.12M / relations: 378,342 / 改正 snapshot: 14,596
- MCP tool 数: 139 (industry packs / chain / composition 含む)

## 接続経路 (4 AI surface、各 5 分)

- **Claude Code**: `claude mcp add jpcite -- uvx autonomath-mcp` 1 行
- **Cursor**: `.cursor/mcp.json` 1 file
- **ChatGPT Custom GPT**: `https://jpcite.com/openapi.agent.gpt30.json` を Action import
- **OpenAI Codex / Agents SDK**: `hosted_mcp(server_url="https://api.jpcite.com/mcp")` 1 import

## 価格

- 完全従量 ¥3/req (税込 ¥3.30)
- 無料 3 req/IP/日 (anon、API key 不要)
- Stripe Checkout 1 分で API key 発行
- 月額固定費なし、解約は dashboard から 1 click
- 法人 invoice / 適格請求書 (T8010001213708) は月次自動発行

## 想定 use case と料金例

- **個人士業の月次顧問先 monitor** — 100 社 × 月次 = ¥330/月 (税込)。インボイス取消 / 行政処分新着 / 採択結果を月初 1 batch で fan-out
- **M&A 仲介の前段 DD** — 1 社 = ¥155.10 (47 req)。法人 6 源泉 + 行政処分 5 年遡及 + 適格事業者推移 + 採択履歴 + 関連法令 + 役員兼任を 1 DD report に
- **BPO 一次受付** — 1000 案件 triage = ¥52,800/月。顧客問合せの法人名から baseline + 業種 + 規模を 3 req で fetch
- **士業の相談前プレ診断** — 50 件 = ¥1,320 (400 req)。初回相談前に相談者の法人状態を 8 req で先回り fetch、面談時間が「ヒアリング 50% → アドバイス 80%」に shift

## ライセンスとデータ源

- 国税庁 適格事業者: PDL v1.0 (出典明記で API 再配布可)
- e-Gov 法令: CC-BY-4.0
- 中小企業庁 / 経産省 / 各府省 補助金: 政府標準利用規約 v2.0
- gBizINFO 法人活動: gBizINFO 利用規約

## 会社概要

- 法人名: Bookyou株式会社 (読み: ブックユー)
- 法人番号: 8010001213708
- 適格請求書発行事業者番号: T8010001213708
- 代表者: 代表取締役 梅田茂利
- 所在地: 東京都文京区小日向 2-22-1
- 連絡: info@bookyou.net

## リンク

- Web: https://jpcite.com
- Playground: https://jpcite.com/playground.html
- 料金: https://jpcite.com/pricing
- API リファレンス: https://jpcite.com/api-reference.html
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/

## 報道機関お問い合わせ先

info@bookyou.net (24h 以内対応)
Bookyou株式会社 広報担当
東京都文京区小日向 2-22-1
