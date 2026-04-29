# 公開開発予定

最終更新: 2026-04-29

このページは社内で動いている計画を、外向けにそのまま開示したものです。
**「予定」であり「確約」ではありません。** 期日コミットメントを必要とする
お客様には別途相談ください (`info@bookyou.net`)。

zero-touch / solo 運営のため、フィードバック窓口はメール (`info@bookyou.net`)
の 1 系統に集約しています。GitHub Issues / Discord / Slack 等のコミュニティ
チャンネルは現時点で運用していません。

---

## 直近 1 ヶ月リリース (Done)

過去 30 日に実装・公開したもの。

- **ブランド改名 (jpintel → 税務会計AI / AutonoMath)** — Intel との著名商標衝突
  リスクを回避するため、user-facing 全面でリネーム。法人は Bookyou株式会社のまま。
- **¥3/req 完全従量モデル確定** — tier SKU / 階層プラン / 無料枠 SKU 等を完全廃止。
  匿名 50 req/月 per IP のみ無料。pricing UI から階層的な表記を削除。
- **freee 助成金AI 比較ページ追加** — `/compare/freee/` 含む 10 競合との honest
  comparison。13-15 軸の matrix + "when to choose us / them" を全 page に。
- **MCP 89 tools 公開 (default gates 74)** — 39 jpintel + 35 autonomath
  (V1 + メタデータ tools + 静的データセット tools + lifecycle/abstract/prerequisite/graph/rule_engine + 合成 tools 5)。
  protocol 2025-06-18 準拠、broken 3 tools は env-flag gated off。
- **OpenAPI 3.1 全 endpoint description 完成** — 111 paths すべてに summary +
  2-3 文 description + realistic example request/response。Stainless / Mintlify
  drop-in 可。
- **AutonoMath self-improvement loop ON** — examiner_feedback 8,189 件を 16,474
  annotation rows に変換、6 generic validation predicate 登録、provenance 4
  endpoint mount。
- **NTA 適格事業者 PDL v1.0 license bulk fill** — 87,251 rows に license 付与
  完了。NULL license ratio < 1% を達成。
- **e-Gov 法令 154 件本文インデックス + 9,484 件 catalog** — 本文ロードは継続中、
  法令名 resolver は 9,484 件全件で稼働。
- **Email-only trial signup** — magic-link で 14 日 / 200 req のカード不要試用。
  evaluator email を bounce 前に補足。

## 今後 3 ヶ月予定 (In Progress)

実装着手済み・優先度高。期日は best-effort、変動あり。

- **法令本文 9,484 件全件ロード完了** — 現在 154 件 indexed、残りを e-Gov 法令
  API V2 経由で順次取り込み。法改正検知 cron は既に稼働中、本文蓄積は進行中。
- **NTA 適格事業者 月次フル取り込み (4M rows)** — 現在 13,801 rows delta only。
  PDL v1.0 で API 再配布可確定済みなので、月次 bulk pipeline を確立。
- **入札 実データ拡充** — 362 rows → 数千 rows。schema 構築済み、
  NEXCO / JR / UR / 都道府県の現行入札を継続収集。
- **判例 実データ拡充** — 2,065 rows → 5,000+。知財高裁
  以外に最高裁 / 高裁の補助金関連判決を追加。
- **制度改正履歴 蓄積開始** — 現在 0 rows。cron で生成された差分の log を
  ためて、`/news/{YYYY}/{MM}/{DD}/{slug}.html` 生成 pipeline を稼働。
- **MCP server 公式 PyPI publish (autonomath-mcp v0.3.x)** — 現在 `dist/` に
  artifact あり、live publish は launch +24h grace 後。
- **dashboard 改善 (per-tool usage breakdown + billing history)** — bearer-auth
  済 user 向け。現在 `/v1/me/dashboard` mount 済み、UI 完成度を上げる。
- **5 言語 SDK サンプル拡充** — Python / TypeScript / Go / Ruby / curl。各
  3-5 use case の copy-paste recipe。
- **法令改正アラート ¥500/月 production 化** — 現在 monthly digest は無料、
  real-time paid 通知の Stripe metering を確立。
- **適格事業者の取消・失効 monitoring** — registered / revoked / expired を
  watchlist 登録した法人について Webhook 通知。

## 検討中 (Considering)

公開アイデア。コミットしていません。優先順位は変動します。

- **多言語対応の深化** — 現在 EN は thin layer。深い翻訳 (用語集 / pricing /
  glossary) を進めるか、JA に集中するか未確定。
- **MCP tool の deprecation 戦略** — 89 tools を 60 程度に絞る (重複統合)。
  external schema なので breaking change の影響が大きく、慎重に検討中。
- **Webhook subscription 機構** — alerts は email、API は polling のみ。
  HTTP webhook の push delivery 需要があれば。
- **gBizINFO 追加 facts 拡張** — corp.* 21 fields は取り込み済み、財務系
  fields (revenue / employees) を追加するかどうか。
- **法人番号 verification API (T-number 単独 lookup)** — `/v1/houjin/{number}`。
  現在は invoice_registrants 経由でしか引けない。
- **MCP プロンプト / チャート ライブラリ** — typical agent flow を MCP の
  `prompts` / `resources` 機能で配信。
- **partnership SDK (税理士事務所向け white-label)** — 現在 widget は単一
  endpoint embed、複数 tier の partner offering は検討段階。

## 取り組まないこと (Won't Do)

明示的な non-goals。リソース配分の透明性のため公開しています。

- **広告出稿** — Google Ads / X Ads / LinkedIn Ads は一切しない。100% organic
  acquisition (SEO / GEO / 直接の引用) で集客。
- **営業電話 / コールド outreach** — 飛び込み営業・cold email・cold DM はゼロ。
  inbound 経由のみ対応。
- **複数ドメイン展開** — `zeimu-kaikei.ai` 1 ドメインに集約。`autonomath.ai`
  等のサブブランドを別ドメインで増やすことはしない (内部識別子は維持)。
- **SaaS UI / ダッシュボード SaaS** — 価値は API / MCP / 静的 docs 経由で配信。
  polished SaaS UI ビルドは AI agents 単独では難しく、その方向の機能拡張は
  しない。dashboard は bearer-auth の最小限の usage / billing 表示のみ維持。
- **tier 制 SKU の復活** — Free tier / Starter / Pro / Enterprise は永久禁止。
  ¥3/req 完全従量 1 本のみ。anonymous 50/月だけが無料。
- **DPA / MSA / SOW の人手交渉** — solo + zero-touch なので個別契約調整は
  しない。標準 ToS / Privacy / 特商法のみ。
- **電話サポート / Slack Connect / 専用 onboarding call** — 全て self-service。
  解決しない場合のみ `info@bookyou.net` 1 系統。
- **多媒体 EC 広告運用 SaaS への pivot** — AutoNoMath EC は別線、当 product
  (税務会計AI) と混在させない。
- **特許出願 (A/B/C/D/E)** — 2026-04-13 に 5 特許全撤退決定済み。新たな
  特許出願は今後もしない方針。
- **商標登録** — Intel との著名商標衝突は rename で回避。商標出願の工数 /
  費用は取らない (2026-04-23 確定方針)。
- **農業 managed service / ブルーベリー栽培事業との結合** — それらは別線
  (内部 project)。当 product (税務会計AI) と混在させない。

---

## §52 / §72 / §1 の範囲

税務会計AI は **検索インデックス + 構造化データ API** であり、税理士法 §52
(税理士業務)、弁護士法 §72 (法律事務)、行政書士法 §1 (行政書士業務) に該当
する業務はおこないません。個別の税務相談・法律相談・申請代行が必要な場合は、
適切な士業 (税理士 / 弁護士 / 行政書士 / 社労士 / 中小企業診断士) にご相談
ください。`/advisors.html` に登録された認定支援機関 / 士業の紹介 marketplace
があります。

---

運営: [Bookyou株式会社](https://www.invoice-kohyo.nta.go.jp/regno-list/?T8010001213708)
(法人番号 T8010001213708)・代表 梅田茂利・[info@bookyou.net](mailto:info@bookyou.net)
