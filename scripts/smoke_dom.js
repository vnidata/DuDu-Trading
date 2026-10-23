/*
 * Smoke test DOM cho website DuDu-Trading.
 *
 * Chạy `site/assets/app.js` trên một DOM giả tối thiểu, nạp dữ liệu JSON thật,
 * và kiểm tra rằng toàn bộ luồng render chạy không lỗi và thực sự ghi nội dung
 * vào các vùng chính. Mục đích: bắt lỗi runtime (truy cập thuộc tính undefined,
 * id sai, hàm thiếu) mà kiểm tra tĩnh không phát hiện được.
 *
 *   node scripts/smoke_dom.js
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.join(ROOT, "site");

/* ------------------------------- DOM giả ------------------------------- */
class El {
  constructor(tag, id = null) {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this._html = "";
    this._text = "";
    this.style = {};
    this.dataset = {};
    this.value = "";
    this._classes = new Set();
    this.listeners = {};
    this.classList = {
      add: (c) => this._classes.add(c),
      remove: (c) => this._classes.delete(c),
      toggle: (c, on) => (on === undefined ? (this._classes.has(c) ? this._classes.delete(c) : this._classes.add(c)) : on ? this._classes.add(c) : this._classes.delete(c)),
      contains: (c) => this._classes.has(c),
    };
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
  addEventListener(ev, cb) { (this.listeners[ev] ||= []).push(cb); }
  remove() {}
  getContext() { return {}; }
  closest() { return null; }
  querySelector(sel) {
    if (sel === "tbody") return (this._tbody ||= new El("tbody"));
    if (sel.startsWith("option")) return (this._option ||= new El("option"));
    return new El("div");
  }
  querySelectorAll() { return []; }
  scrollIntoView() {}
}

const html = fs.readFileSync(path.join(SITE, "index.html"), "utf8");
const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
const elements = new Map();
for (const id of ids) elements.set(id, new El("div", id));

// Bảng nào có <table ... id="X"> thì tbody là nơi app.js ghi nội dung
for (const m of html.matchAll(/<table[^>]*id="([^"]+)"/g)) {
  elements.get(m[1])._tbody = new El("tbody");
}

const tabButtons = ["overview", "symbols", "ga", "walkforward", "portfolio", "constraints", "method"].map((t) => {
  const b = new El("button");
  b.dataset.tab = t;
  return b;
});
const tabSections = ["overview", "symbols", "ga", "walkforward", "portfolio", "constraints", "method"].map((t) => new El("section", "tab-" + t));
const chartWraps = [...html.matchAll(/chart-wrap/g)].map(() => new El("div"));

const document = {
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: (sel) => {
    if (sel === "nav.tabs button") return tabButtons;
    if (sel === "section.tab") return tabSections;
    if (sel === ".chart-wrap") return chartWraps;
    return [];
  },
  addEventListener: (ev, cb) => { if (ev === "DOMContentLoaded") document._ready = cb; },
};

/* ------------------------------ Chart giả ------------------------------ */
const chartsCreated = [];
class Chart {
  constructor(ctx, cfg) { this.config = cfg; chartsCreated.push(cfg); }
  destroy() {}
  resize() {}
}
Chart.defaults = {
  color: "", font: { family: "", size: 11 }, animation: {},
  elements: { line: { borderWidth: 1 }, point: { radius: 0 } },
  plugins: { legend: { labels: {} } },
};

/* ------------------------------ fetch giả ------------------------------ */
const fetchLog = [];
async function fetchStub(url) {
  fetchLog.push(url);
  const p = path.join(SITE, url);
  if (!fs.existsSync(p)) return { ok: false, status: 404, json: async () => null };
  return { ok: true, status: 200, json: async () => JSON.parse(fs.readFileSync(p, "utf8")) };
}

/* ------------------------------ thực thi ------------------------------ */
const warnings = [];
const errors = [];
const sandbox = {
  document, Chart, fetch: fetchStub, console: {
    log: () => {}, warn: (...a) => warnings.push(a.join(" ")), error: (...a) => errors.push(a.join(" ")),
  },
  window: { scrollTo: () => {} }, Number, Math, JSON, Object, Array, Set, Map, Promise, String, Boolean, Date, isNaN, parseFloat, parseInt,
};

const src = fs.readFileSync(path.join(SITE, "assets/app.js"), "utf8");
const runner = new Function(
  "document", "Chart", "fetch", "console", "window", "Number", "Math", "JSON", "Object", "Array",
  "Set", "Map", "Promise", "String", "Boolean", "Date", "isNaN", "parseFloat", "parseInt",
  src + "\n//# sourceURL=app.js"
);

let fatal = null;
try {
  runner(
    sandbox.document, sandbox.Chart, sandbox.fetch, sandbox.console, sandbox.window, Number, Math, JSON,
    Object, Array, Set, Map, Promise, String, Boolean, Date, isNaN, parseFloat, parseInt
  );
} catch (e) { fatal = e; }

async function main() {
  if (fatal) {
    console.log("LỖI  nạp app.js thất bại:", fatal.message);
    process.exit(1);
  }
  if (typeof document._ready !== "function") {
    console.log("LỖI  app.js không đăng ký DOMContentLoaded");
    process.exit(1);
  }
  document._ready();
  // boot() là async: chờ vài vòng microtask + macrotask
  for (let i = 0; i < 40; i++) await new Promise((r) => setImmediate(r));

  let fail = 0;
  const check = (label, ok, detail = "") => {
    if (!ok) fail++;
    console.log(`${ok ? "OK  " : "LỖI "} ${label}${detail ? " — " + detail : ""}`);
  };

  check("Không có cảnh báo nạp dữ liệu", warnings.length === 0, warnings.slice(0, 3).join(" | "));
  check("Không có lỗi console", errors.length === 0, errors.slice(0, 3).join(" | "));
  check("Đã gọi fetch cho đủ 11 tệp dữ liệu", fetchLog.length >= 11, `${fetchLog.length} lời gọi`);
  check("Đã khởi tạo biểu đồ", chartsCreated.length >= 11, `${chartsCreated.length} biểu đồ`);

  const expectFilled = [
    "kpiRow", "symKpi", "gaKpi", "wfKpi", "pfKpi", "constraintCards", "methodStrategy", "methodGA", "methodRisk", "methodLimits",
    "legendPortfolio", "portfolioNote", "benchCompare", "pfMonthly", "symGaParams",
    "snapKpi", "snapNote", "snapBadge", "snapEntryNote",
  ];
  const empty = expectFilled.filter((id) => {
    const e = elements.get(id);
    return !e || (e.innerHTML.length === 0 && e.textContent.length === 0);
  });
  check("Các vùng nội dung chính đều được ghi", empty.length === 0, empty.join(", "));

  const tablesWithBody = ["symTable", "gaBasketTable", "gaCompareTable", "gaParamTable", "wfTable", "wfSymbolTable", "pfTrades", "symTrades", "ablationTable", "liquidityTable", "snapEntry", "snapTurnover", "snapMovers"];
  const emptyTables = tablesWithBody.filter((id) => {
    const tb = elements.get(id) && elements.get(id)._tbody;
    return !tb || tb.innerHTML.length === 0;
  });
  check("Các bảng dữ liệu đều có dòng", emptyTables.length === 0, emptyTables.join(", "));

  // Bấm thử từng tab để chắc không có handler nào lỗi
  let clickFail = null;
  try {
    for (const b of tabButtons) for (const cb of (b.listeners.click || [])) cb({ target: { closest: () => b } });
  } catch (e) { clickFail = e; }
  check("Chuyển tab không lỗi", clickFail === null, clickFail ? clickFail.message : "");

  console.log("---");
  console.log(fail === 0 ? "SMOKE TEST DOM: ĐẠT" : `SMOKE TEST DOM: ${fail} LỖI`);
  process.exit(fail === 0 ? 0 : 1);
}

main();
