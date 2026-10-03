/**
 * せどりナビ ⇄ Googleスプレッドシート 連携用 Apps Script
 * 使い方は gas/README.md を参照。
 * スクリプトプロパティ TOKEN に合言葉を設定してください。
 */
const SHEET = "台帳";
const COLS = ["id", "name", "url", "buy", "list", "ship", "plat", "status", "bd", "sold", "sd"];
const NUM = ["id", "buy", "list", "ship", "sold"];

function sheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(SHEET) || ss.insertSheet(SHEET);
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function authed_(t) {
  const tok = PropertiesService.getScriptProperties().getProperty("TOKEN");
  return !!tok && t === tok;
}

// 読み込み（スプレッドシート → アプリ）
function doGet(e) {
  if (!authed_(e.parameter.token)) return json_({ ok: false, error: "合言葉が違います" });
  const sh = sheet_();
  const v = sh.getLastRow() > 1 ? sh.getRange(2, 1, sh.getLastRow() - 1, COLS.length).getValues() : [];
  const items = v.filter(r => r[0] !== "").map(r => {
    const o = {};
    COLS.forEach((c, i) => {
      let x = r[i];
      if (x instanceof Date) x = Utilities.formatDate(x, "Asia/Tokyo", "yyyy-MM-dd");
      o[c] = x === "" ? null : (NUM.includes(c) ? Number(x) : x);
    });
    return o;
  });
  return json_({ ok: true, items: items });
}

// 保存（アプリ → スプレッドシート。全件を上書き）
function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (!authed_(body.token)) return json_({ ok: false, error: "合言葉が違います" });
  const sh = sheet_();
  sh.clearContents();
  const rows = [COLS].concat(body.items.map(i => COLS.map(c => i[c] ?? "")));
  // 日付が自動変換されないよう、書き込み前に文字列形式にする
  ["bd", "sd"].forEach(c => sh.getRange(1, COLS.indexOf(c) + 1, rows.length).setNumberFormat("@"));
  sh.getRange(1, 1, rows.length, COLS.length).setValues(rows);
  return json_({ ok: true, count: body.items.length });
}
