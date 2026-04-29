// /freee-plugin/{search-tax-incentives,search-subsidies,check-invoice-registrant}
//
// Thin proxy → api.zeimu-kaikei.ai. The freee end-user is NOT charged
// directly. We attach the Bookyou-owned service API key, so usage is metered
// against the marketplace app's Stripe subscription. The freee user's
// company context (法人番号 / company_id) is forwarded as scoping headers but
// never as auth.
//
// Disclaimer: every JSON response carries `_disclaimer` (税理士法 §52).

import { Router } from 'express';

import { ENV } from '../lib/env.js';

export const searchRouter = Router();

const DISCLAIMER =
  '本サービスは情報提供のみを目的とし、税理士法第52条に基づく個別の税務相談・申告書作成等には該当しません。最終的な税務判断は、貴社の顧問税理士にご確認ください。';

// Auth gate: every plugin endpoint requires an active freee session.
function requireFreeeSession(req, res, next) {
  if (!req.session?.freee?.access_token) {
    return res
      .status(401)
      .json({ error: 'not_authenticated', login_url: '/oauth/authorize', _disclaimer: DISCLAIMER });
  }
  // Token age check — freee access_token TTL is 6h; if it's older we force
  // a re-auth (refresh-token rotation can come later).
  const age = Math.floor(Date.now() / 1000) - (req.session.freee.token_acquired_at ?? 0);
  if (age > 6 * 60 * 60 - 60) {
    return res
      .status(401)
      .json({ error: 'session_expired', login_url: '/oauth/authorize', _disclaimer: DISCLAIMER });
  }
  return next();
}

searchRouter.use(requireFreeeSession);

// Build headers for upstream calls. Service key is server-only; never echo'd.
function upstreamHeaders(session) {
  const headers = {
    accept: 'application/json',
    'x-api-key': ENV.ZEIMU_KAIKEI_API_KEY,
    'user-agent': 'zeimu-kaikei-freee-plugin/0.1',
  };
  // Forward freee context for analytics + 法人番号 scoping (read-only).
  // These are NOT auth — server still uses our service key for metering.
  if (session.freee?.houjin_bangou) {
    headers['x-zk-houjin-bangou'] = session.freee.houjin_bangou;
  }
  if (session.freee?.company_id) {
    headers['x-zk-freee-company-id'] = String(session.freee.company_id);
  }
  return headers;
}

// Fetch helper with timeout + JSON safety. Drops upstream `_internal` keys
// before responding to the freee iframe.
async function proxyJson(upstreamPath, params, session, res) {
  const url = new URL(`${ENV.ZEIMU_KAIKEI_API_BASE}${upstreamPath}`);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v == null || v === '') continue;
    if (Array.isArray(v)) {
      for (const vv of v) url.searchParams.append(k, String(vv));
    } else {
      url.searchParams.set(k, String(v));
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  let upstream;
  try {
    upstream = await fetch(url, {
      headers: upstreamHeaders(session),
      signal: controller.signal,
    });
  } catch (e) {
    res.status(504).json({
      error: 'upstream_timeout',
      hint: 'api.zeimu-kaikei.ai did not respond in 15s',
      _disclaimer: DISCLAIMER,
    });
    return;
  } finally {
    clearTimeout(timer);
  }

  const body = await upstream.json().catch(() => null);
  if (!upstream.ok || !body) {
    res.status(upstream.status === 429 ? 429 : 502).json({
      error: 'upstream_error',
      status: upstream.status,
      _disclaimer: DISCLAIMER,
    });
    return;
  }

  // Defense in depth: drop fields that should never reach the freee user.
  const safe = { ...body };
  delete safe.api_key;
  delete safe._internal;

  res.json({
    ...safe,
    _disclaimer: DISCLAIMER,
    _company_context: {
      company_id: session.freee.company_id,
      company_name: session.freee.company_name,
      houjin_bangou: session.freee.houjin_bangou,
    },
  });
}

// 1. 税制優遇 検索 -------------------------------------------------------
// Maps to GET /v1/am/tax_incentives upstream.
searchRouter.get('/search-tax-incentives', async (req, res) => {
  const params = {
    q: req.query.q,
    limit: clampLimit(req.query.limit),
    natural_query: req.query.natural_query,
  };
  await proxyJson('/v1/am/tax_incentives', params, req.session, res);
});

// 2. 補助金 検索 ---------------------------------------------------------
// Maps to GET /v1/programs/search (existing AutonoMath endpoint).
searchRouter.get('/search-subsidies', async (req, res) => {
  const params = {
    q: req.query.q,
    tier: req.query.tier ?? ['S', 'A', 'B'],
    prefecture: req.query.prefecture,
    limit: clampLimit(req.query.limit),
  };
  await proxyJson('/v1/programs/search', params, req.session, res);
});

// 3. インボイス登録番号 確認 --------------------------------------------
// Maps to GET /v1/invoice_registrants/search?q={number}.
// freee user typically pastes a T... number from a 仕入先 record.
searchRouter.get('/check-invoice-registrant', async (req, res) => {
  const raw = String(req.query.q ?? '').trim();
  // 適格請求書発行事業者番号 = "T" + 13 digits. Accept with or without "T".
  const normalized = /^T?\d{13}$/.test(raw)
    ? raw.startsWith('T')
      ? raw
      : `T${raw}`
    : raw;
  const params = {
    q: normalized,
    limit: 5,
  };
  await proxyJson('/v1/invoice_registrants/search', params, req.session, res);
});

// --- helpers -------------------------------------------------------------
function clampLimit(raw) {
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1) return 5;
  return Math.min(n, 20);
}
