// jpcite Chrome 拡張 — popup controller.
//
// 役割: 拡張アイコンクリック時の popup form を管理。
//   submit → background service worker に「open」メッセージを投げる。
//   background が tab を新規 open し、popup は閉じる。
//
// なぜ background 経由か:
//   manifest v3 の popup window から直接 window.open すると、popup が即座に
//   destroy されて新規 tab が開かない環境がある (Chrome 116+ regression)。
//   chrome.runtime.sendMessage は非同期でも background が完遂するので、
//   popup が閉じても tab は開く。

(() => {
  const form = document.getElementById("qf");
  const input = document.getElementById("q");
  if (!form || !input) return;

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = input.value.trim();
    if (!q) {
      input.focus();
      return;
    }
    try {
      chrome.runtime.sendMessage({ type: "jpcite-open", text: q }, () => {
        // background が tab を開いたら popup を閉じる。
        window.close();
      });
    } catch (_) {
      // service worker が起動失敗した稀ケース fallback。
      const digits = q.replace(/\D/g, "");
      const url = (/^T?\d{13}$/i.test(q) && digits.length === 13)
        ? `https://api.jpcite.com/v1/houjin/${digits}`
        : `https://api.jpcite.com/v1/programs/search?q=${encodeURIComponent(q)}`;
      window.open(url, "_blank", "noopener");
      window.close();
    }
  });
})();
