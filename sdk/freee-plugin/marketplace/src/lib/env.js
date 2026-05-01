// Centralized env access. assertEnv() runs at startup so a missing var
// crashes the boot loop instead of leaking 500s at request time.

// Required env vars. JPCITE_API_KEY is the canonical name (post 2026-04-30
// brand rename); ZEIMU_KAIKEI_API_KEY is accepted as a legacy alias and
// satisfies the requirement as well.
const REQUIRED_PLAIN = [
  'FREEE_CLIENT_ID',
  'FREEE_CLIENT_SECRET',
  'PLUGIN_BASE_URL',
  'SESSION_SECRET',
];
const REQUIRED_ALIASES = [['JPCITE_API_KEY', 'ZEIMU_KAIKEI_API_KEY']];

export const ENV = Object.freeze({
  get FREEE_CLIENT_ID() {
    return process.env.FREEE_CLIENT_ID ?? '';
  },
  get FREEE_CLIENT_SECRET() {
    return process.env.FREEE_CLIENT_SECRET ?? '';
  },
  get PLUGIN_BASE_URL() {
    return (process.env.PLUGIN_BASE_URL ?? '').replace(/\/+$/, '');
  },
  get JPCITE_API_BASE() {
    return (
      process.env.JPCITE_API_BASE ?? process.env.ZEIMU_KAIKEI_API_BASE ?? 'https://api.jpcite.com'
    ).replace(/\/+$/, '');
  },
  get JPCITE_API_KEY() {
    return process.env.JPCITE_API_KEY ?? process.env.ZEIMU_KAIKEI_API_KEY ?? '';
  },
  get ZEIMU_KAIKEI_API_BASE() {
    return this.JPCITE_API_BASE;
  },
  get ZEIMU_KAIKEI_API_KEY() {
    return this.JPCITE_API_KEY;
  },
  get SESSION_SECRET() {
    return process.env.SESSION_SECRET ?? '';
  },
  get NODE_ENV() {
    return process.env.NODE_ENV ?? 'development';
  },
});

export function assertEnv() {
  const missing = REQUIRED_PLAIN.filter((k) => !process.env[k]);
  for (const aliasGroup of REQUIRED_ALIASES) {
    if (!aliasGroup.some((k) => process.env[k])) {
      missing.push(aliasGroup.join('|'));
    }
  }
  if (missing.length > 0) {
    // eslint-disable-next-line no-console
    console.error(
      '[jpcite-freee-plugin] missing env vars:',
      missing.join(', '),
    );
    throw new Error('missing_env_vars');
  }
  if ((process.env.SESSION_SECRET ?? '').length < 32) {
    throw new Error(
      'SESSION_SECRET must be at least 32 chars (use `openssl rand -hex 32`)',
    );
  }
}

// freee OAuth2 endpoints (per freee developer docs, verified 2026-04-29).
export const FREEE_OAUTH = Object.freeze({
  AUTHORIZE_URL: 'https://accounts.secure.freee.co.jp/public_api/authorize',
  TOKEN_URL: 'https://accounts.secure.freee.co.jp/public_api/token',
  API_BASE: 'https://api.freee.co.jp',
  // freee returns a 6h access_token + 90d single-use refresh_token.
  ACCESS_TOKEN_TTL_SEC: 6 * 60 * 60,
});
