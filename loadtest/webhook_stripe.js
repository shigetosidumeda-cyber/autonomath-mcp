// k6 load test for /v1/billing/webhook — Stripe retry storm simulation.
//
// Goal: verify idempotency under duplicate delivery. Stripe will replay
// invoice.paid many times (up to ~3 days) until it gets a 2xx. During any
// large customer-lifecycle event (pricing change, dunning clear-out) we
// can see 10-100+ retries per second. This script hammers the endpoint
// at constant-arrival-rate 20 rps for 3 min with the SAME subscription_id
// across events and verifies that the api_keys table does NOT gain more
// than one key for that subscription.
//
// The endpoint's idempotency check lives at
// src/jpintel_mcp/api/billing.py::webhook lines ~189-194:
//   SELECT 1 FROM api_keys WHERE stripe_subscription_id = ? LIMIT 1
//   -> if found, skip issue_key(). First writer wins.
//
// This test does NOT verify the SQL side-effect directly (that's tests/
// territory). It verifies the HTTP-layer contract: every replay returns
// 200, never duplicates or 500s the endpoint.
//
// Signing:
//   Stripe verifies requests via HMAC-SHA256 over "{timestamp}.{body}"
//   using the webhook secret. Without a valid signature we get 400. The
//   runner therefore needs STRIPE_WEBHOOK_TEST_SECRET — this must be a
//   DEDICATED TEST SECRET, never the production webhook secret. Rotate
//   it after each staging load test.
//
// Usage:
//   BASE_URL=https://jpintel-mcp-staging.fly.dev \
//   STRIPE_WEBHOOK_TEST_SECRET=whsec_test_xxx \
//   STRIPE_TEST_PRICE_ID=price_xxx \
//   STRIPE_TEST_SUBSCRIPTION_ID=sub_loadtest_xxx \
//   STRIPE_TEST_CUSTOMER_ID=cus_loadtest_xxx \
//   k6 run loadtest/webhook_stripe.js

import http from 'k6/http';
import crypto from 'k6/crypto';
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const SECRET = __ENV.STRIPE_WEBHOOK_TEST_SECRET || '';
const PRICE_ID = __ENV.STRIPE_TEST_PRICE_ID || 'price_loadtest';
// IMPORTANT: same subscription_id across the whole run. That is THE idempotency
// surface. If you change this per-iteration you are not testing idempotency,
// you are smoke-testing happy-path.
const SUBSCRIPTION_ID = __ENV.STRIPE_TEST_SUBSCRIPTION_ID || 'sub_loadtest_idempotency';
const CUSTOMER_ID = __ENV.STRIPE_TEST_CUSTOMER_ID || 'cus_loadtest';

export const options = {
  scenarios: {
    retry_storm: {
      executor: 'constant-arrival-rate',
      rate: 20,            // 20 events/sec
      timeUnit: '1s',
      duration: '3m',
      preAllocatedVUs: 20,  // 20 VU × 50ms avg latency ≈ enough headroom
      maxVUs: 50,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
    // Every request MUST return 200 (Stripe treats 2xx as ack; 4xx/5xx
    // triggers more retries, amplifying load). A single 500 trips this.
    'http_reqs{status:200}': ['count>3000'],  // 20rps × 180s × 95% floor
    errors_5xx: ['rate<0.001'],
    // A 400 here means our signing logic is broken — secret mismatch,
    // payload encoding, timestamp skew. Fail loudly.
    errors_400: ['rate<0.005'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

const errors400 = new Rate('errors_400');
const errors5xx = new Rate('errors_5xx');
const replays = new Counter('replay_events_sent');

// ---------------------------------------------------------------------------
// Stripe signature
// ---------------------------------------------------------------------------

function stripeSign(body, timestamp, secret) {
  // `Stripe-Signature: t=<ts>,v1=<hex_hmac>` — HMAC-SHA256 of the ASCII
  // string "<timestamp>.<raw_body>". See Stripe docs "Constructing an event".
  const payload = `${timestamp}.${body}`;
  const v1 = crypto.hmac('sha256', secret, payload, 'hex');
  return `t=${timestamp},v1=${v1}`;
}

// ---------------------------------------------------------------------------
// Event builder
// ---------------------------------------------------------------------------

function buildInvoicePaidEvent(iter) {
  // Stripe gives a unique event id per delivery — that's the ONLY thing
  // that differs between the first invoice.paid and its 99 retries. Our
  // idempotency on the server side keys on subscription, not event id,
  // so this ensures we test the "different event_id, same sub" storm.
  const eventId = `evt_loadtest_${Date.now()}_${iter}_${Math.random().toString(36).slice(2, 10)}`;
  const now = Math.floor(Date.now() / 1000);

  return {
    id: eventId,
    object: 'event',
    api_version: '2024-06-20',
    created: now,
    type: 'invoice.paid',
    livemode: false,
    data: {
      object: {
        id: `in_loadtest_${iter}`,
        object: 'invoice',
        status: 'paid',
        subscription: SUBSCRIPTION_ID,
        customer: CUSTOMER_ID,
        customer_email: 'loadtest@example.invalid',
        amount_paid: 11000,      // ¥11,000 ≈ 10,000 req @ ¥1/req 税別 + 10% JCT (pure metered)
        currency: 'jpy',
        // No need to nest full line_items — our handler only touches
        // .subscription, .customer, .customer_email on the invoice obj
        // and fetches Subscription separately (see api/billing.py L187).
      },
    },
    request: { id: null, idempotency_key: null },
  };
}

// ---------------------------------------------------------------------------
// Default VU loop — one event per iteration
// ---------------------------------------------------------------------------

export default function () {
  if (!SECRET) {
    // Fail fast in a way that shows up in the summary, not a 400 storm.
    throw new Error('STRIPE_WEBHOOK_TEST_SECRET not set — cannot sign requests');
  }

  // __ITER is k6-provided per-VU iteration counter; combined with VU number
  // to generate a unique event_id across the run.
  const event = buildInvoicePaidEvent(`${__VU}_${__ITER}`);
  const body = JSON.stringify(event);
  const ts = Math.floor(Date.now() / 1000);
  const sig = stripeSign(body, ts, SECRET);

  const res = http.post(`${BASE_URL}/v1/billing/webhook`, body, {
    headers: {
      'Content-Type': 'application/json',
      'Stripe-Signature': sig,
    },
    tags: { name: '/v1/billing/webhook' },
  });

  replays.add(1);
  errors400.add(res.status === 400);
  errors5xx.add(res.status >= 500);

  check(res, {
    'webhook: 200 OK': (r) => r.status === 200,
    'webhook: status=received in body': (r) => {
      try { return r.json('status') === 'received'; } catch (_e) { return false; }
    },
    // Negative assertion: the endpoint MUST NOT take longer than 500ms
    // under steady state. Stripe's client timeout for webhook delivery
    // is ~30s, but piling up behind a slow handler cascades.
    'webhook: under 500ms': (r) => r.timings.duration < 500,
  });
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data),
    'loadtest/summary_webhook_stripe.json': JSON.stringify(data, null, 2),
  };
}

function textSummary(data) {
  const m = data.metrics;
  const dur = m.http_req_duration.values;
  return [
    '=== jpintel-mcp /v1/billing/webhook idempotency storm ===',
    `  iterations      : ${m.iterations.values.count}`,
    `  replay events   : ${m.replay_events_sent ? m.replay_events_sent.values.count : 0}`,
    `  http reqs       : ${m.http_reqs.values.count}`,
    `  duration p95/p99: ${dur['p(95)'].toFixed(1)}ms / ${dur['p(99)'].toFixed(1)}ms`,
    `  400 rate        : ${(m.errors_400 ? m.errors_400.values.rate * 100 : 0).toFixed(3)}%`,
    `  5xx rate        : ${(m.errors_5xx ? m.errors_5xx.values.rate * 100 : 0).toFixed(3)}%`,
    '',
    '  POST-RUN MANUAL CHECK on staging DB:',
    `    sqlite3 /data/jpintel.db "SELECT COUNT(*) FROM api_keys`,
    `      WHERE stripe_subscription_id = '${SUBSCRIPTION_ID}';"`,
    '    -> expected: 1',
    '',
  ].join('\n');
}
