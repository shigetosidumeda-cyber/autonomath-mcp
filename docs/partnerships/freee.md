# Partnership — freee 会計

> **要約 (summary):** freee 会計 (国内 SMB 25 万社) の Marketplace に **jpcite MCP plugin** として申請。`AI assistant` カテゴリ。月次 ¥3/req メーター売上の **10% を referral fee** として freee に分配。¥0 営業 / self-serve only。

## ターゲットと規模 (Audience & ceiling)

- freee 会計 SMB 顧客: 約 250,000 社 (2026 Q1 公開データ)
- 想定到達率: 1% (= 2,500 社) × 月平均 30,000 req × ¥3 = **¥225,000,000 / 年 ARR 上限** (10-30% realized = ¥22.5M-67.5M / 年)
- 受注経路: freee Marketplace 内 self-serve。営業電話・個別契約は **永久 NG** (memory `feedback_organic_only_no_ads` / `feedback_zero_touch_solo`)

## 連携シナリオ (Use case)

freee 会計のユーザー (会計担当 / 経営者) が、**Claude Desktop** または **freee 会計内 AI assistant**から自然言語で:

```
> 「うちの今期使える税制と補助金の組み合わせを教えて。
>   業種は IT サービス、従業員 12 名、東京都港区。」
```

と質問すると、jpcite MCP server が:

1. `search_tax_incentives` で IT × SMB の税制 (賃上促進税制 / DX 投資促進税制 / 中小企業経営強化税制) を抽出
2. `search_programs` で東京都の併用可能補助金を抽出
3. `combined_compliance_check` で 181 排他ルールに照合
4. freee 会計の決算データから `target_employees` / `industry_jsic` を引いて **互換のあるもののみ** を返す

返却は出典 (e-Gov / 国税庁 / 経産省) 付き。

## MCP plugin 形式 (Integration form)

- freee Marketplace カテゴリ: **「AI アシスタント / 業務効率化」**
- 配布物: PyPI `autonomath-mcp` (既存) + freee 認証 wrapper (新規、`src/jpintel_mcp/integrations/freee.py` で OAuth2 受け取り → `target_employees` / `industry` を query parameter に注入)
- ユーザー導線: freee Marketplace → 「インストール」→ freee OAuth → jpcite が API key を発行 → Claude Desktop に server.json を配信
- **Plugin glue layer published at `sdk/freee-plugin/`** (MIT, stateless, ~250 LOC + tests). freee アプリストア に出す plugin 実装者はこの glue を vendor して `recommend(...)` を呼ぶだけで jpcite ¥3/req メーター API に接続できる。token (freee OAuth + jpcite API key) は plugin 実装者側で管理、Bookyou は預からない (`feedback_zero_touch_solo`)。

## 売上 split / referral

- 課金形態: **jpcite が直接ユーザー課金 (¥3/req)**。freee は決済を中継しない。
- referral fee: jpcite が freee に **月次 metered 売上の 10%** を支払う (Stripe Connect Transfer or 銀行振込)
- 計算式: `referral_fee = SUM(charged_requests_via_freee_referral_code) × ¥3 × 0.10`
- 月末締め / 翌月末払い、Stripe 適格請求書 (T8010001213708) 発行
- **business model check**: 「discount NG (¥3/req 固定)」は厳守。referral 経由ユーザーも **同じ ¥3/req** を支払う。10% は jpcite 側コストとして処理 — discount ではない (memory `project_autonomath_business_model`)

## 申請内容 (Application draft)

```
Partner program: freee Partner Program / Marketplace API Partner
URL (申請): https://corp.freee.co.jp/partnership/
URL (Marketplace 開発者): https://developer.freee.co.jp/

会社名: Bookyou 株式会社 (適格請求書発行事業者番号 T8010001213708)
代表者: 梅田茂利
連絡先: info@bookyou.net
製品名: jpcite
製品概要: 14,472 件の日本制度 (補助金 / 融資 / 税制 / 認定) を MCP サーバーで横断検索。
        freee 会計の決算データを context として、ユーザーの会計事務所 / SMB に
        最適な制度組合せを Claude / 自社 AI から自然言語で取得可能。
契約形態: Marketplace plugin (¥0 月額) + 従量 ¥3/req (税別) は jpcite が直接課金
referral 還元: 月次売上の 10% を freee に Stripe Connect Transfer で還元
法令対応: 適格請求書発行事業者 (T8010001213708) / 個人情報保護法 / 電帳法 対応済
```

## Timeline (T+30d)

| T+ | アクション | 担当 |
|----|-----------|------|
| T+0 | freee Developer Portal で Partner 申請 web form 送信 | self |
| T+7 | freee 側 review。技術質問が来たら docs URL で返信 | self |
| T+14 | OAuth2 client_id / client_secret 受領、`integrations/freee.py` 実装 | self |
| T+21 | Marketplace listing draft 提出 (logo は placeholder、本物は freee から OK 受領後) | self |
| T+30 | listing 公開、Stripe Connect で referral 払出 ready | self |

## 触れない (Out of scope)

- freee 会計のデータを **jpcite DB に保存しない** — pass-through query parameter として受け取り、即破棄 (privacy policy 4.2)
- freee の logo / 商標 は **法務 OK 取得後のみ** 使用 (memory `feedback_no_trademark_registration`)
- 専用 SLA / DPA 締結は **しない**。freee Marketplace の標準 ToS で運用

## 参考リンク

- freee Marketplace: https://app.secure.freee.co.jp/integrations
- freee Partner Program: https://corp.freee.co.jp/partnership/
- freee 会計 API リファレンス: https://developer.freee.co.jp/reference/accounting/
- 内部参照: [partner_referral_mechanism.md](../partner_referral_mechanism.md)
