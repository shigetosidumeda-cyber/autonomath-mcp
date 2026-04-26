---
title: "AutonoMath architecture — primary-source SQLite + FTS5 で構築する 制度 AI database"
description: "AutonoMath の data layer (jpintel + autonomath unified)、search layer (FTS5 trigram + sqlite-vec)、precompute scaffolding (現在 1/33 populated) と、出典 + 取得時刻つき envelope の設計。"
tags:
  - architecture
  - sqlite
  - fts5
  - sqlite-vec
  - mcp
published: false
date: 2026-05-06
author: Bookyou株式会社 (T8010001213708)
---

# AutonoMath architecture — primary-source SQLite + FTS5

> 公開日: 2026-05-06 / 運営: Bookyou株式会社 (T8010001213708)

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

### Data layer (出典つき envelope)

- `data/jpintel.db` (316 MB) — `programs` 10,790 行 (tier S/A/B/C, excluded=0) / `laws` 9,484 / `court_decisions` 2,065 / `invoice_registrants` 13,801 / `tax_rulesets` 35
- `autonomath.db` (8.29 GB, root 配置 — `data/autonomath.db` は 0 byte placeholder) — `am_entities` 503,930 / `am_entity_facts` 6.12M / `am_relation` 23,805 / `am_alias` 335,605 / `am_amendment_snapshot` 14,596
- 各 row に `source_url` + `source_fetched_at` (programs 10,790 行で 99.9% / 99.86% 充足)
- アグリゲータ (noukaweb / hojyokin-portal / biz.stayway) は `source_url` 禁止 — 一次資料のみ
- `source_fetched_at` は **「取得時刻」** であり「最終更新」ではない、と UI/docs で正直に表示

### Search layer

- **FTS5 trigram tokenizer** で日本語形態素境界をスキップ (`税額控除` を `税|額|控|除` の trigram で hit)
- 副作用: 単一漢字の偽 hit (`ふるさと納税` が `税額控除` query にぶら下がる) が出るので、2 文字以上の漢字熟語は phrase query (`"税額控除"`) を使う運用
- **sqlite-vec** は schema + 5-tier インデックスが入っており、 wire-up は段階点灯中。launch 時点で全 query が vec に乗るわけではなく、tier 別に gradual 開放

### API + MCP surface

- FastAPI (`/v1/*`, Stripe metered ¥3/req)
- FastMCP (stdio, 72 tools = 39 jpintel + 33 autonomath at default gates, protocol 2025-06-18)
- 静的サイト (Cloudflare Pages, `/programs/` 配下に SEO page を生成)
- `llms-full.txt` を月次再生成し LLM crawler 向けに publish

---

## まだ scaffold な layer (precompute)

ここは正直に書きます。

`autonomath.db` には **`jpi_pc_*` という precompute 専用 table が 33 個** 切ってあります (migration で schema は完成済)。設計意図は cron で夜間に重い集計 (top subsidies by industry / combo pairs / seasonal calendar 等) を焼き、API は SELECT のみで返す、というもの。

現状:

- **33 table 中 1 table のみ populated** — `jpi_pc_program_health` が 66 行
- 残り 32 table は **0 行**
- `scripts/cron/precompute_refresh.py` の各 `_refresh_*` 関数は現在 `return 0` の no-op (各 table の population SELECT は per-tool ticket で順次差し込み予定)

つまり **「Pre-computed Reasoning Layer が live で全 query を裏打ちしている」状態ではありません**。launch 時点では FTS + entity-fact EAV + 排他ルール 181 件で全 tool が応答し、precompute は **roadmap-aware な scaffold** として共存しています。順次焼いていきますが、今日「全 33 table が冷えたまま動いている」のはそのとおりです。

---

## なぜ SQLite を選んだか

- **single-file replication** — Fly volumes / S3 / R2 へ 1 file コピー 1 行
- **read-heavy + small writes** に用途が一致 (月次 ingest + 24h 配信)
- **FTS5 trigram + sqlite-vec が bundled** で別 search engine 不要
- **¥0 fixed cost** — 100% organic + solo + zero-touch を可能にする条件

---

## 関連ドキュメント

- [API リファレンス](https://autonomath.ai/docs/api-reference/)
- [MCP ツール一覧](https://autonomath.ai/docs/mcp-tools/)
- [Per-Tool 精度表](https://autonomath.ai/docs/per_tool_precision/)

質問・要望は [info@bookyou.net](mailto:info@bookyou.net) または GitHub issues へ。

---

© 2026 Bookyou株式会社 (T8010001213708) · info@bookyou.net · AutonoMath
