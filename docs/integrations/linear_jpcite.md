---
title: "Linear ticket auto-enrich with jpcite"
slug: "linear-jpcite-integration"
audience: "engineering / product ops"
intent: "linear_auto_enrich"
related_tools: ["search_programs", "get_corp_360", "check_invoice_status"]
billable_units_per_run: 6
date_created: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Linear ticket auto-enrich with jpcite

Linear の Issue が「補助金 / 取引先与信 / 法令改正 / 適格事業者検証」絡みの label を持った瞬間に、jpcite REST API を叩いて Issue Comment に **一次資料 + tier + fit_score + canonical URL** を貼り付ける Zap 風 integration。

Linear webhook → AWS Lambda (or Cloudflare Worker) → jpcite ¥3/req → Linear `comment.create` mutation の 4 段。Solo オペでも 1 時間で wire 可能。

## 想定 user

- 中小 SaaS の 1-3 人プロダクト開発チーム
- 営業 / CS が Linear で 「顧客の業種に合いそうな補助金あれば添付」「適格事業者か検証」 等の issue を切る
- 開発側で人力 enrich すると 1 件 5-10 分 × 50 件/週 = 4-8 時間/週 のロス → jpcite で自動化

## 入力 trigger

Linear webhook payload。`label.name` が以下のいずれか:

- `補助金候補` — `search_programs` で top 3 を Issue Comment に貼る
- `与信確認` — `get_corp_360` で 30 日採択 + 行政処分 + 適格事業者 を貼る
- `法令改正watch` — `track_amendment_lineage_am` で affected programs を貼る
- `適格事業者検証` — `check_invoice_status` で T 番号有効性を貼る

## 実装 (Cloudflare Worker)

```javascript
// worker.js — Linear webhook → jpcite enrich → Linear comment
export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok", { status: 200 });
    const payload = await request.json();
    if (payload.type !== "Issue" || payload.action !== "update") return new Response("noop");
    const labels = (payload.data.labels || []).map(l => l.name);
    if (!labels.some(l => ["補助金候補","与信確認","法令改正watch","適格事業者検証"].includes(l))) {
      return new Response("noop");
    }
    const enriched = await enrich(payload.data, labels, env);
    if (!enriched) return new Response("nothing");
    await postLinearComment(payload.data.id, enriched, env);
    return new Response("done");
  },
};

async function enrich(issue, labels, env) {
  const keyword = (issue.description || issue.title || "").slice(0, 200);
  if (labels.includes("補助金候補")) {
    const res = await fetch(
      `https://api.jpcite.com/v1/programs/search?keyword=${encodeURIComponent(keyword)}&top_n=3`,
      { headers: { "X-API-Key": env.JPCITE_API_KEY, "X-Client-Tag": "linear-bot" } }
    );
    const data = await res.json();
    const lines = data.results.map(p =>
      `- **${p.name}** (tier ${p.tier}, fit ${p.fit_score?.toFixed(2) ?? "—"})\n  ${p.source_url}`);
    return `### 候補 補助金 top ${data.results.length}\n\n${lines.join("\n")}\n\n_source: jpcite ¥${data.results.length * 3}/req, fetched_at ${data.fetched_at}_`;
  }
  if (labels.includes("適格事業者検証")) {
    const t = (issue.description || "").match(/T\d{13}/);
    if (!t) return null;
    const res = await fetch(`https://api.jpcite.com/v1/invoice/${t[0]}`,
      { headers: { "X-API-Key": env.JPCITE_API_KEY } });
    const d = await res.json();
    return `### 適格事業者検証: ${t[0]}\n\n- 登録: ${d.registered ? "✅ 有効" : "❌ 抹消/未登録"}\n- 登録日: ${d.registered_date || "—"}\n- 登録法人: ${d.corp_name || "—"}\n- source: ${d.source_url}`;
  }
  return null;
}

async function postLinearComment(issueId, body, env) {
  await fetch("https://api.linear.app/graphql", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": env.LINEAR_API_KEY },
    body: JSON.stringify({
      query: `mutation($issueId: String!, $body: String!) {
        commentCreate(input: { issueId: $issueId, body: $body }) { success }
      }`,
      variables: { issueId, body },
    }),
  });
}
```

## デプロイ

```bash
# 1. Cloudflare Worker をセットアップ
wrangler init jpcite-linear-bot
# 2. JPCITE_API_KEY と LINEAR_API_KEY を Cloudflare secret に
wrangler secret put JPCITE_API_KEY
wrangler secret put LINEAR_API_KEY
# 3. デプロイ
wrangler deploy
# 4. Linear admin → Settings → API → webhook 追加 → URL = worker URL
```

## ROI 試算

- jpcite cost: ¥3-18 / Issue (label による) × 200 Issue/月 = ¥600-3,600/月
- 削減工数: 5-10 min × 200 件 = 16-33 時間/月 (時給 ¥3,000 換算 ¥48,000-100,000)
- **ROI: 13-280 倍**

## known gaps

- Linear API は 100 req/min rate limit、超過時は 60s backoff
- jpcite anonymous 3 req/日 は越えるので API key 必須 (組織用 1 本)
- 採択 30 日窓は ingest lag 1-3 日、当日反映は S/A tier のみ

## 関連 docs

- [jpcite 一次資料 license](https://jpcite.com/legal/licenses)
- [recipes/r15 grant SaaS internal enrich](../recipes/r15-grant-saas-internal-enrich/) — 内部 DB enrich の cron 版
- [recipes/r03 SME M&A public DD](../recipes/r03-sme-ma-public-dd/) — DD 用途の deep version

## canonical source

- jpcite REST API reference: <https://api.jpcite.com/docs>
- Linear API reference: <https://developers.linear.app/docs/graphql/getting-started>
- Cloudflare Workers: <https://developers.cloudflare.com/workers/>
