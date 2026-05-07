# Partnership — SmartHR

> **要約 (summary):** SmartHR (60,000 社、人事 / 労務 SaaS) のダッシュボード内に **jpcite widget** を embed。雇用関係助成金 (キャリアアップ / 雇用調整 / 両立支援) の候補を社員データから自動抽出。¥3/billable unit metered。月次売上の 10% を SmartHR に referral 還元。

## ターゲットと規模

- SmartHR 顧客: 約 60,000 社 (2026 Q1)、累計 user 数 700 万人以上
- 想定到達率: 1.5% (= 900 社) × 月平均 22,000 req × ¥3 = **¥6,000,000 / 月 = ¥72M / 年 ARR 上限** (10-30% realized = ¥7.2M-21.6M / 年)
- 対象 audience: 社労士 / 人事担当 / 経営者
- 受注経路: SmartHR App Store (公式 marketplace) の self-serve embed

## 連携シナリオ

SmartHR 上で人事 / 労務担当が、自社の従業員リストを見ながら:

```
> 「キャリアアップ助成金 (正社員化コース) で対象になる社員は誰?
>   申請に必要な要件と、併用可能な助成金は?」
```

→ jpcite widget が:

1. SmartHR の従業員データから `employment_type` (正社員 / 契約 / パート) / `employment_start_date` / `industry_jsic` を読取
2. `search_programs` で **雇用関係助成金** カテゴリ (厚労省所管 約 80 制度) を絞込
3. 各社員に対し「対象 / 非対象 / 期限切れ」を flagging
4. 排他チェック: キャリアアップ助成金 × トライアル雇用助成金 の **重複申請 NG** ルールで自動除外
5. 申請に必要な書類リスト (賃金台帳 / 雇用契約書 / 出勤簿) を SmartHR の保管書類と紐付け

返却は厚労省 e-Gov 出典 + リーフレット PDF URL 付き。

## widget 形式 (HR ダッシュボード embed)

- 配布物: SmartHR App Store 用 `manifest.yaml` + iframe 配信 `https://widget.jpcite.com/smarthr.html`
- 認証: SmartHR OAuth2 (employee:read / employment:read scope のみ)
- 表示位置: SmartHR ダッシュボードの「カスタマイズ widget」枠 (人事担当向け管理画面)
- 配色 / 文字 token: SmartHR デザイントークンに従い、**SmartHR の look & feel に同化**
- mobile: SmartHR モバイルアプリ内 webview でも動作

```yaml
# manifest.yaml (概略)
name: jpcite — 雇用関係助成金候補
version: 0.1.0
display:
  category: HR / 助成金
  description: 従業員データから雇用関係助成金 80 制度の候補を抽出
oauth:
  scopes:
    - employee:read
    - employment:read
embed:
  type: iframe
  url: https://widget.jpcite.com/smarthr.html
  height: 480
  responsive: true
referral:
  partner_code: smarthr
  share: 0.10
```

## 売上 split

| 項目 | 金額 / 比率 |
|------|------------|
| ユーザー単価 | ¥3 / unit (税別) |
| SmartHR referral | metered 売上の 10% |
| 払出 cycle | 月末締め、翌月末日 Stripe Connect Transfer |
| 最低金額 | なし |

discount NG。referral 経由でも ¥3/billable unit 固定。

## 申請内容

```
Partner: 株式会社 SmartHR — App Store / Tech Partner Program
URL (申請): https://smarthr.jp/partner/
URL (Developer): https://developer.smarthr.jp/

会社名: Bookyou 株式会社 (適格請求書発行事業者番号 T8010001213708)
代表者: 梅田茂利
連絡先: info@bookyou.net
連携形式: SmartHR App Store widget (iframe embed)
データ取扱: pass-through、jpcite は従業員 PII を保存しない
referral 還元: metered 売上の 10% を月次振込
法令: 個人情報保護法 (employee:read scope に限定) / 労基法 / 雇用保険法 整合
```

## Timeline (T+90d、SmartHR の review 期間 + 法務待ち想定)

| T+ | アクション |
|----|-----------|
| T+0 | SmartHR Tech Partner 申請 |
| T+14 | OAuth client 受領、widget スタブ実装 |
| T+30 | データ取扱に関する SmartHR security review |
| T+60 | App Store listing draft 提出 |
| T+90 | listing 公開、referral 仕組み稼動 |

## 触れない

- 従業員氏名 / マイナンバー / 給与額は **jpcite に送信しない** — 雇用区分 / 在籍期間 / 業種のみ
- DPA / 個別契約は **締結しない**。SmartHR App Store の標準 ToS で運用 (memory `feedback_zero_touch_solo`)
- SmartHR の logo は法務 OK 取得後のみ
- 「SmartHR 認定パートナー」呼称は SmartHR から正式付与あるまで使わない (景表法対応)

## 参考リンク

- SmartHR App Store: https://app.smarthr.jp/store
- SmartHR Tech Partner: https://smarthr.jp/partner/
- SmartHR Open API: https://developer.smarthr.jp/api/
- 内部参照: [partner_referral_mechanism.md](../partner_referral_mechanism.md)
