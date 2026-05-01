/**
 * jpcite — Google Sheets custom functions.
 *
 * Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
 * Brand:    jpcite (https://jpcite.com)
 * API:      https://api.jpcite.com  (X-API-Key, ¥3/req metered, 税込 ¥3.30)
 *
 * Five custom functions exposed to the spreadsheet:
 *
 *   =JPCITE_HOUJIN("8010001213708")             法人名 + 住所
 *   =JPCITE_HOUJIN_FULL("8010001213708")        JSON 全体 (raw string)
 *   =JPCITE_PROGRAMS("東京都 設備投資", 5)       上位 N 件 (改行連結)
 *   =JPCITE_LAW("LAW-360AC0000000034")          法令名 + 効力日
 *   =JPCITE_ENFORCEMENT("8010001213708")        該当あり/なし
 *
 * The API key is read from the document's Script Properties, which the
 * sidebar (`Sidebar.html`) writes via `setApiKey()`. Apps Script does not
 * have process env vars; Script Properties is the supported substitute.
 *
 * No LLM call. No DB write. Each successful cell call costs ¥3 metered
 * via the jpcite API gateway. Sheet recalcs multiply this cost — see
 * README.md "Recalc storm" section.
 */

var JPCITE_API_BASE = "https://api.jpcite.com";
var JPCITE_USER_AGENT = "jpcite-gsheets-addon/0.3.2";
var JPCITE_KEY_PROP = "JPCITE_API_KEY";


// ---------------------------------------------------------------------------
// Helpers (private — names start with `_`)
// ---------------------------------------------------------------------------

function _loadApiKey() {
  var props = PropertiesService.getDocumentProperties();
  var v = props ? props.getProperty(JPCITE_KEY_PROP) : "";
  return (v || "").trim();
}

function _asString(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  return String(v);
}

function _coerceLimit(n, fallback) {
  var def = fallback === undefined ? 5 : fallback;
  if (n === undefined || n === null || n === "") return def;
  var x = parseInt(n, 10);
  if (!isFinite(x) || isNaN(x)) return def;
  if (x < 1) return 1;
  if (x > 20) return 20;
  return x;
}

function _normalizeBangou(b) {
  return _asString(b).replace(/\D/g, "");
}

function _jpciteGet(path, query) {
  var apiKey = _loadApiKey();
  if (!apiKey) return { _error: "NEEDS_KEY" };

  var qs = "";
  if (query) {
    var parts = [];
    for (var k in query) {
      if (Object.prototype.hasOwnProperty.call(query, k)) {
        var v = query[k];
        if (v === undefined || v === null || v === "") continue;
        parts.push(
          encodeURIComponent(k) + "=" + encodeURIComponent(String(v))
        );
      }
    }
    if (parts.length) qs = "?" + parts.join("&");
  }
  var url = JPCITE_API_BASE + path + qs;

  var res;
  try {
    res = UrlFetchApp.fetch(url, {
      method: "get",
      muteHttpExceptions: true,
      headers: {
        "X-API-Key": apiKey,
        Accept: "application/json",
        "X-Client": JPCITE_USER_AGENT
      }
    });
  } catch (cause) {
    return { _error: "NETWORK_ERROR" };
  }

  var status = res.getResponseCode();
  var body = res.getContentText() || "";
  if (status === 401 || status === 403) return { _error: "AUTH_ERROR" };
  if (status === 404) return { _error: "NOT_FOUND" };
  if (status === 429) return { _error: "RATE_LIMITED" };
  if (status < 200 || status >= 300) return { _error: "HTTP_" + status };
  try {
    return JSON.parse(body);
  } catch (e) {
    return { _error: "PARSE_ERROR" };
  }
}

function _errorString(payload) {
  if (payload && payload._error) return "#" + payload._error;
  return "";
}

function _joinNonEmpty(parts, sep) {
  var out = [];
  for (var i = 0; i < parts.length; i++) {
    var s = _asString(parts[i]);
    if (s.length > 0) out.push(s);
  }
  return out.join(sep);
}


// ---------------------------------------------------------------------------
// Public custom functions
// ---------------------------------------------------------------------------

/**
 * 法人番号から法人名 + 住所を取得します (¥3/req)。
 *
 * @param {string} houjinBangou 13 桁の法人番号 (例: 8010001213708)
 * @return {string} "法人名 / 住所"
 * @customfunction
 */
function JPCITE_HOUJIN(houjinBangou) {
  var bangou = _normalizeBangou(houjinBangou);
  if (bangou.length !== 13) return "#BAD_INPUT";
  var data = _jpciteGet("/v1/houjin/" + encodeURIComponent(bangou), null);
  var err = _errorString(data);
  if (err) return err;
  var name = _asString(data.name) || _asString(data.houjin_name);
  var addr = _asString(data.address) || _asString(data.houjin_address);
  return _joinNonEmpty([name, addr], " / ");
}

/**
 * 法人番号の全フィールドを JSON 文字列で返します (¥3/req)。
 *
 * @param {string} houjinBangou 13 桁の法人番号
 * @return {string} JSON 文字列
 * @customfunction
 */
function JPCITE_HOUJIN_FULL(houjinBangou) {
  var bangou = _normalizeBangou(houjinBangou);
  if (bangou.length !== 13) return "#BAD_INPUT";
  var data = _jpciteGet("/v1/houjin/" + encodeURIComponent(bangou), null);
  var err = _errorString(data);
  if (err) return err;
  return JSON.stringify(data);
}

/**
 * 制度検索: 上位 N 件の制度名を改行で連結して返します (¥3/req)。
 *
 * @param {string} query 検索キーワード (例: 東京都 設備投資)
 * @param {number} limit 返却件数 (1-20、既定 5)
 * @return {string} 改行区切りの制度名一覧
 * @customfunction
 */
function JPCITE_PROGRAMS(query, limit) {
  var q = _asString(query);
  if (!q) return "#BAD_INPUT";
  var cap = _coerceLimit(limit, 5);
  var data = _jpciteGet("/v1/programs/search", { q: q, limit: cap });
  var err = _errorString(data);
  if (err) return err;
  var rows =
    (data && (data.results || data.items)) ||
    (Array.isArray(data) ? data : []);
  if (!rows || !rows.length) return "";
  var lines = [];
  for (var i = 0; i < rows.length && i < cap; i++) {
    var row = rows[i] || {};
    // Defense in depth: drop aggregator-only rows (no source_url and no authority).
    if (!row.source_url && !row.authority) continue;
    var title = _asString(row.name) || _asString(row.title) || _asString(row.primary_name);
    if (title) lines.push(title);
  }
  return lines.join("\n");
}

/**
 * 法令 ID から名称 + 効力日を返します (¥3/req)。
 *
 * @param {string} lawId e-Gov 法令 ID (例: LAW-360AC0000000034)
 * @return {string} "法令名 / 効力日"
 * @customfunction
 */
function JPCITE_LAW(lawId) {
  var id = _asString(lawId).trim();
  if (!id) return "#BAD_INPUT";
  var data = _jpciteGet("/v1/laws/" + encodeURIComponent(id), null);
  var err = _errorString(data);
  if (err) return err;
  var title = _asString(data.title) || _asString(data.name);
  var eff = _asString(data.effective_date) || _asString(data.effective_from);
  return _joinNonEmpty([title, eff], " / ");
}

/**
 * 法人番号の行政処分有無を返します (¥3/req)。
 *
 * @param {string} houjinBangou 13 桁の法人番号
 * @return {string} "該当あり (N 件)" または "該当なし"
 * @customfunction
 */
function JPCITE_ENFORCEMENT(houjinBangou) {
  var bangou = _normalizeBangou(houjinBangou);
  if (bangou.length !== 13) return "#BAD_INPUT";
  var data = _jpciteGet("/v1/am/enforcement", { houjin_bangou: bangou });
  var err = _errorString(data);
  if (err) return err;
  var n = parseInt(_asString(data.all_count) || "0", 10);
  if (!isFinite(n) || isNaN(n) || n <= 0) return "該当なし";
  return "該当あり (" + n + " 件)";
}


// ---------------------------------------------------------------------------
// Sidebar / API key bootstrap
// ---------------------------------------------------------------------------

function onHomepage() {
  var html = HtmlService.createHtmlOutputFromFile("Sidebar")
    .setTitle("jpcite 設定");
  return html;
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("jpcite")
    .addItem("設定 (API キー)", "showSidebar")
    .addToUi();
}

function showSidebar() {
  var html = HtmlService.createHtmlOutputFromFile("Sidebar")
    .setTitle("jpcite 設定")
    .setWidth(320);
  SpreadsheetApp.getUi().showSidebar(html);
}

function setApiKey(apiKey) {
  var v = (apiKey || "").trim();
  if (!v) throw new Error("API キーが空です。");
  PropertiesService.getDocumentProperties().setProperty(JPCITE_KEY_PROP, v);
  return true;
}

function clearApiKey() {
  PropertiesService.getDocumentProperties().deleteProperty(JPCITE_KEY_PROP);
  return true;
}

function getApiKeyMasked() {
  var v = _loadApiKey();
  if (!v) return "";
  if (v.length <= 6) return "******";
  return v.substring(0, 4) + "***" + v.substring(v.length - 2);
}
