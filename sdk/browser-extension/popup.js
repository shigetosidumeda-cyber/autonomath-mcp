// jpcite browser extension — popup controller.
//
// 役割:
//   1. background から最近の history (最大 50) を取得して描画。クリックで
//      jpcite.com の検索画面を新タブで開く。
//   2. 残 quota を background に問い合わせて表示。匿名 (API key 未設定) の
//      場合は黄色の anon バッジを出す。
//   3. ボタン: [設定] [履歴 clear] [jpcite.com を開く]。

(() => {
  function send(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (resp) => resolve(resp || { ok: false }));
      } catch (e) {
        resolve({ ok: false, error: String(e) });
      }
    });
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function relTime(ts) {
    if (!ts) return "";
    const d = (Date.now() - ts) / 1000;
    if (d < 60) return `${Math.round(d)}秒前`;
    if (d < 3600) return `${Math.round(d / 60)}分前`;
    if (d < 86400) return `${Math.round(d / 3600)}時間前`;
    return `${Math.round(d / 86400)}日前`;
  }

  async function renderQuota() {
    const apiKeyResp = await new Promise((resolve) => {
      chrome.storage.sync.get(["api_key"], (out) => resolve(out?.api_key || ""));
    });
    const isAnon = !apiKeyResp;
    const box = document.getElementById("quota-box");
    const val = document.getElementById("quota-value");

    const r = await send({ type: "jpcite-quota-get" });
    const q = r?.quota;
    if (isAnon) {
      box.classList.add("anon");
      val.textContent = q?.remaining != null ? `${q.remaining} (匿名 3 req/日)` : "匿名 3 req/日";
    } else {
      box.classList.remove("anon");
      val.textContent = q?.remaining != null
        ? `${q.remaining}${q.limit ? "/" + q.limit : ""}`
        : "(未確認)";
    }
  }

  async function renderHistory() {
    const r = await send({ type: "jpcite-history-get" });
    const list = Array.isArray(r?.history) ? r.history : [];
    const ul = document.getElementById("hist");
    const empty = document.getElementById("empty");
    ul.innerHTML = "";
    if (list.length === 0) {
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";
    for (const h of list.slice(0, 30)) {
      const li = document.createElement("li");
      li.className = "hi";
      li.innerHTML = `
        <div class="label">${escapeHtml(h.label || h.id || "")}</div>
        <div class="meta">${escapeHtml(h.kind || "")} · ${escapeHtml(h.hostname || "")} · ${escapeHtml(relTime(h.ts))}</div>
      `;
      li.addEventListener("click", () => {
        const url = `https://jpcite.com/?q=${encodeURIComponent(h.id || h.label || "")}`;
        chrome.tabs.create({ url, active: true });
      });
      ul.appendChild(li);
    }
  }

  document.getElementById("btn-options").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });

  document.getElementById("btn-clear").addEventListener("click", async () => {
    await send({ type: "jpcite-history-clear" });
    renderHistory();
  });

  document.getElementById("btn-site").addEventListener("click", () => {
    chrome.tabs.create({ url: "https://jpcite.com/", active: true });
  });

  renderQuota();
  renderHistory();
})();
