---
title: "LLM エージェントが使う API を設計する時に守った 7 つの前提"
emoji: "🧩"
type: "tech"
topics: ["api", "llm", "mcp", "design"]
published: false
---

## 人間向け API と LLM 向け API は設計原理が違う

REST API を 10 年書いてきて、MCP サーバー (jpcite: 9,998 件の補助金 DB) を書くときに一番悩んだのが**既存の API 設計パターンがほぼ役に立たない**ことでした。

人間向け API は、ドキュメントを読む人間と、そこからコードを書く人間がいる前提で設計されている。LLM 向け API は、**ドキュメントなしで初見の LLM が正しく使える**ことが要件になる。これは根本的に違う制約です。

この記事は jpcite の MCP ツール設計で、人間向け API の習慣を捨てた 7 つの前提をまとめます。

## (1) JSON 構造は flat に近く、ネストは 3 階層まで

LLM は JSON を木構造として理解しているように見えますが、実際には**トークン列として attention を当てている**。深いネストがあると、子要素の値と親要素のキーの距離がトークン単位で長くなり、attention で失われる。

```json
// NG: 深いネスト (5 階層)
{
  "program": {
    "meta": {
      "source": {
        "authority": {
          "name": "農林水産省"
        }
      }
    }
  }
}

// OK: flat (2 階層)
{
  "program_name": "...",
  "source_authority_name": "農林水産省",
  "source_url": "..."
}
```

3 階層までが実用的な上限。それ以上はキーを展開してフラットにする。

## (2) unified_id は決定論的で grep 可能

LLM はコード補完で ID を生成することがあるので、**予測可能な命名則**にする。jpcite では:

```
{prefecture}_{kind}_{source}_{slug}_{sha1[:7]}

例: saitama_subsidy_maff_sousetsu_a7f3c21
```

これで何が嬉しいか:

- LLM が `saitama_subsidy_*` で prefix 検索を自然に提案できる
- ログを grep で追える
- ドキュメント内で ID を機械的に検証できる
- sha1 suffix で衝突を防ぎつつ、短いので人間も読める

UUID v4 にしない理由は、LLM が生成する例示コードに偽の UUID を混ぜてしまうから (hallucination が grep で見分けられない)。

## (3) `description` は 1 文で結論、続けて詳細

人間向け API doc は「概要 → 詳細 → 例」の順で書く。LLM 向けは**最初の 1 文に decision を入れる**。

```yaml
# NG: 人間向け (前置きが長い)
description: |
  このツールは補助金データベースから条件に一致する制度を検索するためのエンドポイントで、
  複数の条件をANDで組み合わせて使用することができます。返り値は...

# OK: LLM 向け (1 文で結論)
description: |
  補助金を検索する。返り値は MonetaryGrant 配列。
  条件: prefecture (都道府県), target_types (個人/法人), funding_purpose, etc.
  すべて AND 結合。該当なしは [] を返す。
```

最初の 200 字で「この tool を呼ぶべきか」の判定がつくように書く。Claude の tool selection ロジックは description の先頭を強く見ます。

## (4) null vs [] vs "" を意味で分ける

ここは人間向け API と全く逆になる。LLM はこの 3 つを**意味が違うシグナル**として読む。

| 値 | 意味 |
|-----|------|
| `null` | 未確認 / 情報がない (「調べていない」) |
| `[]` | 空配列 (「該当なし」と確認済み) |
| `""` | 空文字列 (**非推奨**、意味が曖昧) |

```json
// OK
{
  "exclusion_rules": [],         // 除外ルールがないと確認済み
  "last_audited_at": null,       // 監査済みかは未確認
  "source_url": "https://..."    // 文字列は必ず意味のある値
}

// NG
{
  "exclusion_rules": "",         // 空文字で配列を表現 (意味不明)
  "last_audited_at": "",         // 空文字で null を表現 (意味不明)
  "source_url": null             // URL が null なのは情報欠損
}
```

LLM は `null` を見ると「調べる tool を追加で呼ぶべきか」と判断する。`[]` を見ると「確認済みなのでこれ以上探さない」と判断する。この区別が UX に効きます。

## (5) エラーは自然言語で返す

REST API の定石は `ERR_VALIDATION_002` のような code を返して、別途エラーコード表を参照させることですが、LLM 向けは**自然言語で十分**。

```json
// NG: code だけ
{ "error": "ERR_VALIDATION_002" }

// OK: 自然言語
{
  "error": "amount は 0 以上の整数を指定してください。受け取った値: -100"
}
```

LLM はこのエラーメッセージを読んで、ユーザーに翻訳したり、自動でリトライロジックを組んだりできる。code を返すと、別途 code→message の対応表を LLM に教える必要があり、context を浪費する。

code を併記するのは良い (機械判定用)。しかし**人間が読める message を必ず同梱**する。

## (6) Pagination は cursor ベース、limit <= 50

offset / limit pagination は LLM と相性が悪い。ページ番号を LLM が連続で生成すると、途中でスキップしたり重複取得したりする。

**cursor-based pagination** にすると、LLM は「next_cursor が返ってきたら再度呼ぶ」というシンプルなルールで動ける。

```json
{
  "results": [...],
  "next_cursor": "eyJvZmZzZXQiOjUwfQ==",
  "has_more": true
}
```

さらに `limit` のデフォルトと上限を**厳しめに絞る** (jpcite は default=20, max=50)。LLM の context window を節約するため。人間向けなら max=1000 にしても問題ないが、LLM は 1000 件を context に流し込むと他の思考余地がなくなる。

## (7) Rate-limit は HTTP 429 + Retry-After + natural-language message

rate-limit は LLM がハマりやすい。Retry-After ヘッダーだけでは LLM が「待つべきか諦めるべきか」判断できないことがある。

```
HTTP/1.1 429 Too Many Requests
Retry-After: 604800
Content-Type: application/json

{
  "error": "レート制限に達しました。JST 月初 00:00 にリセットされます。無料枠は匿名 50 req/月 per IP です。",
  "retry_after_seconds": 604800,
  "current_quota": { "used": 50, "limit": 50, "reset_at": "2026-05-01T00:00:00+09:00" }
}
```

自然言語メッセージに**次のアクションと数値コンテキスト**を両方入れる。

## MCP ツールスキーマで気をつけたこと

MCP (Model Context Protocol) でツールを定義するときは、tool description に**動機**を書くのが効きます。「何をするか」だけでなく「なぜ呼ぶか」。

```python
@mcp.tool()
def check_exclusions(
    unified_ids: list[str],
    applicant_type: str,
    household_income: int | None = None,
) -> dict:
    """
    候補制度に対して除外ルールを機械的に判定する。

    動機: search_programs で候補を得た後、申請者の属性
    (世帯所得、従業員数、法人設立年等) で除外される制度を
    事前に除外するために使う。search_programs だけでは
    この判定は返らない。

    返り値: excluded (bool), reason (理由文字列), rule_id
    """
```

「search_programs だけでは返らない」という**他ツールとの境界**を書くと、LLM がツール選択で迷わなくなる。

## jpcite の schema 例

実際の tool 出力から抜粋。

### search_programs の返り値 (抜粋)

```json
{
  "results": [
    {
      "unified_id": "saitama_subsidy_maff_sousetsu_a7f3c21",
      "title": "令和8年度 ○○交付金",
      "authority": "農林水産省",
      "amount_max": 50000000,
      "amount_max_description": "5,000万円 (補助率 1/2 以内)",
      "deadline": "2026-06-30",
      "target_types": ["法人", "認定農業者"],
      "exclusion_rule_ids": ["MAFF_INCOME_CAP_2025"],
      "source_url": "https://www.maff.go.jp/...",
      "last_updated": "2026-04-20"
    }
  ],
  "total": 1,
  "next_cursor": null,
  "has_more": false
}
```

flat (2 階層)、null vs [] が明確、source_url と last_updated が必ず入っている。

### エラーレスポンス

```json
{
  "error": "prefecture には都道府県名 (漢字) を指定してください。受け取った値: 'Tokyo'",
  "suggested_values": ["東京都", "神奈川県", "埼玉県", "..."],
  "field": "prefecture"
}
```

`suggested_values` を付けるのは、LLM が自己修正してリトライできるようにするため。

## まとめ

7 つの前提をもう一度:

1. JSON は flat、ネスト 3 階層まで
2. ID は決定論的で grep 可能
3. description は 1 文で結論
4. null / [] / "" を意味で分ける
5. エラーは自然言語で返す
6. Pagination は cursor、limit は厳しめ
7. Rate-limit は 429 + Retry-After + 自然言語

どれも人間向け API 設計の常識と一致するものもあれば、ずれるものもあります。**LLM が初見で使えるか**が判定基準です。

関連記事:
- [Claude Desktop から日本の補助金 9,998 件を直接引ける MCP サーバーを書いた](./mcp-claude-desktop-autonomath)
- [補助金 API で『採択率予測』を実装しなかった理由](./why-no-shouritsu-yosoku)
- [2026 年、LLM 引用 SEO (GEO) の実測レポート](./llm-citation-seo-2026)

---

jpcite: https://jpcite.com (Bookyou株式会社)
