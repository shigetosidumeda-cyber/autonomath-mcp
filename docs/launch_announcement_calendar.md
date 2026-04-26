# Launch Announcement Calendar (operator-only)

> **operator-only**: launch sequence の運営者用カレンダー。mkdocs.yml の `exclude_docs` で公開除外。
>
> Launch day: **2026-05-06 (水) JST**

更新日: 2026-04-25 / Bookyou株式会社

---

## 全体方針

- 100% organic (memory `feedback_organic_only_no_ads`): 営業 / 広告 / 紹介費なし
- Zero-touch (memory `feedback_zero_touch_solo`): 電話・対面なし、メール 1 窓口
- ¥3/req 完全従量 (memory `project_autonomath_business_model`)
- 動作確認 → publish の順 (memory `feedback_validate_before_apply`)

各日付は **JST**。

---

## T-3d (2026-05-03 土) — Zenn 草稿 publish

**目的**: 検索 indexing を 3 日先行させる。Zenn は Google news index 早い

**Tasks**:

- [ ] `docs/blog/2026-05-06-launch-day-developer.md` (frontmatter `published: false`) を Zenn 用に再フォーマット
- [ ] Zenn 投稿 (operator アカウント、tag: `python`, `mcp`, `claude`, `補助金`, `api`)
- [ ] `published: false` のまま — 公式 launch は T+0
- [ ] Zenn URL を内部メモに記録、T+0 の HN 本文で参照
- [ ] Zenn 本文の数値が fact-sheet.md と一致しているか確認

**所要**: 2-3h
**Owner**: 梅田茂利

---

## T-2d (2026-05-04 日) — GitHub repo public

**目的**: GitHub stars の収集起点 + AI registry crawler に find される

**Tasks**:

- [ ] `pyproject.toml` の version 確認 (server.json と一致)
- [ ] `CHANGELOG.md` 最新版に launch entry 追加
- [ ] README.md の数値 (制度数等) を fact-sheet.md と整合
- [ ] `data/jpintel.db` `data/autonomath.db` `.bak.*` `.venv/` `.wrangler/` が `.gitignore` に入っているか確認
- [ ] private → public に変更
- [ ] GitHub topic tag 設定: `mcp`, `claude`, `python`, `api`, `japan`, `government-data`, `subsidy`
- [ ] GitHub release `v0.3.0` 作成 (CHANGELOG copy)
- [ ] GitHub URL を press kit に反映 (現状 placeholder)

**所要**: 3-4h
**Owner**: 梅田茂利

---

## T-1d (2026-05-05 月) — PyPI publish

**目的**: `uvx autonomath-mcp` で誰でもインストール可能に

**Tasks**:

- [ ] `python -m build` で wheel 生成 (CLAUDE.md release checklist 参照)
- [ ] dist/ 内容確認
- [ ] `twine upload dist/*` (PYPI_TOKEN 必要)
- [ ] PyPI ページ確認: https://pypi.org/project/autonomath-mcp/
- [ ] `uvx autonomath-mcp` をクリーン環境で動作確認
- [ ] MCP registry に publish (smithery, glama, mcp.so, etc., `scripts/mcp_registries.md` 参照)
- [ ] Cloudflare Pages production deploy 確認 (autonomath.ai)
- [ ] Fly.io production deploy 確認 (api.autonomath.ai)
- [ ] Stripe metered live mode 動作確認 (¥3 single test charge)

**所要**: 4-5h
**Owner**: 梅田茂利

---

## T+0 (2026-05-06 水) — Launch day

**目的**: 公式 launch、HN / X / 購読者へ一斉告知

**Time slots (JST)**:

### 09:00 JST — X (Twitter) launch tweet

- [ ] `docs/organic_outreach_templates.md` の「日本語 thread」+ 「英語 thread」を投稿 (個人 X account)
- [ ] press kit + docs URL を pin

### 10:00 JST — 購読者 email

- [ ] subscribers (`subscribers` table の opted-in 全員) へ launch announcement send (operator 用 mailer)
- [ ] 件名: `[AutonoMath] 本日 launch — 日本の公的制度を AI agent から 1 query で`

### 20:00 JST (= 07:00 ET) — Hacker News Show HN

- [ ] `docs/organic_outreach_templates.md` の「Show HN announcement」template を投稿
- [ ] 同 template の first comment 即座に投稿 (HN の慣習)
- [ ] HN URL を X に追加投稿 (「HN にも上げました」程度、過剰宣伝禁止)
- [ ] **自演 upvote / sockpuppet NG** (HN ban worthy)

### 22:00 JST — LinkedIn

- [ ] `docs/organic_outreach_templates.md` の LinkedIn post を投稿 (個人 LinkedIn)

### 翌日午前 (現地時間) — Reddit

- [ ] r/MachineLearning は **Saturday の Self-Promotion Thread のみ可** (T+0 が水曜なので次の Saturday まで待つ → T+3d に投稿)
- [ ] r/LocalLLaMA は MCP 文脈で OK (T+0 投稿可)
- [ ] r/programming は self-promotion 規約注意

**所要**: 全日張り付き (返信対応含む)、合計 8-10h
**Owner**: 梅田茂利

---

## T+1d (2026-05-07 木) — 5 audience pitch detailed blog

**目的**: 5 personas (Dev / 税理士 / SMB / VC / GovTech) ごとに use case を深掘り、SEO + GEO 両狙い

**Tasks**:

- [ ] `docs/blog/2026-05-5_audience_pitch.md` の `published: false` → `true` に flip
- [ ] mkdocs.yml の nav から hidden 解除
- [ ] mkdocs build --strict PASS 確認
- [ ] Cloudflare Pages 自動 deploy 確認
- [ ] 個別の audience に向けた X post (5 投稿、24h 間隔で連投せず)
- [ ] 個別の Zenn / Qiita 投稿 (税理士向けは note.com 検討)

**所要**: 4-5h
**Owner**: 梅田茂利

---

## T+3d (2026-05-09 土) — Case study collection start

**目的**: 実顧客 quote の正式採取開始 (現状 quotes.md は persona quote)

**Tasks**:

- [ ] launch 後 3 日間で API key 登録した顧客 (anonymous tier 超過を含む) を `subscribers` + `api_keys` から抽出
- [ ] 上位利用者 5-10 名に case study request email 送信 (テンプレ: 「使用感を伺えますか?」、見返り提案禁止)
- [ ] 返信 quote を `site/press/quotes.md` の「実顧客 quote」セクションに追加 (operator が手動校正)
- [ ] 実名・社名公表は本人許諾必須
- [ ] r/MachineLearning Self-Promotion Saturday に launch post 投稿 (T+3d が土曜なら可)

**所要**: 3-4h (送信 + 返信待ち)
**Owner**: 梅田茂利

---

## T+7d (2026-05-13 水) — First metrics report (transparent dashboard 公開)

**目的**: launch 後 1 週間の数値を transparent に公開、organic trust 強化

**Tasks**:

- [ ] `site/stats.html` の dashboard を update (launch 後 7 日間の req 数 / 一意 IP 数 / unique tools used / paid req 数 / 売上)
- [ ] `docs/blog/` に「AutonoMath launch 後 7 日のメトリクス」blog 記事を新規作成
- [ ] 数値 transparency: req 数・売上は実績ベース (推測値・誇張禁止)
- [ ] 失敗・課題も併記 (memory `feedback_action_bias`: 即修正前提)
- [ ] X で thread 投稿 (memory: 完全 transparent dashboard)

**所要**: 4-6h
**Owner**: 梅田茂利

---

## 投稿時の禁止事項 (必読)

これは launch 期間中、すべての投稿・送信・公開で守る:

1. **数値捏造禁止** — fact-sheet.md と一致しない数値を投稿しない (memory `feedback_no_fake_data`)
2. **営業・cold call 禁止** — 「弊社にて貴社向けに...」のような営業文句 NG
3. **prtimes.jp / 日経 アグリゲータへ有料掲載依頼禁止** — earned coverage は OK
4. **「jpintel」brand を user-facing strings に出さない** (memory `project_jpintel_trademark_intel_risk`)
5. **tier / seat / 年間最低額 言及禁止** (memory `feedback_zero_touch_solo`)
6. **自演 upvote / sockpuppet 禁止** (HN / Reddit ban worthy、累積評価毀損)
7. **電話・対面取材確約禁止** — zero-touch 方針、メール only
8. **顧客 quote の許諾なし掲載禁止** — quotes.md の persona quote は明示「自作」、実顧客 quote は許諾後のみ

---

## 完了条件 (T+7d 時点)

- [ ] T-3d → T+7d の全 tasks が check 済み
- [ ] HN / X / LinkedIn / Zenn / Qiita / Reddit / 購読者 mail に launch 通知済み
- [ ] press kit (`docs/press_kit.md` + `site/press/*`) が公開状態
- [ ] launch metrics blog (T+7d) が publish
- [ ] 実顧客 quote 1 件以上が `quotes.md` に追加 (T+3d 採取分)
- [ ] mkdocs build --strict PASS

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
