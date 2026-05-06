// jpcite browser extension — service worker (Manifest V3 background).
//
// 役割:
//   1. content script からの "jpcite-fetch" メッセージを受け、api.jpcite.com に
//      実際の HTTP fetch を行う。API key (chrome.storage.sync) を Authorization
//      ヘッダに自動付与。空なら anon (3 req/日 IP base)。
//   2. quota 残量を response header (X-Quota-Remaining 等) から拾い、popup と
//      modal foot に表示できるよう抽出して返す。
//   3. 履歴 (最新 50 件) を chrome.storage.local に保持。popup から取得できる。
//   4. 右クリックメニュー: 選択テキストを jpcite で照会する fallback 経路。
//
// 設計:
//   - LLM API は呼ばない (CLAUDE.md 非交渉制約)。jpcite-API 側で LLM 推論しない
//     のと同様、拡張内でも直接 LLM を叩くことはしない。
//   - host_permissions に対象6サイト + api.jpcite.com を宣言済み。
//     上記以外への fetch はしない (ホワイトリスト制).

const API_BASE = "https://api.jpcite.com";
const ALLOWED_ENDPOINT_RE = /^\/v1\/[A-Za-z0-9_/\-?=&%.]+$/;
const HISTORY_KEY = "jpcite_history_v1";
const HISTORY_MAX = 50;
const QUOTA_KEY = "jpcite_quota_v1";

// ===== util =====

async function getApiKey() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["api_key"], (out) => {
      resolve(out?.api_key || "");
    });
  });
}

async function setQuota(remaining, limit, resetAt) {
  return new Promise((resolve) => {
    chrome.storage.local.set(
      {
        [QUOTA_KEY]: {
          remaining: remaining,
          limit: limit,
          reset_at: resetAt || null,
          checked_at: new Date().toISOString(),
        },
      },
      () => resolve()
    );
  });
}

async function getQuota() {
  return new Promise((resolve) => {
    chrome.storage.local.get([QUOTA_KEY], (out) => resolve(out?.[QUOTA_KEY] || null));
  });
}

async function pushHistory(entry) {
  return new Promise((resolve) => {
    chrome.storage.local.get([HISTORY_KEY], (out) => {
      const list = Array.isArray(out?.[HISTORY_KEY]) ? out[HISTORY_KEY] : [];
      list.unshift(entry);
      const trimmed = list.slice(0, HISTORY_MAX);
      chrome.storage.local.set({ [HISTORY_KEY]: trimmed }, () => resolve());
    });
  });
}

// ===== fetch handler =====

async function jpciteFetch(endpoint) {
  if (!endpoint || typeof endpoint !== "string" || !ALLOWED_ENDPOINT_RE.test(endpoint)) {
    return { ok: false, error: `endpoint not allowed: ${endpoint}` };
  }
  const apiKey = await getApiKey();
  const url = API_BASE + endpoint;
  const headers = {
    "Accept": "application/json",
    "X-Client": "jpcite-browser-extension/0.1.0",
  };
  if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;

  let resp;
  try {
    resp = await fetch(url, { method: "GET", headers, credentials: "omit" });
  } catch (e) {
    return { ok: false, error: `network: ${String(e)}` };
  }

  // quota header (jpcite API は X-RateLimit-Remaining / X-RateLimit-Limit を返す可能性あり)
  const remaining = resp.headers.get("X-RateLimit-Remaining") || resp.headers.get("X-Quota-Remaining");
  const limit = resp.headers.get("X-RateLimit-Limit") || resp.headers.get("X-Quota-Limit");
  const reset = resp.headers.get("X-RateLimit-Reset") || resp.headers.get("X-Quota-Reset");
  if (remaining || limit) {
    await setQuota(remaining, limit, reset);
  }

  let bodyText;
  try {
    bodyText = await resp.text();
  } catch (_) {
    bodyText = "";
  }
  let data;
  try {
    data = bodyText ? JSON.parse(bodyText) : null;
  } catch (_) {
    data = { _raw: bodyText };
  }

  const quotaText = remaining
    ? `残量 ${remaining}${limit ? "/" + limit : ""}`
    : "";

  if (!resp.ok) {
    return {
      ok: false,
      status: resp.status,
      error: data?.detail || data?.error || `HTTP ${resp.status}`,
      data,
      quotaText,
    };
  }
  return { ok: true, status: resp.status, data, quotaText };
}

// ===== contextMenus =====

chrome.runtime.onInstalled.addListener(() => {
  try {
    chrome.contextMenus.create({
      id: "jpcite-lookup-selection",
      title: "jpcite で照会 (\"%s\")",
      contexts: ["selection"],
    });
    chrome.contextMenus.create({
      id: "jpcite-open-site",
      title: "jpcite.com を開く",
      contexts: ["page", "action"],
    });
  } catch (_) {
    // 拡張更新時に既存 menu があると失敗するので握り潰し。
  }
});

chrome.contextMenus.onClicked.addListener((info, _tab) => {
  if (info.menuItemId === "jpcite-lookup-selection" && info.selectionText) {
    const text = info.selectionText.trim();
    const digits = text.replace(/\D/g, "");
    let url;
    if (/^T?\d{13}$/i.test(text) && digits.length === 13) {
      url = `https://jpcite.com/?q=${encodeURIComponent(digits)}`;
    } else {
      url = `https://jpcite.com/?q=${encodeURIComponent(text)}`;
    }
    chrome.tabs.create({ url, active: true });
  } else if (info.menuItemId === "jpcite-open-site") {
    chrome.tabs.create({ url: "https://jpcite.com/", active: true });
  }
});

// ===== message router =====

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg !== "object") {
    sendResponse({ ok: false, error: "invalid message" });
    return false;
  }

  if (msg.type === "jpcite-fetch") {
    const endpoint = msg.payload?.endpoint;
    jpciteFetch(endpoint).then(sendResponse);
    return true; // async
  }

  if (msg.type === "jpcite-history-push") {
    pushHistory(msg.payload || {}).then(() => sendResponse({ ok: true }));
    return true;
  }

  if (msg.type === "jpcite-history-get") {
    chrome.storage.local.get([HISTORY_KEY], (out) => {
      sendResponse({ ok: true, history: out?.[HISTORY_KEY] || [] });
    });
    return true;
  }

  if (msg.type === "jpcite-history-clear") {
    chrome.storage.local.set({ [HISTORY_KEY]: [] }, () => sendResponse({ ok: true }));
    return true;
  }

  if (msg.type === "jpcite-quota-get") {
    getQuota().then((q) => sendResponse({ ok: true, quota: q }));
    return true;
  }

  if (msg.type === "jpcite-open-tab") {
    if (msg.url && /^https:\/\//.test(msg.url)) {
      chrome.tabs.create({ url: msg.url, active: true });
      sendResponse({ ok: true });
    } else {
      sendResponse({ ok: false, error: "invalid url" });
    }
    return false;
  }

  sendResponse({ ok: false, error: `unknown type: ${msg.type}` });
  return false;
});
