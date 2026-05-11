---
source_html: data-licensing.html
brand: jpcite
canonical: https://jpcite.com/data-licensing.html
fetched_at: 2026-05-11T10:54:09.831254+00:00
est_tokens: 1184
token_divisor: 4
license: see https://jpcite.com/tos
---

# data-licensing.html

[メインコンテンツへスキップ / Skip to main content ](#main)

[](/)

# データソース・ライセンス開示 

jpcite が収録する 16 dataset の 出典機関 / license / 商用配信可否 / 出典表示要件 / 更新頻度 を 1 表で開示します。 法人購買・法務部 reviewer の license review をこの 1 page で完了できる構成です。 各 record の am_source.license 列は 96,467 / 97,272 が分類済 (805 件は license_review_queue.csv で個別追跡中)。 

## 凡例 

- 商用配信可否 = 本サービスを通じた API 配信が、出典側 license 上明示的に許諾されているか 
- 出典表示要件 = 顧客が response を再利用する際に同等付与すべき表示文字列 
- 可 = license 確認済で API 経由の配信 OK 
- 要再確認 = license_review_queue.csv 対象、launch 直前に再評価 

## 16 Dataset 一覧 

# Dataset 件数 出典機関 License 商用配信 出典表示要件 更新頻度 

1 e-Gov 法令本文 + メタ 法令本文 + 9,484 メタ [デジタル庁 e-Gov ](https://laws.e-gov.go.jp/)[CC BY 4.0 ](https://creativecommons.org/licenses/by/4.0/deed.ja)可 「デジタル庁 e-Gov 法令データ提供システム」+ license URL 週次 (incremental-law-load) 

2 国税庁 適格請求書発行事業者 13,801 (delta) → 月次 4M bulk [国税庁 (NTA) ](https://www.invoice-kohyo.nta.go.jp/)[PDL v1.0 ](https://www.digital.go.jp/resources/data_policy)可 (TOS 2026-04-24 確認) 「国税庁公表データを Bookyou株式会社が編集の上再配布」 月次 1 日 03:00 JST (nta-bulk-monthly) 

3 国税庁 通達 (法基通・所基通・消基通・相基通) 3,221 (tsutatsu_index) [国税庁 ](https://www.nta.go.jp/law/tsutatsu/)[政府標準利用規約 v2.0 ](https://www.digital.go.jp/resources/data_policy)可 「国税庁 通達」+ 取得時刻 月次 

4 国税不服審判所 裁決事例 137 (saiketsu) [国税不服審判所 ](https://www.kfs.go.jp/)[政府標準利用規約 v2.0 ](https://www.digital.go.jp/resources/data_policy)可 「国税不服審判所 裁決」+ 取得時刻 不定期 (新規裁決公表時) 

5 経済産業省 補助金・行政処分 約 2,000 [METI ](https://www.meti.go.jp/)[政府標準利用規約 v2.0 ](https://www.digital.go.jp/resources/data_policy)可 出典 URL 必須 月次 (ministry-ingest-monthly) 

6 農林水産省 補助金・採択事例 約 2,200 [MAFF ](https://www.maff.go.jp/)[政府標準利用規約 v2.0 ](https://www.digital.go.jp/resources/data_policy)可 出典 URL 必須 月次 

7 国土交通省 行政処分 約 800 [MLIT ](https://www.mlit.go.jp/)[政府標準利用規約 v2.0 ](https://www.digital.go.jp/resources/data_policy)可 出典 URL 必須 月次 

8 厚生労働省 行政処分 (薬機 etc) 約 400 [MHLW ](https://www.mhlw.go.jp/)[政府標準利用規約 v2.0 ](https://www.digital.go.jp/resources/data_policy)可 出典 URL 必須 月次 

9 環境省 行政処分 (産廃) 約 300 [MOE ](https://www.env.go.jp/)[政府標準利用規約 v2.0 ](https://www.digital.go.jp/resources/data_policy)可 出典 URL 必須 月次 

10 47 都道府県 補助金・処分 約 2,500 各都道府県 各団体 利用規約 (大半 政府標準準拠) 都道府県別、license_review_queue.csv で追跡 出典 URL 必須 月次 

11 日本政策金融公庫 (JFC) 融資 108 [JFC ](https://www.jfc.go.jp/)JFC 利用規約 (公開情報整理) 可 (公開情報のみ抽出) 「日本政策金融公庫 公表」 月次 

12 知財高裁 / 特許庁 判例 2,065 知財高裁 / 特許庁 パブリックドメイン 可 事件番号 + 出典 URL 不定期 

13 公共入札 (NEXCO / JR / UR / GEPS) 362 各発注機関 GEPS 等 公開情報 可 出典 URL 必須 週次 

14 JST 採択事例 (一部) [JST ](https://www.jst.go.jp/)JST 利用規約 (要確認) 要再確認 (license_review_queue.csv 対象) 出典 URL 必須 月次 

15 経産省 gBizINFO 法人情報 79,876 [METI gBizINFO ](https://info.gbiz.go.jp/)[CC BY 4.0 ](https://creativecommons.org/licenses/by/4.0/deed.ja)可 「経済産業省 gBizINFO」 月次 

16 公益財団 / 業界団体 補助金 約 200 各団体 各団体 利用規約 個別 license 確認 出典 URL 必須 不定期 

## License 集計 

- CC BY 4.0 : 2 datasets (e-Gov 法令 / gBizINFO 法人情報) 
- PDL v1.0 : 1 dataset (NTA 適格請求書発行事業者) 
- 政府標準利用規約 v2.0 : 6 datasets (METI / MAFF / MLIT / MHLW / MOE / 通達系) 
- パブリックドメイン : 1 dataset (判例) 
- 個別 license (要確認含む) : 6 datasets (47 都道府県 / JFC / 入札 / JST / 公益財団 / 業界団体) 

## 顧客が response を再利用する場合の表示要件 

- jpcite は API response 内に license , source_url , fetched_at , attribution_text の 4 field を返します 
- 顧客はこの 4 field を「同等の文字列」で表示すれば license 義務 (CC BY 4.0 attribution、PDL v1.0 表示要件、政府標準利用規約 v2.0 出典明示) を満たせます 
- am_source.license 列は 96,467 / 97,272 record で分類済。 残り 805 件は license_review_queue.csv で個別追跡し、確認できない record は API response から除外しています 
- AI agent が response を要約・引用する場合も、同等 attribution の継承を推奨 (利用規約 §5.3.1) 

## 再配布禁止 (利用規約 §5.2) 

- jpcite DB を bulk export して同等の data service を再配布する行為は禁止 
- crawler / scraper 的な大量 query で実質 copy を作る行為は禁止 
- 個別案件 query への response を 社内分析・顧客提案・report に使う行為は OK 
- 顧客の AI agent / RAG が runtime で参照する用途は本サービスの想定利用範囲 

## アグリゲータ banned 表明 

以下のアグリゲータは source_url から明示的に除外されています。 一次資料 (政府機関 / 都道府県 / JFC 等) のみを直接参照する設計です。 boot 時の INV-04 invariant により、banned domain が混入した場合は起動を hard-fail します。 

- noukaweb.com、hojyokin-portal.jp、biz.stayway.jp、stayway.jp 
- nikkei.com、prtimes.jp、wikipedia.org (二次情報) 
- その他 SEO アフィリエイト型まとめサイト 

## 関連 page 

- [/sources.html ](/sources.html)— Dataset 一覧 (DataCatalog JSON-LD 完備、monitoring 寄り) 
- [/data-freshness.html ](/data-freshness.html)— 主要 dataset の中央値 fetched_at を live 表示 
- [/audit-log.html ](/audit-log.html)+ [/audit-log.rss ](/audit-log.rss)— 差分検出履歴 
- [/v1/corrections?days=90 ](https://api.jpcite.com/v1/corrections?days=90)— 過去 90 日の修正 feed 
- [/trust/purchasing.html ](/trust/purchasing.html)— 法人購買 1-screen summary 

本一覧は am_source.license 列 (96,467 / 97,272 分類済) と license_review_queue.csv (1,425 行) を一次資料とし、出典機関の利用規約改訂時に随時更新します。 齟齬・誤りを発見した場合は [info@bookyou.net ](mailto:info@bookyou.net)までご連絡ください。 機械可読 manifest: [/.well-known/trust.json ](/.well-known/trust.json)。
