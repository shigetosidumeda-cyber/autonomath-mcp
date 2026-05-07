# Launch day email — first 500 subscribers (operator-only)

> **operator-only**: launch day email blast 用 final draft。mkdocs.yml `exclude_docs` で公開除外。
>
> Send target: T+0 (2026-05-06) 10:00 JST
> Recipients: `subscribers` table の opted-in 購読者 (CLAUDE.md 参照、subscribe form 経由のみ)
> Sender: info@bookyou.net (Bookyou株式会社)
> Mailer: operator 用 transactional mailer (`src/jpintel_mcp/email/`)
>
> Validate (memory `feedback_validate_before_apply`):
> - opted-in 確認 (cold list に送らない、memory `feedback_organic_only_no_ads`)
> - 数値 14,472 / 66 / ¥3 統一
> - INV-22: 過剰強調削除済み
> - unsubscribe link 必須 (特商法 / GDPR)

---

## Subject

```
jpcite launch: 日本制度を 1 query で AI に聞く
```

(全角 24 文字、Gmail / Outlook の preview pane で truncate されない)

---

## Preheader (preview text)

```
本日 launch。日本の公的制度データを REST + MCP で呼び出せます。¥3/billable unit 完全従量、匿名 3 req/日 per IP は無料です。
```

---

## Body (988 chars / within 1,000 cap)

```
{{ subscriber_name | default("購読者各位") }} 様

Bookyou株式会社の梅田です。
本日 2026-05-06、jpcite を launch しました。

日本の公的制度データ — 補助金・融資・税制優遇・認定制度・法令・行政処分・
適格事業者 — を AI エージェントが 1 query で呼び出せる REST + MCP API です。

▼ 収録 (2026-05-06 時点)
- 制度 14,472 件 (経産省・農水省・中小企業庁・公庫・47 都道府県、一次資料)
- 採択事例 2,286 / 融資 108 / 行政処分 1,185
- 法令 9,484 (e-Gov CC-BY) / 適格事業者 13,801 (NTA PDL v1.0)
- 主要な公開行に出典 URL + 取得時刻を付与

▼ どう使うか (5 audience 別)
- AI agent 開発者: Manifest 1 行で MCP ツールを呼び出し (uvx autonomath-mcp)
- 税理士 / 認定支援機関: Claude で措置法を条文単位 walkthrough
- 行政書士: 補助金 + 融資 + 許認可を 1 call で一括
- SMB 経営者 / 経理: ChatGPT で「うちで使える制度?」匿名 3 req/日 無料
- VC / DD: 法人番号 1 つで処分歴 + 採択歴 + 適格事業者 を一括取得

▼ 価格
¥3/billable unit 税別 (税込 ¥3.30) 完全従量。tier / seat / 年間最低額なし。
匿名 3 req/日 per IP は無料 (JST 翌日 00:00 リセット、API key 不要)。

▼ 始め方
1. ドキュメント: https://jpcite.com/docs/getting-started/
2. API リファレンス: https://jpcite.com/docs/api-reference/
3. PyPI: pip install autonomath-mcp
4. プレスキット: https://jpcite.com/press/

質問・要望は本メールへの返信または GitHub issues へ。
電話・対面・営業 cold call は zero-touch 方針のため対応していません。

宜しくお願い致します。

---
梅田茂利 / Bookyou株式会社
東京都文京区小日向2-22-1 / info@bookyou.net

配信停止: {{ unsubscribe_url }}
```

---

## Pre-send checklist (operator)

- [ ] mailer config: from = info@bookyou.net, reply-to = info@bookyou.net
- [ ] subscriber list = opted-in only (cold list に絶対送らない)
- [ ] `{{ subscriber_name }}` placeholder が template engine で正常 render
- [ ] `{{ unsubscribe_url }}` が機能する unique link (per-recipient)
- [ ] 件名 24 文字 / preheader 60 文字以内確認
- [ ] body 1,000 chars 以内確認 (上記 988)
- [ ] 数値 14,472 / 55 / ¥3 統一確認
- [ ] テスト送信 (operator 自身の Gmail / Outlook / Yahoo) で render 確認
- [ ] SPF / DKIM / DMARC pass 確認 (送信失敗回避)
- [ ] launch 関連 URL 全て 200 動作確認

---

## Send strategy

- **Batch size**: 100/min (mailer rate limit に合わせる)
- **Target**: opted-in subscribers のみ (estimated 30-300 at launch)
- **Time**: 10:00 JST, X 投稿 (09:00) の 1h 後 (購読者は X follower と一部
  overlap 想定)
- **Reply handling**: 24h 以内に operator 本人が手で返信 (zero-touch だが
  メール 1 窓口は維持)

---

## Post-send

- bounce / unsubscribe 率を 24h で確認 (memory `solo_ops_handoff` 参照)
- 過度な follow-up email 禁止 (「launch から 1 週間どうですか?」等は organic
  scope 逸脱)
- launch 後 case study が出たら別メールで送信 (separate batch)

---

## Reference

- subscribers table schema: CLAUDE.md
- 配信停止仕組み: 特商法 + GDPR 準拠 (memory `Bookyou株式会社 T号`)
- 営業 cold list NG: memory `feedback_organic_only_no_ads`
- INV-22 enforcement: 比較強調 / "absolute" / "guaranteed" 削除済み
