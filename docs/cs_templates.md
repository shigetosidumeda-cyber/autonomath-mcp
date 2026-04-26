# Customer Support Templates (Operator-Only)

このファイルは operator (info@bookyou.net) 専用の reply template 集です。mkdocs build からは exclude 済み。公開禁止。

- 想定: solo + zero-touch (CS hire なし、email-only)
- 目的: 同一質問への返信を 5 分以内に template ベースで返す
- 強調表現 (必ず / 絶対 / 保証) は INV-22 違反のため使わない
- 営業 / 紹介 / DPA / 専用 Slack / 年契約 / SLA 99.9% は提案しない
- 全 reply に footer 推奨:

  > Bookyou株式会社 (T8010001213708) - info@bookyou.net

---

## A. FAQ reply (5 件)

### A-1. 「¥3 にすると思ったより高い、安くならない?」

```
件名: AutonoMath 料金体系について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

ご質問の bulk discount につきまして、現状のご案内です。

- AutonoMath は ¥3/request (税込 ¥3.30) の完全従量制で運用しております
- 数量割引・年契約割引・seat ライセンスは設けておりません
- 理由は 100% organic acquisition + solo ops の構造上、個別交渉に
  リソースを割けない点と、価格を 1 本化することで請求の透明性を
  維持するためです

一方、実コストは Cache 設計により大きく低減できます。

- L0-L4 cache (docs/cache_architecture.md 参照) で hit ratio 80% 程度
- 同一 query が 1 ヶ月以内に再呼ばれた場合は cache hit となり、料金は
  発生しません (¥0)
- 結果として、月間想定 reqs に対する実質単価はワークロード次第で
  ¥0.6 - ¥1.5 程度に下がるケースが多くなっています

実際の usage が想定と乖離している場合は、お手数ですが
dashboard の usage breakdown をお送りいただけますと、cache hit 率を
お見立ていたします。

よろしくお願いいたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### A-2. 「Free 50 req/月 使い切った後、paid に切替方法?」

```
件名: 課金開始の手順について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

ご質問の paid 切替につきまして、ご案内いたします。

AutonoMath は tier (プラン) を切り替える仕組みではなく、
カード登録後はそのまま metered 課金に移行いたします。

手順:

1. https://autonomath.ai/dashboard へログイン
2. 「お支払い情報」より Stripe の card 登録
3. 登録完了後、その月の 51 リクエスト目以降が ¥3/request
   (税込 ¥3.30) で課金されます
4. 月初 (JST 00:00) に Free 枠 50 req は再度付与されます

Free 枠は card 登録後も維持され、課金対象は 51 req 目以降のみです。
解約はカード解除のみで完了します (年契約・違約金・最低消費はありません)。

不明点がありましたら、ご返信ください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### A-3. 「データソース信頼性?」

```
件名: データソースの取り扱いについて (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

データソースの方針につきまして、ご案内いたします。

- 一次資料 only: 各省庁・都道府県・日本政策金融公庫等の公式ページ
  または公示文書のみを収録対象としています
- aggregator ban: 民間の補助金まとめサイト (例: noukaweb,
  hojyokin-portal, biz.stayway 等) は source_url から除外しています
- 全件メタ付与: 各 program に source_url + source_fetched_at
  (出典取得日時) を記録し、API レスポンスに含めて返却します
- 出典取得日時の意味: source_fetched_at は「最終確認日」ではなく
  「当方が出典 URL を取得した日時」です。現時点で URL が live で
  あることは別途 nightly liveness scan (refresh_sources.py) で確認
  しています

詳細は docs/exclusions.md および docs/confidence_methodology.md を
ご参照ください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### A-4. 「個人情報 (法人番号) は redaction されている?」

```
件名: PII の取り扱いについて (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

PII redaction の運用につきまして、ご案内いたします。

- INV-21 に基づき、query log の保存前に PII redaction を適用しています
- 対象: 法人番号 (13 桁), 個人マイナンバー候補 (12 桁),
  メールアドレス, 電話番号 (E.164 / 国内表記), クレジットカード番号
  正規表現候補
- 保存先 table: query_log_v2 (redact 済み, 90 日 rolling 保持)
- API key 自体は SHA-256 + PEPPER でハッシュ化保存
- 法人番号を query で送られた場合: 検索時はメモリ上のみで使用し、
  log 書き込み時に [REDACTED:CORP_NUM] へ置換します

詳細は compliance/privacy_policy.md および
compliance/data_governance.md をご参照ください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### A-5. 「日本以外の制度対応?」

```
件名: 海外制度の対応について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

国際展開のロードマップにつきまして、ご案内いたします。

- 現状: 日本国内の制度 (補助金・融資・税制・認定) のみが対象です
- V4 English (T+150 日予定): 日本国内制度の英語インターフェース版を
  予定しています。データ自体は引き続き日本制度です
- 海外制度本体への展開: 現時点では未定です。Singapore IRAS や
  US SBA 等の制度カバレッジは検討対象に入っていますが、launch
  済みではなく時期も確定していません

詳細は docs/english_v4_plan.md をご参照ください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

## B. Refund / dispute (5 件)

### B-1. Stripe dispute received (通常返答)

```
件名: ご請求についてのお問い合わせ (Re: dispute)

ご連絡ありがとうございます。AutonoMath の梅田です。

Stripe 経由でお申し出いただいた dispute を確認いたしました。

- 当方からは Stripe 規定の 7 日以内に証憑を提出いたします
- 提出予定証憑: usage_events log (ご利用日時 / endpoint / cache hit
  フラグ / 課金額), Stripe meter ledger, 請求書 PDF
- カード会社による最終判定までにお時間をいただく場合があります
  (通常 30-75 日)
- ご利用内容に事実誤認がある場合は、本メールへご返信ください。
  内容を確認のうえ、Stripe dispute 取下げと当方からの直接返金 (¥-credit)
  でも対応可能です

ご不便をおかけしております。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### B-2. False charge claim (使った覚えがない)

```
件名: ご利用内容の確認について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

ご請求への懸念につきまして、確認結果をお送りいたします。

- 該当期間 (YYYY-MM-DD - YYYY-MM-DD) の usage_events を確認しました
- 件数: NN 件 / うち課金対象: NN 件 (Free 50 超過分)
- 主な呼出元 IP: x.x.x.x (XX 件)
- API key 末尾: ...XXXX
- 添付: usage_events_extract.csv (本メールに添付)

身に覚えのないご利用と判断される場合、選択肢:

1. API key rotate (dashboard より即時可能、漏洩時の標準対応)
2. ¥-credit 返金 (該当 NN 件分 ¥XXX、次回請求から差引)
3. Stripe dispute 継続

ご希望の対応をお知らせください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### B-3. Service interruption (落ちていた間も課金されている)

```
件名: 障害期間のご請求について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

障害期間の取り扱いにつきまして、ご案内いたします。

- 該当期間: YYYY-MM-DD HH:MM - HH:MM JST (XX 分)
- 公開 SLA は 99.5%/月 です。月間 ダウンタイム許容は約 3 時間 36 分
  となります
- 今回の XX 分はその範囲内のため、SLA 違反には該当しません
- 一方、ご請求への影響として、障害時間帯に発生した usage は
  5xx 応答となっており、課金対象から自動除外されています
  (200/206 のみ課金) → 追加返金の対象は通常生じません
- 念のため該当期間の課金件数を確認しましたところ、NN 件 / ¥XXX
  でした。ご納得いただけない場合は ¥-credit でも対応いたします

詳細は docs/sla.md をご参照ください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### B-4. cap_reached 後の請求 (上限あると思っていた)

```
件名: 利用上限 (cap) の設定について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

cap (利用上限) の仕様につきまして、ご案内いたします。

- AutonoMath の既定値は cap = NULL (上限なし) です
- これは「Free 50 を超えた分は上限なく metered 課金される」状態を
  意味します
- 上限を設けたい場合は、dashboard の Self-cap 機能で月次の
  最大課金額 (¥) または最大 reqs 数を設定いただけます
- 設定値到達後は 429 Too Many Requests を返却し、課金は停止します
  (翌月初に再起動)

今月分のご請求につきまして:

- 該当期間の課金額: ¥XXX (NN 件)
- ご事情を考慮し、初回に限り ¥-credit 対応も可能です

来月以降の Self-cap 設定をおすすめいたします。手順は
dashboard_guide.md をご参照ください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### B-5. Duplicate charge (二重請求)

```
件名: 二重請求のご指摘について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

ご指摘いただいた二重請求につきまして、確認結果をご報告します。

- 確認対象: Stripe Charge ID ch_XXX / ch_YYY
- ledger 突合結果: [パターンA] 同一 charge の retry ではなく別 charge
  と判定 / [パターンB] retry による重複と判定
- usage_events dedupe: idempotency_key で重複呼出は 1 件として
  集計されています。API 呼出側の重複ではなく billing 側の重複です

(パターン B の場合の追記)
重複分 ¥XXX を本日 Stripe より返金処理いたしました。
カード会社の都合で実際の入金まで 5-10 営業日かかる場合があります。
ご不便をおかけしました。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

## C. Outage / incident comms (5 件)

### C-1. Planned maintenance pre-notice (24h 前)

```
件名: [予定] AutonoMath メンテナンス (YYYY-MM-DD HH:MM JST)

AutonoMath をご利用いただきありがとうございます。

下記の通り予定メンテナンスを実施いたします。

- 日時: YYYY-MM-DD HH:MM - HH:MM JST (約 XX 分)
- 影響: API / MCP server 全体が短時間停止する可能性があります
- 内容: SQLite migration / Fly.io machine 再起動
- 課金: 停止期間中の 5xx は課金対象外です

復旧後 https://status.autonomath.ai に完了通知を掲載します。

ご不便をおかけしますが、ご理解のほどよろしくお願いいたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### C-2. Unplanned outage post-mortem (1h 経過時点での暫定通知)

```
件名: [障害] AutonoMath API 障害のご報告 (YYYY-MM-DD)

AutonoMath をご利用の皆様

下記の障害が発生したことをご報告いたします。

- 検知時刻: YYYY-MM-DD HH:MM JST
- 復旧時刻: YYYY-MM-DD HH:MM JST (合計 XX 分)
- 影響範囲: /v1/* API 全 endpoint / MCP server (一部 / 全体)
- 症状: 5xx 応答、または response time 30s 超
- 暫定原因: (例) Fly.io Tokyo region machine の再起動失敗
- 課金: 障害期間中の 5xx は課金対象から除外済み
- 恒久対策と詳細 RCA: 7 営業日以内に
  status.autonomath.ai/incidents/YYYY-MM-DD に掲載予定

ご不便をおかけしました。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### C-3. Data corruption restoration (DB 破損 → backup 復旧)

```
件名: [障害] AutonoMath DB 復旧のご報告 (YYYY-MM-DD)

AutonoMath をご利用の皆様

YYYY-MM-DD HH:MM JST 頃、jpintel.db (programs テーブル) で
データ不整合を検知いたしました。下記の通り対応いたしました。

- 検知方法: invariant_check (excluded=0 件数の急激な減少)
- 復旧方法: 直近の S3 backup (YYYY-MM-DD HH:MM JST 時点) からリストア
- 復旧時点でのデータ: 検知の XX 時間前までの状態に戻しています
- 影響: 復旧前に実施したデータ追加 (NN 件) は再投入が必要となります
- 課金: 不整合期間中に発生した 200 応答のうち、誤データを含む
  可能性のあるものを Stripe meter から取消処理しました (¥-credit XXX)
- 恒久対策: invariant_check の閾値見直しと、ingest 時の
  pre-write snapshot 自動取得を追加いたしました

詳細は docs/disaster_recovery.md (operator 向け) に基づき進めています。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### C-4. PII leak emergency (緊急通知)

```
件名: [重要] 個人情報インシデントのご報告 (YYYY-MM-DD)

AutonoMath をご利用の皆様

YYYY-MM-DD HH:MM JST、当方の運用上の不備により、一部のお客様の
情報が意図しない範囲に閲覧可能な状態となっていたことを
確認いたしました。事実関係を下記の通りご報告いたします。

- 漏洩可能性のある項目: メールアドレス / API key 末尾 4 桁 /
  ご請求金額 (法人番号・カード番号は対象外)
- 影響規模: NN 件 (お客様への個別通知を別途送付済み)
- 期間: YYYY-MM-DD HH:MM - YYYY-MM-DD HH:MM JST
- 検知後の対応:
  - 漏洩経路の即時遮断 (HH:MM JST)
  - 影響を受けた API key の rotate を強制 (HH:MM JST)
  - 個人情報保護委員会への速報を実施
- 恒久対策: redaction layer の二重化、access log のレビュー強化

ご不便と不安をおかけしましたこと、深くお詫び申し上げます。
追加情報・ご質問は本メールへ直接ご返信ください。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### C-5. PEPPER rotation (API key hash 用 secret の rotate)

```
件名: [予定] API key 検証 secret (PEPPER) ローテーションについて

AutonoMath をご利用の皆様

セキュリティ運用の一環として、下記の通り API key 検証用の
PEPPER ローテーションを実施いたします。

- 実施日: YYYY-MM-DD HH:MM JST
- 影響: なし (お客様側の API key 値は変更されません)
- 仕組み: 当方サーバ側のハッシュ計算 secret のみが入れ替わります。
  rotation 中は旧 PEPPER と新 PEPPER の両方で検証する dual-verify
  期間 (24 時間) を設けています
- お客様側で必要なご対応: ありません

不安なくご利用を継続いただけますが、念のためご通知いたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

## D. Data correction (制度情報誤り) (5 件)

### D-1. 誤情報指摘 → 確認・curate・反映

```
件名: ご指摘いただいた制度情報について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

ご指摘いただいた制度情報につきまして、下記の通り対応いたします。

- 対象 program ID: prog_XXX
- ご指摘内容: (例) 補助率が 1/2 ではなく 2/3 が正しい
- 対応:
  1. 一次資料 (省庁公示 / 募集要項 PDF) で確認
  2. 確認できた場合は次回 ingest cycle (24-48h 以内) で反映
  3. 確認できない / 一次資料の記載が異なる場合は別途ご連絡
- 反映後は source_url + source_fetched_at が新しい日時に更新されます

確認結果は本メールへ追って返信いたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### D-2. source_url dead link

```
件名: source_url リンク切れのご報告について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

source_url の dead link 報告、ありがとうございます。

- 対象 program ID: prog_XXX
- 確認結果: (404 / domain 失効 / リダイレクト先が変更)
- 対応:
  - nightly liveness scan (refresh_sources.py) で同状態を検知済み
  - 後継 URL を web archive または同省庁の現行ページから探索のうえ、
    24 時間以内に置換予定です
  - 後継が見つからない場合は当該 program を tier='X' (quarantine) へ
    移動し、検索結果から除外します

別の制度を引き続きご利用いただけますと幸いです。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### D-3. Tier 異議 (tier 'X' 不当 quarantine の異議)

```
件名: Tier 判定へのご異議について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

Tier 判定へのご異議、ありがとうございます。

- 対象 program ID: prog_XXX (現状 tier='X' = quarantine)
- 判定根拠: source_url 失効 / 公示期限切れ / 一次資料との不整合
- ご指摘内容: (例) 当該制度は現在も募集中である
- 対応:
  1. ご教示いただいた一次資料 URL を確認
  2. 内容が確認でき、判定根拠の不在が立証できた場合は tier を
     S/A/B/C のいずれかに復帰
  3. 反映は次回 ingest cycle (24-48h 以内)

ご教示いただいた URL またはスクリーンショットを返信に添付いただける
と確認が早く済みます。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### D-4. 排他ルール 誤判定 (該当しないはずなのに excluded 表示)

```
件名: 排他ルール判定へのご指摘について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

排他ルール (exclusion_rules) の判定にご指摘ありがとうございます。

- 対象 query / program ID: prog_XXX
- 判定: excluded = true / rule_id = excl_XXX
- ルール内容: (例) 「同一年度の中小企業庁系補助金との重複受給不可」
- ご指摘: (例) 当該制度は中小企業庁ではなく経産省直轄のため対象外
- 対応:
  1. rule の根拠条文 (公示文 / 交付要綱) を再確認
  2. 適用範囲が誤っていれば、該当 rule の scope を修正
  3. 反映は次回 ingest cycle、影響を受ける program 一覧を別途ご報告

詳細は docs/exclusions.md にて運用方針を公開しています。
本ケースを反映後、改訂内容を公開いたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### D-5. law_basis 誤り (引用条文が違う)

```
件名: 法令基礎 (law_basis) のご指摘について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

引用条文の誤りのご指摘、ありがとうございます。

- 対象: program ID prog_XXX / law_basis フィールド
- 現状: 「租税特別措置法 第 XX 条」
- ご指摘: 正しくは「租税特別措置法 第 YY 条第 Z 項」
- 確認方法: e-Gov 法令検索 + 当方の am_law_article テーブル
  (28,048 rows) から条文 hash 突合
- 対応: 一次資料で確認のうえ、24-48h 以内に修正反映予定

am_law_article は施行日付き snapshot を保持しているため、過去
時点の条文も検索可能です。誤り反映と同時に、修正前後の差分も
内部 changelog に記録いたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

## E. Sales-y inquiry rejection (5 件)

### E-1. DPA / MSA / NDA を求められた場合

```
件名: 契約書類のご依頼について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

DPA / MSA / NDA のご依頼、ありがとうございます。

恐れ入りますが、当方は zero-touch operation を運営方針として
おり、個別の契約書ご対応は承っておりません。代わりに公開済みの
規約類で同等の内容をご確認いただける構成としております。

- 利用規約: https://autonomath.ai/docs/compliance/terms_of_service/
- プライバシーポリシー: https://autonomath.ai/docs/compliance/privacy_policy/
- データガバナンス: https://autonomath.ai/docs/compliance/data_governance/
- データ主体の権利: https://autonomath.ai/docs/compliance/data_subject_rights/

社内ご審査が個別契約を必須とする場合、現状の運営体制では
ご要件をお引き受けできない可能性が高いです。事前にお知らせいただき、
ありがとうございます。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### E-2. SLA 99.9% を求められた場合

```
件名: SLA 水準についてのご質問 (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

SLA 99.9% のご要望、ありがとうございます。

恐れ入りますが、現行の公開 SLA は 99.5%/月 です。99.9% への
個別引き上げ・補償増額のオプションは設定しておりません。

- 公開 SLA: docs/sla.md
- 99.5% の根拠: 単一 region (Fly.io Tokyo) 構成、solo ops により
  実態と乖離しない水準で公開しています
- 課金除外: 5xx 応答は課金対象外 (実質的な credit)

要求水準が 99.9% を必須とされる場合、現状の運営体制では
ご要件をお引き受けできない可能性が高いです。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### E-3. 専用 Slack channel を求められた場合

```
件名: コミュニケーションチャネルのご相談 (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

専用 Slack channel のご要望、ありがとうございます。

恐れ入りますが、専用 Slack / Slack Connect / Microsoft Teams 等
での個別チャネル開設は承っておりません。代わりに下記をご利用ください。

- 一般質問・公開議論: GitHub Discussions
  https://github.com/Bookyou/autonomath/discussions
- 個別の問い合わせ: 本 email アドレス (info@bookyou.net)
- Bug report: GitHub Issues
- 障害情報: status.autonomath.ai

solo ops の運営方針上、複数チャネル運用は対応外です。
ご理解のほどよろしくお願いいたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### E-4. 営業 call / video call を求められた場合

```
件名: ミーティングのご依頼について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

ミーティングのご依頼、ありがとうございます。

恐れ入りますが、現状 call / video meeting でのご対応は承って
おりません。お問い合わせは email のみで運用しております。

- 技術質問: 本 email にて、再現手順 / 該当 endpoint / 想定 vs 実際
  をいただければ、内容に応じて返信いたします
- 製品 demo: 公開ドキュメント (https://autonomath.ai/docs/) と
  Free 50 req/月 でお試しいただけます
- 価格交渉: ¥3/req (税込 ¥3.30) 一律のため、call による交渉は
  実施しておりません

zero-touch を維持することで、料金を低位に保てております。
ご理解のほどよろしくお願いいたします。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```

---

### E-5. Paid tier (年契約 / enterprise) を求められた場合

```
件名: ご契約形態のご相談について (Re: お問い合わせ)

ご連絡ありがとうございます。AutonoMath の梅田です。

年契約・enterprise tier のご検討、ありがとうございます。

恐れ入りますが、AutonoMath は ¥3/request (税込 ¥3.30) の完全
従量制のみで運用しており、下記の形態はご提供しておりません。

- 年契約 / 月固定 / seat ライセンス
- enterprise tier / dedicated infra
- 最低消費 / volume commitment 割引

代わりにご検討いただけるアプローチ:

1. card 登録のうえ metered で運用 (Free 50/月 + 超過分のみ ¥3/req)
2. cache hit 80% 程度を見込めるワークロードでは実質単価が
   ¥0.6 - ¥1.5 程度に下がるケースが多くなっています
3. 月次の予算上限は dashboard の Self-cap 機能で設定可能です

組織規程上、年契約調達でなければ採用できないご事情の場合は、
現状の運営体制ではお引き受けできない可能性が高いです。

Bookyou株式会社 (T8010001213708) - info@bookyou.net
```
