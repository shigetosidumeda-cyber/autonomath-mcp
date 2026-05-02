// dashboard.js — wires site/dashboard.html to /v1/session + /v1/me/*
// Plain ES2020, no build system, no external deps. Same-origin relative URLs
// assume the dashboard is served from the same host as the API (or a reverse
// proxy that forwards /v1/* to the API). Override via window.JPCITE_API_BASE
// if a separate origin is ever used (then CORS + allow_credentials must be on).
(() => {
  'use strict';

  // ------------------------------------------------------------------
  // config
  // ------------------------------------------------------------------
  const API_BASE = (typeof window !== 'undefined' && window.JPCITE_API_BASE) || (typeof window !== 'undefined' && window.location && window.location.hostname === 'jpcite.com' ? 'https://api.jpcite.com' : '');
  const api = (p) => API_BASE.replace(/\/$/, '') + p;

  // CSRF double-submit cookie pattern. On /v1/session sign-in
  // the server sets a non-httponly `am_csrf` cookie alongside the session
  // cookie. Every state-changing session-cookie POST must echo the cookie
  // value back as `X-CSRF-Token`. We also keep the historic
  // `X-Requested-With` flag — a defence-in-depth signal, harmless to send.
  function _readCookie(name) {
    if (typeof document === 'undefined' || !document.cookie) return '';
    const parts = document.cookie.split(';');
    for (let i = 0; i < parts.length; i++) {
      const seg = parts[i].trim();
      if (!seg) continue;
      const eq = seg.indexOf('=');
      const k = eq < 0 ? seg : seg.slice(0, eq);
      if (k === name) {
        return eq < 0 ? '' : decodeURIComponent(seg.slice(eq + 1));
      }
    }
    return '';
  }
  function csrfHeaders() {
    const tok = _readCookie('am_csrf');
    const h = { 'X-Requested-With': 'XMLHttpRequest' };
    if (tok) h['X-CSRF-Token'] = tok;
    return h;
  }

  // Authenticated users are 100% metered ¥3/req (税込 ¥3.30) with no daily
  // cap. The 100/day floor below is *only* surfaced when a Stripe
  // subscription enters dunning recovery (past_due / unpaid / incomplete) —
  // it is not a tier and there is no "free plan" at the authenticated layer.
  // Anonymous IP-based 3/day behavior lives in the anon_rate_limit
  // middleware and never reaches this dashboard view.
  // Mirror of .env.example: RATE_LIMIT_FREE_PER_DAY=100.
  const DUNNING_DEMOTE_DAILY = 100;
  const DUNNING_STATUSES = new Set(['past_due', 'unpaid', 'incomplete']);
  function isDunningDemoted(me) {
    const s = me && typeof me.subscription_status === 'string'
      ? me.subscription_status.toLowerCase()
      : null;
    return s !== null && DUNNING_STATUSES.has(s);
  }

  // Min interval between quota refreshes (ms). 60s keeps overnight tabs quiet.
  const QUOTA_REFRESH_MS = 60 * 1000;
  let _quotaTimer = null;
  // Cached /v1/me payload so the 60s refresher can re-derive the tier quota
  // without re-hitting /v1/me (only /v1/me/usage actually needs to refresh).
  let _lastMe = null;

  // ------------------------------------------------------------------
  // tiny helpers
  // ------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const setText = (sel, txt) => { const el = $(sel); if (el) el.textContent = txt; };
  // NB: the existing stylesheet sets `display: flex/grid` on .dash-nav,
  // .stat-grid, .actions-row — those declarations win over [hidden]'s
  // `display: none`. We therefore toggle display directly (restoring ''
  // means "whatever CSS said").
  const show = (el) => {
    if (!el) return;
    el.removeAttribute('hidden');
    el.style.display = '';
  };
  const hide = (el) => {
    if (!el) return;
    el.setAttribute('hidden', '');
    el.style.display = 'none';
  };

  async function fetchJSON(path, opts = {}) {
    const init = Object.assign({ credentials: 'same-origin' }, opts);
    init.headers = Object.assign(
      { 'Accept': 'application/json' },
      opts.body ? { 'Content-Type': 'application/json' } : {},
      opts.headers || {}
    );
    // Default 15 s timeout. Hung connections (3G, Stripe degraded, server
    // wedged) used to leave the user staring at "送信中..." forever. Caller
    // can pass init.signal to chain its own AbortController, or opts.timeoutMs
    // to override.
    let _timer = null;
    if (!init.signal) {
      const ctrl = new AbortController();
      init.signal = ctrl.signal;
      _timer = setTimeout(() => ctrl.abort(), opts.timeoutMs || 15000);
    }
    let resp;
    try {
      resp = await fetch(api(path), init);
    } catch (err) {
      if (err && err.name === 'AbortError') {
        const e = new Error('タイムアウト — 回線が遅いか、サーバが応答していません。');
        e.status = 0; e.timeout = true;
        throw e;
      }
      throw err;
    } finally {
      if (_timer) clearTimeout(_timer);
    }
    let body = null;
    const text = await resp.text();
    if (text) {
      try { body = JSON.parse(text); } catch { body = null; }
    }
    if (!resp.ok) {
      // Non-JSON upstream bodies (e.g. a static-host HTML 404 page) used to
      // bleed verbatim into the status bar. Surface the HTTP code only and
      // keep the raw text off-screen to avoid escaping DOCTYPE into the UI.
      const detail = (body && (body.detail || body.message)) || `HTTP ${resp.status}`;
      const err = new Error(detail);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  // ------------------------------------------------------------------
  // DOM setup — we augment the existing dashboard.html in place
  // ------------------------------------------------------------------
  function buildScaffold() {
    // Container where we'll render alerts / spinners.
    const dashSection = document.querySelector('.dash .container');
    if (!dashSection) return;

    // --- status bar (alerts + spinner) — inserted right after <.sub> (or <h1>) ---
    if (!$('#dash-status')) {
      const bar = document.createElement('div');
      bar.id = 'dash-status';
      bar.style.cssText = 'margin:0 0 14px;min-height:0;';
      const anchor = $('.dash .sub') || $('.dash h1');
      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(bar, anchor.nextSibling);
      } else {
        dashSection.prepend(bar);
      }
    }

    // --- sign-in card — hidden by default, shown when /v1/me returns 401.
    // Inserted right after the status bar so it's the first thing users see
    // when not signed in.
    if (!$('#dash-signin')) {
      const card = document.createElement('div');
      card.id = 'dash-signin';
      card.hidden = true;
      card.className = 'stat-card';
      card.style.cssText = 'margin:18px 0 24px;max-width:520px;';
      card.innerHTML = `
        <p class="stat-label" id="dash-signin-heading">サインイン</p>
        <p class="stat-note" id="dash-signin-help" style="margin:0 0 12px;">Stripe から発行された API key を貼り付けてください (<code>am_…</code>)。</p>
        <form id="dash-signin-form" autocomplete="off" aria-labelledby="dash-signin-heading" aria-describedby="dash-signin-help" style="display:flex;gap:8px;flex-wrap:wrap;">
          <label for="dash-signin-key" class="visually-hidden">API key</label>
          <input id="dash-signin-key" name="api_key" type="password" inputmode="text" required
                 autocomplete="off"
                 placeholder="am_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                 aria-describedby="dash-signin-help dash-signin-err"
                 style="flex:1;min-width:260px;padding:9px 12px;border:1px solid var(--border);border-radius:6px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;" />
          <button type="submit" class="btn btn-primary" id="dash-signin-submit">Sign in</button>
        </form>
        <p class="stat-note" id="dash-signin-err" role="alert" aria-live="polite" style="color:var(--danger);margin:10px 0 0;" hidden></p>
      `;
      const status = $('#dash-status');
      if (status && status.parentNode) {
        status.parentNode.insertBefore(card, status.nextSibling);
      } else {
        dashSection.appendChild(card);
      }
    }

    // --- signed-in wrapper — we'll hide all pre-existing cards until login.
    // Collect existing blocks so we can toggle them as a group.
    const prelogin = $('#dash-signin');
    const postElsSet = new Set();
    const postSelectors = [
      '.dash-nav',
      '#quota-counter',
      '.stat-grid',
      '.chart-card',
      '.keybox',
      '.actions-row',
    ];
    for (const sel of postSelectors) {
      document.querySelectorAll(sel).forEach((el) => postElsSet.add(el));
    }
    // billing stat-card (outside stat-grid)
    document
      .querySelectorAll('.dash .stat-card:not(#dash-signin)')
      .forEach((el) => {
        // skip ones already inside stat-grid since that's already queued
        if (!el.closest('.stat-grid')) postElsSet.add(el);
      });
    window.__dashPostEls = Array.from(postElsSet);
    window.__dashPreEl = prelogin;

    // Wire buttons that already exist in the HTML.
    const rotateBtn = document.querySelector('.keybox .btn-danger');
    const copyBtn = document.querySelector('.keybox .btn-ghost');
    const manageBilling = Array.from(document.querySelectorAll('.btn')).find(
      (a) => (a.textContent || '').trim().toLowerCase().startsWith('manage billing')
    );
    const logoutLink = Array.from(document.querySelectorAll('.dash-nav a, .dash-nav button')).find(
      (a) => (a.textContent || '').trim().toLowerCase() === 'log out'
    );
    if (rotateBtn) { rotateBtn.id = 'dash-rotate-btn'; rotateBtn.type = 'button'; }
    if (copyBtn) { copyBtn.id = 'dash-copy-btn'; copyBtn.type = 'button'; }
    if (manageBilling) manageBilling.id = 'dash-billing-btn';
    if (logoutLink) logoutLink.id = 'dash-logout-link';
  }

  // ------------------------------------------------------------------
  // status bar (spinner + alert)
  // ------------------------------------------------------------------
  let _spinCount = 0;
  function withSpinner(label = '') {
    _spinCount += 1;
    renderStatus();
    return () => {
      _spinCount = Math.max(0, _spinCount - 1);
      renderStatus();
    };
  }
  let _alertMsg = null;
  function setAlert(msg) { _alertMsg = msg || null; renderStatus(); }
  function renderStatus() {
    const bar = $('#dash-status');
    if (!bar) return;
    const spin = _spinCount > 0
      ? `<span role="status" aria-live="polite" style="display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--text-muted);">
           <span style="width:12px;height:12px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;display:inline-block;animation:dash-spin 0.8s linear infinite;"></span>
           読み込み中…
         </span>`
      : '';
    const alert = _alertMsg
      ? `<div role="alert" style="margin-top:${spin?'8px':'0'};padding:10px 14px;border:1px solid var(--danger);background:#fff0f0;color:var(--danger);border-radius:6px;font-size:13px;">${escapeHtml(_alertMsg)}</div>`
      : '';
    bar.innerHTML = spin + alert;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]
    ));
  }
  // inject spinner keyframes once
  if (!document.getElementById('dash-spin-kf')) {
    const st = document.createElement('style');
    st.id = 'dash-spin-kf';
    st.textContent = '@keyframes dash-spin { to { transform: rotate(360deg); } }';
    document.head.appendChild(st);
  }

  // ------------------------------------------------------------------
  // view state
  // ------------------------------------------------------------------
  function showSignedIn() {
    hide(window.__dashPreEl);
    (window.__dashPostEls || []).forEach(show);
  }
  function showSignedOut() {
    show(window.__dashPreEl);
    (window.__dashPostEls || []).forEach(hide);
    const sub = document.querySelector('.dash .sub');
    if (sub) sub.innerHTML = 'API key を入力してダッシュボードを開いてください。';
  }

  // ------------------------------------------------------------------
  // bind handlers
  // ------------------------------------------------------------------
  function bind() {
    const form = $('#dash-signin-form');
    if (form) form.addEventListener('submit', onSignIn);

    const rotateBtn = $('#dash-rotate-btn');
    if (rotateBtn) rotateBtn.addEventListener('click', onRotate);

    const copyBtn = $('#dash-copy-btn');
    if (copyBtn) copyBtn.addEventListener('click', onCopyPrefix);

    const billingBtn = $('#dash-billing-btn');
    if (billingBtn) {
      billingBtn.addEventListener('click', (e) => {
        e.preventDefault();
        onBillingPortal();
      });
    }
    const logoutLink = $('#dash-logout-link');
    if (logoutLink) {
      logoutLink.addEventListener('click', (e) => {
        e.preventDefault();
        onLogout();
      });
    }
  }

  // ------------------------------------------------------------------
  // load flow
  // ------------------------------------------------------------------
  async function loadMe() {
    setAlert(null);
    const done = withSpinner();
    try {
      const me = await fetchJSON('/v1/me');
      renderMe(me);
      showSignedIn();
      // fetch usage independently
      loadUsage().catch((e) => {
        setAlert(`usage: ${e.message || e}`);
      });
    } catch (e) {
      // Suppress the red banner for the unauthenticated
      // initial load. A first-time visitor with no cookie hits /v1/me and
      // gets 401 (or 404 against a static-host preview, or 0 for offline).
      // Showing "HTTP 404" / "ネットワークエラー" here is hostile UX —
      // the user has not even tried to sign in. Only surface a banner
      // when there is an active session that just broke (5xx) or when
      // a status code arrives that is unambiguous breakage.
      // 401 / 403 / 404 / 0 (network/timeout) → silent sign-out card.
      // 5xx / other → banner so we don't hide real outages.
      const silentStatuses = new Set([0, 401, 403, 404]);
      if (silentStatuses.has(e.status)) {
        showSignedOut();
      } else {
        setAlert(e.message || 'ネットワークエラー');
        showSignedOut();
      }
    } finally {
      done();
    }
  }

  function renderMe(me) {
    _lastMe = me;
    // "signed in as <prefix…>" — no tier label; everyone is metered ¥3/req.
    const sub = document.querySelector('.dash .sub');
    if (sub) {
      const prefix = me.key_hash_prefix || '—';
      const created = me.created_at ? `  ·  since ${String(me.created_at).slice(0,10)}` : '';
      const cust = me.customer_id ? `  ·  ${me.customer_id}` : '';
      sub.innerHTML = `signed in as <code>${escapeHtml(prefix)}…</code>${escapeHtml(created)}${escapeHtml(cust)}`;
    }
    const hashP = document.querySelector('.keybox .hash-prefix');
    if (hashP && me.key_hash_prefix) {
      hashP.textContent = `hash prefix: ${me.key_hash_prefix}`;
    }
    const keyEl = document.querySelector('.keybox .key');
    if (keyEl) {
      const dots = '•'.repeat(28);
      keyEl.innerHTML = `am_${dots}${escapeHtml(String(me.key_hash_prefix || '').slice(0,4))}`;
    }
    renderBillingCard(me);
    renderDunningBanner(me);
    renderPeriodEnd(me && me.subscription_current_period_end);
    renderNewKeyReveal(me);
  }

  // Surface the current Stripe billing period end ("今月の請求期間: YYYY-MM-DD
  // まで") so users see when the next ¥3/req invoice will close. Reads from
  // /v1/me.subscription_current_period_end (ISO 8601 UTC) and renders the
  // YYYY-MM-DD slice. Hidden when the value is null (free / pre-billing).
  function renderPeriodEnd(iso) {
    const wrap = document.getElementById('dash-period-end');
    if (!wrap) return;
    if (!iso || typeof iso !== 'string') {
      wrap.hidden = true;
      wrap.style.display = 'none';
      return;
    }
    const date = String(iso).slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      wrap.hidden = true;
      wrap.style.display = 'none';
      return;
    }
    const dateEl = document.getElementById('dash-period-end-date');
    if (dateEl) dateEl.textContent = date;
    wrap.hidden = false;
    wrap.style.display = '';
  }

  // ------------------------------------------------------------------
  // P0 fix #1 — Dunning banner
  // Shows a top-of-dashboard alert when the user's Stripe subscription is
  // delinquent. Gracefully degrades: if /v1/me does not include
  // `subscription_status`, the banner stays hidden (parallel agent may add
  // the field later). Banner copy is polite Japanese; the CTA links to the
  // Stripe customer portal session endpoint (POST /v1/me/billing-portal —
  // we wire the click via onBillingPortal so we get the redirect URL).
  // ------------------------------------------------------------------
  const DUNNING_COPY = Object.freeze({
    past_due: '💳 直近のお支払いに失敗しました。Stripe ポータルから支払い方法を更新してください。',
    unpaid: '⚠️ お支払い未確定です。サービス停止前に Stripe ポータルからご確認ください。',
    incomplete: '⚠️ お支払い未確定です。サービス停止前に Stripe ポータルからご確認ください。',
    canceled: 'ℹ️ サブスクリプションはキャンセル済みです。当月末まで API アクセス可能です。',
  });
  function renderDunningBanner(me) {
    const banner = $('#dash-dunning-banner');
    if (!banner) return;
    const status = me && typeof me.subscription_status === 'string'
      ? me.subscription_status.toLowerCase()
      : null;
    const msg = status && DUNNING_COPY[status];
    if (!msg) {
      banner.hidden = true;
      banner.style.display = 'none';
      return;
    }
    const msgEl = $('#dash-dunning-msg');
    if (msgEl) msgEl.textContent = msg;
    const portalLink = $('#dash-dunning-portal');
    if (portalLink) {
      portalLink.onclick = (e) => {
        e.preventDefault();
        onBillingPortal();
      };
    }
    banner.hidden = false;
    banner.style.display = 'block';
  }

  // ------------------------------------------------------------------
  // P0 fix #2 — First-key reveal
  // Shows a one-time, copyable plaintext key when the dashboard loads right
  // after key creation. Two sources:
  //   (a) /v1/me.raw_api_key   — preferred (server-issued one-shot).
  //   (b) sessionStorage `am_first_key` — fallback we set when a key is
  //       created via the dashboard (rotate flow already shows raw inline).
  // We also gate on key_count == 1 + key_created_at within 5 min if the
  // server provides those fields, so refreshes hours later don't re-leak.
  // sessionStorage clears on tab close — the security best-practice choice.
  // ------------------------------------------------------------------
  function renderNewKeyReveal(me) {
    const box = $('#dash-newkey-reveal');
    if (!box) return;
    let raw = (me && typeof me.raw_api_key === 'string' && me.raw_api_key) || null;
    if (!raw) {
      try { raw = sessionStorage.getItem('am_first_key') || null; } catch (_) { raw = null; }
    }
    if (!raw) {
      box.hidden = true;
      box.style.display = 'none';
      return;
    }
    // If server provides key_count + key_created_at, use them to suppress
    // stale reveals (e.g. user has rotated 5x — don't show a 30-day-old key
    // surfaced from a rogue sessionStorage entry).
    const count = me && typeof me.key_count === 'number' ? me.key_count : null;
    const createdAt = me && me.key_created_at ? Date.parse(me.key_created_at) : NaN;
    if (count !== null && count !== 1) {
      // not a brand-new account; still allow the sessionStorage fallback (it
      // self-clears on dismiss) but only if no server signal contradicts.
      // We choose to err toward showing — losing the reveal silently is a
      // worse UX than over-showing once.
    }
    if (!Number.isNaN(createdAt)) {
      const ageMs = Date.now() - createdAt;
      if (ageMs > 5 * 60 * 1000 + 30 * 1000) { // 5 min + 30s grace for clock skew
        box.hidden = true;
        box.style.display = 'none';
        try { sessionStorage.removeItem('am_first_key'); } catch (_) {}
        return;
      }
    }
    const valEl = $('#dash-newkey-value');
    if (valEl) valEl.textContent = raw;
    const copyBtn = $('#dash-newkey-copy');
    if (copyBtn) {
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(raw);
          copyBtn.textContent = 'Copied!';
          setTimeout(() => { copyBtn.textContent = 'Copy key'; }, 1600);
        } catch (_) {
          copyBtn.textContent = 'Copy failed';
        }
      };
    }
    const dismissBtn = $('#dash-newkey-dismiss');
    if (dismissBtn) {
      dismissBtn.onclick = () => {
        box.hidden = true;
        box.style.display = 'none';
        try { sessionStorage.removeItem('am_first_key'); } catch (_) {}
      };
    }
    box.hidden = false;
    box.style.display = 'block';
  }

  // Billing card is the same shape for every authenticated user (no tiers,
  // no upgrade gating). The Stripe-portal button is always live; the
  // headline reflects the current subscription state instead of a plan name.
  function renderBillingCard(me) {
    const billingBtn = $('#dash-billing-btn');
    if (billingBtn) {
      billingBtn.removeAttribute('aria-disabled');
      billingBtn.style.opacity = '';
      billingBtn.style.pointerEvents = '';
      billingBtn.textContent = 'Stripe ポータルを開く →';
    }
    const billingCard = billingBtn ? billingBtn.closest('.stat-card') : $('#billing-section');
    if (!billingCard) return;
    const val = billingCard.querySelector('[data-billing-headline], .stat-value');
    if (!val) return;
    const status = me && typeof me.subscription_status === 'string'
      ? me.subscription_status.toLowerCase()
      : null;
    let headline;
    if (status === 'active' || status === 'trialing' || status === null) {
      headline = '¥3 / req <span class="unit">(税込 ¥3.30) — metered, no cap</span>';
    } else if (DUNNING_STATUSES.has(status)) {
      headline = '¥3 / req <span class="unit">(税込 ¥3.30) — payment recovery in progress</span>';
    } else if (status === 'canceled') {
      headline = '¥3 / req <span class="unit">(税込 ¥3.30) — canceled, access ends month-end</span>';
    } else {
      headline = '¥3 / req <span class="unit">(税込 ¥3.30) — metered</span>';
    }
    val.innerHTML = headline;
  }

  // ------------------------------------------------------------------
  // usage
  // ------------------------------------------------------------------
  async function loadUsage() {
    const done = withSpinner();
    try {
      const series = await fetchJSON('/v1/me/usage?days=30');
      // server returns list of { date, calls }
      const safe = Array.isArray(series) ? series : [];
      renderUsage(safe);
      renderQuotaCounter(_lastMe, safe);
      startQuotaTimer();
    } finally {
      done();
    }
  }

  function renderUsage(series) {
    // series.length should be 30
    const today = series[series.length - 1] || { calls: 0, date: '' };
    const last7 = series.slice(-7).reduce((s, x) => s + (x.calls || 0), 0);
    const peak = series.reduce(
      (acc, x) => (x.calls > acc.calls ? x : acc),
      { calls: -1, date: '' }
    );
    // No tier-based daily limit. Authenticated users are metered ¥3/req
    // with no cap; only dunning-demoted users see the 100/day floor.
    const dailyLimit = isDunningDemoted(_lastMe) ? DUNNING_DEMOTE_DAILY : 0;

    // Today card
    const todayCard = document.querySelectorAll('.stat-grid .stat-card')[0];
    if (todayCard) {
      const val = todayCard.querySelector('.stat-value');
      const fill = todayCard.querySelector('.quota-fill');
      const note = todayCard.querySelector('.stat-note');
      if (val) {
        if (dailyLimit > 0) {
          val.innerHTML = `${today.calls} <span class="unit">/ ${dailyLimit.toLocaleString()} calls</span>`;
        } else {
          val.innerHTML = `${today.calls} <span class="unit">calls (metered)</span>`;
        }
      }
      if (fill && dailyLimit > 0) {
        const pct = Math.min(100, Math.round((today.calls / dailyLimit) * 100));
        fill.style.width = pct + '%';
      } else if (fill) {
        fill.style.width = '0%';
      }
      if (note) {
        const remaining = Math.max(0, dailyLimit - today.calls);
        note.textContent = dailyLimit > 0
          ? `dunning 緊急枠 (UTC 00:00 reset)。 ${remaining.toLocaleString()} remaining today — restore billing to lift the cap.`
          : 'Metered ¥3/req (税込 ¥3.30) — no daily cap.';
      }
    }
    // Last-7 card
    const weekCard = document.querySelectorAll('.stat-grid .stat-card')[1];
    if (weekCard) {
      const val = weekCard.querySelector('.stat-value');
      const note = weekCard.querySelector('.stat-note');
      if (val) val.innerHTML = `${last7} <span class="unit">calls</span>`;
      if (note) note.textContent = `Avg ${Math.round(last7 / 7)} / day.`;
    }

    // 30-day chart
    renderChart(series, peak);
    // P0 fix #3 — monthly projection line.
    renderMonthlyProjection(series);
  }

  // ------------------------------------------------------------------
  // P0 fix #3 — Monthly usage projection
  // Linear extrapolation: sum month-to-date calls, divide by elapsed days,
  // multiply by total days in month. Cost shown at ¥3/req (the only SKU).
  // Edge case: if today is the 1st-2nd, hide the projection (insufficient
  // data) and show "今月始まりました" — same DOM slot.
  // We rely on the JST month boundary loosely (server buckets by UTC date
  // per dashboard.js:_todayCalls comment); for the "current month" filter
  // we use the local date which matches the user's mental model. The minor
  // UTC/JST drift around midnight is acceptable for a coarse projection.
  // ------------------------------------------------------------------
  function renderMonthlyProjection(series) {
    const el = $('#dash-projection');
    if (!el) return;
    if (!Array.isArray(series) || series.length === 0) {
      el.textContent = '';
      return;
    }
    const now = new Date();
    const yyyy = now.getFullYear();
    const mm = now.getMonth(); // 0-indexed
    const dayOfMonth = now.getDate(); // 1..31
    const totalDays = new Date(yyyy, mm + 1, 0).getDate();

    if (dayOfMonth <= 2) {
      el.textContent = '今月始まりました — 数日後に projection を表示します。';
      return;
    }

    // Prefix that current-month entries' ISO date string starts with.
    const monthPrefix = `${yyyy}-${String(mm + 1).padStart(2, '0')}-`;
    const mtd = series.reduce((sum, x) => {
      const d = x && typeof x.date === 'string' ? x.date : '';
      if (d.startsWith(monthPrefix)) {
        return sum + (Number(x.calls) || 0);
      }
      return sum;
    }, 0);

    if (mtd <= 0) {
      el.textContent = `今月のペース: 〜0 req (まだ呼び出しがありません)`;
      return;
    }
    const projected = Math.round((mtd / dayOfMonth) * totalDays);
    const yenCost = Math.round(projected * 3);

    // Compare to previous month's calls for the same number of days (or
    // the entire previous month if the current month is past total). We
    // approximate by summing all previous-month entries in the 30-day
    // series — for early-month days this may include the tail of two
    // months prior, which is close enough for a "last month so far" ratio.
    const prevMm = mm === 0 ? 11 : mm - 1;
    const prevYy = mm === 0 ? yyyy - 1 : yyyy;
    const prevPrefix = `${prevYy}-${String(prevMm + 1).padStart(2, '0')}-`;
    const prevMonthSoFar = series.reduce((sum, x) => {
      const d = x && typeof x.date === 'string' ? x.date : '';
      if (d.startsWith(prevPrefix)) {
        // Take only the first dayOfMonth days of last month for apples-to-apples.
        const dayPart = parseInt(d.slice(8, 10), 10);
        if (Number.isFinite(dayPart) && dayPart <= dayOfMonth) {
          return sum + (Number(x.calls) || 0);
        }
      }
      return sum;
    }, 0);

    let pctTxt = '';
    if (prevMonthSoFar > 0) {
      const pct = Math.round(((mtd - prevMonthSoFar) / prevMonthSoFar) * 100);
      const sign = pct >= 0 ? '+' : '';
      pctTxt = ` (前回月初比 ${sign}${pct}%)`;
    }
    el.textContent =
      `今月のペース: 〜${projected.toLocaleString()} req` +
      `${pctTxt}` +
      `  ·  推定 ¥${yenCost.toLocaleString()} (¥3/req)`;
  }

  // --------------------------------------------------------------------
  // Quota counter widget (#quota-counter). Derives the daily tier quota
  // from the hardcoded TIER_DAILY_QUOTA map (sourced from .env.example) and
  // reads today's call count from the usage series.
  //
  // The backend (me.py:get_me_usage) returns the series oldest-first; the
  // task-spec claims newest-first. We handle both by picking the entry whose
  // date matches today (UTC, which is how usage_events are bucketed in
  // deps.py:_day_bucket). If no entry matches, fall back to the last item.
  // --------------------------------------------------------------------
  function _todayCalls(usage) {
    if (!Array.isArray(usage) || usage.length === 0) return 0;
    const todayUTC = new Date().toISOString().slice(0, 10);
    const hit = usage.find((x) => x && x.date === todayUTC);
    if (hit) return Math.max(0, Number(hit.calls) || 0);
    // Fall back to the last element (oldest-first -> last is newest) which
    // matches the existing renderUsage() behaviour.
    const last = usage[usage.length - 1];
    return Math.max(0, Number((last && last.calls) || 0));
  }

  function renderQuotaCounter(me, usage) {
    const el = $('#quota-counter');
    if (!el) return;

    // Authenticated users are metered with no daily cap — hide the widget
    // entirely. The only time we surface it is during Stripe dunning
    // recovery, where a 100/day floor kicks in until billing is restored.
    if (!isDunningDemoted(me)) {
      el.setAttribute('data-quota-state', 'unmetered');
      hide(el);
      return;
    }

    const quota = DUNNING_DEMOTE_DAILY;
    const calls = _todayCalls(usage);
    const pct = Math.min(100, Math.round((calls / quota) * 100));
    const over = calls >= quota;
    const state = over ? 'over' : pct >= 90 ? 'over' : pct >= 70 ? 'warn' : 'ok';

    const labelEl = el.querySelector('#quota-counter-label');
    if (labelEl) labelEl.textContent = 'Dunning 緊急枠 (今日)';

    const valueEl = el.querySelector('.quota-counter-value');
    if (valueEl) valueEl.textContent = calls.toLocaleString();

    const limitEl = el.querySelector('.quota-counter-limit');
    if (limitEl) limitEl.textContent = quota.toLocaleString();

    const pctEl = el.querySelector('.quota-counter-pct');
    if (pctEl) {
      const isEmpty = !Array.isArray(usage) || usage.length === 0;
      if (isEmpty && calls === 0) {
        pctEl.textContent = '· ready to go';
      } else {
        pctEl.textContent = `· ${pct}% used`;
      }
    }

    const fill = el.querySelector('.quota-counter-fill');
    if (fill) fill.style.width = `${pct}%`;

    const bar = el.querySelector('.quota-counter-bar');
    if (bar) {
      bar.setAttribute('aria-valuenow', String(pct));
      bar.setAttribute(
        'aria-label',
        `Dunning daily quota: ${calls} of ${quota} used (${pct}%)`
      );
    }

    const note = el.querySelector('.quota-counter-note');
    if (note) {
      if (over) {
        note.innerHTML = '429 — Stripe ポータルから支払い方法を更新すると枠は即時解除されます';
      } else {
        note.textContent = 'reset at 00:00 UTC · restore billing to lift';
      }
    }

    el.setAttribute('data-quota-state', state);
    show(el);
  }

  async function refreshQuotaCounter() {
    if (!_lastMe) return;
    // Only poll if the tab is visible — no overnight hammering of the API.
    if (document.visibilityState !== 'visible') return;
    try {
      const series = await fetchJSON('/v1/me/usage?days=30');
      renderQuotaCounter(_lastMe, Array.isArray(series) ? series : []);
    } catch (_) {
      // Silent — the next tick will retry. Don't clobber setAlert with a
      // background poll failure.
    }
  }

  function startQuotaTimer() {
    if (_quotaTimer != null) return;
    _quotaTimer = setInterval(refreshQuotaCounter, QUOTA_REFRESH_MS);
    // Refresh on regaining visibility so a tab backgrounded for an hour
    // catches up immediately instead of waiting up to 60s.
    if (!window.__dashVisListener) {
      window.__dashVisListener = () => {
        if (document.visibilityState === 'visible') refreshQuotaCounter();
      };
      document.addEventListener('visibilitychange', window.__dashVisListener);
    }
  }

  function renderChart(series, peak) {
    const svg = document.querySelector('.chart-svg');
    if (!svg) return;
    const w = 300;
    const h = 80;
    const n = series.length;
    const gap = 2;
    const barW = n > 0 ? Math.max(1, Math.floor((w - gap * (n - 1)) / n)) : 8;
    const maxV = Math.max(1, ...series.map((x) => x.calls || 0));
    const maxBarH = 70;
    const baseY = 78;

    const rects = series.map((d, i) => {
      const v = d.calls || 0;
      const bh = maxV > 0 ? Math.round((v / maxV) * maxBarH) : 0;
      const x = i * (barW + gap);
      const y = baseY - bh;
      return `<rect x="${x}" y="${y}" width="${barW}" height="${bh}" fill="#1e3a8a"><title>${escapeHtml(d.date)}: ${v} calls</title></rect>`;
    }).join('');

    // clear, then inject
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.innerHTML = rects;

    // chart title subline
    const title = document.querySelector('.chart-title .muted');
    if (title) {
      if (peak.calls > 0) {
        const dateStr = peak.date ? peak.date.slice(5) : '';
        title.textContent = `peak ${peak.calls} calls on ${dateStr}`;
      } else {
        title.textContent = 'no calls yet';
      }
    }
    // axis labels
    const axis = document.querySelector('.chart-axis');
    if (axis && series.length >= 2) {
      const first = series[0].date || '';
      const last = series[series.length - 1].date || '';
      const fmt = (iso) => iso.slice(5).replace('-', '/');
      axis.innerHTML = `<span>${escapeHtml(fmt(first))}</span><span>${escapeHtml(fmt(last))}</span>`;
    }
  }

  // ------------------------------------------------------------------
  // sign-in
  // ------------------------------------------------------------------
  async function onSignIn(e) {
    e.preventDefault();
    setAlert(null);
    const errEl = $('#dash-signin-err');
    if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
    const input = $('#dash-signin-key');
    const submit = $('#dash-signin-submit');
    const key = (input && input.value || '').trim();
    if (!key) return;
    if (submit) submit.disabled = true;
    const done = withSpinner();
    try {
      await fetchJSON('/v1/session', {
        method: 'POST',
        headers: csrfHeaders(),
        body: JSON.stringify({ api_key: key })
      });
      if (input) input.value = '';
      await loadMe();
    } catch (err) {
      const msg = err.status === 429
        ? 'サインイン試行回数が多すぎます (1時間あたり最大 5 回)。時間をおいて再試行してください。'
        : err.status === 401
          ? 'API key が無効、または失効しています。'
          : (err.message || 'サインインに失敗しました。');
      if (errEl) { errEl.textContent = msg; errEl.hidden = false; }
    } finally {
      done();
      if (submit) submit.disabled = false;
    }
  }

  // ------------------------------------------------------------------
  // rotate key
  // ------------------------------------------------------------------
  async function onRotate(e) {
    e.preventDefault();
    const btn = e.currentTarget;
    if (btn.disabled) return;
    const ok = window.confirm(
      'API key をローテーションすると、現在の key は即座に失効します。\n' +
      '新しい key は 1 度だけ表示されます。続けますか？'
    );
    if (!ok) return;
    btn.disabled = true;
    setAlert(null);
    const done = withSpinner();
    try {
      const body = await fetchJSON('/v1/me/rotate-key', {
        method: 'POST',
        headers: csrfHeaders()
      });
      revealNewKey(body.api_key);
    } catch (err) {
      setAlert(err.message || 'rotate に失敗しました。');
      btn.disabled = false; // allow retry on failure
    } finally {
      done();
    }
  }

  function revealNewKey(rawKey) {
    // Rotate flow invalidates the key in any other surface that cached it.
    // dashboard_v2.js Bearer flow stores the latest key in localStorage
    // 'am_api_key'; without overwriting it the user keeps Bearer-calling
    // /v1/me/* with the now-invalid key and gets 401 spam. The
    // sessionStorage 'am_first_key' bridge is also stale post-rotate so
    // clear it to avoid a one-shot reveal of an old key on next refresh.
    try { localStorage.setItem('am_api_key', rawKey); } catch (_) {}
    try { sessionStorage.removeItem('am_first_key'); } catch (_) {}
    const keybox = document.querySelector('.keybox');
    if (!keybox) return;
    const keyEl = keybox.querySelector('.key');
    if (keyEl) {
      keyEl.textContent = rawKey;
      keyEl.style.wordBreak = 'break-all';
      keyEl.style.whiteSpace = 'normal';
      keyEl.style.background = '#fff8e6';
      keyEl.style.borderColor = '#f59e0b';
    }
    // append warning
    let warn = keybox.querySelector('.rotate-warning');
    if (!warn) {
      warn = document.createElement('p');
      warn.className = 'rotate-warning stat-note';
      warn.style.cssText = 'margin-top:10px;color:#92400e;font-weight:600;';
      warn.textContent = 'この key は再表示されません。今すぐ安全な場所に保存してください。';
      keybox.appendChild(warn);
    }
    // copy-to-clipboard button — replace the Copy prefix label
    const copyBtn = $('#dash-copy-btn');
    if (copyBtn) {
      copyBtn.textContent = 'Copy new key';
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(rawKey);
          copyBtn.textContent = 'Copied!';
          setTimeout(() => { copyBtn.textContent = 'Copy new key'; }, 1600);
        } catch {
          copyBtn.textContent = 'Copy failed';
        }
      };
    }
  }

  async function onCopyPrefix(e) {
    e.preventDefault();
    const btn = e.currentTarget;
    const prefixText = (document.querySelector('.keybox .hash-prefix') || {}).textContent || '';
    const m = prefixText.match(/hash prefix:\s*(\S+)/);
    const val = m ? m[1] : '';
    if (!val) return;
    try {
      await navigator.clipboard.writeText(val);
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = orig; }, 1400);
    } catch {
      btn.textContent = 'Copy failed';
    }
  }

  // ------------------------------------------------------------------
  // billing portal
  // ------------------------------------------------------------------
  async function onBillingPortal() {
    const btn = $('#dash-billing-btn');
    if (btn && btn.getAttribute('aria-disabled') === 'true') return;
    setAlert(null);
    const done = withSpinner();
    try {
      const body = await fetchJSON('/v1/me/billing-portal', {
        method: 'POST',
        headers: csrfHeaders()
      });
      if (body && body.url) {
        window.location = body.url;
      }
    } catch (err) {
      // 404 + {status:"no_customer"} is the legitimate "Stripe カスタマー未作成"
      // path — happens before the user has made their first metered request.
      // Surface the server's structured message verbatim. FastAPI wraps
      // `HTTPException(detail={...})` so the inner dict is at err.body.detail.
      const body = err && err.body;
      const inner = body && (body.detail && typeof body.detail === 'object' ? body.detail : body);
      if ((err.status === 404 || err.status === 400) && inner && inner.status === 'no_customer') {
        setAlert(inner.message || 'Stripe カスタマーが未作成です。¥3/req の従量課金は使用後に自動作成されます。');
      } else if (err.status === 404 || err.status === 400) {
        setAlert('Stripe カスタマーが未作成です。¥3/req の従量課金は使用後に自動作成されます。');
      } else {
        setAlert(err.message || 'billing portal を開けませんでした。');
      }
    } finally {
      done();
    }
  }

  // ------------------------------------------------------------------
  // logout
  // ------------------------------------------------------------------
  async function onLogout() {
    const done = withSpinner();
    try {
      await fetchJSON('/v1/session/logout', {
        method: 'POST',
        headers: csrfHeaders()
      });
    } catch (_) {
      // ignore — logout best-effort
    } finally {
      done();
      window.location.reload();
    }
  }

  // ------------------------------------------------------------------
  // boot
  // ------------------------------------------------------------------
  function boot() {
    buildScaffold();
    bind();
    // hide post-login blocks until /v1/me succeeds (avoids flash of stale data)
    (window.__dashPostEls || []).forEach(hide);
    const sub = document.querySelector('.dash .sub');
    if (sub) sub.textContent = '';
    loadMe();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
