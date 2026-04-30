---
title: "AutonoMath architecture — primary-source SQLite + 全文検索 で構築する 制度 AI database"
description: "AutonoMath の data layer (jpintel + autonomath unified)、search layer (全文検索インデックス + ベクトル検索)、precompute scaffolding (現在 1/33 populated) と、出典 + 取得時刻つき 注記 の設計。"
tags:
  - architecture
  - sqlite
  - 全文検索
  - ベクトル検索
  - mcp
published: false
date: 2026-05-06
author: Bookyou株式会社 (T8010001213708)
---

# AutonoMath architecture — primary-source SQLite + 全文検索

> 公開日: 2026-05-06 / (T8010001213708)

AutonoMath は「LLM に投げる前に、出典つきで構造化された答えが SQLite に焼かれている」ことを目指す制度 database です。
ただし launch 時点で全部が live なわけではありません。 **今動いているもの** と **scaffold だけ立っているもの** を正直に分けて書きます。

---

## なぜ SQLite に焼くのか

LLM が日本の制度に弱い根本は 3 つ。

1. **散らかっている** — 47 都道府県 + 各省庁 + 公庫 + 国税庁、ぜんぶ別ポータル + PDF
2. **license が曖昧** — 「再配布可？」を一次資料まで遡らないと分からない
3. **構造化されていない** — 要綱の脚注 (「併用したら失格」等) が機械可読でない

これを LLM プロンプトで毎回解くのは無駄。一次資料を取りに行って canonical 化し、SQLite に焼く工程を AutonoMath 側で持ちます。

---

## 今 live な layer

### Data layer (出典つき 注記)

- `data/jpintel.db` (316 MB) — `programs` 11,684 行 (tier S/A/B/C, excluded=0) / `laws` 9,484 行 (本文 154 件 + メタデータ stubs 9,330 件、 本文ロード継続中) / `court_decisions` 2,065 / `invoice_registrants` 13,801 / `tax_rulesets` 35
- `autonomath.db` (8.29 GB, root 配置 — `data/autonomath.db` は 0 byte placeholder) — 503,930 件の正規化レコード / 612 万件の structured 属性 / 17.7 万件の関係性 link / 別名・略称 index 335,605 行 / 制度時系列 snapshot 14,596 行
- 各 row に `source_url` + `source_fetched_at` (programs 11,684 行で 99.9% / 99.86% 充足)
- 集約サイト (noukaweb / hojyokin-portal / biz.stayway) は `source_url` 禁止 — 一次資料のみ
- `source_fetched_at` は **「取得時刻」** であり「最終更新」ではない、と UI/docs で正直に表示

### Search layer

- **全文検索インデックス (3-gram 分割)** で日本語形態素境界をスキップ (`税額控除` を `税|額|控|除` の 3-gram で hit)
- 副作用: 単一漢字の偽 hit (`ふるさと納税` が `税額控除` query にぶら下がる) が出るので、2 文字以上の漢字熟語は phrase query (`"税額控除"`) を使う運用
- **ベクトル検索** は schema + 5-tier インデックスが入っており、 wire-up は段階点灯中。launch 時点で全 query が vec に乗るわけではなく、tier 別に gradual 開放

### API + MCP surface

- FastAPI (`/v1/*`, Stripe metered ¥3/req)
- FastMCP (stdio, 93 tools =  + 30 autonomath at default gates, protocol 2025-06-18)
- 静的サイト (Cloudflare Pages, `/programs/` 配下に SEO page を生成)
- `llms-full.txt` を月次再生成し LLM crawler 向けに publish

---

## まだ scaffold な layer (precompute)

ここは正直に書きます。

`autonomath.db` には **precompute 専用 table が 33 個** 切ってあります (migration で schema は完成済)。設計意図は cron で夜間に重い集計 (top subsidies by industry / combo pairs / seasonal calendar 等) を焼き、API は SELECT のみで返す、というもの。

現状:

- **33 table 中 1 table のみ populated** — program_health 集計 table が 66 行
- 残り 32 table は **0 行**
- `scripts/cron/precompute_refresh.py` の各 `_refresh_*` 関数は現在 `return 0` の no-op (各 table の population SELECT は per-tool ticket で順次差し込み予定)

つまり **「Pre-computed Reasoning Layer が live で全 query を裏打ちしている」状態ではありません**。launch 時点では FTS + entity-fact EAV + 排他ルール 181 件で全 tool が応答し、precompute は **roadmap-aware な scaffold** として共存しています。順次焼いていきますが、今日「全 33 table が冷えたまま動いている」のはそのとおりです。

---

## なぜ SQLite を選んだか

- **single-file replication** — Fly volumes / S3 / R2 へ 1 file コピー 1 行
- **read-heavy + small writes** に用途が一致 (月次 ingest + 24h 配信)
- **全文検索インデックス + ベクトル検索 が bundled** で別 search engine 不要
- **¥0 fixed cost** — 100% organic + solo + zero-touch を可能にする条件

---

## 関連ドキュメント

- [API リファレンス](https://jpcite.com/docs/api-reference/)
- [MCP ツール一覧](https://jpcite.com/docs/mcp-tools/)
- [Per-Tool 精度表](https://jpcite.com/docs/per_tool_precision/)

質問・要望は [info@bookyou.net](mailto:info@bookyou.net) または GitHub issues へ。

---

© 2026 Bookyou株式会社 (T8010001213708) · info@bookyou.net · AutonoMath
