---
source_html: about.html
brand: jpcite
canonical: https://jpcite.com/about.html
fetched_at: 2026-05-11T10:54:09.811945+00:00
est_tokens: 577
token_divisor: 4
license: see https://jpcite.com/tos
---

# about.html

[メインコンテンツへスキップ / Skip to main content ](#main)

[](/)

# jpcite とは

日本の制度データを、AI が読む前に小さな根拠パケットへ圧縮する Evidence API + MCP サービス。

[サービスを試す → ](index.html#path-email-trial)[料金 → ](pricing.html)

## AI が読む前の制度データ圧縮レイヤー

jpcite は回答文を生成するサービスではありません。AI が毎回 PDF・検索結果・官公庁ページを長く読む前に、 source_url 、 source_fetched_at 、 known_gaps 、互換 / 排他ルールを小さい Evidence Packet として返す前処理レイヤーです。登録不要の匿名枠は [3 リクエスト/日 per IP ](pricing.html#api-free)、継続利用は [¥3/課金単位 (税込 ¥3.30) ](pricing.html#api-paid)です。

- 11,601 検索できる制度の数
- 2,286 補助金 採択事例
- 108 融資商品 (担保・個人保証人・第三者保証人で分類)
- 1,185 行政処分 公表記録
- 9,484 法令メタデータ・本文参照
- 179 AI から呼べる MCP ツール
- 出典付き 主要公開行に一次資料 URL を付与

## なぜ作ったか

jGrants は申請窓口であり、 適合判定の層ではありません。 「自社が使える補助金はどれか」 「併用可能か」 「無担保・無保証人の融資はどれか」 — これらの問いに答えるには、 依然として人間が省庁サイトを巡回し、 PDF を読み、 通達を突き合わせる必要があります。

jpcite は、 その欠落した層を AI エージェントが直接呼べる API として提供します。

## 一次資料を優先

主要公開レコードでは、省庁・自治体・政府系金融 (日本政策金融公庫)・国税庁・e-Gov などの一次資料 URL と取得日時を優先して付与します。 集約サイト・二次情報源は出典扱いしない方針で、未取得・未確認領域は tier や known_gaps で示します。

## 主な収録範囲

制度数 11,601 (検索対象)

採択事例 2,286

融資プログラム 108

行政処分 1,185

法令 9,484 法令メタデータ・本文参照 (e-Gov 法令検索 CC-BY 4.0)

判例 2,065

税制ルールセット 50

適格請求書発行事業者 13,801

## 法令データの扱い

法令データは e-Gov 法令検索を出典として、法令名・法令番号・所管・施行日などのメタデータ検索と、e-Gov 法令メタデータ・条文参照に対応しています。API の結果には、確認用の e-Gov 参照 URL と取得時点を付けて返します。

区分 件数

法令メタデータ 9,484 件

条文参照 e-Gov 法令本文参照

条文行 353,278 行

制度 ↔ 法令 のクロスリファレンスは、法令メタデータと条文参照を使って、根拠法令・参照条文・関連制度をたどれるように構成しています。

## 新しい交差参照エンドポイント

制度・法令・採択事例・行政処分・適格事業者・改正履歴を横断する深いリンクを、 順次以下のエンドポイントで提供します。 一部は段階提供。

エンドポイント 用途

/v1/programs/{id}/full_context 制度 1 件に紐づく 法令条文・採択事例・排他ルール・改正履歴・対象地域 を 1 リクエストで返す深リンク

/v1/cases/cohort_match 同業種 同規模 の採択事例 cohort 照合 (申請傾向の手がかり)

/v1/eligibility/dynamic_check 排他ルール 181 件 連動の動的適格性チェック (制度 ID 群 → 衝突判定)

/v1/regions/{code}/coverage 地域コード単位の 制度・採択 カバレッジ (地理 cohort)

/v1/invoice_registrants/{tnum}/risk 取引先 (T 番号) の登録状態 + 行政処分 履歴 リスクサマリ

/v1/me/amendment_alerts 登録 制度・法令 群の改正アラート フィード (¥3 / 通知)

## 提供形態

- REST API + MCP サーバー
- メール通知チャネル · 法令改正アラート · Embedded Evidence Entry · 根拠付き相談パック / Evidence-to-Expert Handoff

## 連絡先

- お問い合わせ: [info@bookyou.net ](mailto:info@bookyou.net)
- 開発者向け: [スタートガイド ](/docs/getting-started/)
- 稼働率・データ鮮度・修正履歴をまとめて検証: [信頼センター ](trust.html)
- 法的開示: [特商法 ](tokushoho.html)· [利用規約 ](tos.html)· [プライバシー ](privacy.html)

本サービスは情報検索です。 個別具体的な税務・法律判断は資格を有する専門家にご相談ください (税理士法 §52 / 弁護士法 §72)。
