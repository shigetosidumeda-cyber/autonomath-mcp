# A/B Copy Variants — AutonoMath

> **要約:** 2026-05-06 launch 直後から回す A/B テスト用のコピー素材集。`docs/conversion_funnel.md` §4 の P0 レバー「Pricing 上部 curl snippet 常設」「Hero 明瞭化」に対応する paste-ready variant。Japanese primary、Do-not-edit-HTML 原則 (本稿は投入前の素材庫)。ドメイン名は rebrand pending のため `zeimu-kaikei.ai` placeholder で固定。

関連: `site/index.html` L74-85 (index hero)、`site/pricing.html` L46-48 (pricing hero)、L50-108 (price grid)、`docs/conversion_funnel.md` §4 #2, §5 T3/T9。

---

## 1. `site/index.html` Hero (L74-85)

### Control A (現行)

```html
<h1 id="hero-title">日本の制度を、API で。</h1>
<p class="hero-sub">6,658 programs. Exclusion-aware. MCP-native.</p>
<p class="hero-tag">Jグランツ は application portal、AutonoMath は discovery + compatibility API。AI エージェントから直接呼べる。</p>
<div class="cta-row">
  <a class="btn btn-primary" href="/docs/getting-started">5 秒で始める</a>
  <a class="btn btn-secondary" href="#" aria-label="GitHub リポジトリを開く">View on GitHub</a>
</div>
<p class="hero-note">Agri 制度から汎用へ拡張中 (Week 2-4 で非農業 exclusion 50 件追加予定)。</p>
```

### Variant B — value-first (できる事に寄せる)

```html
<h1 id="hero-title">補助金 6,658 件を、1 行の curl で。</h1>
<p class="hero-sub">検索 / 詳細 / 排他チェック を REST + MCP で直呼び。SDK 不要。</p>
<p class="hero-tag">「該当制度の一覧が欲しい」「この 2 つは併用できる?」を AI エージェントが自前で引ける。</p>
<div class="cta-row">
  <a class="btn btn-primary" href="/docs/getting-started">API キーを取得</a>
  <a class="btn btn-secondary" href="#" aria-label="GitHub リポジトリを開く">View on GitHub</a>
</div>
<p class="hero-note">農業制度を核に、非農業 50 件を Week 2-4 で追加予定。</p>
```

### Variant C — trust-first (出典 + 更新頻度 + 仕様準拠)

```html
<h1 id="hero-title">日本の制度を、一次資料 URL 付きで。</h1>
<p class="hero-sub">6,658 programs / 全件 source_url + fetched_at / 週次更新 / MCP 2025-06-18 対応。</p>
<p class="hero-tag">Jグランツ は application portal、AutonoMath は primary-source 裏付きの discovery API。幻覚 (hallucination) を一次資料で潰す。</p>
<div class="cta-row">
  <a class="btn btn-primary" href="/docs/getting-started">5 秒で始める</a>
  <a class="btn btn-secondary" href="#" aria-label="GitHub リポジトリを開く">View on GitHub</a>
</div>
<p class="hero-note">Tier 分類 S/A/B/C/X、排他ルール 35 本 (農業 22 + 非農業 13)、47 都道府県網羅。</p>
```

---

## 2. `site/pricing.html` Hero (L46-48)

### Control A (現行)

```html
<h1>料金</h1>
<p class="lead">完全従量課金。使った分だけ。最低金額・契約・解約違約金なし。</p>
```

### Variant B — value-first

```html
<h1>料金</h1>
<p class="lead">¥0 の Free で叩いて、欲しくなったら ¥3/req の従量へ。決済 → API キー発行まで 30 秒、SDK 不要で即 curl。</p>
```

### Variant C — trust-first

```html
<h1>料金</h1>
<p class="lead">tier 分岐なし、契約・最低金額なし。Free 50 req/月 (JST) + Paid ¥3/req 従量。使わない月は ¥0。</p>
```

### Variant D — price-first

```html
<h1>¥0 から、使った分だけ</h1>
<p class="lead">Free 50 req/月 (JST) → Paid ¥3/req (税別、hard cap なし)。1,000 req = ¥3,000、10,000 req = ¥30,000。self-serve、年額契約なし。</p>
```

---

## 3. Above-the-fold curl snippet (pricing.html)

現状 `pricing.html` は hero 直下に price grid が来る。hero と grid の間 (L48 と L50 の間) に 1 block 挿入する。`conversion_funnel.md` §4 #2 で「+3-5pt on CTA」と見積もった仕掛け。デザインは既存 `.code-block` を流用 (index.html L136-137 と同じ tokens)。

```html
<section class="code-demo" aria-labelledby="pricing-demo-title">
  <h2 id="pricing-demo-title" class="section-title">30 秒で叩く</h2>
  <p class="demo-lead">Free tier キーで動く。アカウント不要で response 形式を確認できる。</p>
  <pre class="code-block" aria-label="curl コマンド例"><code>$ curl https://zeimu-kaikei.ai/v1/programs/search?q=農業&limit=5 \
    -H "X-API-Key: YOUR_KEY"</code></pre>
  <p class="demo-note">レスポンス (抜粋):</p>
  <pre class="code-block" aria-label="JSON レスポンス例"><code>{
  "total": 412,
  "limit": 5,
  "results": [
    {"unified_id": "maff-shinkinoushasha-2026",
     "primary_name": "認定新規就農者制度",
     "tier": "S", "amount_max_man_yen": 1000,
     "source_url": "https://www.maff.go.jp/...",
     "fetched_at": "2026-04-22T03:00:00+09:00"}
  ]
}</code></pre>
</section>
```

---

## 4. A/B instrumentation plan

**Rotation**: index hero は B / C を 50/50 split (Control A は停止、launch 直後は「どちらが勝つか」のみ知りたい)。pricing hero は A/B/C/D の 4-way 25% 均等。curl snippet は全訪問に常時出す (単独 on/off テスト、±curl の 50/50、7 日)。

**割当**: `jpintel_sid` cookie (既に `docs/conversion_funnel.md` §2.2 で発行、90 日) の last byte を `mod N` で variant 決定。初回訪問で固定、以後同 sid は同 variant を継続。`POST /v1/events/pageview` の payload に `{exp_id: "hero_index_v1" | "hero_pricing_v1" | "curl_above_fold_v1", variant: "A"|"B"|"C"|"D"}` を追加 (既存 event schema の optional field 2 本追加)。

**サンプルサイズ**: baseline CTA click rate 12%、detect ±2pt (Δ=2%) at α=0.05, power 0.8, 両側。`n = 2 × (1.96+0.84)² × p(1-p) / Δ² ≈ 2,067 / arm`。安全側で 2,500 / arm。index hero 2-way = 5,000 visits、pricing 4-way = 10,000 visits、curl 2-way = 5,000 pricing visits。

**除外**: 同一 `jpintel_sid` は最初の 30 日間に 1 回だけカウント (repeat を rollup 時に dedupe)。DNT=1 および cookie 拒否 session は全テストから除外 (事前同意の代替)。internal IP / `/healthz` は既存フィルタ流用。

**停止条件**: 14 日経過 OR 両側検定 p<0.05 に到達、いずれか先着。勝者未確定なら Control 復帰、差が±1pt 以内なら Variant C (trust-first) を默認に昇格する指針 (tone 整合性優先)。

---

## 5. Anti-pattern list (採用しない 6 手)

1. **「最安値」「No.1」「業界最高」の絶対最上級**: 景表法 5 条 優良誤認の直撃。dev-tool の比較母集団が定義不能で立証不可。
2. **「Start Free Trial NOW!!」「期間限定!」等のグロースハッカー CTA**: 日本 B2B は「叫ばないトーン」がデフォルト、既存 hero の understated tone (「5 秒で始める」「料金」) と断絶。
3. **pre-checked ニュースレター / auto-opt-in**: `conversion_funnel.md` §7 #3 で dark pattern 禁止を明示済み。景表法・特商法より先に自社ポリシーが禁ずる。
4. **urgency countdown timer (「残り◯時間」)**: self-serve SaaS に時限性なし = 虚偽表示の恐れ、かつ日本エンジニア読者の信用を最速で失う導線。
5. **「Jグランツより速い / 詳しい」等の名指し比較**: `conversion_funnel.md` §7 #4 で **棲み分け** 路線を明文化。比較広告は景表法 5 条 + 不競法 2 条 1 項 15 号 (他人の営業誹謗) リスク。
6. **テスティモニアル (「〇〇社導入!」) の launch 前掲載**: 実績ゼロで載せれば虚偽、導入直後の匿名体験談も優良誤認。launch 後 D+30 以降、実名 + 許諾取得後のみ。

---

## Report

- **最高 Ex[lift] 候補**: **pricing.html の curl snippet (§3)**。`conversion_funnel.md` §4 #2 で +3-5pt CTA→checkout、かつ pricing 到達済み訪問者は既に intent ありで「動くか」不安のみが残っているため、snippet 1 つで「動く証拠 + response 形態の見せ込み」を一撃で片付けられる。hero 文言テストは tone 相性が強く出て ±1-3pt 止まりの見込み。
- **業界慣習だが採用しない手**: Free-tier CTA 上に **「クレジットカード不要」バッジ** を付けるのは意図的に避けた (既に Free=¥0 自明、バッジは「カード必要が業界通念である」逆暗示を生み、understated tone を崩す)。
