/* trust-strip.en.js — fills the discreet trust strip with the live data
   freshness from /v1/meta.last_ingested_at. No retries, no spinners; if
   the API is unreachable, the strip simply keeps its server-rendered
   fallback text (the static data_as_of from build time). All other trust
   info (company registration, Tokushoho compliance, Terms, Privacy,
   OpenAPI) is plain HTML so the strip stays readable with JS off. */
(function () {
  'use strict';
  var MONTHS = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
  ];
  function fmt(iso) {
    if (!iso || typeof iso !== 'string') return null;
    var m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return null;
    var year = m[1];
    var monthIdx = parseInt(m[2], 10) - 1;
    var day = parseInt(m[3], 10);
    if (monthIdx < 0 || monthIdx > 11 || isNaN(day)) return null;
    return MONTHS[monthIdx] + ' ' + day + ', ' + year;
  }
  function apply(text) {
    var nodes = document.querySelectorAll('[data-trust-fresh]');
    for (var i = 0; i < nodes.length; i++) nodes[i].textContent = text;
  }
  function load() {
    if (!document.querySelector('[data-trust-fresh]')) return;
    var base =
      window.AUTONOMATH_API_BASE ||
      'https://api.jpcite.com';
    fetch(base + '/v1/meta', { credentials: 'omit' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        var d = fmt(j.last_ingested_at) || fmt(j.data_as_of);
        if (d) apply(d);
      })
      .catch(function () { /* keep fallback text */ });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
