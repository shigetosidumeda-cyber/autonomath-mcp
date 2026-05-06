// jpcite browser extension — content script (e-Gov / 国税庁 / 法務省 / 裁判所).
//
// 役割:
//   1. 法令番号 / 事件番号 / 法人番号 を URL とページ本文から検出し、
//      右下に floating overlay button を inject。
//   2. ボタン clic で:
//        a) 「この法令を jpcite で見る」 → /v1/laws/search?q={law_id} を fetch
//           → 結果を modal で overlay 表示
//        b) 「Evidence Packet 化」 → /v1/evidence/packets/{kind}/{id} を fetch
//           → 同 modal に packet envelope を表示
//   3. 全 fetch は background service worker 経由 (API key + quota tracking)。
//
// 設計:
//   - host_permissions に対象6ドメイン + api.jpcite.com を宣言済み。
//     content script は fetch を直接行わず、chrome.runtime.sendMessage で
//     background に委譲する (Manifest V3 推奨)。
//   - DOM 改変は最小限: 右下 fab + (open 時のみ) modal の 2 要素のみ。
//     ページ本文は触らない (chrome-extension/ の hover-highlight は別物)。
//   - SPA / 動的ページ対応のため URL 変更を polling で検出する
//     (history.pushState / popstate を hook できないサイトがあるため)。

(() => {
  if (window.__jpciteOverlayLoaded) return;
  window.__jpciteOverlayLoaded = true;

  // ===== 検出 regex =====
  // e-Gov 法令 ID: era(3桁) + type(2文字大英) + serial(10桁), 例 415AC1000000086.
  // 厳密パターン: ^\d{3}[A-Z]{2}\d{10}$
  const LAW_ID_RE = /\b(\d{3}[A-Z]{2}\d{10})\b/;
  // 法人番号: 13 桁数字 (T プレフィックス可)
  const HOUJIN_RE = /\b(T?\d{13})\b/;
  // 裁判所 事件番号 (例: 令和5年(行ヒ)第123号 / 平成30年(ワ)第456号)
  const CASE_RE = /(令和|平成|昭和)\s*\d+\s*年\s*\([^\)]{1,8}\)\s*第\s*\d+\s*号/;

  // ===== サイト判定 =====
  function detectSite() {
    const h = location.hostname;
    if (h.endsWith("e-gov.go.jp")) return "egov";
    if (h.endsWith("nta.go.jp")) return "nta";
    if (h.endsWith("moj.go.jp")) return "moj";
    if (h.endsWith("courts.go.jp")) return "courts";
    if (h.endsWith("kfs.go.jp")) return "kfs";
    return "other";
  }

  // ===== 検出ロジック =====
  // 戻り値: { kind: "law"|"houjin"|"case"|null, id: string|null, label: string }
  function detectSubject() {
    // 1) URL から e-Gov 法令 ID を抽出 (最優先 — 法令本文ページ確定)
    const urlLaw = LAW_ID_RE.exec(location.pathname + location.search + location.hash);
    if (urlLaw) {
      return { kind: "law", id: urlLaw[1], label: `法令 ${urlLaw[1]}` };
    }

    // 2) ページ本文 (h1, h2, .law-title, title tag) から法令 ID を探す
    const titleText = (document.title || "") + " " + (document.querySelector("h1")?.textContent || "");
    const titleLaw = LAW_ID_RE.exec(titleText);
    if (titleLaw) {
      return { kind: "law", id: titleLaw[1], label: `法令 ${titleLaw[1]}` };
    }

    // 3) 裁判所サイト: 事件番号
    if (detectSite() === "courts" || detectSite() === "kfs") {
      const caseMatch = CASE_RE.exec(titleText) || CASE_RE.exec(document.body?.innerText?.slice(0, 4000) || "");
      if (caseMatch) {
        return { kind: "case", id: caseMatch[0].replace(/\s+/g, ""), label: `事件 ${caseMatch[0]}` };
      }
    }

    // 4) 国税庁・法務省・他: 法人番号
    const bodyHead = document.body?.innerText?.slice(0, 4000) || "";
    const houjinMatch = HOUJIN_RE.exec(bodyHead);
    if (houjinMatch) {
      const digits = houjinMatch[1].replace(/\D/g, "");
      if (digits.length === 13) {
        return { kind: "houjin", id: digits, label: `法人 ${digits}` };
      }
    }

    // 5) フォールバック: page title をそのまま検索クエリに
    if (document.title) {
      return { kind: "search", id: document.title.slice(0, 80), label: `"${document.title.slice(0, 30)}…"` };
    }
    return { kind: null, id: null, label: "" };
  }

  // ===== UI 構築 =====
  let fab = null;
  let modal = null;
  let currentSubject = null;

  function ensureFab() {
    if (fab) return fab;
    fab = document.createElement("div");
    fab.id = "jpcite-fab";
    fab.setAttribute("role", "button");
    fab.setAttribute("tabindex", "0");
    fab.setAttribute("aria-label", "jpcite で見る");
    fab.innerHTML = `
      <span class="jpcite-fab-icon">jp</span>
      <span class="jpcite-fab-text">jpcite で見る</span>
    `;
    fab.addEventListener("click", onFabClick);
    fab.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        onFabClick();
      }
    });
    document.documentElement.appendChild(fab);
    return fab;
  }

  function refreshFab() {
    const subj = detectSubject();
    currentSubject = subj;
    if (!subj.kind) {
      if (fab) fab.style.display = "none";
      return;
    }
    ensureFab();
    fab.style.display = "flex";
    const txt = fab.querySelector(".jpcite-fab-text");
    if (txt) txt.textContent = `jpcite で見る (${subj.label})`;
    fab.dataset.kind = subj.kind;
    fab.dataset.id = subj.id;
  }

  // ===== Modal =====
  function ensureModal() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "jpcite-modal-root";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML = `
      <div class="jpcite-modal-backdrop"></div>
      <div class="jpcite-modal-card">
        <header class="jpcite-modal-head">
          <span class="jpcite-modal-title">jpcite</span>
          <div class="jpcite-modal-actions">
            <button type="button" class="jpcite-btn-ep" data-action="evidence">Evidence Packet 化</button>
            <button type="button" class="jpcite-btn-open" data-action="open-site">jpcite.com で開く</button>
            <button type="button" class="jpcite-btn-close" aria-label="閉じる">×</button>
          </div>
        </header>
        <div class="jpcite-modal-body">
          <div class="jpcite-loading">読み込み中…</div>
        </div>
        <footer class="jpcite-modal-foot">
          <span class="jpcite-quota"></span>
          <span class="jpcite-disclaimer">本データは情報提供のみ。法令・税務判断は一次資料と専門家確認を要します。</span>
        </footer>
      </div>
    `;
    modal.style.display = "none";
    document.documentElement.appendChild(modal);

    modal.querySelector(".jpcite-modal-backdrop").addEventListener("click", closeModal);
    modal.querySelector(".jpcite-btn-close").addEventListener("click", closeModal);
    modal.querySelector(".jpcite-btn-ep").addEventListener("click", onEvidenceClick);
    modal.querySelector(".jpcite-btn-open").addEventListener("click", onOpenSiteClick);
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && modal && modal.style.display !== "none") closeModal();
    });
    return modal;
  }

  function openModal() {
    ensureModal();
    modal.style.display = "block";
  }

  function closeModal() {
    if (modal) modal.style.display = "none";
  }

  function setModalBody(html) {
    ensureModal();
    const body = modal.querySelector(".jpcite-modal-body");
    if (body) body.innerHTML = html;
  }

  function setQuota(quotaText) {
    if (!modal) return;
    const q = modal.querySelector(".jpcite-quota");
    if (q) q.textContent = quotaText || "";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ===== fetch via background =====
  function callBackground(action, payload) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: action, payload }, (resp) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message });
          } else {
            resolve(resp || { ok: false, error: "no response" });
          }
        });
      } catch (e) {
        resolve({ ok: false, error: String(e) });
      }
    });
  }

  // ===== クリックハンドラ =====
  async function onFabClick() {
    const subj = currentSubject || detectSubject();
    if (!subj || !subj.kind) return;
    openModal();
    setModalBody(`<div class="jpcite-loading">jpcite に問い合わせ中…</div>`);

    let resp;
    if (subj.kind === "law") {
      resp = await callBackground("jpcite-fetch", {
        endpoint: `/v1/laws/search?q=${encodeURIComponent(subj.id)}&limit=5`,
      });
    } else if (subj.kind === "houjin") {
      resp = await callBackground("jpcite-fetch", {
        endpoint: `/v1/houjin/${subj.id}`,
      });
    } else if (subj.kind === "case") {
      resp = await callBackground("jpcite-fetch", {
        endpoint: `/v1/court_decisions/search?q=${encodeURIComponent(subj.id)}&limit=5`,
      });
    } else {
      resp = await callBackground("jpcite-fetch", {
        endpoint: `/v1/programs/search?q=${encodeURIComponent(subj.id)}&limit=5`,
      });
    }
    renderResponse(resp, subj);
  }

  async function onEvidenceClick() {
    const subj = currentSubject || detectSubject();
    if (!subj || !subj.kind) return;
    setModalBody(`<div class="jpcite-loading">Evidence Packet 生成中…</div>`);

    let kind, id;
    if (subj.kind === "houjin") {
      kind = "houjin";
      id = subj.id;
    } else if (subj.kind === "law") {
      // Evidence Packet は subject_kind ∈ {program, houjin}。法令は packets/query 未対応のため
      // search を返してユーザに program 候補を選ばせる。
      setModalBody(
        `<div class="jpcite-info">Evidence Packet は <code>program</code> / <code>houjin</code> のみ対応。` +
          `法令の場合はまず関連 program を選択してください。</div>`
      );
      return;
    } else {
      setModalBody(`<div class="jpcite-info">この対象は Evidence Packet 化に対応していません。</div>`);
      return;
    }
    const resp = await callBackground("jpcite-fetch", {
      endpoint: `/v1/evidence/packets/${kind}/${encodeURIComponent(id)}`,
    });
    renderResponse(resp, subj);
  }

  function onOpenSiteClick() {
    const subj = currentSubject || detectSubject();
    if (!subj || !subj.id) return;
    const url = `https://jpcite.com/?q=${encodeURIComponent(subj.id)}`;
    chrome.runtime.sendMessage({ type: "jpcite-open-tab", url });
  }

  function renderResponse(resp, subj) {
    if (!resp || !resp.ok) {
      const err = resp?.error || "不明なエラー";
      setModalBody(`<div class="jpcite-error">エラー: ${escapeHtml(err)}</div>`);
      return;
    }
    setQuota(resp.quotaText || "");

    const data = resp.data;
    let html = "";
    try {
      // 簡易レンダラ — 主要フィールドだけテーブルで、生 JSON は折りたたみ。
      if (data && data.items && Array.isArray(data.items)) {
        html += `<div class="jpcite-summary"><strong>${data.items.length}</strong> 件 / total ${escapeHtml(data.total ?? data.items.length)}</div>`;
        html += `<ul class="jpcite-result-list">`;
        for (const item of data.items.slice(0, 10)) {
          const title = item.law_title || item.law_short_title || item.title || item.case_name || item.program_name || item.houjin_name || JSON.stringify(item).slice(0, 80);
          const num = item.law_number || item.case_number || item.unified_id || item.houjin_bangou || item.program_id || "";
          const url = item.source_url || item.full_text_url || "";
          html += `<li class="jpcite-result-item">
            <div class="jpcite-result-title">${escapeHtml(title)}</div>
            <div class="jpcite-result-meta">${escapeHtml(num)}</div>
            ${url ? `<a class="jpcite-result-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">一次資料 →</a>` : ""}
          </li>`;
        }
        html += `</ul>`;
      } else if (data && (data.houjin_bangou || data.unified_id)) {
        // 単発 record (houjin / law / packet)
        html += `<div class="jpcite-record">`;
        const title = data.houjin_name || data.law_title || data.subject_id || data.unified_id || "(無題)";
        html += `<div class="jpcite-result-title">${escapeHtml(title)}</div>`;
        const fields = ["law_number", "houjin_bangou", "ministry", "promulgated_date", "address", "subject_kind", "subject_id"];
        for (const f of fields) {
          if (data[f]) {
            html += `<div class="jpcite-kv"><span class="jpcite-k">${escapeHtml(f)}</span><span class="jpcite-v">${escapeHtml(data[f])}</span></div>`;
          }
        }
        html += `</div>`;
      }

      html += `<details class="jpcite-raw">
        <summary>raw JSON</summary>
        <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </details>`;
    } catch (e) {
      html = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
    }
    setModalBody(html);

    // 履歴に push (background が storage に保存)
    callBackground("jpcite-history-push", {
      ts: Date.now(),
      kind: subj.kind,
      id: subj.id,
      label: subj.label,
      hostname: location.hostname,
    });
  }

  // ===== URL 変化 polling (SPA 対応) =====
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      refreshFab();
    }
  }, 1000);

  // ===== 起動 =====
  function init() {
    if (!document.body) {
      window.requestAnimationFrame(init);
      return;
    }
    refreshFab();
    // body の動的書き換え (e-Gov の lazy load 等) にも反応
    const mo = new MutationObserver(() => {
      if (!fab || fab.style.display === "none") refreshFab();
    });
    mo.observe(document.body, { childList: true, subtree: false });
  }
  init();
})();
