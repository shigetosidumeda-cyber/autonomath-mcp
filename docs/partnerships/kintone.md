# Partnership — kintone (Cybozu Marketplace)

> **要約 (summary):** kintone Marketplace に **jpcite JS plugin** を出品。kintone レコード上で「補助金候補」テーブルを inline 表示。kintone 顧客 (Cybozu 公開ベースで 30,000 社、ライセンス換算 18.75 万 user 想定) を self-serve で取込。¥3/billable unit metered。月次売上の 10% を Cybozu に referral 還元。

## ターゲットと規模

- kintone 導入企業: 約 30,000 社 (2025 Cybozu IR、社員 6 人以上中心)
- ライセンス user 数想定: 約 187,500 (1 社平均 6.25 user)。20% AI 活用層を置いた場合の上限感は **37,500 user × 月平均 30,000 billable units × ¥3** で試算し、実売上予測ではなく市場規模の上限シナリオとして扱う。
- 参考シナリオ: 到達率 5% (= 1,875 user) × 月平均 30,000 billable units × ¥3 = **月 ¥18,750,000 = 年 ¥225M 規模の流通額上限 (historical "年 ARR 上限" 表現)**。公開時は実売上見込みではなく、利用頻度に依存する上限モデルとして説明する。per-user 節約額は [cost saving examples](../canonical/cost_saving_examples.md) 参照。
- 受注経路: kintone Marketplace の self-serve 出品。営業 / 個別契約 NG

## 連携シナリオ

kintone で「顧客マスタ」「案件管理」アプリを運用する SMB 経営者 / 営業担当が、レコード詳細画面で:

- レコードの **業種フィールド (industry_jsic)** + **本社所在地 (region_pref)** + **従業員数 (target_employees)** を読取
- jpcite plugin が `/v1/programs/search` を叩き、上位 10 件の補助金 / 税制 / 融資候補を inline テーブル表示
- 各候補に「出典 URL (e-Gov / 経産省 / JFC)」「適用条件チェック (排他ルール 181 件と照合)」「採択率 (case_studies から逆引き)」 を併記
- ユーザーが「気になる」をクリックすると、kintone の **メモフィールド** に候補 ID を保存 (1 click で応募準備テンプレ生成)

## plugin 形式 (JS embed)

- 配布物: kintone Marketplace 用 `.zip` (`manifest.json` + `js/desktop.js` + `css/desktop.css`)
- 規模: 約 12 KB (gzip)、外部 CDN 依存なし
- 認証: kintone 管理者が jpcite の **X-API-Key** を plugin 設定画面で入力 → kintone レコードから query が走る
- フィールド mapping: kintone 側で「業種 / 所在地 / 従業員数」フィールドをドロップダウンで jpcite schema にひも付け
- レンダリング: kintone レコード詳細ページの「ヘッダー追加領域」(`kintone.events.on('app.record.detail.show', ...)`) に inline table 描画

```javascript
// js/desktop.js (概略、実装は src/jpintel_mcp/integrations/kintone/ に置く)
kintone.events.on('app.record.detail.show', async (event) => {
  const record = event.record;
  const config = kintone.plugin.app.getConfig(PLUGIN_ID);
  const params = new URLSearchParams({
    industry_jsic: record[config.industryField].value,
    region_pref:    record[config.regionField].value,
    target_employees: record[config.employeesField].value,
    referral_code: 'kintone-' + kintone.app.getId(),  // referral 紐付け
  });
  const r = await fetch(`https://api.jpcite.com/v1/programs/search?${params}`, {
    headers: { 'X-API-Key': config.apiKey }
  });
  const { items } = await r.json();
  renderTable(items);
  return event;
});
```

## 売上 split

| 項目 | 金額 / 比率 |
|------|------------|
| ユーザー単価 | ¥3 / unit (税別) |
| Cybozu / kintone Marketplace referral | metered 売上の 10% |
| 払出 cycle | 月末締め、翌月末日 銀行振込 (Cybozu が Stripe Connect 不要なら振込) |
| 最低金額 | なし |

discount NG。referral 経由でも ¥3/billable unit 固定 (memory)。

## 申請内容

```
Partner: Cybozu, Inc. — kintone Marketplace 開発者プログラム
URL (申請): https://kintone-sol.cybozu.co.jp/
URL (developer): https://developer.cybozu.io/hc/ja

会社名: Bookyou 株式会社 (適格請求書発行事業者番号 T8010001213708)
代表者: 梅田茂利
連絡先: info@bookyou.net
plugin 名: jpcite — 補助金 / 税制候補 inline 表示
plugin 形式: JS plugin (.zip)、kintone v5.x.x 以上、PC + モバイル対応
カテゴリ: 業務支援 / AI 連携
referral 還元: metered 売上の 10%
法令: 適格請求書 / 個情法 / 電帳法 対応
```

## Timeline (T+60d、kintone 審査が 1 ヶ月想定)

| T+ | アクション |
|----|-----------|
| T+0 | kintone Marketplace 開発者登録 |
| T+10 | plugin (.zip) 提出、test 環境で動作確認 |
| T+20 | Cybozu 側 1st review (security / fields) |
| T+40 | listing draft 提出 (logo は placeholder) |
| T+60 | listing 公開、referral 仕組み稼動 |

## 触れない

- kintone 内のレコード本体を **jpcite サーバーに送信しない** — 業種 / 所在地 / 従業員数 の **3 フィールドのみ** を query parameter として送り、即破棄
- 専用 SLA / DPA は **設定しない**
- Cybozu / kintone の logo は法務 OK 受領後のみ
- 商標出願はしない (memory `feedback_no_trademark_registration`)

## 参考リンク

- kintone Marketplace: https://kintone-sol.cybozu.co.jp/
- kintone JS API: https://cybozu.dev/ja/kintone/docs/js-api/
- plugin 仕様: https://cybozu.dev/ja/kintone/docs/plug-in/
- 内部参照: [partner_referral_mechanism.md](../partner_referral_mechanism.md)
