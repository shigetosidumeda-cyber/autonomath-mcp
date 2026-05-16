# AWS credit review 11/20: source terms, robots, redistribution, and no-hit safety

作成日: 2026-05-15
対象: AWS実行前計画。AWSリソース作成、CLI/API実行、収集ジョブ実行は行っていない。

## 1. 結論

jpcite のAWSクレジット活用では、まず「収集できるか」ではなく「どの根拠・利用条件で、どの粒度まで再配布できるか」を `source_profile` と `source_receipt` に固定してから処理を開始するべきである。

実行順は次の順番にする。

1. `J01 Official source profile sweep` を最優先で実施し、各データ源の利用規約、API規約、robots.txt、出典表記、再配布可否、アクセス制限、個人情報注意点を保存する。
2. `green` のデータ源だけをAPIまたは公式ダウンロードで収集する。
3. `yellow` はメタデータ、URL、ハッシュ、短い引用、派生集計までに制限する。
4. `red` はリンクのみ、または人手承認待ちにする。
5. すべての no-hit は `no_hit_not_absence` として扱い、「存在しない」「安全」「違法ではない」「対象外」と断定しない。

この順番を守らないと、AWSで大量処理した後に「再配布できないrawミラー」「出典表示が不足したpacket」「robotsまたはAPI規約に反する取得ログ」が残る。jpciteの価値は一次情報ベースの信頼性なので、このリスクはP0扱いにする。

## 2. 共通ルール

### 2.1 取得方法の優先順位

優先順位は以下に固定する。

1. 公式API
2. 公式一括ダウンロード
3. 公式に許容されるXML/CSV/JSON/PDFダウンロード
4. 公式サイトのHTML/PDFクロール
5. 第三者サイト由来の情報

第4順位のHTML/PDFクロールは、APIや一括ダウンロードが存在しない場合だけ使う。第5順位は原則として `source_receipt` の主出典にしない。第三者サイトは「探索補助」または「比較参考」に留め、jpciteのclaim根拠は一次情報へ戻す。

### 2.2 robots.txt と過負荷回避

AWS実行前に全ドメインで以下を `robots_receipt` として保存する。

- `robots_url`
- `fetched_at`
- `http_status`
- `content_sha256`
- `matched_user_agent`
- `allow_disallow_decision`
- `crawl_delay_or_internal_delay`
- `operator_contact`
- `decision: allow | api_only | download_only | metadata_only | blocked | manual_review`

robots.txt が取得できない場合は「自由にクロールしてよい」ではなく `manual_review` とする。`Disallow` 対象、ログイン後ページ、検索結果を大量にたどる動線、明示的な大量取得禁止があるサイトはクロールしない。APIまたは公式ダウンロードへ切り替える。

クロールを許可する場合も、標準設定は以下にする。

- User-Agent は jpcite 用の識別可能な名称と連絡先を含める。
- 1ドメインあたり低並列で開始し、429/403/5xx増加時は自動停止する。
- 検索フォームを総当たりしない。
- robotsや規約の回避、IPローテーション、ログイン突破、CAPTCHA回避はしない。
- CloudWatch Logs には本文全文や個人情報を出さない。

### 2.3 再配布の基本線

jpciteの公開API/MCPで返すものは、原則として以下に限定する。

- `source_url`
- `source_title`
- `publisher`
- `retrieved_at`
- `document_date`
- `content_hash`
- `claim_refs[]`
- 必要最小限の短い引用
- jpcite側で生成した構造化メタデータ、集計、分類、差分、矛盾検出結果

raw PDF、raw HTML、raw CSV、全文本文、記事全文、添付資料一式は、利用条件が明確に許す場合を除き公開再配布しない。AWS S3内ではprivate raw lakeとして保持できるが、クレジット消化後はユーザー要件に従いエクスポート後に削除する。

### 2.4 出典・加工表示

公共データ利用規約(PDL1.0)または政府標準系の利用規約では、出典表示と、編集・加工した場合の加工主体表示が重要になる。jpcite packetには次の2段階を入れる。

- claim単位: `claim_refs[]` に出典URL、取得時刻、該当箇所、ハッシュを入れる。
- packet単位: `attribution_notice` に出典、加工主体、非保証文を入れる。

公的機関の情報を加工して返す場合は、「国、自治体、所管府省がjpciteの分析を保証している」ように見せない。

## 3. source別レビュー

### 3.1 国税庁 法人番号公表サイト

判断: `green`。ただしWeb-API利用時はアプリケーションIDと規約遵守が前提。

使うべき取得方法:

- 基本3情報ダウンロード
- 法人番号システムWeb-API

注意点:

- 利用規約は公共データ利用規約ベースで、出典表示が必要。
- Web-API利用サービスでは、国税庁がサービス内容を保証しない旨の表示が必要。
- 公式ダウンロードやAPIがあるため、HTML検索結果の大量クロールは不要。
- 住所表記、商号変更、統合・閉鎖などの履歴は時点差分を残す。

safe no-hit:

- 「この検索条件では、取得時点の法人番号公表サイト/APIスナップショット内に一致レコードを確認できませんでした。」

禁止:

- 「この法人は存在しません」
- 「実在しない会社です」
- 「反社・不正ではありません」

### 3.2 国税庁 インボイス 適格請求書発行事業者公表サイト

判断: `green/yellow`。法人・法人番号照合はgreen。個人事業者名が含まれる領域は個人情報配慮によりyellow。

使うべき取得方法:

- 公表情報ダウンロード
- 適格請求書発行事業者公表システムWeb-API

注意点:

- Web-APIはアプリケーションID、利用規約同意、審査・承認が絡む。
- Web-API取得情報をもとにしたサービスでは、国税庁が保証しない旨の表示が必要。
- 個人名が公表される場合があり、用途外の人物評価、信用毀損、ランキング化は避ける。
- 登録取消、失効、変更履歴は時点付きで扱う。

safe no-hit:

- 「取得時点のインボイス公表情報/APIスナップショットでは、この登録番号または検索条件に一致する公表レコードを確認できませんでした。」

禁止:

- 「免税事業者です」
- 「請求書を発行できません」
- 「税務上問題があります」
- 「取引してはいけません」

### 3.3 e-Gov 法令検索 / e-Gov APIカタログ

判断: `green`。API・一括XML等の公式手段を優先。

使うべき取得方法:

- e-Gov法令API
- 法令標準XML、一括ダウンロード
- e-Gov APIカタログの公式情報

注意点:

- e-Gov系サイトは出典表示、加工表示、第三者権利の確認が必要。
- 法令本文は条文時点、施行日、改正履歴、未施行・廃止の区別を必ず保持する。
- jpciteは法的助言ではなく、条文・制度根拠へのナビゲーションとして返す。

safe no-hit:

- 「このAPI/スナップショットでは、指定条件に一致する法令メタデータまたは条文を確認できませんでした。」

禁止:

- 「法的義務はありません」
- 「この手続きは不要です」
- 「違法ではありません」

### 3.4 J-Grants

判断: `green/yellow`。公開APIの対象項目はgreen。添付PDF、自治体・外部資料、募集要領全文の再配布はyellow。

使うべき取得方法:

- Jグランツ補助金情報取得API
- 公式公開ページ

注意点:

- Web-APIはベータ版で、公開補助金情報の集計・状況確認を想定している。
- 出典表示は必須。加工した場合は、jpciteが作成した加工物であり政府・自治体が保証しない旨を表示する。
- 募集終了、予算消化、自治体独自条件、要領PDFの更新差分を時点管理する。

safe no-hit:

- 「取得時点のJ-Grants公開API/スナップショットでは、指定条件に一致する公募情報を確認できませんでした。」

禁止:

- 「使える補助金はありません」
- 「不採択になります」
- 「申請資格がありません」

### 3.5 gBizINFO

判断: `green/yellow`。利用申請・アクセストークン・利用目的内でのAPI利用はgreen。元データ由来の再配布条件が不明な項目はyellow。

使うべき取得方法:

- gBizINFO REST API v2
- 公式データダウンロード

注意点:

- 事前申請とアクセストークンが必要。
- 申請時に申告した目的の範囲内で利用する。
- API/ダウンロードにはアクセス頻度、リクエスト数、通信量等の制限が設定される可能性がある。
- 外部データベース等から取得されたコンテンツは提供元条件に従う。
- 法人活動情報は「公開情報の集約」であり、網羅性や最新性の保証として扱わない。

safe no-hit:

- 「取得時点のgBizINFO API/スナップショットでは、指定法人番号または条件に一致する公開レコードを確認できませんでした。」

禁止:

- 「補助金・調達・認定の履歴が一切ありません」
- 「信用上の問題はありません」
- 「公的評価が低い/高い」

### 3.6 e-Stat

判断: `green`。ただしアプリケーションID、クレジット表示、アクセス制限遵守が前提。

使うべき取得方法:

- e-Stat API
- 公式統計表ダウンロード

注意点:

- API利用には利用登録とアプリケーションIDが必要。
- サービス提供時は出所・クレジット表示が必要。
- 短時間大量アクセスは禁止され、負荷状況でアクセス制限があり得る。
- 統計表は調査年、地域コード、分類、秘匿値、欠損、改定履歴を保持する。

safe no-hit:

- 「取得したe-Stat統計表の範囲では、指定地域・期間・分類に一致するセルを確認できませんでした。」

禁止:

- 「その地域に該当者はいません」
- 「市場が存在しません」
- 「統計上リスクがありません」

### 3.7 EDINET

判断: `green/yellow`。EDINET API利用はgreen。PDF/XBRL/CSV全文の再配布や投資判断表現はyellow/red。

使うべき取得方法:

- EDINET API
- EDINET公式ダウンロード

注意点:

- EDINET API利用規約とEDINET利用規約の両方を確認する。
- EDINETは機械取得にはAPI利用を案内している。
- 短時間大量アクセスや運用支障行為は禁止。
- 出典表示が必要。
- jpciteの出力は情報提供であり、投資助言・会計監査・信用保証に見せない。

safe no-hit:

- 「指定日付範囲・書類種別・提出者条件に対するEDINET APIの取得結果では、一致書類を確認できませんでした。」

禁止:

- 「この企業は開示義務がありません」
- 「財務リスクはありません」
- 「投資してよい/投資すべきではない」

### 3.8 JPO / J-PlatPat / 特許情報

判断: `yellow`。JPOの特許情報取得APIは登録・アクセス上限前提で利用可能。J-PlatPat画面の大量収集やロボットアクセスは避ける。

使うべき取得方法:

- 特許情報取得API
- 特許情報一括ダウンロードサービス
- J-PlatPatは通常検索・個別確認の参照に留める

注意点:

- 特許情報取得APIは試行提供で、利用登録と遵守事項が必要。
- 安定稼働のためアクセス数上限がある。
- J-PlatPatは一般利用を妨げる単純な大量ダウンロードやロボットアクセスを禁止しているため、AWS大量クロール対象にしない。
- 権利状態、審査経過、出願人名寄せ、商標類似性などは専門判断に踏み込まない。

safe no-hit:

- 「許可されたAPI/ダウンロード範囲では、指定条件に一致する特許・意匠・商標情報を確認できませんでした。」

禁止:

- 「権利侵害はありません」
- 「商標登録できます」
- 「競合特許は存在しません」

### 3.9 調達ポータル / GEPS

判断: `green/yellow`。公開案件のメタデータはgreen。ログイン後情報、入札・契約手続、添付資料全文再配布はyellow/red。

使うべき取得方法:

- 調達ポータルの公開検索
- 公開資料のURL/メタデータ取得
- 公式に提供されるダウンロードがある場合はそれを優先

注意点:

- 利用規約とサイトポリシーを確認する。
- 外部データベース/API連携由来のコンテンツは提供元条件に従う。
- 入札参加、電子契約、利用者登録等の業務領域はjpciteの自動処理対象にしない。
- 公開案件の過去データは、掲載終了・訂正・取り下げがあり得るため時点付きで扱う。

safe no-hit:

- 「取得時点の公開調達情報スナップショットでは、指定条件に一致する案件を確認できませんでした。」

禁止:

- 「この官公庁は調達していません」
- 「落札可能です」
- 「参加資格があります」

### 3.10 JETRO

判断: `yellow/red`。ニュース、レポート、動画、イベント資料は再配布制約が強い。jpciteの主データソースとして大量取得しない。

使うべき取得方法:

- 原則はリンク、タイトル、公開日、短い引用、要約ではなくjpcite独自メモ
- 事前許諾が必要なコンテンツは取得しない

注意点:

- JETROサイトのコンテンツはJETROまたは表示された所有者に権利が帰属する。
- 意図された目的の範囲でのダウンロード・印刷が中心で、記事・レポートの掲載には許諾が必要になる場合がある。
- 第三者コンテンツや翻訳が含まれ、リンク先条件も別途確認が必要。
- robots.txtでは特定クローラ向けに多くのパスがDisallowされており、jpciteは大量クロール対象から外すのが安全。

safe no-hit:

- 「jpciteが許容取得範囲で確認したJETRO公開ページでは、指定条件に一致する情報を確認できませんでした。」

禁止:

- 「海外規制は存在しません」
- 「輸出可能です」
- 「JETROが推奨しています」

### 3.11 地方自治体PDF・省庁PDF

判断: `yellow`。自治体ごと、省庁ページごとに利用規約・PDL1.0適用・第三者権利・PDF添付条件が異なる。

使うべき取得方法:

- 自治体/省庁公式ページのPDF URL、タイトル、公開日、ハッシュ
- 公式RSS、サイトマップ、オープンデータカタログがある場合は優先

注意点:

- PDL1.0を採用している場合でも、ロゴ、写真、地図、第三者資料、パンフレット画像、委託先作成資料は別権利の可能性がある。
- PDF本文全文の公開再配布は避け、URL、ハッシュ、該当ページ、短い引用、抽出した制度フィールドに留める。
- PDF OCRはAWS Textract等で可能だが、生成物は「抽出結果」であり原本性を持たない。
- 地方自治体はURL変更・掲載終了が多いため、`retrieved_at` と `content_hash` が特に重要。

safe no-hit:

- 「取得対象にした自治体/省庁ページとPDFスナップショットの範囲では、指定条件に一致する制度情報を確認できませんでした。」

禁止:

- 「この自治体に制度はありません」
- 「申請できません」
- 「この条件なら必ず対象です」

## 4. `source_profile` 必須フィールド

AWS実行前に、各sourceを以下のスキーマで管理する。

```json
{
  "source_id": "nta_corporate_number",
  "publisher": "国税庁",
  "official_url": "https://www.houjin-bangou.nta.go.jp/",
  "access_method": "api|bulk_download|html|pdf|manual",
  "terms_url": "...",
  "api_terms_url": "...",
  "robots_url": "...",
  "license_family": "PDL1.0|site_terms|api_terms|unknown",
  "attribution_required": true,
  "required_notice": "...",
  "modification_notice_required": true,
  "redistribution_scope": "metadata_only|derived_fields|raw_allowed|link_only|manual_review",
  "personal_data_flag": "none|possible|contains_public_personal_data",
  "rate_limit_policy": "official_limit|internal_conservative|manual_review",
  "no_hit_policy": "no_hit_not_absence",
  "risk_tier": "green|yellow|red",
  "last_terms_checked_at": "2026-05-15T00:00:00+09:00",
  "last_robots_checked_at": "2026-05-15T00:00:00+09:00"
}
```

## 5. AWS実行に入れるGo/No-Go

### Go条件

- `source_profile` が存在する。
- `terms_url` と `robots_url` またはAPI規約が取得済み。
- 出典表示文と加工表示文がpacket templateに入っている。
- no-hit文言がsource別に定義済み。
- raw再配布可否が `redistribution_scope` で固定されている。
- private CSV、個人情報、APIキーがBedrock/Textract/OpenSearchの外部処理やCloudWatch Logsに流れない。

### No-Go条件

- 利用規約が見つからない、または再配布可否が不明。
- robots.txtまたはサイトポリシーが大量取得を禁止している。
- APIキー/アクセストークン/アプリケーションIDの利用目的とジョブ目的が一致しない。
- 429/403/5xxが増加しているのにリトライを続ける設計。
- raw PDF/HTML/CSVをjpcite公開APIで返す設計。
- no-hitを不在証明・安全証明・適格性否定として返す設計。

## 6. packet出力への反映

各packetは最低限以下を持つ。

```json
{
  "source_receipts": [
    {
      "source_id": "jgrants_public_api",
      "publisher": "J-Grants",
      "source_url": "https://api.jgrants-portal.go.jp/...",
      "retrieved_at": "2026-05-15T00:00:00+09:00",
      "content_hash": "sha256:...",
      "terms_url": "https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf",
      "attribution_notice": "出典: Jグランツ。jpciteが加工して作成。政府及び自治体は本分析を保証しません。",
      "redistribution_scope": "derived_fields",
      "no_hit_policy": "no_hit_not_absence"
    }
  ],
  "known_gaps": [
    "API取得対象外の自治体独自要領PDFは未確認",
    "掲載終了・更新・予算消化により現時点の条件と異なる可能性"
  ],
  "_disclaimer": "一次資料への到達補助であり、法務・税務・投資・入札参加資格の判断を代替しません。"
}
```

## 7. 追加で作るべき成果物

AWS本番投入前に以下を作るべきである。

1. `source_profiles.yaml`
   - 上記スキーマで全sourceを管理する。
2. `attribution_templates.json`
   - source別の出典表示、加工表示、非保証表示を管理する。
3. `no_hit_templates.json`
   - source別に安全文言と禁止文言を管理する。
4. `robots_receipts/`
   - robots.txt、取得時刻、判定、ハッシュを保存する。
5. `terms_receipts/`
   - 利用規約、API規約、サイトポリシーのURL、取得時刻、ハッシュを保存する。
6. `redistribution_policy.csv`
   - raw公開可否、derived公開可否、metadata公開可否、link-only判定をsource別に保存する。
7. `legal_red_team_cases.jsonl`
   - no-hit断定、政府保証誤認、個人事業者評価、投資助言化、入札資格断定などの禁止ケースを評価する。

## 8. 公式参照URL

- 国税庁 法人番号公表サイト 利用規約: https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html
- 国税庁 法人番号システム Web-API: https://www.houjin-bangou.nta.go.jp/webapi/
- 国税庁 法人番号 Web-API利用規約: https://www.houjin-bangou.nta.go.jp/webapi/riyokiyaku.html
- 国税庁 法人番号 基本3情報ダウンロード: https://www.houjin-bangou.nta.go.jp/download/
- 国税庁 インボイス 公表サイト ご利用ガイド: https://www.invoice-kohyo.nta.go.jp/aboutweb/index.html
- 国税庁 インボイス Web-API: https://www.invoice-kohyo.nta.go.jp/web-api/index.html
- 国税庁 インボイス Web-API利用規約: https://www.invoice-kohyo.nta.go.jp/web-api/riyou_kiyaku.html
- 国税庁 インボイス 公表情報ダウンロード: https://www.invoice-kohyo.nta.go.jp/download/index.html
- e-Gov Developer 利用規約: https://developer.e-gov.go.jp/contents/terms
- e-Gov APIカタログ 利用規約: https://api-catalog.e-gov.go.jp/info/terms
- e-Gov 法令API情報: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44
- e-Stat API利用ガイド: https://www.e-stat.go.jp/api/api-info/api-guide
- e-Stat API利用規約: https://www.e-stat.go.jp/api/terms-of-use
- gBizINFO APIの利用: https://content.info.gbiz.go.jp/api/index.html
- gBizINFO API・データダウンロード利用規約: https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102
- gBizINFO 利用規約: https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406
- EDINET利用規約: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0030.html
- EDINET API機能利用規約: https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140191.pdf
- EDINET API情報: https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/33
- 特許庁 APIを利用した特許情報の試行提供: https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html
- 特許庁 このサイトについて: https://www.jpo.go.jp/toppage/about/index.html
- INPIT J-PlatPat 利用上のご案内: https://www.inpit.go.jp/j-platpat_info/guide/j-platpat_notice.html
- 特許情報の一括ダウンロードサービス: https://www.jpo.go.jp/system/laws/sesaku/data/download.html
- J-Grants APIドキュメント: https://developers.digital.go.jp/documents/jgrants/api/
- J-Grants Web-API利用規約: https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf
- J-Grants 補助金情報取得API利用概要: https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E6%A6%82%E8%A6%81.pdf
- 調達ポータル ご利用にあたって: https://www.p-portal.go.jp/pps-web-biz/resources/app/html/sitepolicy.html
- JETRO 利用規約・免責事項: https://www.jetro.go.jp/legal.html
- JETRO robots.txt: https://www.jetro.go.jp/robots.txt
- 公共データ利用規約 第1.0版: https://www.digital.go.jp/resources/open_data/public_data_license_v1.0
