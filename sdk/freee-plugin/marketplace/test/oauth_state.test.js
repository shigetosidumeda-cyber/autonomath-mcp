// Smoke tests for the OAuth state machine + proxy header logic.
// node --test compatible (Node 20+). No external dependencies.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

// Stand up the env BEFORE importing modules that read it.
process.env.FREEE_CLIENT_ID = 'test_client_id';
process.env.FREEE_CLIENT_SECRET = 'test_client_secret';
process.env.PLUGIN_BASE_URL = 'https://test.example.com';
process.env.JPCITE_API_BASE = 'https://api.test.jpcite.com';
process.env.JPCITE_API_KEY = 'am_test_KEY_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';
process.env.SESSION_SECRET = 'a'.repeat(40);
process.env.NODE_ENV = 'test';

const { ENV, FREEE_OAUTH, assertEnv } = await import('../src/lib/env.js');

test('assertEnv passes when all required vars present', () => {
  assert.doesNotThrow(() => assertEnv());
});

test('FREEE_OAUTH constants point at official freee endpoints', () => {
  assert.equal(FREEE_OAUTH.AUTHORIZE_URL, 'https://accounts.secure.freee.co.jp/public_api/authorize');
  assert.equal(FREEE_OAUTH.TOKEN_URL, 'https://accounts.secure.freee.co.jp/public_api/token');
  assert.equal(FREEE_OAUTH.API_BASE, 'https://api.freee.co.jp');
  assert.equal(FREEE_OAUTH.ACCESS_TOKEN_TTL_SEC, 6 * 60 * 60);
});

test('PLUGIN_BASE_URL strips trailing slash', () => {
  process.env.PLUGIN_BASE_URL = 'https://test.example.com/';
  assert.equal(ENV.PLUGIN_BASE_URL, 'https://test.example.com');
  process.env.PLUGIN_BASE_URL = 'https://test.example.com';
});

test('JPCITE_API_BASE has a sane default', () => {
  const saved = process.env.JPCITE_API_BASE;
  delete process.env.JPCITE_API_BASE;
  assert.equal(ENV.JPCITE_API_BASE, 'https://api.jpcite.com');
  process.env.JPCITE_API_BASE = saved;
});

test('legacy ZEIMU_KAIKEI aliases still work', () => {
  const savedBase = process.env.JPCITE_API_BASE;
  const savedKey = process.env.JPCITE_API_KEY;
  delete process.env.JPCITE_API_BASE;
  delete process.env.JPCITE_API_KEY;
  process.env.ZEIMU_KAIKEI_API_BASE = 'https://legacy-api.test.jpcite.com';
  process.env.ZEIMU_KAIKEI_API_KEY = 'legacy_test_key';

  assert.equal(ENV.JPCITE_API_BASE, 'https://legacy-api.test.jpcite.com');
  assert.equal(ENV.JPCITE_API_KEY, 'legacy_test_key');

  process.env.JPCITE_API_BASE = savedBase;
  process.env.JPCITE_API_KEY = savedKey;
  delete process.env.ZEIMU_KAIKEI_API_BASE;
  delete process.env.ZEIMU_KAIKEI_API_KEY;
});

test('assertEnv rejects short SESSION_SECRET', () => {
  const saved = process.env.SESSION_SECRET;
  process.env.SESSION_SECRET = 'short';
  assert.throws(() => assertEnv(), /SESSION_SECRET/);
  process.env.SESSION_SECRET = saved;
});

test('assertEnv reports missing var by name', () => {
  const saved = process.env.FREEE_CLIENT_ID;
  delete process.env.FREEE_CLIENT_ID;
  assert.throws(() => assertEnv(), /missing_env_vars/);
  process.env.FREEE_CLIENT_ID = saved;
});

test('public app does not synthesize direct program detail URLs', async () => {
  const source = await readFile(new URL('../src/public/app.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /https:\/\/jpcite\.com\/programs\/\$\{/);
  assert.match(source, /data\.static_url/);
  assert.match(source, /programs\/share\.html\?ids=/);
  assert.match(source, /https:\/\/jpcite\.com\/programs\//);
});
