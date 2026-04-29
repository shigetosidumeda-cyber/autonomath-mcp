<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "税務会計AI FAQ",
  "description": "税務会計AI についてよく聞かれる質問 16 件。更新頻度・データソース・法律相談/申請代行の対象外・SLA・解約・rate limit リセット等。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://zeimu-kaikei.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://zeimu-kaikei.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://zeimu-kaikei.ai/docs/faq/"
  }
}
</script>

# FAQ

> **要約 (summary):** 税務会計AI についてよく聞かれる質問 16 件。更新頻度・データソース・法律相談/申請代行の対象外・SLA・解約・rate limit リセット等。

## Q1. データはどの頻度で更新されるか (Update cadence)

canonical データは **月次で再 ingest** を予定。日次の差分更新は Month 2 (2026-06 以降) で順次導入する。`GET /meta` の `last_ingested_at` / `data_as_of` で最新タイムスタンプを確認できる。

重要な制度変更 (年度替わり時の要綱改訂等) は手動で priority 投入する。

## Q2. データソースは何か (Data sources)

全データが **日本政府の一次資料** から取得:

- 農林水産省 (MAFF) — 農業系制度要綱
- 経済産業省 (METI) / 中小企業庁 — ものづくり / IT 導入補助金等
- 日本政策金融公庫 (JFC) — 青年等就農資金 / スーパー L
- 各都道府県 / 市区町村 公式サイト — 地域制度
- e-Gov 法令検索 — 法令本文
- 環境省 / 厚生労働省 — 省庁系施策

すべてのレコードに `source_mentions` (URL + fetched_at) が付与されており、`GET /v1/programs/{unified_id}` で参照可能。

## Q3. これは法的・税務アドバイスか (Is this legal/tax advice?)

**いいえ。** 税務会計AI は構造化された一般情報 (制度要件・金額・URL・排他関係) を返す **データ API** であり、個別案件の助言を行わない。

- 行政書士法第1条の2 (書類作成独占)
- 税理士法第52条 (税務代理独占)
- 弁護士法第72条 (法律事務取扱独占)

上記の業務は提供せず、構造的にリスクを排除する設計。個別判断は一次資料または専門家へ。

## Q3.1. これで法律相談できますか? / 申請代行できますか? (Can this give legal advice or file applications?)

いいえ、 これは検索 API です。 法律相談 / 税務相談 / 行政書士業務代行は提供しません。 弁護士法 § 72 / 税理士法 § 52 / 行政書士法 § 1 該当行為は対象外。 検索結果は一次資料 URL を必ず開いて確認してください。

## Q4. サブスクリプションの解約方法 (Canceling)

`POST /v1/billing/portal` で Stripe Customer Portal URL を取得し、ブラウザから解約操作。当期末まで API key 有効、次期から revoke される。詳細: [pricing.md](./pricing.md#解約返金-cancellation--refunds)。

## Q5. データの正確性は保証されるか (Data accuracy)

**保証しない。** 各レコードに **tier ラベル** を付けて enrichment 充足度を正直に露出する。**tier は内容の正確性ではなく、当方が拾えた次元の数を表す指標**:

- **Tier S (114件):** URL + 一次資料 + A-J 次元のほぼ全て enriched
- **Tier A (1,340件):** 主要次元 enriched、一部 (J_statistics 等) が null
- **Tier B (4,186件):** 部分 enriched、coverage 中程度 (**網羅が浅い**)
- **Tier C (6,044件):** sparse、基本情報のみ
- **公開保留 (2,788件):** 二次レビュー待ち (default では検索結果から除外)

**全 tier で正確性は保証しない。** 検索結果は必ず `source_url` の一次資料を開いて内容確認すること。誤りを見つけた場合は issue にご報告ください。

## Q6. 日本語・英語の混在 (Japanese/English mix)

現状、API response / MCP tool description は **日本語 primary**。制度名・要綱・都道府県名はすべて日本語のまま返る。英訳版は Month 3 以降で検討 (海外 B2D 市場)。

field 名 (`unified_id`, `primary_name` 等) は英語 snake_case で統一。

## Q7. 法人 / エンタープライズ契約 (Enterprise inquiries)

完全セルフサーブ / 自動化方針。Free (50 req/月 per IP) と Paid (¥3/req 税別・税込 ¥3.30・従量・無上限) の 2 プラン固定で、個別契約・個別見積・請求書払い・専用レート上限等は提供していない。大量に叩く場合も ¥3/req が変わらず適用される (100 万 req/月で ¥300 万、税別)。

## Q8. SLA はあるか (SLA)

launch 時点は **全 tier best effort**。契約上の可用性保証はなく、運用実績を基に引き上げる。詳細は [sla.md](./sla.md):

- **全 tier:** best effort、月次目標 99.0% (fair-warning / 契約上の保証ではない)
- 個別 SLA 条項 (99.5% 以上 / credit 条項等) は提供していない (完全セルフサーブ方針)

public status page は Month 1 末に公開予定 (`status.zeimu-kaikei.ai` placeholder)。

## Q9. オフライン / self-host 可能か (Offline / self-hosted)

- Python package `autonomath-mcp` をインストールすれば **MCP server はローカルで動作**する (SQLite DB を含む)。
- ただし **DB ファイルの定期更新は別途必要**。canonical データの配布方法は Month 2 以降で検討中 (S3 snapshot / delta 配信等)。
- 完全オフライン運用の個別契約は提供していない (セルフサーブ方針)。

## Q10. rate limit のリセットタイミング (Reset timing)

**匿名 (Free): JST 月初 00:00 月次リセット** (IP 単位、YYYY-MM-01 bucket)。`anon_rate_limit` テーブルで IP hash ごとに暦月単位で管理。
**Paid (認証済み): 上限なし**。Stripe 従量課金、メーター集計は UTC 0 時基準 (subscription anchor date)。翌 UTC 月に請求。

匿名上限超過時のレスポンス: `429 Too Many Requests`, body `{"detail": "anon rate limit exceeded", "limit": 50, "resets_at": "<次月 JST 00:00>"}`。

## Q11. API key の revoke / rotate (Revoking keys)

- **Stripe 経由で自動 revoke:** サブスクリプション解約時、webhook (`customer.subscription.deleted`) で自動的に `revoked_at` セット。
- **手動 rotate:** `POST /v1/billing/portal` で Customer Portal にアクセスし、一度解約 → 再契約で新しい key 発行。
- **即時 revoke が必要な場合** (漏洩時等): `info@bookyou.net` に連絡で個別対応。

## Q12. MCP クライアントの対応状況 (MCP client support)

- **Claude Desktop:** 公式対応 (`claude_desktop_config.json` に登録)
- **Cursor:** MCP 対応あり
- **ChatGPT:** Plus 以降 (2025-10+) で MCP 対応
- **Gemini:** MCP 対応あり

詳細は各クライアントのドキュメント参照。共通で stdio 転送に対応。

## Q13. 排他ルールは全制度をカバーしているか (Exclusion coverage)

**現在 181 件** (hand-seeded 35 = 農業核心 22 + 非農業 13 + 要綱 一次資料 auto-extracted 146)。kind 内訳は exclude 125 / prerequisite 17 / absolute 15 / その他 24。非農業は IT導入・持続化・M&A・雇用調整・経営強化税制、auto-extracted は 要綱 PDF パーサで抽出した primary-source evidence 付 mutex / cooldown / 同一資産 exclusive。

カバー範囲外の組み合わせで `check_exclusions` が空配列 (`hits: []`) を返しても「併用安全」を保証するものではない。最終判断は一次資料で確認を。詳細: [exclusions.md](./exclusions.md)。

## Q14. 全文検索の日本語検索の挙動 (Japanese FTS behavior)

- 3 文字以上のクエリ: 全文検索インデックス (3-gram) で検索 (`rank` 順)
- 2 文字以下のクエリ: `primary_name` / `aliases_json` の substring 一致にフォールバック

例: `q=IT導入` は 3 文字以上なので FTS ヒット、`q=IT` は substring。英数字の短いクエリは精度が落ちるため、3 文字以上を推奨。

## Q15. データの商用利用・再配布は可能か (Commercial use / redistribution)

- **API response の商用利用:** 自社プロダクト内での参照・表示は OK (Free / Paid どちらでも)。
- **bulk 再配布 (データセット販売等):** 元データのライセンスは出典ごとに異なる (例: e-Gov 法令 = CC-BY 4.0、国税庁 適格事業者 = PDL v1.0 出典明記+編集注記、JST = proprietary 等)。 一律で再配布可能とは限らないため、bulk 再配布前に各 record の `source_url` のライセンス条件を必ず確認すること。
- **出典明記:** 必須 (`official_url` / `source_urls` をユーザーに提示)。集約サイト経由ではなく、各 record の一次資料 URL を表示する。
- 個情法対応として applicant 個人名のマスク等は実施済み。

## その他

上記で解決しない場合:

- GitHub issues (repo URL: launch 時に公開)
- email: `sss@bookyou.net` (暫定、launch 時に dedicated アドレス)

## 関連

- [index.md](./index.md) — 概要
- [getting-started.md](./getting-started.md) — 導入
- [api-reference.md](./api-reference.md) — 全エンドポイント仕様
- [pricing.md](./pricing.md) — 料金 (Free 50 req/月 / Paid ¥3/req)
- [exclusions.md](./exclusions.md) — 排他ルールの概念
- [mcp-tools.md](./mcp-tools.md) — MCP ツール
