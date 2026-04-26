<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "AutonoMath FAQ",
  "description": "AutonoMath についてよく聞かれる質問 15 件。更新頻度・データソース・SLA・解約・rate limit リセット等。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://autonomath.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://autonomath.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://autonomath.ai/docs/faq/"
  }
}
</script>

# FAQ

> **要約 (summary):** AutonoMath についてよく聞かれる質問 15 件。更新頻度・データソース・SLA・解約・rate limit リセット等。

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

**いいえ。** AutonoMath は構造化された一般情報 (制度要件・金額・URL・排他関係) を返す **データ API** であり、個別案件の助言を行わない。

- 行政書士法第1条の2 (書類作成独占)
- 税理士法第52条 (税務代理独占)
- 弁護士法第72条 (法律事務取扱独占)

上記の業務は提供せず、構造的にリスクを排除する設計。個別判断は一次資料または専門家へ。

## Q4. サブスクリプションの解約方法 (Canceling)

`POST /v1/billing/portal` で Stripe Customer Portal URL を取得し、ブラウザから解約操作。当期末まで API key 有効、次期から revoke される。詳細: [pricing.md](./pricing.md#解約返金-cancellation--refunds)。

## Q5. データの正確性は保証されるか (Data accuracy)

**保証しない** が、各レコードに **tier ラベル** と **coverage_score** を付けて正直に露出する:

- **Tier S (59件):** URL + 一次資料 + 全 A-J 次元 enriched、verified
- **Tier A (525件):** 主要次元は verified、一部 J_statistics 等が null
- **Tier B (3,297件):** 部分 enriched、coverage 中程度 (**網羅が浅い**)
- **Tier C (2,421件):** sparse、基本情報のみ
- **Tier X (469件):** excluded / deprecated (default では検索結果から除外)

**Tier B 以下は内容検証が浅いため、本番投入前に `official_url` で一次確認を推奨。** 誤りを見つけた場合は issue にご報告ください。

## Q6. 日本語・英語の混在 (Japanese/English mix)

現状、API response / MCP tool description は **日本語 primary**。制度名・要綱・都道府県名はすべて日本語のまま返る。英訳版は Month 3 以降で検討 (海外 B2D 市場)。

field 名 (`unified_id`, `primary_name` 等) は英語 snake_case で統一。

## Q7. 法人 / エンタープライズ契約 (Enterprise inquiries)

完全セルフサーブ / 自動化方針。Free (50 req/月 per IP) と Paid (¥3/req 税別・税込 ¥3.30・従量・無上限) の 2 プラン固定で、個別契約・個別見積・請求書払い・専用レート上限等は提供していない。大量に叩く場合も ¥3/req が変わらず適用される (100 万 req/月で ¥300 万、税別)。

## Q8. SLA はあるか (SLA)

launch 時点は **全 tier best effort**。契約上の可用性保証はなく、運用実績を基に引き上げる。詳細は [sla.md](./sla.md):

- **全 tier:** best effort、月次目標 99.0% (fair-warning / 契約上の保証ではない)
- 個別 SLA 条項 (99.5% 以上 / credit 条項等) は提供していない (完全セルフサーブ方針)

public status page は Month 1 末に公開予定 (`status.autonomath.ai` placeholder)。

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

## Q14. FTS5 の日本語検索の挙動 (Japanese FTS behavior)

- 3 文字以上のクエリ: FTS5 trigram で検索 (`rank` 順)
- 2 文字以下のクエリ: `primary_name` / `aliases_json` の substring 一致にフォールバック

例: `q=IT導入` は 3 文字以上なので FTS ヒット、`q=IT` は substring。英数字の短いクエリは精度が落ちるため、3 文字以上を推奨。

## Q15. データの商用利用・再配布は可能か (Commercial use / redistribution)

- **API response の商用利用:** 自社プロダクト内での参照・表示は OK (Free / Paid どちらでも)。
- **bulk 再配布 (データセット販売等):** 元データ自体は一次資料のため出典明記で再配布可能。自社サービスに組み込む場合は Paid (¥3/req 税別 / 税込 ¥3.30) で叩けば制限なし。
- **出典明記:** 推奨 (`official_url` / `source_urls` をユーザーに提示)。
- 元データ自体は日本政府の公開一次資料であり、出典明記で再配布可能なものが中心。個情法・GDPR 対応として applicant 名のマスク等は実施済み。

## その他

上記で解決しない場合:

- GitHub issues (repo URL: launch 時に公開)
- email: `sss@bookyou.net` (暫定、launch 時に dedicated アドレス)

## 関連

- [index.md](./index.md) — 概要
- [getting-started.md](./getting-started.md) — 導入
- [api-reference.md](./api-reference.md) — 全エンドポイント仕様
- [pricing.md](./pricing.md) — tier 別制限
- [exclusions.md](./exclusions.md) — 排他ルールの概念
- [mcp-tools.md](./mcp-tools.md) — MCP ツール
