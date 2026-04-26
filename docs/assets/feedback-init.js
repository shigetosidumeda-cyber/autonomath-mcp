/* Mount the AutonoMath feedback widget on every mkdocs page.
 * Uses a small retry loop because Material's `navigation.instant` SPA-swaps
 * <body>, which would otherwise drop the floating button on route change.
 */
(function () {
  "use strict";
  function mount() {
    if (!window.AutonoMathFeedback) return;
    if (document.getElementById("am-fb-fab")) return;
    window.AutonoMathFeedback.mount("body", { position: "bottom-right" });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
  // Re-mount after Material instant-navigation swaps.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(function () {
      setTimeout(mount, 0);
    });
  }
})();
