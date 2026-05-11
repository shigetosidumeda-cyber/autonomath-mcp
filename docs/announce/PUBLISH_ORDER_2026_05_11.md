# jpcite 寄稿 8 本 — Publish Order 2026-05-11

audit 実施: 2026-05-11 / 対象: docs/announce/ 配下 8 本

## audit 観点 (6 軸)

1. **旧 brand**: 「税務会計AI」/「AutonoMath」/「zeimu-kaikei.ai」が前面でなく、SEO bridge marker として最小表記か (memory: feedback_legacy_brand_marker)
2. **7 業法 fence**: §52 / §72 / §73 / §19 / §27 / 診断士登録規則 / 弁理士法 §75 — 「弊社が判断」「最終回答」等の踏み込み無し
3. **solo zero-touch**: CS チーム / 営業担当 / 法務チーム / 専用 Slack の人的介在表現無し (memory: feedback_zero_touch_solo)
4. **広告ゼロ**: 「広告予算」/「marketing spend」/「リード獲得単価」言及無し (memory: feedback_organic_only_no_ads)
5. **¥3/req 表記**: 「¥3/req 完全従量 (税込 ¥3.30)」で統一、過去案 ¥1/req 等の混入無し
6. **誤字 / 旧 URL**: zeimu-kaikei.ai が active link で残っていないか (301 案内のみ可)

green = 全項 clean / yellow = 軽微指摘 (publish 前に 5 分 patch 推奨) / red = publish 不可 (修正必須)

---

## article-by-article audit

### 1. zenn_jpcite_mcp.md  [green]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し、jpcite + Bookyou 株式会社のみ |
| 7 業法 fence | green | §52 etc 7 業法を列挙して「個別税務・法律助言は出力しない」と明示、踏み込み表現無し |
| solo zero-touch | green | 「24h 以内に返信」のみ、CS チーム / 営業担当 等の表現無し |
| 広告ゼロ | green | 価格 + 無料 3 req/IP/日 のみ、広告予算等の言及無し |
| ¥3/req | green | 「¥3/req 完全従量 (税込 ¥3.30)」明記、計算例も全て ¥3.30 ベース |
| 誤字 / 旧 URL | green | jpcite.com のみ、zeimu-kaikei.ai 言及無し |

総合: **green**、優先 publish 候補。

---

### 2. note_jpcite_mcp.md  [green]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し |
| 7 業法 fence | green | 7 業法を列挙、「個別の税額計算 / 法的判断 / 適合性判定は出力しない」と明示 |
| solo zero-touch | green | 「24h 以内に返信」のみ |
| 広告ゼロ | green | 言及無し |
| ¥3/req | green | 「¥3/req (税込 ¥3.30)」+ 「無料 3 req/IP/日」 |
| 誤字 / 旧 URL | green | jpcite.com のみ |

総合: **green**、二番手 publish。

---

### 3. prtimes_jpcite_release.md  [green]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し |
| 7 業法 fence | green | 7 業法を列挙、「独占業務には踏み込まない設計」と明示 |
| solo zero-touch | green | 「24h 以内対応」のみ、Bookyou 株式会社広報担当 = 表現として人的チーム想起させない範囲 |
| 広告ゼロ | green | 言及無し |
| ¥3/req | green | 「¥3/req (税込 ¥3.30)」+ 「無料 3 req/IP/日」 |
| 誤字 / 旧 URL | green | jpcite.com のみ |

総合: **green**、3 番手 publish。

---

### 4. zeirishi_shimbun_jpcite.md  [yellow]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し |
| 7 業法 fence | green | 税理士法 §52 を 3 層 fence で防護と明示、踏み込み表現無し。「最終判断は資格専門家へ」を末尾に明示 |
| solo zero-touch | green | 「営業電話は行わず、organic outreach のみ」明記 |
| 広告ゼロ | green | 明示的に「営業電話行わず」+ organic のみ |
| ¥3/req | **yellow** | 「API 価格は ¥1/request」(L27) **旧価格表記が残存** — ¥3/req に修正必須 |
| 誤字 / 旧 URL | green | jpcite.com のみ |

総合: **yellow**、L27 の `¥1/request` を `¥3/req (税込 ¥3.30)` に修正してから publish。
ROI 試算の `¥5,940` の根拠も ¥3 ベースで再計算が必要 (5,940 req × ¥3.30 = ¥19,602 になるため、文脈に応じ「100 社 月次 = 1,800 req = ¥5,940」等に reframe)。

---

### 5. tkc_journal_jpcite.md  [yellow]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し |
| 7 業法 fence | green | 7 業法列挙 + disclaimer 階層を明示、踏み込み表現無し |
| solo zero-touch | green | 「営業電話行わず、organic outreach のみ」明記 |
| 広告ゼロ | green | 明示 organic only |
| ¥3/req | **yellow** | 「月額 ¥5,940」(L1, L3) は ROI 試算文脈で残るが、req 単価が文中に未表記 — 「¥3/req (税込 ¥3.30)」の base 表記を一文補足推奨 |
| 誤字 / 旧 URL | green | jpcite.com のみ |
| 注記 | yellow | 業法列挙の 6 番に「中小企業診断士・中小企業支援法」とあり、CLAUDE.md の「中小企業診断士登録規則」と表現が違う (法令名 vs 登録規則)、両論併記でも可だが統一推奨 |

総合: **yellow**、req 単価明記 1 行追加 + 6 番業法名統一を patch してから publish。

---

### 6. gyosei_kaiho_jpcite.md  [yellow]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し |
| 7 業法 fence | green | 行政書士法 §19 fence を 3 層で防護と明示、書類作成は「行政書士業務」と明確 |
| solo zero-touch | green | 「営業電話行わず、organic outreach のみ」明記 |
| 広告ゼロ | green | 明示 organic only |
| ¥3/req | **yellow** | 「API ¥1,200」(L56) — ROI 試算が ¥1/req 前提で計算されている可能性高、¥3 ベース再計算必要 |
| 誤字 / 旧 URL | green | jpcite.com のみ |

総合: **yellow**、ROI 試算 (¥1,200) を ¥3 base で再計算 + 単価明記 1 行追加してから publish。

---

### 7. ma_online_jpcite.md  [yellow]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し |
| 7 業法 fence | green | §72 / §52 / 金商法 §29 の 3 業法 fence を明示、契約書ドラフト等は「一切生成しない」と明確 |
| solo zero-touch | green | 「営業電話行わず、organic outreach のみ」明記 |
| 広告ゼロ | green | 明示 organic only |
| ¥3/req | **yellow** | 「価格は ¥1/request」(L66) + 「約 ¥120/案件」 — 旧 ¥1/req 表記が残存、¥3/req に修正必須 |
| 誤字 / 旧 URL | green | jpcite.com のみ |
| 注記 | yellow | L51 ROI 試算「API ¥600」も ¥1/req 前提 — ¥3 base 再計算必要 |
| 注記 | yellow | 業法列挙の中で **弁理士法 §75 が無い** (M&A 文脈なので任意だが、prtimes/zenn/note と整合させたいなら触れた方が良い) |

総合: **yellow**、¥1/req → ¥3/req patch + ROI 数字更新してから publish。

---

### 8. shindanshi_kaiho_jpcite.md  [yellow]

| 観点 | 結果 | 詳細 |
|------|------|------|
| 旧 brand | green | 旧称言及無し |
| 7 業法 fence | green | 中小企業支援法 + 税理士法 §52 の 2 業法 fence を明示、診断士業務の中核は変わらないと言及 |
| solo zero-touch | green | 「営業電話行わず、organic outreach のみ」明記 |
| 広告ゼロ | green | 明示 organic only |
| ¥3/req | **yellow** | 「月額 ¥3,300」(L1, L3, L48) — 文脈上 ROI 試算結果として表記、単価明記が無い。「¥3/req (税込 ¥3.30) を base に 1,000 req = ¥3,300」等 1 行補足推奨 |
| 誤字 / 旧 URL | green | jpcite.com のみ |
| 注記 | yellow | 業法列挙が「中小企業支援法」になっており、CLAUDE.md の「中小企業診断士登録規則」と表現差 — 両論併記でも可 |

総合: **yellow**、req 単価明記 1 行追加 + 業法名統一を patch してから publish。

---

## red 件数: 0 件 / yellow: 5 件 (4-8) / green: 3 件 (1-3)

red 無し、publish blocker 無し。yellow は ¥3/req 単価明記と ROI 試算再計算 (¥1/req → ¥3/req) が主軸。

---

## 推奨 publish 順序 (4-stage cascade)

### Stage 1 (Day 0, 2026-05-11 10:00 JST): Zenn

- **1st**: `zenn_jpcite_mcp.md` → Zenn
- 理由: AI 技術コミュニティ起点、developer organic 流入。GitHub / PyPI / Smithery 経由の self-discovery を最初に発火。
- 投下 surface: Zenn Books / Topics (mcp, claudecode, ai, rag, openapi, stripe)

### Stage 2 (Day 0, 2026-05-11 14:00 JST): note + PRTIMES 並列

- **2nd**: `note_jpcite_mcp.md` → note
- **3rd**: `prtimes_jpcite_release.md` → PRTIMES
- 理由: note は SNS 拡散 (X / LinkedIn) の起点、PRTIMES は検索エンジン indexing と業界紙パブリック露出。同時 publish で organic backlink 同時形成。

### Stage 3 (Day 1-5): 業界紙 5 本逐次 (¥3/req patch 後)

- **4th** (Day 1, 5/12): `zeirishi_shimbun_jpcite.md` → 税理士新聞 寄稿
- **5th** (Day 2, 5/13): `tkc_journal_jpcite.md` → TKC ジャーナル / TKC NF 系 寄稿
- **6th** (Day 3, 5/14): `gyosei_kaiho_jpcite.md` → 月刊行政書士 / 日本行政書士会連合会会報 寄稿
- **7th** (Day 4, 5/15): `ma_online_jpcite.md` → M&A Online / M&A 仲介協会会報 寄稿
- **8th** (Day 5, 5/16): `shindanshi_kaiho_jpcite.md` → 中小企業診断協会会報 / 月刊企業診断 寄稿
- 理由: 業界紙は organic backlink + 業界専門用語 SEO + 信頼性 stamp を 5 業界に分散して獲得。Day 1 から 1 日 1 本 cadence で publish することで初期 7 日間の検索 impression を accumulate。

---

## 24h 計測 KPI (各 publish 後)

各 article publish 後 24h で以下 3 指標を Google Search Console + Cloudflare Analytics + jpcite usage_events で実測:

### A. Organic search impressions (Google Search Console)
- 計測キー: `site:jpcite.com` + `"jpcite"` キーワード impressions
- target Day 0 (Zenn + note + PRTIMES 3 本 publish): 24h impressions ≥ 500
- target Day 5 (8 本 cumulative): 7 日 cumulative impressions ≥ 5,000
- 副指標: クエリ別 CTR、TOP 10 着地頁、新規 indexed pages

### B. Referral traffic (Cloudflare Analytics)
- 計測キー: Cloudflare 「Top referrers」+ Plausible (もし入れていれば) referrer breakdown
- target per article publish 後 24h: referral session ≥ 50 (Zenn / note)、≥ 30 (業界紙)
- 副指標: bounce rate < 60%、avg session > 60s、playground 着地比率

### C. GEO citation rate (AI agent からの直接参照率)
- 計測キー: jpcite usage_events `referer` で AI agent UA (Claude / GPT / Cursor / Codex hosted_mcp) を絞り込み、anon req 数 / day と比較
- target Day 0 publish 後 24h: AI-UA anon req ≥ 30 / day (現在 baseline ~ 5-10)
- target Day 5 cumulative: AI-UA anon req ≥ 100 / day
- 副指標: source_url click-through、`X-Client-Tag` で誰が citation してるか breakdown (Custom GPT name / Cursor workspace name 等)

---

## publish 前 patch 一覧 (4-7 を business hours で対応、合計 30 分以内)

| article | 修正項目 | 推奨 patch |
|---------|----------|------------|
| zeirishi_shimbun | `¥1/request` → `¥3/req (税込 ¥3.30)` 表記統一 + ROI 試算 ¥5,940 の base 説明追加 | L27 単価行 + L46 ROI 計算式 |
| tkc_journal | ¥3/req base 単価 1 行補足 + 業法 6 番統一 | L1 直後 + L17 |
| gyosei_kaiho | `API ¥1,200` → ¥3 base 再計算 + 単価明記 | L56 |
| ma_online | `¥1/request` + `¥120/案件` → ¥3 base 再計算、ROI ¥600 更新 | L51, L66 |
| shindanshi_kaiho | ¥3/req base 単価 1 行補足 + 業法名統一 | L1 直後 + 業法 sec |

---

## 全体まとめ

- red **0** / yellow **5** / green **3** (合計 8)
- publish blocker は zero、業界紙 5 本のみ ¥3/req 単価表記 patch 後に publish
- Day 0 (Zenn / note / PRTIMES) は patch 不要、即時 publish 可
- Day 1-5 で業界紙 1 日 1 本 cadence、7 日累計で organic impressions / referrals / AI-UA citation を多軸計測
