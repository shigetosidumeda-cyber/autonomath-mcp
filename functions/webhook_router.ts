/// <reference types="@cloudflare/workers-types" />
/*
 * Wave 26 — Custom webhook router for customer integrations.
 *
 * Cloudflare Pages Function that receives inbound webhook payloads from
 * customers' internal systems (CI/CD, Linear, Notion automations, etc.)
 * and forwards them to one of three reference handlers — Slack, Discord,
 * Teams — after HMAC-SHA256 signature verification.
 *
 * Endpoint layout (mounted at `/webhook/{customer_key}` via the project
 * `_routes.json` and the file path):
 *
 *   POST /webhook/{customer_key}
 *
 * Body shape (JSON):
 *   {
 *     "kind":   "program.amended" | "enforcement.added" | "custom",
 *     "title":  "...",                 // human-readable headline
 *     "url":    "https://jpcite.com/...", // canonical link
 *     "summary": "...",                // 1-3 sentences
 *     "targets": ["slack" | "discord" | "teams"],
 *     "data":   { ... }                // raw event payload (echoed)
 *   }
 *
 * Headers:
 *   X-JPCITE-Signature: hex(HMAC_SHA256(secret, raw_body))
 *   X-JPCITE-Timestamp: <ms epoch>
 *
 * Behaviour:
 *   - signature mismatch → 401
 *   - timestamp drift > 5 minutes → 401 (replay defence)
 *   - targets unknown → 200 with `delivered_to: []`
 *   - per-target webhook URLs are resolved from Pages secrets
 *     `JPCITE_WEBHOOK_SLACK_<customer_key>` etc.
 *
 * Memory references:
 *   - feedback_zero_touch_solo : no human review — agent integrations
 *     must self-serve.
 *   - feedback_organic_only_no_ads : this is action infra, not paid
 *     marketing — fits the AX 4-pillar "Tools" layer.
 *   - feedback_ax_4_pillars : webhook-out is the Layer-3 surface AI
 *     agents need to commit to a workflow after a /v1 read.
 *   - feedback_no_operator_llm_api : NO model API calls anywhere in
 *     this file. We only forward structured payloads.
 */

interface WebhookPayload {
  kind: string;
  title: string;
  url: string;
  summary: string;
  targets: Array<"slack" | "discord" | "teams">;
  data?: Record<string, unknown>;
}

interface Env {
  // Per-customer outbound URLs are loaded dynamically by key — see
  // `loadDestinations`. The static bindings below are the global
  // fallbacks the function uses when a customer-specific secret is
  // not present (useful for the operator's own monitoring channels).
  JPCITE_WEBHOOK_FALLBACK_SLACK?: string;
  JPCITE_WEBHOOK_FALLBACK_DISCORD?: string;
  JPCITE_WEBHOOK_FALLBACK_TEAMS?: string;
  // The HMAC secret. Either a global key (single-tenant) or a JSON map
  // of `{ "<customer_key>": "<secret>" }` for multi-tenant.
  JPCITE_WEBHOOK_SECRET?: string;
  JPCITE_WEBHOOK_SECRETS_JSON?: string;
}

const MAX_BODY_BYTES = 32_768;
const REPLAY_WINDOW_MS = 5 * 60 * 1000;

const ALLOWED_TARGETS = new Set(["slack", "discord", "teams"]);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function hexFromBuffer(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let out = "";
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i].toString(16).padStart(2, "0");
  }
  return out;
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) {
    mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return mismatch === 0;
}

async function verifySignature(
  raw: string,
  signature: string,
  timestamp: string,
  secret: string,
): Promise<boolean> {
  const ts = Number(timestamp);
  if (!Number.isFinite(ts)) return false;
  const drift = Math.abs(Date.now() - ts);
  if (drift > REPLAY_WINDOW_MS) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const body = `${timestamp}.${raw}`;
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  const expected = hexFromBuffer(digest);
  return timingSafeEqual(expected.toLowerCase(), signature.toLowerCase());
}

function resolveSecret(env: Env, customerKey: string): string | null {
  if (env.JPCITE_WEBHOOK_SECRETS_JSON) {
    try {
      const map = JSON.parse(env.JPCITE_WEBHOOK_SECRETS_JSON) as Record<string, string>;
      if (typeof map[customerKey] === "string") return map[customerKey];
    } catch {
      // fall through to single-tenant secret
    }
  }
  return env.JPCITE_WEBHOOK_SECRET ?? null;
}

function loadDestinations(
  env: Env,
  customerKey: string,
  targets: WebhookPayload["targets"],
): Record<string, string> {
  // Resolution priority: per-customer named secret (e.g.
  // `JPCITE_WEBHOOK_SLACK_acme`) → global fallback secret.
  // Cloudflare Pages does NOT support dynamic env names via the
  // wrangler runtime API, so we encode per-customer URLs in a JSON
  // map similar to the secret store above. In production this is
  // populated via `wrangler pages secret put JPCITE_WEBHOOK_URLS_JSON`.
  const urlMap: Record<string, Record<string, string>> = (() => {
    const raw = (env as unknown as { JPCITE_WEBHOOK_URLS_JSON?: string })
      .JPCITE_WEBHOOK_URLS_JSON;
    if (!raw) return {};
    try {
      return JSON.parse(raw) as Record<string, Record<string, string>>;
    } catch {
      return {};
    }
  })();
  const perCustomer = urlMap[customerKey] ?? {};

  const fallback: Record<string, string | undefined> = {
    slack: env.JPCITE_WEBHOOK_FALLBACK_SLACK,
    discord: env.JPCITE_WEBHOOK_FALLBACK_DISCORD,
    teams: env.JPCITE_WEBHOOK_FALLBACK_TEAMS,
  };
  const resolved: Record<string, string> = {};
  for (const target of targets) {
    const url = perCustomer[target] ?? fallback[target];
    if (url) resolved[target] = url;
  }
  return resolved;
}

function buildSlackBlocks(payload: WebhookPayload): unknown {
  return {
    text: payload.title,
    blocks: [
      {
        type: "header",
        text: { type: "plain_text", text: payload.title.slice(0, 150) },
      },
      {
        type: "section",
        text: { type: "mrkdwn", text: payload.summary.slice(0, 2500) },
      },
      {
        type: "context",
        elements: [
          {
            type: "mrkdwn",
            text: `<${payload.url}|jpcite> · kind=\`${payload.kind}\``,
          },
        ],
      },
    ],
  };
}

function buildDiscordPayload(payload: WebhookPayload): unknown {
  return {
    embeds: [
      {
        title: payload.title.slice(0, 256),
        description: payload.summary.slice(0, 4000),
        url: payload.url,
        footer: { text: `jpcite · ${payload.kind}` },
      },
    ],
  };
}

function buildTeamsPayload(payload: WebhookPayload): unknown {
  // MessageCard schema — the simplest Teams webhook contract that
  // every connector still accepts. AdaptiveCard would be richer but
  // requires the workflow connector instead of the legacy webhook.
  return {
    "@type": "MessageCard",
    "@context": "https://schema.org/extensions",
    summary: payload.title.slice(0, 100),
    themeColor: "0078D4",
    title: payload.title,
    text: payload.summary,
    potentialAction: [
      {
        "@type": "OpenUri",
        name: "View on jpcite",
        targets: [{ os: "default", uri: payload.url }],
      },
    ],
  };
}

async function fanOut(
  destinations: Record<string, string>,
  payload: WebhookPayload,
): Promise<Record<string, number>> {
  const builders: Record<string, (p: WebhookPayload) => unknown> = {
    slack: buildSlackBlocks,
    discord: buildDiscordPayload,
    teams: buildTeamsPayload,
  };
  const results: Record<string, number> = {};
  await Promise.all(
    Object.entries(destinations).map(async ([target, url]) => {
      const body = builders[target](payload);
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        results[target] = resp.status;
      } catch {
        results[target] = 0;
      }
    }),
  );
  return results;
}

export const onRequestPost: PagesFunction<Env, "customer_key"> = async (ctx) => {
  const customerKey = ctx.params.customer_key;
  if (typeof customerKey !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(customerKey)) {
    return jsonResponse(400, { error: "invalid customer_key" });
  }

  const signature = ctx.request.headers.get("x-jpcite-signature");
  const timestamp = ctx.request.headers.get("x-jpcite-timestamp");
  if (!signature || !timestamp) {
    return jsonResponse(401, { error: "missing signature headers" });
  }

  const raw = await ctx.request.text();
  if (raw.length > MAX_BODY_BYTES) {
    return jsonResponse(413, { error: "body too large" });
  }

  const secret = resolveSecret(ctx.env, customerKey);
  if (!secret) {
    return jsonResponse(401, { error: "unknown customer_key" });
  }
  const ok = await verifySignature(raw, signature, timestamp, secret);
  if (!ok) {
    return jsonResponse(401, { error: "signature mismatch" });
  }

  let parsed: WebhookPayload;
  try {
    parsed = JSON.parse(raw) as WebhookPayload;
  } catch {
    return jsonResponse(400, { error: "invalid JSON" });
  }
  if (
    typeof parsed.title !== "string" ||
    typeof parsed.url !== "string" ||
    typeof parsed.summary !== "string" ||
    !Array.isArray(parsed.targets)
  ) {
    return jsonResponse(400, { error: "payload schema invalid" });
  }

  const targets = parsed.targets.filter((t): t is "slack" | "discord" | "teams" =>
    ALLOWED_TARGETS.has(t),
  );
  if (targets.length === 0) {
    return jsonResponse(200, { delivered_to: [], skipped: "no valid targets" });
  }

  const destinations = loadDestinations(ctx.env, customerKey, targets);
  const results = await fanOut(destinations, parsed);

  return jsonResponse(200, {
    delivered_to: Object.keys(results),
    status_per_target: results,
    customer_key: customerKey,
  });
};

export const onRequestGet: PagesFunction<Env> = async () => {
  // Liveness probe — does NOT consume customer billing, returns the
  // verification expectations so an agent can self-configure.
  return jsonResponse(200, {
    name: "jpcite custom webhook router",
    method: "POST",
    body_schema: {
      kind: "string",
      title: "string",
      url: "string",
      summary: "string",
      targets: "string[] (slack|discord|teams)",
      data: "object (optional)",
    },
    headers: {
      "X-JPCITE-Signature": "hex(HMAC_SHA256(secret, timestamp + '.' + body))",
      "X-JPCITE-Timestamp": "ms epoch",
    },
    replay_window_ms: REPLAY_WINDOW_MS,
    max_body_bytes: MAX_BODY_BYTES,
  });
};
