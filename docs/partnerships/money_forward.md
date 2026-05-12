# Partnership — Money Forward (MF Cloud)

> **要約 (summary):** Money Forward Cloud (国内中堅企業中心、20 万社) の API integration として **jpcite REST + MCP** を組込。ME (経費精算 / 会計) ユーザーが自社の科目データを context に補助金 / 税制を発見。¥3/billable unit metered。月次売上の 10% を MF に referral 還元。

## ターゲットと規模

- MF Cloud 顧客: 約 200,000 社 (会計 / 給与 / 経費の合算、2026 Q1)
- 想定到達率: 0.75% (= 1,500 社) × 月平均 33,000 req × ¥3 = **年 ¥150,000,000 規模の流通額上限 (historical "年 ARR 上限" 表現)**、10-30% realized = ¥15M-45M / 年。per-顧客 節約額は [cost saving examples](../canonical/cost_saving_examples.md) 参照。
- 受注経路: MF Cloud Marketplace + ME パートナー API。営業電話 NG、self-serve のみ

## 連携シナリオ

MF Cloud 給与 / 会計を使う社労士 / 経理 が自社の AI チャット (Claude / Cursor / 社内 RAG) で:

```
> 「弊社 (建設業 / 従業員 32 名 / 京都府宇治市) で
>   今期使える助成金と融資、行政処分のリスクを見たい。」
```

→ jpcite が:

1. MF API から `industry_jsic` (建設業 06) / `target_employees` / `region_pref` を取得
2. `search_programs` (建設業 × 京都) + `search_loans_am` (担保 / 個人保証 / 第三者保証 三軸) + `check_enforcement_am` (法人番号で行政処分歴 5 年)
3. `combined_compliance_check` で **電帳法 / インボイス / 雇用保険** の整合性検証
4. MF Cloud の損益データを参照して「申請書類で必要な前年売上 / 雇用人数」を自動代入

## API integration 形式

- 配布: jpcite REST `/v1/programs/search` + MCP server (既存)
- MF 側統合点: **MF クラウド連携 API** (`https://expense-api.moneyforward.com/`) の partner 登録
- 認証: OAuth2 (MF) + jpcite API key (X-API-Key)
- データ授受: pass-through (MF 顧客データは jpcite DB に **保存しない**)

## 売上 split

| 項目 | 金額 / 比率 |
|------|------------|
| ユーザー単価 | ¥3 / unit (税別、税込 ¥3.30) |
| MF referral fee | metered 売上の 10% |
| 払出 cycle | 月末締め、翌月末日 Stripe Connect Transfer |
| 適格請求書 | T8010001213708 で jpcite が MF 宛に発行 |
| 最低金額 | なし (MF referral 経由で 0 req の月は ¥0 払出) |

discount は **しない**: referral 経由でも ¥3/billable unit 固定 (memory `project_autonomath_business_model`)。

## 申請内容

```
Partner: Money Forward, Inc. — Partner Program (MF Cloud Connect)
URL (申請): https://biz.moneyforward.com/partner/
URL (Developer): https://corp.moneyforward.com/partner/cloud/

会社名: Bookyou 株式会社 (適格請求書発行事業者番号 T8010001213708)
代表者: 梅田茂利
連絡先: info@bookyou.net
連携形式: API integration (REST) + MCP plugin (Claude Desktop / Cursor から呼出)
配布: PyPI `autonomath-mcp` 0.2.0 (既存) — MF からは追加コード不要
referral 還元: metered 売上の 10% を月次振込
法令: 電帳法対応 (法令第 7 条 真実性・可視性) を jpcite 自身でも遵守
データ: pass-through、jpcite は MF 顧客データを保存しない (privacy policy)
```

## Timeline (T+30d)

| T+ | アクション |
|----|-----------|
| T+0 | MF Cloud Connect Partner 申請 form 送信 |
| T+10 | MF 側 review、技術担当との非同期 Q&A (email のみ、call なし) |
| T+20 | OAuth client 受領、`integrations/moneyforward.py` 実装 |
| T+30 | listing 公開、Stripe Connect で payout ready |

## 触れない

- 専用 SLA / DPA / Slack Connect は **設定しない** (memory `feedback_zero_touch_solo`)
- MF の logo は法務 OK まで placeholder
- MF の決算データを jpcite DB に保存しない
- 個別契約書 / 紙押印は永久 NG

## 参考リンク

- MF Cloud Marketplace: https://biz.moneyforward.com/marketplace/
- MF Cloud Connect Partner: https://corp.moneyforward.com/partner/cloud/
- MF Developer: https://moneyforward.com/developer
- 内部参照: [partner_referral_mechanism.md](../partner_referral_mechanism.md)
