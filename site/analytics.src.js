// analytics.js — env-gated Plausible injector + funnel beacon helper.
//
// 1. Plausible injection (consent-free, no cookies).
//
//    Activate by setting window.JPCITE_ANALYTICS before this script loads,
//    e.g. via a small inline tag in index.html / pricing.html:
//
//      <script>window.JPCITE_ANALYTICS = { domain: "jpcite.com" };</script>
//
//    If unset this block is a no-op and no external request is made.
//
// 2. Funnel beacon helper (`window.jpciteTrack`).
//
//    Posts a single funnel event to /v1/funnel/event so the operator can
//    see playground / pricing / quickstart-copy / mcp-install / checkout /
//    dashboard-signin breadcrumbs in `funnel_events`. Used by §4-E item 3:
//      pricing_view, cta_click, playground_request, playground_success,
//      playground_quota_exhausted, quickstart_copy, openapi_import_click,
//      mcp_install_copy, checkout_start, dashboard_signin_success
//
//    Usage from page scripts:
//      jpciteTrack('pricing_view');
//      jpciteTrack('cta_click', { target: 'playground' });
//      jpciteTrack('quickstart_copy', { snippet: 'curl-search' });
//
//    Defaults:
//      - API base: window.JPCITE_API_BASE ||
//        'https://api.jpcite.com'
//      - Endpoint: <base>/v1/funnel/event (POST JSON payload)
//      - Transport: navigator.sendBeacon when available (survives nav),
//        falls back to fetch keepalive. Beacon payloads are sent as
//        text/plain so cross-origin navigation clicks do not depend on
//        an application/json preflight finishing in time.
//      - Session id: random 128-bit hex stored in sessionStorage so events
//        within the same tab can be chained without persistent identifiers.
//      - Page: location.pathname (query string stripped).
//      - Authorisation: included as Bearer when window.JPCITE_API_KEY is
//        set (dashboard pages); otherwise omitted (anon).
//      - All exceptions swallowed — analytics MUST NOT break the page.
(function () {
  // ----- 1. Plausible injection -------------------------------------------
  try {
    var cfg = window.JPCITE_ANALYTICS;
    if (cfg && cfg.domain) {
      var s = document.createElement('script');
      s.defer = true;
      s.setAttribute('data-domain', cfg.domain);
      s.src = cfg.src || 'https://plausible.io/js/script.js';
      document.head.appendChild(s);
    }
  } catch (_e) { /* no-op */ }

  // ----- 2. Funnel beacon helper -------------------------------------------
  var ALLOWED_EVENTS = {
    pricing_view: 1,
    cta_click: 1,
    playground_request: 1,
    playground_success: 1,
    playground_quota_exhausted: 1,
    quickstart_copy: 1,
    openapi_import_click: 1,
    mcp_install_copy: 1,
    checkout_start: 1,
    dashboard_signin_success: 1,
  };

  var SESSION_KEY = 'jpcite.session_id';

  function getOrCreateSessionId() {
    try {
      var sid = sessionStorage.getItem(SESSION_KEY);
      if (sid && sid.length >= 16) return sid;
      var bytes = new Uint8Array(16);
      (window.crypto || window.msCrypto).getRandomValues(bytes);
      var hex = '';
      for (var i = 0; i < bytes.length; i++) {
        hex += bytes[i].toString(16).padStart(2, '0');
      }
      sessionStorage.setItem(SESSION_KEY, hex);
      return hex;
    } catch (_e) {
      return null;
    }
  }

  function apiBase() {
    var base = window.JPCITE_API_BASE;
    if (typeof base === 'string' && base.length > 0) return base;
    return 'https://api.jpcite.com';
  }

  function send(eventName, properties) {
    try {
      if (!ALLOWED_EVENTS[eventName]) return;
      var url = apiBase().replace(/\/$/, '') + '/v1/funnel/event';
      var body = JSON.stringify({
        event: eventName,
        page: (location.pathname || '/').slice(0, 256),
        session_id: getOrCreateSessionId(),
        properties: properties && typeof properties === 'object' ? properties : null,
      });

      var apiKey = window.JPCITE_API_KEY;
      var hasApiKey = typeof apiKey === 'string' && apiKey.length > 0;
      var headers = {
        'Content-Type': hasApiKey
          ? 'application/json'
          : 'text/plain;charset=UTF-8',
      };
      if (hasApiKey) {
        headers['Authorization'] = 'Bearer ' + apiKey;
      }

      // sendBeacon doesn't support custom headers — use it only when we
      // can ship the payload as text/plain (anonymous events, no Bearer).
      var canBeacon = !hasApiKey
        && typeof navigator !== 'undefined'
        && typeof navigator.sendBeacon === 'function';

      if (canBeacon) {
        try {
          var blob = new Blob([body], { type: 'text/plain;charset=UTF-8' });
          if (navigator.sendBeacon(url, blob)) return;
        } catch (_e) { /* fall through */ }
      }

      // Fallback: fetch with keepalive so the beacon survives navigation.
      if (typeof fetch === 'function') {
        fetch(url, {
          method: 'POST',
          headers: headers,
          body: body,
          keepalive: true,
          mode: 'cors',
          credentials: 'omit',
        }).catch(function () { /* swallow */ });
      }
    } catch (_e) { /* analytics MUST NOT break the page */ }
  }

  // Public surface — single global so page scripts can call it.
  // Idempotent: re-loading this script does not break previously-bound
  // listeners that closed over the old reference.
  window.jpciteTrack = send;

  function bindCtaTracking() {
    if (window.__jpciteCtaTrackingBound) return;
    window.__jpciteCtaTrackingBound = true;
    document.addEventListener('click', function (e) {
      try {
        var target = e.target;
        var el = target && target.closest && target.closest('[data-cta-variant]');
        if (!el) return;
        send('cta_click', {
          cta_variant: el.getAttribute('data-cta-variant'),
          href: el.getAttribute('href') || null,
        });
      } catch (_e) { /* no-op */ }
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindCtaTracking, { once: true });
  } else {
    bindCtaTracking();
  }

  // Auto-fire pricing_view when the page is /pricing or /en/pricing.
  try {
    var p = (location.pathname || '').replace(/\/$/, '');
    if (
      p === '/pricing'
      || p === '/pricing.html'
      || p === '/en/pricing'
      || p === '/en/pricing.html'
    ) {
      // Defer to the next tick so any inline JPCITE_API_KEY assignment
      // gets to run before we check for it.
      setTimeout(function () {
        send('pricing_view', p.indexOf('/en/') === 0 ? { locale: 'en' } : null);
      }, 0);
    }
  } catch (_e) { /* no-op */ }
})();
