(() => {
  const selector = 'input[data-md-component="search-query"]';

  const patch = input => {
    if (input.dataset.jpciteSearchInputPatch === "1") return;
    input.dataset.jpciteSearchInputPatch = "1";

    let frame = 0;
    const notify = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        input.dispatchEvent(new KeyboardEvent("keyup", {
          bubbles: true,
          key: "Unidentified"
        }));
      });
    };

    input.addEventListener("input", notify);
    input.addEventListener("change", notify);
    input.addEventListener("compositionend", notify);
  };

  const scan = () => {
    for (const input of document.querySelectorAll(selector)) patch(input);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scan, { once: true });
  } else {
    scan();
  }

  new MutationObserver(scan).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
