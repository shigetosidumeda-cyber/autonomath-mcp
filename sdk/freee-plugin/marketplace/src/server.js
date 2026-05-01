// jpcite — freee app marketplace plugin entry point.
//
// This is a thin proxy that:
//   1. Owns the freee OAuth2 dance (authorization_code grant).
//   2. Stores the freee user's access_token + company snapshot in an Express
//      session cookie (server-side, HttpOnly, Secure).
//   3. Proxies search requests to api.jpcite.com using a Bookyou-owned
//      service API key. The freee end-user is NEVER charged directly; usage
//      is metered against the marketplace app subscription owned by Bookyou.
//   4. Renders a vanilla-HTML pop-out UI inside freee's iframe.
//
// Constraints (do not relax):
//   - NO Anthropic / OpenAI / LLM API calls from this process. The plugin
//     is a stateless proxy + UI. Inference, if any, happens on the customer's
//     own LLM (Claude Desktop, ChatGPT etc.).
//   - NO seat fees, NO tier upgrades. Per-request ¥3.30 metering only.
//   - 税理士法 §52 disclaimer is hard-coded into the UI and every JSON
//     response carries a `_disclaimer` field.
//
// Reference: see ../README.md and ../submission/ for the marketplace package.

import express from 'express';
import session from 'express-session';
import cookieParser from 'cookie-parser';
import helmet from 'helmet';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { oauthRouter } from './routes/oauth.js';
import { searchRouter } from './routes/search.js';
import { healthRouter } from './routes/health.js';
import { ENV, assertEnv } from './lib/env.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

assertEnv();

const app = express();

// --- security middleware -------------------------------------------------
// freee renders our app inside an iframe at https://app.secure.freee.co.jp
// Allow that single ancestor; deny everything else.
app.use(
  helmet({
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        scriptSrc: ["'self'", "'unsafe-inline'"], // inline only for the small popup
        styleSrc: ["'self'", "'unsafe-inline'"],
        imgSrc: ["'self'", 'data:', 'https://jpcite.com'],
        connectSrc: ["'self'"],
        frameAncestors: [
          "'self'",
          'https://app.secure.freee.co.jp',
          'https://accounts.secure.freee.co.jp',
        ],
      },
    },
    crossOriginEmbedderPolicy: false, // freee iframe is on a different origin
  }),
);

app.use(cookieParser());
app.use(express.json({ limit: '64kb' }));
app.use(express.urlencoded({ extended: false }));

// Trust X-Forwarded-Proto on Fly.io / Cloudflare so secure cookies work.
app.set('trust proxy', 1);

app.use(
  session({
    name: 'jpcite_freee_sid',
    secret: ENV.SESSION_SECRET,
    resave: false,
    saveUninitialized: false,
    rolling: true,
    cookie: {
      httpOnly: true,
      secure: ENV.NODE_ENV === 'production',
      sameSite: 'none', // required to be readable inside freee's iframe
      maxAge: 6 * 60 * 60 * 1000, // 6h matches freee access token TTL
    },
  }),
);

// --- routes --------------------------------------------------------------

// /healthz — Fly.io / uptime probe
app.use('/healthz', healthRouter);

// /oauth/{authorize,callback,logout} — freee OAuth2 dance
app.use('/oauth', oauthRouter);

// /freee-plugin/{search-tax-incentives,search-subsidies,check-invoice-registrant}
// — proxy endpoints to api.jpcite.com
app.use('/freee-plugin', searchRouter);

// /static — vanilla HTML + JS popup UI rendered inside freee's iframe
app.use(
  '/static',
  express.static(join(__dirname, 'public'), {
    maxAge: '1h',
    setHeaders(res) {
      res.setHeader('X-Content-Type-Options', 'nosniff');
    },
  }),
);

// Root — bounce to the popup UI (or to OAuth if not authed)
app.get('/', (req, res) => {
  if (!req.session?.freee?.access_token) {
    return res.redirect('/oauth/authorize');
  }
  return res.redirect('/static/index.html');
});

// --- 404 + error handler -------------------------------------------------
app.use((req, res) => {
  res.status(404).json({
    error: 'not_found',
    path: req.path,
    _disclaimer:
      '税理士法 §52 — 本サービスは税理士業務に該当する個別アドバイスを行いません。',
  });
});

app.use((err, _req, res, _next) => {
  // Never leak token / secret in error bodies.
  const safeMessage =
    typeof err?.publicMessage === 'string'
      ? err.publicMessage
      : 'internal_server_error';
  const status = Number.isInteger(err?.status) ? err.status : 500;
  res.status(status).json({
    error: safeMessage,
    request_id: res.getHeader('X-Request-Id') ?? null,
  });
  // Server-side log: scrub auth headers before printing.
  const scrubbed = {
    name: err?.name,
    message: err?.message,
    stack: err?.stack?.split('\n').slice(0, 5).join('\n'),
  };
  // eslint-disable-next-line no-console
  console.error('[plugin-error]', JSON.stringify(scrubbed));
});

// --- boot ----------------------------------------------------------------
const PORT = Number(process.env.PORT ?? 8080);
app.listen(PORT, '0.0.0.0', () => {
  // eslint-disable-next-line no-console
  console.log(
    `[jpcite-freee-plugin] listening on :${PORT} (env=${ENV.NODE_ENV})`,
  );
});
