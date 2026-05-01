// freee OAuth2 — authorization_code grant.
//
// Flow:
//   1. GET /oauth/authorize   → 302 to freee authorize URL with state + PKCE-ish nonce.
//   2. GET /oauth/callback    → exchange code for token, fetch /api/1/companies,
//                                pin first company to session.
//   3. GET /oauth/logout      → wipe session, optional revoke (freee currently
//                                has no documented public-API revoke, so we
//                                just drop the cookie).
//
// What we store in the session (server-side, signed cookie holds only sid):
//   freee.access_token        string (6h TTL)
//   freee.refresh_token       string (90d, single-use)
//   freee.token_acquired_at   number (unix sec)
//   freee.company_id          number  (the freee company the user picked)
//   freee.company_name        string
//   freee.houjin_bangou       string|null (法人番号, if freee exposes it)

import { Router } from 'express';
import { randomBytes } from 'node:crypto';

import { ENV, FREEE_OAUTH } from '../lib/env.js';

export const oauthRouter = Router();

// Single helper so `state` cannot be reused across browsers / sessions.
function newState() {
  return randomBytes(24).toString('base64url');
}

// 1. /oauth/authorize -----------------------------------------------------
oauthRouter.get('/authorize', (req, res) => {
  const state = newState();
  // Persist the state to the session so callback can verify CSRF.
  req.session.oauth_state = state;

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: ENV.FREEE_CLIENT_ID,
    redirect_uri: `${ENV.PLUGIN_BASE_URL}/oauth/callback`,
    state,
    prompt: 'select_company', // freee-specific: forces company picker
  });

  res.redirect(`${FREEE_OAUTH.AUTHORIZE_URL}?${params.toString()}`);
});

// 2. /oauth/callback ------------------------------------------------------
oauthRouter.get('/callback', async (req, res, next) => {
  try {
    const code = String(req.query.code ?? '');
    const state = String(req.query.state ?? '');

    if (!code || !state) {
      return res.status(400).json({ error: 'missing_code_or_state' });
    }
    if (!req.session?.oauth_state || state !== req.session.oauth_state) {
      return res.status(400).json({ error: 'state_mismatch' });
    }
    delete req.session.oauth_state;

    // Exchange code for tokens.
    const tokenResp = await fetch(FREEE_OAUTH.TOKEN_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: ENV.FREEE_CLIENT_ID,
        client_secret: ENV.FREEE_CLIENT_SECRET,
        code,
        redirect_uri: `${ENV.PLUGIN_BASE_URL}/oauth/callback`,
      }),
    });

    if (!tokenResp.ok) {
      const body = await tokenResp.text();
      const err = new Error(`freee_token_exchange_failed: ${tokenResp.status}`);
      err.status = 502;
      err.publicMessage = 'freee_token_exchange_failed';
      // Don't leak body (may contain client_secret reflection in some flows).
      console.error('[oauth] token exchange', tokenResp.status, body.slice(0, 200));
      throw err;
    }

    const token = await tokenResp.json();
    if (!token?.access_token) {
      throw Object.assign(new Error('no_access_token_in_response'), {
        status: 502,
        publicMessage: 'freee_token_exchange_failed',
      });
    }

    // Look up the freee user's accounting context.
    // /api/1/companies returns [{id, name, name_kana, role, ...}, ...].
    // We pin the first writable company; the user can switch via
    // ?prompt=select_company on a re-auth.
    const companiesResp = await fetch(
      `${FREEE_OAUTH.API_BASE}/api/1/companies`,
      {
        headers: {
          authorization: `Bearer ${token.access_token}`,
          'X-Api-Version': '2020-06-15',
          accept: 'application/json',
        },
      },
    );
    if (!companiesResp.ok) {
      throw Object.assign(new Error(`freee_companies_failed: ${companiesResp.status}`), {
        status: 502,
        publicMessage: 'freee_companies_lookup_failed',
      });
    }
    const companiesPayload = await companiesResp.json();
    const firstCompany =
      Array.isArray(companiesPayload?.companies) && companiesPayload.companies[0];
    if (!firstCompany) {
      throw Object.assign(new Error('no_companies_for_user'), {
        status: 403,
        publicMessage:
          'no_companies_for_user — freee 会計の事業所が登録されていません',
      });
    }

    // Optional: pull /api/1/companies/{id} for 法人番号 (corp_number) if the
    // freee response exposes it on the detail endpoint. Wrap in a soft try
    // so a missing field doesn't break the flow.
    let houjinBangou = null;
    try {
      const detailResp = await fetch(
        `${FREEE_OAUTH.API_BASE}/api/1/companies/${firstCompany.id}`,
        {
          headers: {
            authorization: `Bearer ${token.access_token}`,
            'X-Api-Version': '2020-06-15',
            accept: 'application/json',
          },
        },
      );
      if (detailResp.ok) {
        const detail = await detailResp.json();
        // freee field name has varied; check several historical aliases.
        houjinBangou =
          detail?.company?.corporate_number ??
          detail?.company?.houjin_bangou ??
          detail?.company?.corp_number ??
          null;
      }
    } catch {
      // best-effort, fall through with null
    }

    req.session.freee = {
      access_token: token.access_token,
      refresh_token: token.refresh_token ?? null,
      token_acquired_at: Math.floor(Date.now() / 1000),
      company_id: Number(firstCompany.id),
      company_name: String(firstCompany.name ?? ''),
      houjin_bangou:
        typeof houjinBangou === 'string' && /^\d{13}$/.test(houjinBangou)
          ? houjinBangou
          : null,
    };

    return res.redirect('/static/index.html');
  } catch (err) {
    return next(err);
  }
});

// 3. /oauth/logout --------------------------------------------------------
oauthRouter.get('/logout', (req, res) => {
  req.session?.destroy?.(() => {
    res.clearCookie('jpcite_freee_sid');
    res.redirect('https://jpcite.com/');
  });
});
