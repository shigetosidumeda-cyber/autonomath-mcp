// Verifies that the search proxy:
//   - Refuses unauthenticated requests.
//   - Forwards x-api-key + 法人番号 header.
//   - Strips api_key / _internal from upstream payloads.
//   - Always appends _disclaimer.

import { test } from 'node:test';
import assert from 'node:assert/strict';

process.env.FREEE_CLIENT_ID ??= 'test_client_id';
process.env.FREEE_CLIENT_SECRET ??= 'test_client_secret';
process.env.PLUGIN_BASE_URL ??= 'https://test.example.com';
process.env.JPCITE_API_BASE ??= 'https://api.test.jpcite.com';
process.env.JPCITE_API_KEY ??= 'am_test_KEY_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';
process.env.SESSION_SECRET ??= 'a'.repeat(40);
process.env.NODE_ENV = 'test';

// Replace global fetch with a stub for upstream calls.
const calls = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  calls.push({ url: String(url), init });
  return new Response(
    JSON.stringify({
      items: [
        { unified_id: 'P-1', primary_name: 'テスト補助金', tier: 'A', source_url: 'https://example.gov.jp/' },
      ],
      api_key: 'LEAKED_NEVER_FORWARD',
      _internal: { secret: 'LEAKED' },
    }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  );
};

const express = (await import('express')).default;
const session = (await import('express-session')).default;
const { searchRouter } = await import('../src/routes/search.js');

function buildApp() {
  const app = express();
  app.use(express.json());
  app.use(
    session({
      name: 'test_sid',
      secret: 'a'.repeat(40),
      resave: false,
      saveUninitialized: true,
    }),
  );
  // For the test we mount a hook to inject a fake freee session.
  app.use((req, _res, next) => {
    if (req.headers['x-test-auth']) {
      req.session.freee = {
        access_token: 'tok_test',
        token_acquired_at: Math.floor(Date.now() / 1000),
        company_id: 999001,
        company_name: 'テスト株式会社',
        houjin_bangou: '8010001213708',
      };
    }
    next();
  });
  app.use('/freee-plugin', searchRouter);
  return app;
}

test('search proxy rejects unauthenticated request', async () => {
  const app = buildApp();
  const server = app.listen(0);
  const port = server.address().port;
  const r = await realFetch(`http://127.0.0.1:${port}/freee-plugin/search-subsidies?q=foo`);
  const j = await r.json();
  assert.equal(r.status, 401);
  assert.equal(j.error, 'not_authenticated');
  assert.match(j._disclaimer, /税理士法/);
  server.close();
});

test('search proxy forwards x-api-key + houjin_bangou; strips secrets', async () => {
  calls.length = 0;
  const app = buildApp();
  const server = app.listen(0);
  const port = server.address().port;
  const r = await realFetch(
    `http://127.0.0.1:${port}/freee-plugin/search-subsidies?q=省エネ&prefecture=東京都`,
    { headers: { 'x-test-auth': '1' } },
  );
  const j = await r.json();
  assert.equal(r.status, 200);

  // Upstream call carried the right headers.
  assert.equal(calls.length, 1);
  const headers = calls[0].init.headers;
  assert.equal(headers['x-api-key'], process.env.JPCITE_API_KEY);
  assert.equal(headers['x-zk-houjin-bangou'], '8010001213708');
  assert.equal(headers['x-zk-freee-company-id'], '999001');

  // Response stripped api_key and _internal.
  assert.equal(j.api_key, undefined);
  assert.equal(j._internal, undefined);
  assert.match(j._disclaimer, /税理士法/);
  assert.equal(j._company_context.company_name, 'テスト株式会社');
  assert.equal(j.items[0].unified_id, 'P-1');

  server.close();
});

test('invoice number normalization adds T prefix when missing', async () => {
  calls.length = 0;
  const app = buildApp();
  const server = app.listen(0);
  const port = server.address().port;
  await realFetch(
    `http://127.0.0.1:${port}/freee-plugin/check-invoice-registrant?q=8010001213708`,
    { headers: { 'x-test-auth': '1' } },
  );
  const url = calls[0].url;
  assert.match(url, /q=T8010001213708/);
  server.close();
});

// Restore fetch for any subsequent tests.
test.after(() => {
  globalThis.fetch = realFetch;
});
