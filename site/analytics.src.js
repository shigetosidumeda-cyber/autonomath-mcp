// analytics.js — env-gated Plausible injector (consent-free, no cookies).
//
// Activate on launch by setting window.JPINTEL_ANALYTICS before this script
// loads, e.g. from a small inline tag in index.html/pricing.html:
//
//   <script>window.JPINTEL_ANALYTICS = { domain: "jpcite.com" };</script>
//
// If unset this file is a no-op. No external request is made.
(function () {
  try {
    var cfg = window.JPINTEL_ANALYTICS;
    if (!cfg || !cfg.domain) return;
    var s = document.createElement('script');
    s.defer = true;
    s.setAttribute('data-domain', cfg.domain);
    s.src = cfg.src || 'https://plausible.io/js/script.js';
    document.head.appendChild(s);
  } catch (_e) { /* no-op */ }
})();
