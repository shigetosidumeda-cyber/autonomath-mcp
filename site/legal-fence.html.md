---
source_html: legal-fence.html
brand: jpcite
canonical: https://jpcite.com/legal-fence.html
fetched_at: 2026-05-11T10:54:09.835886+00:00
est_tokens: 1234
token_divisor: 4
license: see https://jpcite.com/tos
---

# legal-fence.html

[メインコンテンツへスキップ / Skip to main content ](#main)

[](/)

# jpcite が触らない 8 業法 

jpcite は情報検索・根拠確認の補助に徹し、 個別具体的な税務・法律・申請・監査・登記・労務・知財・労基の判断は行いません。 該当する 8 業法 (税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47-2 / 行政書士法 §1 / 司法書士法 §3 / 社会保険労務士法 §27 / 弁理士法 §75 / 労働基準法 §36) の業務範囲・「やる/やらない」境界線・違反通報先を 1 page で開示します。 API response の _disclaimer field 仕様も末尾に記載しています。 

目次 

- [1. 税理士法 §52 ](#fence-52)
- [2. 弁護士法 §72 ](#fence-72)
- [3. 公認会計士法 §47-2 ](#fence-47-2)
- [4. 行政書士法 §1 ](#fence-gyosei)
- [5. 司法書士法 §3 ](#fence-shiho)
- [6. 社会保険労務士法 §27 (36協定 含む) ](#fence-shaho)
- [7. API response の _disclaimer field 仕様 ](#disclaimer)
- [8. MCP tool ごとの sensitive 業法 マッピング ](#mapping)

## 1. 税理士法 §52 

### 業務範囲 (税理士法 §52 が独占) 

税務代理 / 税務書類作成 / 税務相談 (税理士法 §2 で定義する税理士業務) 

### jpcite が やる 

- 制度検索 (補助金・税制優遇・認定) 
- 租税特別措置法・通達・裁決事例の引用 + 出典 URL 提示 
- 税制 ID lookup (措置法 〇条 〇項 等) 
- 税法改正の差分検出 + 改正 effective date の提示 

### jpcite が やらない 

- 個別具体的な税額計算 
- 申告書 (法人税 / 所得税 / 消費税) の作成 
- 税務署対応 / 税務調査立会 
- 「あなたの場合は〇〇円控除できます」型の個別断定 

違反通報先 : 日本税理士会連合会 [https://www.nichizeiren.or.jp/ ](https://www.nichizeiren.or.jp/)

## 2. 弁護士法 §72 

### 業務範囲 (弁護士法 §72 が独占) 

法律事務 (具体的事件についての法律相談・代理・書類作成)。 報酬を得る目的での非弁活動を禁止 

### jpcite が やる 

- 法令本文・判例・行政処分の検索 + 出典 URL 
- e-Gov 法令データの全文検索 (CC BY 4.0) 
- 知財高裁・特許庁の判例検索 
- 行政処分の事業者横断検索 

### jpcite が やらない 

- 個別事案への法律意見の表明 
- 訴訟代理 / 紛争代理 
- 契約書・示談書・告訴状等の作成 
- 「この場合は違法/合法です」型の個別断定 

違反通報先 : 日本弁護士連合会 [https://www.nichibenren.or.jp/ ](https://www.nichibenren.or.jp/)

## 3. 公認会計士法 §47の2 

### 業務範囲 (公認会計士法 §47の2 が独占) 

監査証明業務 (財務書類の監査又は証明) を、公認会計士又は監査法人以外が行うことを禁止 

### jpcite が やる 

- 監査作業文書の draft 整理 ( compose_audit_workpaper ) 
- 採択事例 / 決算情報 briefing ( prepare_kessan_briefing ) 
- DD 質問 checklist の生成 ( match_due_diligence_questions ) 
- 業界 pack (建設・製造・不動産) の通達・裁決引用 

### jpcite が やらない 

- 監査意見の表明 (適正意見 / 限定意見 / 不適正意見 / 意見不表明) 
- 財務書類の正当性証明 
- 監査証明書類の発行 
- 「監査済」「監査報告書」相当の対外表示 

違反通報先 : 日本公認会計士協会 [https://jicpa.or.jp/ ](https://jicpa.or.jp/)

## 4. 行政書士法 §1 

### 業務範囲 (行政書士法 §1 が独占) 

官公署に提出する書類等の作成、その代理・相談業務 

### jpcite が やる 

- 制度の必要書類 checklist ( bundle_application_kit ) 
- 応募要領 PDF への一次資料 link 集約 
- 類似採択事例の参照 
- scaffold (項目見出し) の生成 

### jpcite が やらない 

- 申請書面そのものの作成 (記入済の応募書類) 
- 提出代行 (官公署窓口対応) 
- 許認可申請の代理 
- 「申請して採択を保証」型の表現 

違反通報先 : 日本行政書士会連合会 [https://www.gyosei.or.jp/ ](https://www.gyosei.or.jp/)

## 5. 司法書士法 §3 

### 業務範囲 (司法書士法 §3 が独占) 

登記又は供託に関する手続の代理、登記又は供託に関する審査請求の手続の代理 等 

### jpcite が やる 

- 法人番号 / 登記情報の cross-check ( cross_check_jurisdiction ) 
- 登記住所と適格請求書発行事業者公表住所の整合性検証 
- 採択事例の事業所所在地と登記住所の比較 
- houjin_master / invoice_registrants / adoption_records の不一致検出 

### jpcite が やらない 

- 登記申請の代理 
- 登記書類 (申請書 / 添付書類) の作成 
- 法務局窓口対応 
- 商業登記・不動産登記・成年後見登記の審査請求代理 

違反通報先 : 日本司法書士会連合会 [https://www.shiho-shoshi.or.jp/ ](https://www.shiho-shoshi.or.jp/)

## 6. 社会保険労務士法 §27 (36協定 含む) 

### 業務範囲 (社会保険労務士法 §27 が独占) 

労働社会保険諸法令に基づく書類作成・申請代行、労務相談 (社労士法 §2 で定義)。 36協定 (労働基準法 §36) も範囲 

### jpcite が やる 

- 助成金検索 (キャリアアップ助成金 / 雇用調整助成金 等) 
- 厚生労働省の行政処分検索 
- 労働関連法令の検索 (e-Gov 法令) 

### jpcite が やらない 

- 36協定 (時間外労働・休日労働に関する協定届) の生成 — render_36_kyotei_am + get_36_kyotei_metadata_am は AUTONOMATH_36_KYOTEI_ENABLED gate で default off 
- 就業規則作成・改定 
- 助成金申請代行 
- 労働社会保険諸法令に基づく申告書類の作成 

違反通報先 : 全国社会保険労務士会連合会 [https://www.shakaihokenroumushi.jp/ ](https://www.shakaihokenroumushi.jp/)

36協定 gate : AUTONOMATH_36_KYOTEI_ENABLED = False (default)。 仮に gate ON でも、render response は draft 扱いで「社労士確認必須」 disclaimer を必ず付与します。 

## 7. API response の _disclaimer field 仕様 

業法に該当する 11 sensitive tool branch では、API response 末尾に _disclaimer field を自動付与します (Wave 30 disclaimer hardening 済)。 

### 統一文体 
{ "_disclaimer": { "law": "税理士法 §52", "scope_excluded": "個別税務代理・申告書作成・税務相談", "professional": "税理士", "professional_directory": "https://www.nichizeiren.or.jp/", "message": "本 response は情報検索の結果です。 個別具体的な税務判断は税理士にご相談ください (税理士法 §52 に基づく業務範囲外)。", "source_urls": ["https://elaws.e-gov.go.jp/...", ...] } } 
### 表記の統一 

「本 response は情報検索の結果です。 個別具体的な {税務 / 法律 / 申請 / 監査 / 登記 / 労務} 判断は {税理士 / 弁護士 / 行政書士 / 公認会計士 / 司法書士 / 社労士} にご相談ください。 ({業法 §条文} に基づく業務範囲外)。 出典: {source_url}」 

## 8. MCP tool ごとの sensitive 業法 マッピング 

MCP Tool Sensitive 業法 _disclaimer 対象 

get_am_tax_rule 税理士法 §52 ○ 

search_tax_incentives 税理士法 §52 ○ 

compose_audit_workpaper §52 + 公認会計士法 §47-2 ○ 

prepare_kessan_briefing 税理士法 §52 ○ 

match_due_diligence_questions §52 + 弁護士法 §72 ○ 

cross_check_jurisdiction §52 + §72 + 司法書士法 §3 ○ 

bundle_application_kit 行政書士法 §1 ○ 

render_36_kyotei_am (gated off) 社労士法 §27 + 労基法 §36 ○ (gate ON 時) 

pack_construction §52 + §47-2 ○ 

pack_manufacturing §52 + §47-2 ○ 

pack_real_estate §52 + §47-2 ○ 

これらは CI で継続確認し、「全 sensitive branch の response が _disclaimer を含む」ことを検証します。 

本 page の各業法引用は e-Gov 法令データ (CC BY 4.0) と各業法主管団体の公開情報を一次資料とします。 jpcite が「やる/やらない」境界線に関する記述は、 [利用規約 ](/tos.html)§7 (免責) と整合します。 関連 page: [法人購買 1-screen ](/trust/purchasing.html)· [Security Overview ](/security/)· [データソース・ライセンス ](/data-licensing.html)· [trust.json ](/.well-known/trust.json)
