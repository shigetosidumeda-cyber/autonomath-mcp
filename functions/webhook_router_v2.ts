/// <reference types="@cloudflare/workers-types" />
/*
 * Wave 35 Axis 6e (2026-05-12) — extended customer webhook router.
 *
 * Builds on `functions/webhook_router.ts` (Wave 26) with deeper per-target
 * message templates:
 *   - Slack:   Block Kit (header / section / actions / context)
 *   - Discord: Embed (color + fields + footer)
 *   - Teams:   AdaptiveCard 1.4 (FactSet + Action.OpenUrl)
 *
 * Endpoint: POST /webhook/v2/{customer_key}
 *
 * Headers:
 *   X-JPCITE-Signature: hex(HMAC_SHA256(secret, timestamp + "." + body))
 *   X-JPCITE-Timestamp: <ms epoch>
 *
 * Behaviour:
 *   - signature mismatch → 401
 *   - timestamp drift > 5 min → 401 (replay defence)
 *   - body > 64 KB → 413
 *   - unknown targets → 200 { delivered_to: [] }
 *
 * Memory:
 *   - feedback_zero_touch_solo : self-serve, no admin onboarding.
 *   - feedback_ax_4_pillars    : Layer-3 action surface for AI agents.
 *   - feedback_no_operator_llm_api : forwards payloads; no LLM call.
 */

interface WebhookField { name: string; value: string; short?: boolean; }
interface WebhookAction { label: string; url: string; }
interface WebhookPayloadV2 {
  kind: string;
  event?: "info" | "warn" | "alert";
  title: string;
  url: string;
  summary: string;
  targets: Array<"slack" | "discord" | "teams">;
  fields?: WebhookField[];
  actions?: WebhookAction[];
  data?: Record<string, unknown>;
}

interface Env {
  JPCITE_WEBHOOK_FALLBACK_SLACK?: string;
  JPCITE_WEBHOOK_FALLBACK_DISCORD?: string;
  JPCITE_WEBHOOK_FALLBACK_TEAMS?: string;
  JPCITE_WEBHOOK_SECRET?: string;
  JPCITE_WEBHOOK_SECRETS_JSON?: string;
  JPCITE_WEBHOOK_URLS_JSON?: string;
}

const MAX_BODY_BYTES = 65_536;
const REPLAY_WINDOW_MS = 5 * 60 * 1000;
const OUTBOUND_FETCH_TIMEOUT_MS = 5_000;
const ALLOWED_TARGETS = new Set(["slack", "discord", "teams"]);
const EVENT_COLORS: Record<string, string> = {
  info: "0078D4", warn: "FFA500", alert: "FF3333",
};
const EVENT_EMOJI: Record<string, string> = {
  info: "ℹ️", warn: "⚠️", alert: "🚨",
};

type LimitedTextResult = { ok: true; text: string } | { ok: false };

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function contentLengthExceeds(headers: Headers, maxBytes: number): boolean {
  const value = headers.get("content-length");
  if (!value) return false;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > maxBytes;
}

async function readRequestTextLimited(
  request: Request,
  maxBytes: number,
): Promise<LimitedTextResult> {
  if (contentLengthExceeds(request.headers, maxBytes)) {
    return { ok: false };
  }
  if (!request.body) {
    return { ok: true, text: "" };
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      try {
        await reader.cancel();
      } catch {
        // Best effort; the response will be rejected either way.
      }
      return { ok: false };
    }
    chunks.push(value);
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, text: new TextDecoder().decode(bytes) };
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
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
  raw: string, signature: string, timestamp: string, secret: string,
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
  const digest = await crypto.subtle.sign(
    "HMAC", key, new TextEncoder().encode(body),
  );
  const expected = hexFromBuffer(digest);
  return timingSafeEqual(expected.toLowerCase(), signature.toLowerCase());
}

function resolveSecret(env: Env, customerKey: string): string | null {
  if (env.JPCITE_WEBHOOK_SECRETS_JSON) {
    try {
      const map = JSON.parse(env.JPCITE_WEBHOOK_SECRETS_JSON) as Record<string, string>;
      if (typeof map[customerKey] === "string") return map[customerKey];
    } catch {}
  }
  return env.JPCITE_WEBHOOK_SECRET ?? null;
}

function loadDestinations(
  env: Env, customerKey: string, targets: WebhookPayloadV2["targets"],
): Record<string, string> {
  const urlMap = ((): Record<string, Record<string, string>> => {
    if (!env.JPCITE_WEBHOOK_URLS_JSON) return {};
    try {
      return JSON.parse(env.JPCITE_WEBHOOK_URLS_JSON) as Record<string, Record<string, string>>;
    } catch { return {}; }
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

function buildSlackBlockKit(payload: WebhookPayloadV2): unknown {
  const event = payload.event ?? "info";
  const emoji = EVENT_EMOJI[event] ?? "ℹ️";
  const blocks: unknown[] = [
    { type: "header", text: { type: "plain_text", text: `${emoji} ${payload.title.slice(0, 140)}` } },
    { type: "section", text: { type: "mrkdwn", text: payload.summary.slice(0, 2900) } },
  ];
  if (payload.fields && payload.fields.length > 0) {
    blocks.push({
      type: "section",
      fields: payload.fields.slice(0, 10).map((f) => ({
        type: "mrkdwn", text: `*${f.name}*\n${f.value}`.slice(0, 2000),
      })),
    });
  }
  if (payload.actions && payload.actions.length > 0) {
    blocks.push({
      type: "actions",
      elements: payload.actions.slice(0, 5).map((a) => ({
        type: "button",
        text: { type: "plain_text", text: a.label.slice(0, 70) },
        url: a.url,
      })),
    });
  }
  blocks.push({
    type: "context",
    elements: [{
      type: "mrkdwn",
      text: `<${payload.url}|jpcite> · kind=\`${payload.kind}\` · event=\`${event}\``,
    }],
  });
  return { text: payload.title, blocks };
}

function buildDiscordEmbed(payload: WebhookPayloadV2): unknown {
  const event = payload.event ?? "info";
  const color = parseInt(EVENT_COLORS[event] ?? "0078D4", 16);
  const embed: Record<string, unknown> = {
    title: payload.title.slice(0, 256),
    description: payload.summary.slice(0, 4000),
    url: payload.url,
    color,
    timestamp: new Date().toISOString(),
    footer: { text: `jpcite · ${payload.kind} · ${event}` },
  };
  if (payload.fields && payload.fields.length > 0) {
    embed.fields = payload.fields.slice(0, 8).map((f) => ({
      name: f.name.slice(0, 256),
      value: f.value.slice(0, 1024),
      inline: f.short ?? false,
    }));
  }
  if (payload.actions && payload.actions.length > 0) {
    const lastFields = (embed.fields as Array<{ name: string; value: string; inline?: boolean }>) ?? [];
    lastFields.push({
      name: "Actions",
      value: payload.actions.slice(0, 5)
        .map((a) => `[${a.label.slice(0, 80)}](${a.url})`)
        .join(" · "),
      inline: false,
    });
    embed.fields = lastFields;
  }
  return { embeds: [embed] };
}

function buildTeamsAdaptiveCard(payload: WebhookPayloadV2): unknown {
  const event = payload.event ?? "info";
  const facts = payload.fields?.slice(0, 10).map((f) => ({
    title: f.name.slice(0, 60), value: f.value.slice(0, 200),
  })) ?? [];
  const actions = (payload.actions ?? []).slice(0, 5).map((a) => ({
    type: "Action.OpenUrl", title: a.label.slice(0, 60), url: a.url,
  }));
  const colorMap: Record<string, string> = {
    info: "accent", warn: "warning", alert: "attention",
  };
  const card = {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.4",
    body: [
      {
        type: "TextBlock",
        text: payload.title.slice(0, 200),
        weight: "Bolder", size: "Large",
        color: colorMap[event] ?? "default",
        wrap: true,
      },
      {
        type: "TextBlock",
        text: payload.summary.slice(0, 1900),
        wrap: true,
      },
      ...(facts.length > 0 ? [{ type: "FactSet", facts }] : []),
      {
        type: "TextBlock",
        text: `jpcite · kind=${payload.kind} · event=${event}`,
        size: "Small", isSubtle: true, wrap: true,
      },
    ],
    actions: [
      { type: "Action.OpenUrl", title: "View on jpcite", url: payload.url },
      ...actions,
    ],
  };
  return {
    type: "message",
    attachments: [{
      contentType: "application/vnd.microsoft.card.adaptive",
      contentUrl: null,
      content: card,
    }],
  };
}

async function fanOut(
  destinations: Record<string, string>, payload: WebhookPayloadV2,
): Promise<Record<string, number>> {
  const builders: Record<string, (p: WebhookPayloadV2) => unknown> = {
    slack: buildSlackBlockKit,
    discord: buildDiscordEmbed,
    teams: buildTeamsAdaptiveCard,
  };
  const results: Record<string, number> = {};
  await Promise.all(
    Object.entries(destinations).map(async ([target, url]) => {
      const body = builders[target](payload);
      try {
        const resp = await fetchWithTimeout(url, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }, OUTBOUND_FETCH_TIMEOUT_MS);
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

  const bodyRead = await readRequestTextLimited(ctx.request, MAX_BODY_BYTES);
  if (!bodyRead.ok) {
    return jsonResponse(413, { error: "body too large" });
  }
  const raw = bodyRead.text;

  const secret = resolveSecret(ctx.env, customerKey);
  if (!secret) {
    return jsonResponse(401, { error: "unknown customer_key" });
  }
  const ok = await verifySignature(raw, signature, timestamp, secret);
  if (!ok) {
    return jsonResponse(401, { error: "signature mismatch" });
  }

  let parsed: WebhookPayloadV2;
  try {
    parsed = JSON.parse(raw) as WebhookPayloadV2;
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
  if (parsed.event && !["info", "warn", "alert"].includes(parsed.event)) {
    return jsonResponse(400, { error: "invalid event level" });
  }

  const targets = parsed.targets.filter((t): t is "slack" | "discord" | "teams" =>
    ALLOWED_TARGETS.has(t),
  );
  if (targets.length === 0) {
    return jsonResponse(200, { delivered_to: [], skipped: "no valid targets" });
  }
  parsed.targets = targets;

  const destinations = loadDestinations(ctx.env, customerKey, targets);
  const results = await fanOut(destinations, parsed);

  return jsonResponse(200, {
    delivered_to: Object.keys(results),
    status_per_target: results,
    customer_key: customerKey,
    version: "v2",
  });
};

export const onRequestGet: PagesFunction<Env> = async () => {
  return jsonResponse(200, {
    name: "jpcite custom webhook router (v2)",
    method: "POST",
    body_schema: {
      kind: "string",
      event: "info | warn | alert (optional, default=info)",
      title: "string",
      url: "string",
      summary: "string",
      targets: "string[] (slack|discord|teams)",
      fields: "Array<{name,value,short?}> (optional, max 10)",
      actions: "Array<{label,url}> (optional, max 5)",
      data: "object (optional)",
    },
    headers: {
      "X-JPCITE-Signature": "hex(HMAC_SHA256(secret, timestamp + '.' + body))",
      "X-JPCITE-Timestamp": "ms epoch",
    },
    replay_window_ms: REPLAY_WINDOW_MS,
    max_body_bytes: MAX_BODY_BYTES,
    formats: {
      slack: "Block Kit (header + section + actions + context)",
      discord: "Embed (color + fields + timestamp)",
      teams: "AdaptiveCard 1.4 (FactSet + Action.OpenUrl)",
    },
  });
};
