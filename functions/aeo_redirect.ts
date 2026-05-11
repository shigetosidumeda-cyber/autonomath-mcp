/// <reference types="@cloudflare/workers-types" />
/*
 * AEO short-circuit edge function (Wave 24 — CDN routing optimization).
 *
 * AI answer engines (GPTBot, ClaudeBot, PerplexityBot, Google-Extended,
 * etc.) fetch `/` and then `/llms.txt` as a fixed two-round-trip handshake.
 * The HTML at `/` is human-targeted (1+MB with hero + nav + CTA + JSON-LD
 * + CSS + JS); LLM crawlers parse none of it usefully — they just want
 * the llms.txt site map. Serving llms.txt directly on `/` when the UA is
 * a known AI bot cuts the handshake from two RTTs to one, drops ~95% of
 * the bytes those bots pull, and improves AI-citation freshness because
 * the bot fetches less and re-fetches more often within a crawl budget.
 *
 * Human UAs (Chrome / Safari / Firefox / curl / wget / SDK) and verified
 * search-engine bots (Googlebot / Bingbot) get the normal HTML — they
 * have working renderers and want the full page. Only AI answer-engine
 * crawlers are short-circuited.
 *
 * Strategy: at-edge UA classifier → if-AI-bot serve llms.txt body with
 * `Content-Type: text/markdown` and `Vary: User-Agent` so downstream
 * caches don't poison human visitors with the markdown response.
 *
 * Memory references:
 *   * feedback_ax_4_pillars       — AX surface (Access / Context / Tools / Orch).
 *   * feedback_organic_only_no_ads — bot-friendly, no paid acquisition.
 *   * feedback_zero_touch_solo     — no operator gates the short-circuit.
 *
 * Bot list maintained in sync with `cloudflare-rules.yaml` AI bot allowlist
 * + WAF custom-rule allowlist (Wave 24, `cf_waf_ai_bot_allowlist.py`).
 */

export interface Env {
  ASSETS: Fetcher;
}

// Canonical AI-bot UA substrings (case-insensitive contains match).
// Keep in sync with scripts/ops/cf_waf_ai_bot_allowlist.py — both files
// must reference the same exact substring set so allowlist + redirect
// behaviour stay coherent.
const AI_BOT_UA_SUBSTRINGS = [
  "gptbot",          // OpenAI primary crawler
  "chatgpt-user",    // OpenAI on-demand fetch (ChatGPT browsing)
  "oai-searchbot",   // OpenAI search-engine crawler
  "claudebot",       // Anthropic primary crawler
  "claude-web",      // Anthropic on-demand fetch
  "anthropic-ai",    // Anthropic generic UA prefix
  "perplexitybot",   // Perplexity primary crawler
  "perplexity-user", // Perplexity on-demand fetch
  "google-extended", // Google AI / Gemini training crawler (Vertex / Bard)
  "googleother",     // Google AI experimental crawler
  "bingbot-ai",      // Bing AI-related crawler tag (Copilot)
  "youbot",          // You.com AI search crawler
  "amazonbot",       // Alexa / Amazon AI crawler
  "bytespider",      // ByteDance / Doubao crawler
  "ccbot",           // CommonCrawl (often used by AI training datasets)
  "diffbot",         // Diffbot semantic crawler (AI partner)
  "facebookbot",     // Meta AI training crawler
  "applebot-extended", // Apple AI training crawler (separate from search Applebot)
  "cohere-ai",       // Cohere training/inference crawler
  "mistral",         // Mistral AI crawler (newer)
];

/** Returns true if UA matches an AI-bot substring. Case-insensitive. */
function isAiBot(ua: string | null): boolean {
  if (!ua) return false;
  const lower = ua.toLowerCase();
  for (const sub of AI_BOT_UA_SUBSTRINGS) {
    if (lower.includes(sub)) return true;
  }
  return false;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);

  // Only short-circuit GET / (the homepage). Any other path defers to
  // the static site / other Pages Functions / CF Pages auto-routing.
  if (context.request.method !== "GET" || url.pathname !== "/") {
    return context.next();
  }

  const ua = context.request.headers.get("User-Agent");
  if (!isAiBot(ua)) {
    return context.next();
  }

  // AI bot detected — serve llms.txt content as markdown.
  // Fetch the static llms.txt asset from the same Pages deployment.
  const llmsReq = new Request(`${url.origin}/llms.txt`, {
    headers: { "User-Agent": ua || "" },
  });
  const llmsResp = await context.env.ASSETS.fetch(llmsReq);
  if (!llmsResp.ok) {
    // Failure-mode: fall back to normal HTML so we never 5xx the bot.
    return context.next();
  }

  const body = await llmsResp.text();
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
      "Vary": "User-Agent",
      "X-AEO-Short-Circuit": "1",
      "X-Robots-Tag": "index, follow",
      // CORS allowed so multi-origin AI clients (Claude / GPT) can fetch.
      "Access-Control-Allow-Origin": "*",
    },
  });
};
