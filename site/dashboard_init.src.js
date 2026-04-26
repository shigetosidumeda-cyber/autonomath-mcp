// dashboard_init.js — extracted from inline <script> in dashboard.html
// for CSP compliance (script-src 'self', no 'unsafe-inline').
// Mounts the AutonoMath feedback widget bottom-right after DOMContentLoaded.
// Loaded with `defer` so DOMContentLoaded may have already fired by the time
// this executes — handle both cases.
(function () {
  function mountFeedback() {
    if (window.AutonoMathFeedback && typeof window.AutonoMathFeedback.mount === 'function') {
      window.AutonoMathFeedback.mount('body', { position: 'bottom-right' });
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountFeedback);
  } else {
    mountFeedback();
  }
})();
