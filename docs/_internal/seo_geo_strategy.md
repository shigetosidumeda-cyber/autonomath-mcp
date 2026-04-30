# SEO + GEO 移行戦略 — zeimu-kaikei.ai → jpcite.com

> **Internal only.** mkdocs は `_internal/` を exclude する。公開 site には出ない。
>
> Status: 2026-04-30 起票 / 移行作業未着手

## 0. ゴール

- **正準ドメイン**: `jpcite.com` (Cloudflare Registrar、2026-04-30 取得済み)
- **旧ドメイン**: `zeimu-kaikei.ai` (Japanese keyword: 税務 / 会計 / AI で SEO 認証蓄積済み)
- **やる事**: zeimu-kaikei.ai → jpcite.com を 301 redirect で全 SEO juice 移転
- **やらない事**: 旧ドメインのコンテンツ並走配信 (canonical 戦争を起こす)、ドメイン放棄 (juice 喪失)、 paid migration tool

---

## 1. 301 redirect 設計

### 1.1 redirect ルール

```
zeimu-kaikei.ai/*  →  https://jpcite.com/$1     (301 Permanent)
www.zeimu-kaikei.ai/*  →  https://jpcite.com/$1 (301 Permanent)
```

**鉄則**:

- **パス保持** (`/foo/bar?q=1` → `/foo/bar?q=1`)。ルート集約 (`/* → /`) は SEO 喪失の典型 anti-pattern なので絶対禁止
- **301 (Permanent)**、 302 ではない。 302 では Google が PageRank を移転しない
- **HTTPS** で受けて HTTPS で返す。 chain redirect (HTTP → HTTPS → 別ドメイン) は juice 漏れ
- **サブドメイン** `www.` も明示的に同じ rule を適用

### 1.2 実装場所

Cloudflare の Page Rule または Bulk Redirect で `zeimu-kaikei.ai` zone に設定する。

```
# Cloudflare Bulk Redirect (例)
Source URL: https://zeimu-kaikei.ai/*
Target URL: https://jpcite.com/$1
Status: 301
Preserve query string: ON
Preserve path suffix: ON (上の $1 で吸収)
```

origin server 側 (Cloudflare Workers / R2 / Pages) でも HTTP 301 を発行する fallback を仕込む。 Cloudflare ダッシュボード変更ミスで素通し配信される事故を二段で防ぐ。

### 1.3 HTML <head> 補強 (二重保険)

zeimu-kaikei.ai がもし配信されてしまった場合のフォールバックとして、配信 HTML に以下を埋める:

```html
<link rel="canonical" href="https://jpcite.com/[同一パス]" />
<meta http-equiv="refresh" content="0; url=https://jpcite.com/[同一パス]" />
```

ただし **301 が一次防衛、 canonical/meta-refresh は事故時の二次防衛**。 301 を主、 canonical を従に保つ。両者矛盾するなら 301 が勝つ (= jpcite.com が canonical)。

### 1.4 DNS TXT record (任意)

zeimu-kaikei.ai 側に検索エンジン向けの hint を残す:

```
TXT  _migration.zeimu-kaikei.ai  "moved-to=jpcite.com; date=2026-04-30; reason=brand-rename"
```

Google は標準で読まないが、人間 (将来の自分) と LLM crawler 向けの足跡として置く。

---

## 2. SEO 移行 timeline

### 2.1 標準ケース (Google 公式 ground truth + 業界経験則)

| 経過時間 | 期待される状態 | 観測点 |
|---|---|---|
| 0-7 日 | 301 を Google が認識開始、 jpcite.com の crawl 急増 | GSC の "Discovered - currently not indexed" 数 |
| 7-30 日 | jpcite.com の indexed pages が zeimu-kaikei.ai の 30-50% 規模に | GSC Coverage report |
| 30-90 日 | **PageRank の 80%+ が jpcite.com に移転**、検索順位は -10〜-30% で底打ち | GSC organic clicks の推移 |
| 90-180 日 | 順位回復、移行前と同等または上昇 | top queries の SERP 位置 |
| 180 日 (6 ヶ月) | **移転完了**、 zeimu-kaikei.ai は GSC の old hostname として残るのみ | indexed page 数、 click 数 |

### 2.2 重要な前提

- jpcite.com も **同じ Japanese content** を serve する事 (税務 / 会計 / AI / 法令 / 判例 etc.)
- robots.txt で jpcite.com を許可、 zeimu-kaikei.ai もブロックしない (301 が読めなくなる)
- sitemap.xml を jpcite.com 側で再生成、 GSC に submit

---

## 3. GEO 戦略 (Generative Engine Optimization)

LLM の training cutoff によって "zeimu-kaikei.ai" として既に学習されている可能性がある。 GPT/Claude/Perplexity の RAG が新ドメインを取り損ねるリスクを最小化する。

### 3.1 llms.txt の冒頭明記

`jpcite.com/llms.txt` の最初の H1 直下に明示:

```markdown
# jpcite (formerly 税務会計AI / zeimu-kaikei.ai)

> jpcite (旧: 税務会計AI、 zeimu-kaikei.ai) は日本の税務・会計・法令・判例・入札・税務 ruleset を
> 統合した API/MCP プラットフォームです。 2026-04 にブランド統一のため jpcite.com に移行しました。
> 旧ドメイン zeimu-kaikei.ai は jpcite.com に 301 redirect されています。

## URL
- Canonical: https://jpcite.com
- Redirect-from: https://zeimu-kaikei.ai (301 permanent)
```

これで LLM が `zeimu-kaikei.ai` の訓練済み知識から新ドメインに正しく bridge できる。

### 3.2 schema.org / JSON-LD

`<script type="application/ld+json">` に Organization / WebSite を載せ、 `sameAs` と `alternateName` で旧ブランドを明記:

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "jpcite",
  "alternateName": ["税務会計AI", "zeimu-kaikei.ai"],
  "url": "https://jpcite.com",
  "sameAs": ["https://zeimu-kaikei.ai"]
}
```

### 3.3 ChatGPT / Perplexity の対応

- ChatGPT plugin / GPTs に登録している場合は manifest URL を更新
- Perplexity, You.com, Phind 等の bot user-agent (PerplexityBot, YouBot 等) を robots.txt で明示的に Allow する
- HuggingFace / npm / PyPI / MCP registry の README に新 URL を反映 (別 task)

---

## 4. リスク評価

### 4.1 リスクと対応

| リスク | 影響 | 対応 |
|---|---|---|
| 301 chain (古い 302 や HTTP→HTTPS→別 domain) | PageRank 漏れ | 設定後 `curl -I` で chain 確認、最大 1 hop |
| canonical 矛盾 (jpcite.com が zeimu-kaikei.ai を canonical 指定) | Google 混乱、 indexed 重複 | 全 page の canonical を jpcite.com に統一する deploy 前 audit |
| zeimu-kaikei.ai を放棄 (期限切れ) | 全 backlink juice 喪失 | Cloudflare Registrar の auto-renewal を ON、最低 3 年 keep |
| jpcite.com の Japanese keyword density 不足 | 順位回復遅延 | 旧コンテンツを 1:1 移植、新 brand 名は h1/title に追加 *だけ* で keyword は維持 |
| 商標衝突 ("Intel" 連想) | rename 強制 | 既に jpcite.com に rename 済 (memory: jpintel_trademark_intel_risk) |
| 並列に SEO 戦争 (両ドメイン active) | 自分自身と競合 | jpcite.com 以外で content を serve しない、 zeimu-kaikei.ai は 301 only |

### 4.2 やってはいけない事

- **301 を 302 に置き換え** (永久 → 一時)
- **zeimu-kaikei.ai でコンテンツを並走配信** (canonical で逃げても重複扱い)
- **新 site で keyword を英語化** ("tax accounting AI" にする等)。 Japanese keyword の SEO 蓄積を捨てる事になる
- **GSC の change-of-address tool を使わない** (使う、忘れない)

---

## 5. 検証 KPI (Google Search Console)

### 5.1 月次 tracking 項目

| KPI | 期待される推移 | tooling |
|---|---|---|
| Indexed pages (jpcite.com) | 0 → zeimu-kaikei.ai と同数に 90 日で到達 | GSC Coverage |
| Indexed pages (zeimu-kaikei.ai) | 既存数 → 6 ヶ月で 0 に近づく | GSC (old property) |
| Organic clicks (jpcite.com) | 0 → 旧 click 数の 80%+ に 90 日で到達 | GSC Performance |
| Organic clicks (zeimu-kaikei.ai) | 既存 → 6 ヶ月で 0 に近づく | GSC (old property) |
| Top queries (Japanese) | "税務 AI", "会計 API", "法令 検索" 等で順位維持 | GSC Performance > Queries |
| Average position | 30-90 日に -10 ポイント程度の dip → 90 日以降回復 | GSC Performance |

### 5.2 アラート閾値

- **30 日経過しても jpcite.com の indexed が 100 page 未満** → 301 設定ミス疑い、即 audit
- **90 日経過しても organic clicks が旧 50% 未満** → content gap or 順位下落、 top query 個別調査
- **zeimu-kaikei.ai の click が増える** → 301 が効いていない、 Cloudflare rule を再確認

### 5.3 GSC 必須 task

1. jpcite.com を新 property として GSC に追加・所有権検証
2. zeimu-kaikei.ai (旧 property) で **Change of Address tool** を実行 → jpcite.com を指定
3. sitemap.xml を jpcite.com で submit
4. URL Inspection で代表 5-10 page を手動 indexing request

---

## 6. 緊急時のロールバック手順

### 6.1 トリガー条件 (どれか 1 つでも該当 = ロールバック検討)

- 30 日で organic clicks が旧 30% を切る
- jpcite.com で indexing 不能エラーが大量発生 (GSC Coverage の Error が急増)
- Cloudflare で routing loop が発生 (実害)
- 商標 / 法務上の jpcite.com 撤退要求

### 6.2 手順 (5 分で完了)

```bash
# Cloudflare dashboard
# 1. Bulk Redirect の有効化を OFF
# 2. zeimu-kaikei.ai の DNS を origin (旧サーバー) に戻す
# 3. jpcite.com は DNS 残置 (将来再挑戦のため放棄しない)

# 検証
curl -I https://zeimu-kaikei.ai/ja/laws  # → 200 (301 ではない) を確認
curl -I https://jpcite.com/ja/laws       # → 200 (もしくは 404 で OK)
```

### 6.3 ロールバック後

- GSC Change of Address tool の reverse は **不要**。ただし 30 日以内に Google に再認識させる必要があるので URL Inspection で再 fetch
- jpcite.com は domain だけ keep して content 配信停止
- 原因特定して再挑戦の段取り (memory に記録)

---

## 7. 移行後の運用 (恒久)

- **zeimu-kaikei.ai は手放さない**: 301 だけ仕込んで 3 年以上 keep。 backlink 価値が永続的に jpcite.com に流れる
- **canonical 監視**: 新 page を deploy する度に canonical が jpcite.com を指している事を CI で確認
- **llms.txt の旧名表記は 1 年残す**: GEO の knowledge bridge として機能、 1 年後に削除検討

---

## 8. 関連 docs / memory

- memory: `project_jpcite_rename.md` (2026-04-30)
- memory: `project_jpintel_trademark_intel_risk.md` (rename trigger の経緯)
- memory: `feedback_no_trademark_registration.md` (商標出願しない方針)
- docs: `docs/_internal/seo_technical_audit.md` (技術 SEO の baseline)
- docs: `docs/_internal/json_ld_strategy.md` (schema.org 戦略)
