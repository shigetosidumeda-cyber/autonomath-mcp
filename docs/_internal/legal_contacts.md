# Legal Contacts — AutonoMath / Bookyou株式会社

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

> Solo + zero-touch (`feedback_zero_touch_solo`)。launch (2026-05-06) 時点で
> 顧問弁護士・顧問税理士は **未契約**。一次窓口は operator 自身
> (info@bookyou.net)。incident 発生時のみ ad-hoc に外部 spot 委任する想定。
> このファイルは launch 後も「契約したら row を追加」する append-only ledger。

参照 SOP: [`breach_notification_sop.md`](./breach_notification_sop.md) §9。

---

## 1. Operator (一次窓口、24/7)

| 役割 | 氏名 | 連絡 | 備考 |
|---|---|---|---|
| 代表者 / data controller | 梅田茂利 (Bookyou株式会社) | info@bookyou.net | APPI §26 通知、特商法 §32 表示、Stripe ToS 全責任。代替なし (operator_succession_runbook.md 参照) |

---

## 2. Retained legal counsel (未契約)

launch 前は ad-hoc spot 委任で運用。incident 発生時のみ下記候補から選定:

| 区分 | 候補 | 検討理由 | 契約状態 |
|---|---|---|---|
| 弁護士 (IT・個人情報) | 都内 IT 法務系事務所 (TBD) | APPI §26 重大事故、開示請求、利用規約紛争 | 未契約 (incident まで pending) |
| 弁護士 (景表法・特商法) | 上記と同一窓口で兼任予定 | landing copy / pricing 表示の事前 review | 未契約 |
| 司法書士 | (TBD) | 商業登記変更 (本店・代表) のみ。launch 時点で必要なし | 未契約 |
| 税理士 / 公認会計士 | (TBD) | 法人決算 (Bookyou株式会社、決算期 TBD)、JCT 適格事業者 (T8010001213708) 申告 | 未契約 (初決算期前に契約予定) |
| 社労士 | (TBD) | 36協定 launch gate 解除 (`saburoku_kyotei_gate_decision_2026-04-25.md`) 時のみ必要 | 未契約 (gate 解除しない限り不要) |

**契約したら**: 上記表の「契約状態」を「契約済 (yyyy-mm-dd)」に更新し、retainer 額・連絡 channel・委任範囲を本ファイル末尾に append。

---

## 3. Regulators / 公的窓口 (顧客 incident 時)

### 個人情報漏えい (APPI)

- **個人情報保護委員会 (PPC)** — Personal Information Protection Commission
  - 代表: 03-6457-9849
  - 漏えい等報告: https://www.ppc.go.jp/personalinfo/legal/leakAction/
  - 一般窓口: https://www.ppc.go.jp/personal/contact/
  - 報告様式: 速報 = 発覚から 3-5日以内、確報 = 30日以内 (要配慮個人情報含む or 不正アクセス起因 = 60日以内)
  - 詳細手順: [`breach_notification_sop.md`](./breach_notification_sop.md) §4

### 反社会的勢力 / 不当要求 / 強要 (incident 時のみ)

- **警視庁 暴力団排除条例 相談窓口**
  - 代表: 03-3581-4321 (警視庁本部)
  - 暴力相談センター: 03-3580-2222
  - 全国共通 暴追ホットライン: **0120-893-240** (フリーダイヤル、平日 9:00-17:30)
  - 都道府県警の暴力団対策課にも個別窓口あり (https://www.npa.go.jp/sosikihanzai/boutaikoku/)
  - 用途: 不当な金銭要求 / 名誉毀損目的の review 連投 / 法人代表者を装う恫喝メール等

### 消費者契約・特商法 (B2C 限定だが備忘)

- **国民生活センター** — 188 (消費者ホットライン、operator は受信側)
- **消費者庁 表示対策課** — 03-3507-8800 (景表法、operator は受信側)
- 注: AutonoMath は B2B API のため §63 総額表示義務の対象外。それでも顧客から消費者庁経由で問い合わせが来た場合の備忘。

### 知財 (商標衝突など)

- **特許庁 ユーザサポート課** — 03-3581-1101
  - 商標衝突は出願しない方針 (`feedback_no_trademark_registration`)。intel 衝突は rename で回避済 (AutonoMath ブランド)。
  - incident 時のみ問い合わせ (申立て受領 / 警告書受領)。

---

## 4. Vendor security/legal desks (incident 時のみ)

正本は [`breach_notification_sop.md`](./breach_notification_sop.md) §9。ここでは duplicate 最小化のため reference のみ:

- Stripe / Postmark / Cloudflare / Fly.io / Sentry の各 security@ アドレスは breach SOP §9 を参照。
- Anthropic (Claude API は **顧客側で呼ぶ**、`feedback_autonomath_no_api_use` のため operator は契約者ではない) → 通知不要。

---

## 5. EU / 海外 (現状 out of scope)

- AutonoMath は日本国内 B2B API、サイト copy は日本語のみ (EN ページは技術者向け補助)。GDPR の establishment は無し。
- 仮に EU からの登録が無視できない量 (≥ 5%/月) になったら下記を契約:
  - **Irish DPC** (デフォルト lead authority for non-EU controllers): https://www.dataprotection.ie/en/contact/breach-notification
  - EU representative (Article 27 GDPR): TBD — solo 構造上 representative service を spot 契約する想定

---

## 6. Update protocol

- 新たに弁護士・税理士等を retain したら **§2 を編集 + §1 の Last reviewed 更新**。
- 公的窓口の電話番号 / URL に変更があった場合 (年次 audit で確認):
  1. 一次ソース (PPC / 警察庁 / 国センの公式 site) で current 値を確認
  2. 本ファイル + `breach_notification_sop.md` §9 の両方を同時更新
  3. drift 防止: 番号は **両方に書かず**、本ファイル → SOP は reference のみ にしたい (将来的 refactor task)
- 契約解除 / 担当者交代時: 旧 row を残して strikethrough、新 row を append (incident 後の経緯追跡のため)。

---

## 7. 関連 doc

- [`breach_notification_sop.md`](./breach_notification_sop.md) — APPI §26 通知 SOP (本ファイルの参照元)
- [`incident_runbook.md`](./incident_runbook.md) — 障害対応 (a)-(f)
- [`operator_succession_runbook.md`](./operator_succession_runbook.md) — 死亡 / 長期不能時 successor 引継 (本ファイルが最低限の external contact になる)
- [`launch_compliance_checklist.md`](./launch_compliance_checklist.md) — 法務 gate 全体
