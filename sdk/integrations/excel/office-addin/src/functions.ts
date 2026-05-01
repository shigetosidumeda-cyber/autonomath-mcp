/**
 * jpcite Excel custom functions (Office.js).
 *
 * Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
 * API base: https://api.jpcite.com
 * Cost:     ¥3/req metered (税込 ¥3.30). Recalc storms multiply this; see README.
 *
 * The five UDFs below mirror the XLAM module 1:1 so the surface looks the same
 * to consultants regardless of whether they install the Office Add-in or the
 * VBA `.xlam`. Stored API key persists in `OfficeRuntime.storage` (browser
 * sandbox; not synced).
 */

/* global CustomFunctions, OfficeRuntime */

const API_BASE = "https://api.jpcite.com";
const API_KEY_STORAGE_KEY = "jpcite.apiKey";
const USER_AGENT_NOTE = "jpcite-officejs/0.3.2";

interface JpciteError extends Error {
  jpciteCode?: string;
}

async function loadApiKey(): Promise<string> {
  // OfficeRuntime.storage exists in custom-function runtime; fall back to
  // localStorage when the file is loaded by the test harness in a plain
  // browser. Never throw on absence — return "" so the caller emits #NEEDS_KEY.
  try {
    if (typeof OfficeRuntime !== "undefined" && OfficeRuntime.storage) {
      const v = await OfficeRuntime.storage.getItem(API_KEY_STORAGE_KEY);
      return (v ?? "").trim();
    }
  } catch {
    /* fall through */
  }
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      return (window.localStorage.getItem(API_KEY_STORAGE_KEY) ?? "").trim();
    }
  } catch {
    /* ignore */
  }
  return "";
}

async function jpciteGet(
  path: string,
  query: Record<string, string | number | undefined> = {},
): Promise<unknown> {
  const apiKey = await loadApiKey();
  if (!apiKey) {
    const err: JpciteError = new Error("#NEEDS_KEY");
    err.jpciteCode = "NEEDS_KEY";
    throw err;
  }

  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  const url = `${API_BASE}${path}${qs ? `?${qs}` : ""}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      headers: {
        "X-API-Key": apiKey,
        Accept: "application/json",
        "X-Client": USER_AGENT_NOTE,
      },
    });
  } catch (cause) {
    const err: JpciteError = new Error("#NETWORK_ERROR");
    err.jpciteCode = "NETWORK_ERROR";
    throw err;
  }

  if (res.status === 401 || res.status === 403) {
    const err: JpciteError = new Error("#AUTH_ERROR");
    err.jpciteCode = "AUTH_ERROR";
    throw err;
  }
  if (res.status === 404) {
    const err: JpciteError = new Error("#NOT_FOUND");
    err.jpciteCode = "NOT_FOUND";
    throw err;
  }
  if (res.status === 429) {
    const err: JpciteError = new Error("#RATE_LIMITED");
    err.jpciteCode = "RATE_LIMITED";
    throw err;
  }
  if (res.status < 200 || res.status >= 300) {
    const err: JpciteError = new Error(`#HTTP_${res.status}`);
    err.jpciteCode = `HTTP_${res.status}`;
    throw err;
  }

  return await res.json();
}

function asString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "";
}

function joinNonEmpty(parts: string[], sep: string): string {
  return parts.filter((p) => p && p.length > 0).join(sep);
}

/**
 * Returns 法人名 + 住所 for a 13-digit 法人番号.
 * @customfunction HOUJIN
 * @param {string} houjinBangou 13-digit 法人番号
 * @returns {string} 法人名 / 住所 — slash-joined.
 */
export async function houjin(houjinBangou: string): Promise<string> {
  const data = (await jpciteGet(`/v1/houjin/${encodeURIComponent(houjinBangou)}`)) as Record<
    string,
    unknown
  >;
  const name = asString(data.name) || asString(data.houjin_name);
  const addr = asString(data.address) || asString(data.houjin_address);
  return joinNonEmpty([name, addr], " / ");
}

/**
 * Returns the full JSON response for a 法人番号 (raw string).
 * @customfunction HOUJIN_FULL
 * @param {string} houjinBangou 13-digit 法人番号
 * @returns {string} JSON 全体
 */
export async function houjinFull(houjinBangou: string): Promise<string> {
  const data = await jpciteGet(`/v1/houjin/${encodeURIComponent(houjinBangou)}`);
  return JSON.stringify(data);
}

/**
 * Returns the top N program names for a free-text query, joined by newlines.
 * @customfunction PROGRAMS
 * @param {string} query 検索キーワード (例: 東京都 設備投資)
 * @param {number} [limit] 返却件数 (1-20、既定 5)
 * @returns {string} 改行区切りの制度名一覧
 */
export async function programs(query: string, limit?: number): Promise<string> {
  const cap = Math.max(1, Math.min(20, Math.floor(limit ?? 5)));
  const data = (await jpciteGet(`/v1/programs/search`, { q: query, limit: cap })) as {
    results?: Array<Record<string, unknown>>;
  };
  const list = Array.isArray(data.results) ? data.results : [];
  return list
    .map((row) => asString(row.name))
    .filter((s) => s.length > 0)
    .join("\n");
}

/**
 * Returns 法令名 / 効力日 for an e-Gov law id.
 * @customfunction LAW
 * @param {string} lawId 法令 ID (例: LAW-360AC0000000034)
 * @returns {string} 法令名 / 効力日
 */
export async function law(lawId: string): Promise<string> {
  const data = (await jpciteGet(`/v1/laws/${encodeURIComponent(lawId)}`)) as Record<
    string,
    unknown
  >;
  const title = asString(data.title) || asString(data.name);
  const eff = asString(data.effective_date) || asString(data.effective_from);
  return joinNonEmpty([title, eff], " / ");
}

/**
 * Returns "該当なし" or "該当あり (N 件)" for 行政処分.
 * @customfunction ENFORCEMENT
 * @param {string} houjinBangou 13-digit 法人番号
 * @returns {string} 行政処分の有無
 */
export async function enforcement(houjinBangou: string): Promise<string> {
  const data = (await jpciteGet(`/v1/am/enforcement`, {
    houjin_bangou: houjinBangou,
  })) as { all_count?: number | string };
  const raw = data.all_count;
  const n = typeof raw === "number" ? raw : parseInt(asString(raw) || "0", 10);
  if (!Number.isFinite(n) || n <= 0) return "該当なし";
  return `該当あり (${n} 件)`;
}

// Office.js custom-functions runtime requires associations between the JS
// callable and the metadata `id`. The build pipeline (custom-functions
// metadata generator) typically auto-emits these, but we register explicitly
// so a hand-built bundle still works.
if (typeof CustomFunctions !== "undefined") {
  CustomFunctions.associate("HOUJIN", houjin);
  CustomFunctions.associate("HOUJIN_FULL", houjinFull);
  CustomFunctions.associate("PROGRAMS", programs);
  CustomFunctions.associate("LAW", law);
  CustomFunctions.associate("ENFORCEMENT", enforcement);
}
