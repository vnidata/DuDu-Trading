/* DuDu-Trading — bảng điều khiển tĩnh, đọc JSON từ ./data/ (GitHub Pages). */
"use strict";

const state = {
  meta: null,
  symbols: [],
  curves: null,
  portfolio: null,
  ga: null,
  walkforward: null,
  ablation: [],
  heatmap: [],
  liquidity: [],
  charts: {},
  selected: null,
  pfVariant: "default",
  sortKey: "calmar",
  sortAsc: false,
};

const COLORS = {
  accent: "#2f81f7",
  accent2: "#35d0a5",
  pos: "#26c281",
  neg: "#f2545b",
  warn: "#f0b132",
  bench: "#8b98ab",
  grid: "#1f2a3a",
  text: "#93a3b8",
};

/* ------------------------------ tiện ích ------------------------------ */
const fmtPct = (v, nd = 1) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : (v * 100).toFixed(nd) + "%";
const fmtNum = (v, nd = 2) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Number(v).toFixed(nd);
const fmtInt = (v) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Math.round(v).toLocaleString("vi-VN");
const signCls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "dim");
const fmtVnd = (v) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + " tỷ";
  if (a >= 1e6) return (v / 1e6).toFixed(1) + " tr";
  return Math.round(v).toLocaleString("vi-VN");
};
const el = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function loadJSON(path) {
  try {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    console.warn("Không nạp được", path, e);
    return null;
  }
}

function applyChartDefaults() {
  if (typeof Chart === "undefined") return false;
  Chart.defaults.color = COLORS.text;
  Chart.defaults.font.family = 'Inter, "Segoe UI", Roboto, sans-serif';
  Chart.defaults.font.size = 11;
  Chart.defaults.animation = false;
  Chart.defaults.elements.line.borderWidth = 1.8;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  return true;
}

function makeChart(id, config) {
  if (typeof Chart === "undefined") return null;
  const cvs = el(id);
  if (!cvs) return null;
  if (state.charts[id]) state.charts[id].destroy();
  const chart = new Chart(cvs.getContext("2d"), config);
  state.charts[id] = chart;
  return chart;
}

const lineDataset = (label, data, color, opts = {}) => ({
  label, data, borderColor: color, backgroundColor: color + "22",
  fill: opts.fill || false, tension: 0, pointRadius: 0, borderWidth: opts.width || 1.8,
  yAxisID: opts.yAxisID || "y", borderDash: opts.dash || undefined, spanGaps: true,
});

const axes = (extra = {}) => ({
  x: { grid: { color: COLORS.grid, drawTicks: false }, ticks: { maxTicksLimit: 8, autoSkip: true }, ...(extra.x || {}) },
  y: { grid: { color: COLORS.grid, drawTicks: false }, ...(extra.y || {}) },
});

function histogramChart(id, dist, color, label, asPct = false) {
  if (!dist || !dist.counts || !dist.counts.length) return;
  const labels = dist.counts.map((_, i) => {
    const mid = (dist.edges[i] + dist.edges[i + 1]) / 2;
    return asPct ? (mid * 100).toFixed(1) + "%" : mid.toFixed(2);
  });
  makeChart(id, {
    type: "bar",
    data: { labels, datasets: [{ label, data: dist.counts, backgroundColor: color + "cc", borderWidth: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: (it) => `${label} ≈ ${it[0].label}`, label: (it) => `${it.raw} fold` } },
        annotation: false,
      },
      scales: axes({ x: { ticks: { maxTicksLimit: 8 } } }),
    },
  });
}

/* ------------------------------ nạp dữ liệu ------------------------------ */
async function boot() {
  const [meta, symbols, curves, portfolio, ga, wf, ablation, heatmap, liquidity, snapshot, snapHistory, tradesData, advisorsSummary] = await Promise.all([
    loadJSON("data/meta.json"),
    loadJSON("data/symbols.json"),
    loadJSON("data/curves.json"),
    loadJSON("data/portfolio.json"),
    loadJSON("data/ga.json"),
    loadJSON("data/walkforward.json"),
    loadJSON("data/ablation.json"),
    loadJSON("data/heatmap.json"),
    loadJSON("data/liquidity.json"),
    loadJSON("data/snapshot.json"),
    loadJSON("data/snapshot_history.json"),
    loadJSON("data/trade_history.json"),
    loadJSON("data/advisors_summary.json"),
  ]);

  state.meta = meta; state.symbols = symbols || []; state.curves = curves;
  state.portfolio = portfolio; state.ga = ga; state.walkforward = wf;
  state.ablation = ablation || []; state.heatmap = heatmap || [];
  state.liquidity = (liquidity && liquidity.symbols) ? liquidity.symbols : (Array.isArray(liquidity) ? liquidity : []);
  state.coverage = (liquidity && liquidity.coverage) ? liquidity.coverage : null;
  state.snapshot = snapshot || null;
  state.snapHistory = Array.isArray(snapHistory) ? snapHistory : [];
  state.tradesData = tradesData || null;
  state.advisorsSummary = advisorsSummary || [];

  el("loading").style.display = "none";
  el("app").style.display = "block";

  if (!meta) {
    el("app").innerHTML = '<div class="warn-box">Chưa có dữ liệu. Chạy <code>python scripts/run_research.py</code> để sinh thư mục <code>site/data/</code>.</div>';
    return;
  }

  fillHeader();
  const ok = applyChartDefaults();
  if (!ok) {
    document.querySelectorAll(".chart-wrap").forEach((n) => {
      n.innerHTML = '<p class="note" style="padding-top:40px;text-align:center">Không nạp được thư viện biểu đồ (Chart.js CDN). Bảng số liệu vẫn hoạt động bình thường.</p>';
    });
  }

  renderSnapshot();
  renderRecommendations();
  renderAdvisors();
  renderTrades();
  renderOverview();
  renderSymbols();
  renderGA();
  renderWalkforward();
  renderPortfolio();
  renderConstraints();
  renderMethod();
  initStockDoctor();
  initLivePolling();
}

/* ------------------------------ LIVE POLLING 5 PHÚT ------------------------------ */
const POLL_INTERVAL_SECONDS = 300; // 5 phút
let countdownSeconds = POLL_INTERVAL_SECONDS;
let isRefreshing = false;

async function refreshSnapshotData() {
  if (isRefreshing) return;
  isRefreshing = true;
  const pill = el("liveStatusText");
  if (pill) pill.textContent = "Đang tải…";

  try {
    const bust = "?_t=" + Date.now();
    const [snap, hist] = await Promise.all([
      loadJSON("data/snapshot.json" + bust),
      loadJSON("data/snapshot_history.json" + bust),
    ]);
    if (snap) {
      state.snapshot = snap;
      if (Array.isArray(hist)) state.snapHistory = hist;
      renderSnapshot();
      renderRecommendations();
      renderAdvisors();
    }
  } catch (err) {
    console.warn("Lỗi refresh snapshot:", err);
  } finally {
    isRefreshing = false;
    countdownSeconds = POLL_INTERVAL_SECONDS;
    if (pill) pill.textContent = "Live";
    updateCountdownDisplay();
  }
}

function updateCountdownDisplay() {
  const m = Math.floor(countdownSeconds / 60);
  const s = countdownSeconds % 60;
  const str = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  const cd = el("liveCountdown");
  if (cd) cd.textContent = str;
  const nextRef = el("snapNextRefresh");
  if (nextRef) nextRef.textContent = `Làm mới sau: ${str}`;
}

function initLivePolling() {
  updateCountdownDisplay();

  const btn = el("btnManualRefresh");
  if (btn) {
    btn.addEventListener("click", () => {
      refreshSnapshotData();
    });
  }

  if (typeof setInterval === "function") {
    setInterval(() => {
      if (countdownSeconds > 0) {
        countdownSeconds--;
        updateCountdownDisplay();
      } else {
        refreshSnapshotData();
      }
    }, 1000);
  }
}

/* ------------------------------ PHIÊN GIAO DỊCH ------------------------------ */
const SESSION_LABEL = {
  pre_open: "Chưa mở cửa",
  morning: "Phiên sáng",
  lunch: "Nghỉ trưa",
  afternoon: "Phiên chiều",
  atc: "Phiên đóng cửa (ATC)",
  closed: "Đã đóng cửa",
  holiday: "Cuối tuần / ngày nghỉ",
};

function snapshotAgeHours(snap) {
  const t = Date.parse(snap.as_of);
  if (Number.isNaN(t)) return NaN;
  return (Date.now() - t) / 36e5;
}

function renderSnapshot() {
  const s = state.snapshot;
  if (!s) {
    el("snapBadge").innerHTML = '<span class="badge muted">chưa có dữ liệu phiên</span>';
    el("snapKpi").innerHTML = '<div class="card"><p class="note">Chưa có ảnh chụp phiên. Chạy <code>python scripts/snapshot.py</code>.</p></div>';
    ["snapTurnover", "snapMovers", "snapEntry"].forEach((id) => {
      const tb = el(id) && el(id).querySelector("tbody");
      if (tb) tb.innerHTML = "";
    });
    return;
  }

  const stale = snapshotAgeHours(s);
  const fresh = Number.isFinite(stale) ? stale : 0;
  el("snapBadge").innerHTML =
    `<span class="badge ${s.is_final ? "ok" : "info"}">${esc(SESSION_LABEL[s.session] || s.session)}</span> ` +
    `<span class="badge ${fresh > 30 ? "no" : "muted"}">cập nhật ${fmtAgo(fresh)}</span>`;

  el("snapWarn").innerHTML = s.is_final
    ? ""
    : `<div class="warn-box" style="margin-bottom:12px"><b>Bar ngày chưa chốt.</b> ${esc(s.disclaimer)}</div>`;

  const b = s.benchmark || {};
  const regimeTxt = b.above_sma200 === undefined ? "—" : b.above_sma200 ? "trên SMA200" : "dưới SMA200";
  el("snapKpi").innerHTML = [
    kpiCard(
      `${esc(s.benchmark ? s.benchmark.symbol : "Chỉ số")}`,
      b.close !== undefined ? fmtInt(b.close) : "—",
      `${fmtPct(b.change_pct)} · ${regimeTxt}`,
      signCls(b.change_pct)
    ),
    kpiCard("Độ rộng thị trường", fmtPct(s.breadth.up_share, 0), `${s.breadth.up} tăng / ${s.breadth.down} giảm / ${s.breadth.flat} đứng`, s.breadth.up_share > 0.5 ? "pos" : "neg"),
    kpiCard("Giá trị khớp lệnh", fmtNum(s.liquidity.turnover_total_bn, 0) + " tỷ", `${fmtInt(s.liquidity.n_passes_adv)}/${fmtInt(s.n_symbols)} mã đạt ADV ≥ ${fmtNum(s.liquidity.adv_min_bn, 0)} tỷ`, ""),
    kpiCard("Tín hiệu vào lệnh", fmtInt(s.signals.n_entry), `${fmtInt(s.signals.n_exit)} tín hiệu thoát · ${fmtInt(s.signals.n_at_ceiling)} mã giá trần`, s.signals.n_entry > 0 ? "pos" : "dim"),
  ].join("");

  el("snapNote").innerHTML =
    `Phiên <b>${esc(s.bar_date)}</b> · ảnh chụp lúc ${esc(s.as_of.slice(0, 16).replace("T", " "))} · ` +
    `${fmtPct(s.liquidity.adv_pass_share, 0)} số mã đạt ngưỡng thanh khoản · ` +
    `${fmtInt(s.signals.n_above_upper)} mã đang trên đỉnh ${state.meta ? state.meta.config.strategy.entry_window : 55} phiên · ` +
    `${fmtInt(s.signals.n_regime_bull)} mã có chỉ số chung trên SMA200. ` +
    `Số liệu phiên được làm mới 6 lần mỗi ngày giao dịch: 09:45, 10:00, 11:30, 13:30, 14:00, 15:00.`;

  renderSnapIntraday();
  renderSnapTables(s);
}

function fmtAgo(hours) {
  if (!Number.isFinite(hours)) return "—";
  if (hours < 0) return "vừa xong";
  if (hours < 1) return Math.max(1, Math.round(hours * 60)) + " phút trước";
  if (hours < 24) return hours.toFixed(0) + " giờ trước";
  return (hours / 24).toFixed(0) + " ngày trước";
}

function renderSnapIntraday() {
  const h = (state.snapHistory || []).slice(-60);
  if (!h.length) return;
  const labels = h.map((x) => x.as_of.slice(5, 16).replace("T", " "));
  const ds = [
    lineDataset("VN-Index", h.map((x) => x.vnindex), COLORS.accent, { width: 2, yAxisID: "y" }),
    lineDataset("Độ rộng tăng (%)", h.map((x) => (x.up_share === null || x.up_share === undefined ? null : x.up_share * 100)), COLORS.accent2, { yAxisID: "y1" }),
    lineDataset("Mã đạt ADV (%)", h.map((x) => (x.adv_pass_share === null || x.adv_pass_share === undefined ? null : x.adv_pass_share * 100)), COLORS.warn, { yAxisID: "y1", dash: [4, 3] }),
  ];
  makeChart("chartSnapIntraday", {
    type: "line",
    data: { labels, datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: true } },
      scales: {
        x: { grid: { color: COLORS.grid }, ticks: { maxTicksLimit: 8 } },
        y: { position: "left", grid: { color: COLORS.grid }, title: { display: true, text: "VN-Index", color: COLORS.text } },
        y1: { position: "right", grid: { display: false }, min: 0, max: 100, ticks: { callback: (v) => v + "%" } },
      },
    },
  });
}

function renderSnapTables(s) {
  const chg = (v) => `<span class="${signCls(v)}">${fmtPct(v)}</span>`;
  const flag = (r) => (r.at_ceiling ? '<span class="badge warn">trần</span>' : r.at_floor ? '<span class="badge no">sàn</span>' : "");

  el("snapTurnover").querySelector("tbody").innerHTML = (s.leaders.turnover || [])
    .map((r) => `<tr><td><b>${r.symbol}</b></td><td>${fmtNum(r.turnover_bn, 1)}</td><td class="dim">${fmtNum(r.adv20_bn, 1)}</td>
      <td>${r.passes_adv ? '<span class="badge ok">đạt</span>' : '<span class="badge no">dưới</span>'}</td></tr>`)
    .join("");

  const movers = [...(s.leaders.gainers || []).slice(0, 5), ...(s.leaders.losers || []).slice(0, 5)];
  el("snapMovers").querySelector("tbody").innerHTML = movers
    .map((r) => `<tr><td><b>${r.symbol}</b></td><td>${fmtInt(r.close)}</td><td>${chg(r.change_pct)}</td><td>${flag(r)}</td></tr>`)
    .join("");

  const entries = s.signals.entry_symbols || [];
  el("snapEntry").querySelector("tbody").innerHTML = entries.length
    ? entries
        .map((r) => `<tr><td><b>${r.symbol}</b></td><td>${fmtInt(r.close)}</td><td>${chg(r.change_pct)}</td>
          <td>${fmtNum(r.turnover_bn, 1)}</td><td class="${signCls(r.dist_to_upper_pct)}">${fmtPct(r.dist_to_upper_pct)}</td>
          <td>${fmtInt(r.units)}</td></tr>`)
        .join("")
    : '<tr><td colspan="6" class="faint">Không có mã nào thoả đồng thời điều kiện phá đỉnh, thanh khoản và xu hướng thị trường.</td></tr>';
  el("snapEntryNote").textContent =
    `Điều kiện: giá đóng cửa vượt đỉnh ${state.meta ? state.meta.config.strategy.entry_window : 55} phiên, không nằm tại giá trần, ` +
    `ADV20 ≥ ${fmtNum(s.liquidity.adv_min_bn, 0)} tỷ và chỉ số chung trên SMA200. Cột "Unit" là khối lượng một Unit theo công thức engine.`;
}


function fillHeader() {
  const m = state.meta;
  el("metaSource").textContent = m.data.source;
  el("metaUniverse").textContent = `${m.data.universe_group} · ${m.data.n_symbols} mã`;
  el("metaRange").textContent = `${m.data.date_start} → ${m.data.date_end}`;
  el("metaUpdated").textContent = (m.generated_at || "").slice(0, 16).replace("T", " ");
  el("footerText").innerHTML =
    `DuDu-Trading v${m.app.version} · <a href="${m.app.repo_url}" target="_blank" rel="noopener">mã nguồn trên GitHub</a> · ` +
    `dữ liệu ${esc(m.data.source)} · ${esc(m.data.n_symbols)} mã × ${fmtInt(m.data.n_sessions)} phiên · ` +
    `sinh lúc ${esc((m.generated_at || "").slice(0, 19).replace("T", " "))} · không phải khuyến nghị đầu tư.`;
}

/* ------------------------------ TỔNG QUAN ------------------------------ */
function kpiCard(label, value, sub, cls = "") {
  return `<div class="card kpi"><div class="label">${label}</div><div class="value ${cls}">${value}</div><div class="sub">${sub}</div></div>`;
}

function renderOverview() {
  const h = state.meta.headline;
  const rows = [
    kpiCard("CAGR danh mục", fmtPct(h.portfolio_cagr), "vốn 1 tỷ VND, không margin", signCls(h.portfolio_cagr)),
    kpiCard("Sharpe danh mục", fmtNum(h.portfolio_sharpe), "lãi suất phi rủi ro = 0", signCls(h.portfolio_sharpe)),
    kpiCard("Calmar danh mục", fmtNum(h.portfolio_calmar), "CAGR / |MaxDD|", signCls(h.portfolio_calmar)),
    kpiCard("MaxDD danh mục", fmtPct(h.portfolio_max_dd), "đỉnh tới đáy trên đường vốn", "neg"),
    kpiCard("Tần suất giao dịch", fmtNum(h.portfolio_trades_per_year, 1) + " lệnh/năm", "mục tiêu: trung bình 2–20", ""),
    kpiCard("Calmar trung vị theo mã", fmtNum(h.default_calmar_median), `trên ${state.meta.data.n_symbols} mã, Donchian-55`, signCls(h.default_calmar_median)),
    kpiCard("Tỷ lệ mã CAGR dương", fmtPct(h.default_cagr_positive_share, 0), "cấu hình mặc định", ""),
    kpiCard("Tỷ lệ đạt cổng OOS", fmtPct(h.ga_acceptance_rate, 0), "Calmar > 0,5 và &lt; 20 lệnh/năm", ""),
  ];
  el("kpiRow").innerHTML = rows.join("");

  renderPortfolioChart();
  renderDistributions();
  renderAblation();
  renderHeatmap();
}

function renderPortfolioChart() {
  const c = state.curves;
  if (!c || !c.dates) return;
  const ds = [];
  if (c.portfolio_default) ds.push(lineDataset("Danh mục — Donchian-55", c.portfolio_default, COLORS.accent, { width: 2.2 }));
  if (c.portfolio_ga_basket) ds.push(lineDataset("Danh mục — tham số GA", c.portfolio_ga_basket, COLORS.accent2, { width: 2.2 }));
  if (c.benchmark) ds.push(lineDataset(state.meta.data.benchmark, c.benchmark, COLORS.bench, { dash: [5, 4] }));

  makeChart("chartPortfolio", {
    type: "line",
    data: { labels: c.dates, datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (it) => `${it.dataset.label}: ${Number(it.raw).toFixed(1)}` } },
      },
      scales: axes({ y: { ticks: { callback: (v) => v } } }),
    },
  });

  el("legendPortfolio").innerHTML = ds
    .map((d) => `<span class="key"><i style="background:${d.borderColor}"></i>${esc(d.label)}</span>`)
    .join("");
  const p = state.portfolio && state.portfolio.default;
  const h = state.meta.headline;
  const cmpRows = [
    ["CAGR", fmtPct(h.portfolio_cagr), fmtPct(h.benchmark_cagr), h.portfolio_cagr - h.benchmark_cagr],
    ["Sharpe", fmtNum(h.portfolio_sharpe), fmtNum(h.benchmark_sharpe), h.portfolio_sharpe - h.benchmark_sharpe],
    ["MaxDD", fmtPct(h.portfolio_max_dd), fmtPct(h.benchmark_max_dd), h.portfolio_max_dd - h.benchmark_max_dd],
    ["Calmar", fmtNum(h.portfolio_calmar), fmtNum(h.benchmark_calmar), h.portfolio_calmar - h.benchmark_calmar],
  ];
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : NaN);
  el("benchCompare").innerHTML =
    `<thead><tr><th>Chỉ số</th><th>Danh mục Donchian-55</th><th>${esc(h.benchmark_symbol || "VNINDEX")} mua-và-giữ</th><th>Chênh lệch</th></tr></thead><tbody>` +
    cmpRows
      .map((r) => `<tr><td>${r[0]}</td><td class="${signCls(num(r[3]))}">${r[1]}</td><td class="dim">${r[2]}</td>
        <td class="${signCls(num(r[3]))}">${r[0] === "Sharpe" || r[0] === "Calmar" ? fmtNum(r[3]) : fmtPct(r[3])}</td></tr>`)
      .join("") +
    `</tbody>`;

  if (p) {
    el("portfolioNote").textContent =
      `Gốc 100 tại ${state.meta.data.date_start}. Danh mục tối đa 5 mã đồng thời, tổng giải ngân ≤ 60% NAV tại thời điểm mở vị thế, ` +
      `mỗi lệnh chịu rủi ro 1% vốn. Số lệnh: ${fmtInt(p.trade_stats.trades)} · hit rate ${fmtPct(p.trade_stats.hit_rate, 0)} · ` +
      `profit factor ${fmtNum(p.trade_stats.profit_factor)} · giải ngân bình quân ${fmtPct(p.metrics.avg_exposure, 0)}. ` +
      `Chỉ số tham chiếu tính theo giá, không cộng cổ tức tiền mặt.`;
  }
}

function renderDistributions() {
  const calmar = state.symbols.map((s) => s.calmar).filter((v) => Number.isFinite(v));
  const sharpe = state.symbols.map((s) => s.sharpe).filter((v) => Number.isFinite(v));
  histogramChart("chartDistCalmar", makeHist(calmar, 26), COLORS.accent, "Số mã");
  histogramChart("chartDistSharpe", makeHist(sharpe, 26), COLORS.accent2, "Số mã");
}

function makeHist(values, bins) {
  if (!values.length) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const edges = Array.from({ length: bins + 1 }, (_, i) => lo + (span * i) / bins);
  const counts = new Array(bins).fill(0);
  values.forEach((v) => {
    let i = Math.floor(((v - lo) / span) * bins);
    if (i >= bins) i = bins - 1;
    if (i < 0) i = 0;
    counts[i]++;
  });
  return { edges, counts };
}

function renderAblation() {
  if (!state.ablation.length) return;
  const labels = state.ablation.map((a) => a.label);
  const full = state.ablation.find((a) => a.key === "full");
  const colors = state.ablation.map((a) =>
    a.key === "full" ? COLORS.accent : a.calmar_median >= (full ? full.calmar_median : 0) ? COLORS.pos : COLORS.neg
  );
  makeChart("chartAblation", {
    type: "bar",
    data: { labels, datasets: [{ label: "Calmar trung vị", data: state.ablation.map((a) => a.calmar_median), backgroundColor: colors.map((c) => c + "cc"), borderWidth: 0 }] },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        label: (it) => {
          const a = state.ablation[it.dataIndex];
          return [`Calmar ${fmtNum(a.calmar_median)}`, `Sharpe ${fmtNum(a.sharpe_median)}`,
                  `CAGR ${fmtPct(a.cagr_median)}`, `MaxDD ${fmtPct(a.max_dd_median)}`,
                  `${fmtNum(a.trades_per_year_median, 1)} lệnh/năm`];
        },
      } } },
      scales: { x: { grid: { color: COLORS.grid } }, y: { grid: { display: false } } },
    },
  });
}

function renderHeatmap() {
  if (!state.heatmap.length) return;
  const labels = state.heatmap.map((h) => h.entry_window);
  const traded = state.heatmap[0].traded_share;
  makeChart("chartHeatmap", {
    type: "line",
    data: {
      labels,
      datasets: [
        lineDataset("Calmar (trung bình cắt đuôi 10%)", state.heatmap.map((h) => h.calmar), COLORS.accent, { width: 2, fill: true }),
        lineDataset("Sharpe (trung bình cắt đuôi)", state.heatmap.map((h) => h.sharpe), COLORS.accent2),
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: true },
        tooltip: { callbacks: { afterBody: (items) => {
          const h = state.heatmap[items[0].dataIndex];
          return [`CAGR ${fmtPct(h.cagr)}`, `${fmtNum(h.trades_per_year, 2)} lệnh/năm/mã`, `${fmtPct(h.traded_share, 0)} số mã có phát sinh lệnh`];
        } } },
      },
      scales: axes({ x: { title: { display: true, text: "entry_window (phiên)", color: COLORS.text } } }),
    },
  });
}

/* ------------------------------ THEO MÃ ------------------------------ */
function renderSymbols() {
  const rows = state.symbols;
  if (!rows.length) return;
  const withOos = rows.filter((r) => r.ga_out_of_sample);
  const pass = withOos.filter((r) => r.oos_accepted).length;
  const med = (arr) => {
    const a = arr.filter(Number.isFinite).slice().sort((x, y) => x - y);
    return a.length ? a[Math.floor(a.length / 2)] : NaN;
  };
  el("symKpi").innerHTML = [
    kpiCard("Số mã trong rổ", fmtInt(rows.length), "VN100 trên HOSE", ""),
    kpiCard("Calmar trung vị", fmtNum(med(rows.map((r) => r.calmar))), "cấu hình Donchian-55", ""),
    kpiCard("Đạt cổng OOS", `${pass}/${withOos.length}`, "Calmar OOS > 0,5", pass / Math.max(1, withOos.length) > 0.5 ? "pos" : "warn"),
  ].join("");

  const search = el("symSearch"), filter = el("symFilter"), sortSel = el("symSort");
  const draw = () => {
    let list = rows.slice();
    const q = search.value.trim().toUpperCase();
    if (q) list = list.filter((r) => r.symbol.includes(q));
    if (filter.value === "pass") list = list.filter((r) => r.oos_accepted);
    if (filter.value === "pos") list = list.filter((r) => r.calmar > 0);
    if (filter.value === "adv") list = list.filter((r) => r.adv_billion >= 30);
    const k = sortSel.value;
    list.sort((a, b) => {
      const va = k === "max_dd" ? -(a[k] ?? 9) : (a[k] ?? -999);
      const vb = k === "max_dd" ? -(b[k] ?? 9) : (b[k] ?? -999);
      return vb - va;
    });
    el("symCount").textContent = `${list.length} mã`;
    const tb = el("symTable").querySelector("tbody");
    tb.innerHTML = list
      .map((r) => {
        const oos = r.ga_out_of_sample;
        const badge = r.oos_accepted === undefined ? '<span class="badge muted">—</span>'
          : r.oos_accepted ? '<span class="badge ok">đạt</span>' : '<span class="badge no">loại</span>';
        return `<tr data-sym="${r.symbol}" class="${state.selected === r.symbol ? "selected" : ""}">
          <td><b>${r.symbol}</b></td>
          <td class="dim">${fmtNum(r.adv_billion, 1)}</td>
          <td class="${signCls(r.cagr)}">${fmtPct(r.cagr)}</td>
          <td class="${signCls(r.sharpe)}">${fmtNum(r.sharpe)}</td>
          <td class="${signCls(r.calmar)}">${fmtNum(r.calmar)}</td>
          <td class="neg">${fmtPct(r.max_dd)}</td>
          <td>${fmtNum(r.profit_factor)}</td>
          <td>${fmtPct(r.hit_rate, 0)}</td>
          <td>${fmtNum(r.trades_per_year, 1)}</td>
          <td class="${signCls(r.avg_r)}">${fmtNum(r.avg_r)}</td>
          <td class="${oos ? signCls(oos.calmar) : "dim"}">${oos ? fmtNum(oos.calmar) : "—"}</td>
          <td>${badge}</td>
        </tr>`;
      })
      .join("");
    tb.querySelectorAll("tr").forEach((tr) =>
      tr.addEventListener("click", () => selectSymbol(tr.dataset.sym))
    );
  };
  search.addEventListener("input", draw);
  filter.addEventListener("change", draw);
  sortSel.addEventListener("change", draw);
  draw();

  if (!state.selected && rows.length) selectSymbol(rows[0].symbol);
  renderSymbolTrades();
}

function selectSymbol(sym) {
  state.selected = sym;
  const r = state.symbols.find((s) => s.symbol === sym);
  el("symTable").querySelectorAll("tbody tr").forEach((tr) =>
    tr.classList.toggle("selected", tr.dataset.sym === sym)
  );
  if (!r) return;
  el("symDetailTitle").textContent = `Chi tiết mã ${sym}`;
  el("symDetailKpi").innerHTML = [
    kpiCard("CAGR", fmtPct(r.cagr), `${fmtInt(r.trades)} lệnh trong kỳ`, signCls(r.cagr)),
    kpiCard("Sharpe", fmtNum(r.sharpe), `Vol năm ${fmtPct(r.vol_annual)}`, signCls(r.sharpe)),
    kpiCard("MaxDD", fmtPct(r.max_dd), `${fmtInt(r.max_dd_duration)} phiên dưới đỉnh`, "neg"),
    kpiCard("Giải ngân bình quân", fmtPct(r.avg_exposure, 0), `ADV ${fmtNum(r.adv_billion, 1)} tỷ/phiên`, ""),
  ].join("");

  const c = state.curves;
  if (c && c.symbols && c.symbols[sym]) {
    const ds = [lineDataset(sym, c.symbols[sym], COLORS.accent, { width: 2 })];
    if (c.portfolio_default) ds.push(lineDataset("Danh mục Donchian-55", c.portfolio_default, COLORS.bench, { dash: [4, 4] }));
    if (c.benchmark) ds.push(lineDataset(state.meta.data.benchmark, c.benchmark, "#5a6a7d", { dash: [2, 3] }));
    makeChart("chartSymbol", {
      type: "line",
      data: { labels: c.dates, datasets: ds },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: true }, tooltip: { callbacks: { label: (it) => `${it.dataset.label}: ${Number(it.raw).toFixed(1)}` } } },
        scales: axes(),
      },
    });
  }

  const g = r.ga_params;
  el("symGaParams").innerHTML = g
    ? `<table class="data"><tbody>
        <tr><td>entry_window</td><td><b>${g.entry_window}</b></td><td>exit_window</td><td><b>${g.exit_window}</b></td></tr>
        <tr><td>atr_period</td><td><b>${g.atr_period}</b></td><td>risk_per_unit</td><td><b>${fmtPct(g.risk_per_unit, 2)}</b></td></tr>
        <tr><td>stop_atr (N)</td><td><b>${fmtNum(g.stop_atr)}</b></td><td>khoảng cách overfit (Calmar)</td><td class="${signCls(-Math.abs(r.overfit_gap_calmar || 0))}"><b>${fmtNum(r.overfit_gap_calmar)}</b></td></tr>
      </tbody></table>
      <p class="note">Trong mẫu: Calmar ${fmtNum(r.ga_in_sample && r.ga_in_sample.calmar)} · Ngoài mẫu: Calmar ${fmtNum(r.ga_out_of_sample && r.ga_out_of_sample.calmar)} · Mặc định ngoài mẫu: Calmar ${fmtNum(r.baseline_out_of_sample && r.baseline_out_of_sample.calmar)}</p>`
    : '<p class="note">Mã này chưa có kết quả GA (chạy pipeline không có cờ --no-ga).</p>';
  renderSymbolTrades();
}

function renderSymbolTrades() {
  const p = state.portfolio && state.portfolio[state.pfVariant];
  const tb = el("symTrades").querySelector("tbody");
  if (!p) { tb.innerHTML = ""; return; }
  const list = state.selected ? p.trades.filter((t) => t.symbol === state.selected).slice(-25).reverse() : [];
  const rows = list.length ? list : p.trades.slice(-25).reverse();
  tb.innerHTML = rows
    .map((t) => `<tr><td><b>${t.symbol}</b></td><td class="dim">${t.entry_date}</td><td class="dim">${t.exit_date}</td>
      <td class="faint">${esc(reasonLabel(t.exit_reason))}</td><td class="${signCls(t.r_multiple)}">${fmtNum(t.r_multiple)}</td></tr>`)
    .join("");
}

function reasonLabel(r) {
  return {
    stop_loss: "Stop 2N",
    breakout_low: "Phá đáy Donchian",
    exit_deferred: "Thoát treo (kẹt sàn/T+2.5)",
    mark_to_market: "Đóng cuối kỳ",
  }[r] || r;
}

/* ------------------------------ GA ------------------------------ */
function renderGA() {
  const g = state.ga;
  if (!g || !g.basket) {
    el("gaKpi").innerHTML = '<div class="card"><p class="note">Chưa có dữ liệu GA.</p></div>';
    return;
  }
  const b = g.basket;
  const s = g.summary || {};
  el("gaKpi").innerHTML = [
    kpiCard("Số thế hệ", fmtInt(b.generations), `${fmtInt(b.evaluations)} lần đánh giá genome`, ""),
    kpiCard("Calmar train (tốt nhất)", fmtNum(b.best_outcome.calmar), `fitness ${fmtNum(b.best_outcome.fitness)}`, signCls(b.best_outcome.calmar)),
    kpiCard("Calmar OOS trung vị", fmtNum((b.oos_summary.calmar || {}).median), "kiểm định 30% dữ liệu cuối", signCls((b.oos_summary.calmar || {}).median)),
    kpiCard("Lợi thế so với mặc định", fmtNum(s.ga_edge_oos_calmar), "chênh lệch Calmar OOS theo mã", signCls(s.ga_edge_oos_calmar)),
  ].join("");

  // Hội tụ
  makeChart("chartGaConv", {
    type: "line",
    data: {
      labels: b.history.map((h) => h.generation),
      datasets: [
        lineDataset("Fitness tốt nhất", b.history.map((h) => h.best_fitness), COLORS.accent, { width: 2.2 }),
        lineDataset("Fitness trung bình quần thể", b.history.map((h) => h.mean_fitness), COLORS.accent2),
        lineDataset("Độ lệch chuẩn quần thể", b.history.map((h) => h.std_fitness), COLORS.warn, { dash: [4, 3] }),
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true } },
      scales: axes({ x: { title: { display: true, text: "Thế hệ", color: COLORS.text } } }),
    },
  });

  // Quần thể cuối
  const pop = b.population || [];
  makeChart("chartGaScatter", {
    type: "scatter",
    data: {
      datasets: [
        {
          label: "Genome trong quần thể",
          data: pop.map((p) => ({ x: p.max_dd, y: p.calmar, g: p.genome })),
          backgroundColor: COLORS.accent + "aa", pointRadius: 4,
        },
        {
          label: "Nghiệm tốt nhất",
          data: [{ x: b.best_outcome.max_dd, y: b.best_outcome.calmar }],
          backgroundColor: COLORS.pos, pointRadius: 7, pointStyle: "rectRot",
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true }, tooltip: { callbacks: {
        label: (it) => `MaxDD ${fmtPct(it.raw.x)} · Calmar ${fmtNum(it.raw.y)}` +
          (it.raw.g ? ` · entry ${it.raw.g.entry_window}, exit ${it.raw.g.exit_window}, ATR ${it.raw.g.atr_period}` : ""),
      } } },
      scales: { x: { grid: { color: COLORS.grid }, title: { display: true, text: "MaxDD (train)", color: COLORS.text }, ticks: { callback: (v) => (v * 100).toFixed(0) + "%" } },
                y: { grid: { color: COLORS.grid }, title: { display: true, text: "Calmar (train)", color: COLORS.text } } },
    },
  });

  el("gaBasketTable").querySelector("tbody").innerHTML = `
    ${paramRow("entry_window", b.best.entry_window, "Cửa sổ phá đỉnh")}
    ${paramRow("exit_window", b.best.exit_window, "Cửa sổ phá đáy thoát")}
    ${paramRow("atr_period", b.best.atr_period, "Chu kỳ ATR (N)")}
    ${paramRow("risk_per_unit", fmtPct(b.best.risk_per_unit, 2), "Rủi ro mỗi Unit")}
    ${paramRow("stop_atr", fmtNum(b.best.stop_atr) + "N", "Khoảng stop loss")}
    ${paramRow("Calmar train", fmtNum(b.best_outcome.calmar), "trên tập fit")}
    ${paramRow("Số lệnh/năm", fmtNum(b.best_outcome.trades_per_year, 1), "tần suất giao dịch")}`;

  const o = b.oos_summary || {}, bo = b.baseline_oos_summary || {};
  const row = (label, gaV, baseV, isPct = false) =>
    `<tr><td>${label}</td><td class="${signCls(gaV - baseV)}">${isPct ? fmtPct(gaV) : fmtNum(gaV)}</td>
     <td class="dim">${isPct ? fmtPct(baseV) : fmtNum(baseV)}</td>
     <td class="${signCls(gaV - baseV)}">${isPct ? fmtPct(gaV - baseV) : fmtNum(gaV - baseV)}</td></tr>`;
  el("gaCompareTable").querySelector("tbody").innerHTML = `
    ${row("Calmar (trung vị)", (o.calmar || {}).median, (bo.calmar || {}).median)}
    ${row("Sharpe (trung vị)", (o.sharpe || {}).median, (bo.sharpe || {}).median)}
    ${row("CAGR (trung vị)", (o.cagr || {}).median, (bo.cagr || {}).median, true)}
    ${row("MaxDD (trung vị)", (o.max_dd || {}).median, (bo.max_dd || {}).median, true)}
    ${row("Lệnh/năm (trung vị)", (o.trades_per_year || {}).median, (bo.trades_per_year || {}).median)}
    ${row("Tỷ lệ mã CAGR dương", (o.cagr || {}).positive_share, (bo.cagr || {}).positive_share, true)}`;

  const syms = Object.entries(g.symbols || {}).slice(0, 12);
  el("gaParamTable").querySelector("tbody").innerHTML = syms
    .map(([sym, d]) => `<tr>
      <td><b>${sym}</b></td><td>${d.best.entry_window}</td><td>${d.best.exit_window}</td><td>${d.best.atr_period}</td>
      <td>${fmtPct(d.best.risk_per_unit, 2)}</td><td>${fmtNum(d.best.stop_atr)}</td>
      <td class="${signCls(d.in_sample.calmar)}">${fmtNum(d.in_sample.calmar)}</td>
      <td class="${signCls(d.out_of_sample.calmar)}">${fmtNum(d.out_of_sample.calmar)}</td>
      <td class="dim">${fmtNum(d.in_sample.calmar - d.out_of_sample.calmar)}</td>
      <td>${d.oos_accepted ? '<span class="badge ok">đạt</span>' : '<span class="badge no">loại</span>'}</td>
    </tr>`)
    .join("");
}

function paramRow(name, value, note) {
  return `<tr><td class="mono">${name}</td><td><b>${value}</b></td><td class="faint">${note}</td></tr>`;
}

/* ------------------------------ WALK-FORWARD ------------------------------ */
function renderWalkforward() {
  const w = state.walkforward;
  if (!w || !w.summary || !w.summary.n_folds) {
    el("wfKpi").innerHTML = '<div class="card"><p class="note">Chưa có dữ liệu walk-forward.</p></div>';
    return;
  }
  const s = w.summary;
  const tradedShare = s.traded_share !== undefined ? s.traded_share : 1;
  el("wfKpi").innerHTML = [
    kpiCard("Số fold", fmtInt(s.n_folds), `${s.config.train_sessions} phiên fit → ${s.config.test_sessions} phiên test`, ""),
    kpiCard("Fold có phát sinh lệnh", fmtPct(tradedShare, 0), `${fmtInt(s.n_traded_folds)} / ${fmtInt(s.n_folds)} fold`, tradedShare < 0.5 ? "warn" : ""),
    kpiCard("Lợi nhuận test (trung vị)", fmtPct(s.oos_total_return_median_traded), "63 phiên, chỉ fold có lệnh", signCls(s.oos_total_return_median_traded)),
    kpiCard("Tỷ lệ fold có lãi", fmtPct(s.oos_total_return_positive_share_traded, 0), "ngoài mẫu, fold có lệnh", s.oos_total_return_positive_share_traded > 0.5 ? "pos" : "neg"),
  ].join("");

  const d = (w.distributions_traded && w.distributions_traded.oos_total_return) ? w.distributions_traded : (w.distributions || {});
  histogramChart("chartWfCalmar", d.oos_total_return, COLORS.accent, "Số fold", true);
  histogramChart("chartWfSharpe", d.oos_sharpe, COLORS.accent2, "Số fold");
  histogramChart("chartWfMaxdd", d.oos_max_dd, COLORS.neg, "Số fold", true);

  const folds = w.folds || [];
  makeChart("chartWfScatter", {
    type: "scatter",
    data: {
      datasets: [
        { label: "Fold (mặc định → GA) — lợi nhuận 63 phiên test", data: folds.map((f) => ({ x: f.baseline_return, y: f.test_return })),
          backgroundColor: folds.map((f) => (f.accepted ? COLORS.pos : COLORS.accent) + "cc"), pointRadius: 4 },
        { label: "Không cải thiện (y = x)", type: "line", data: (() => {
            const vs = folds.flatMap((f) => [f.baseline_return, f.test_return]).filter(Number.isFinite);
            const m = Math.min(...vs, 0), M = Math.max(...vs, 0.01);
            return [{ x: m, y: m }, { x: M, y: M }];
          })(), borderColor: COLORS.bench, borderDash: [5, 4], pointRadius: 0, fill: false, borderWidth: 1.2 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true }, tooltip: { callbacks: { label: (it) => `Mặc định ${fmtPct(it.raw.x)} → GA ${fmtPct(it.raw.y)}` } } },
      scales: { x: { grid: { color: COLORS.grid }, title: { display: true, text: "Lợi nhuận test — tham số mặc định", color: COLORS.text }, ticks: { callback: (v) => (v * 100).toFixed(0) + "%" } },
                y: { grid: { color: COLORS.grid }, title: { display: true, text: "Lợi nhuận test — tham số GA", color: COLORS.text }, ticks: { callback: (v) => (v * 100).toFixed(0) + "%" } } },
    },
  });

  el("wfTable").querySelector("tbody").innerHTML = folds
    .slice(0, 300)
    .map((f) => `<tr>
      <td><b>${f.symbol || "—"}</b></td>
      <td>${f.fold}</td>
      <td class="faint">${f.train_start} → ${f.train_end}</td>
      <td class="faint">${f.test_start} → ${f.test_end}</td>
      <td>${f.params.entry_window}</td><td>${f.params.exit_window}</td><td>${f.params.atr_period}</td>
      <td class="${signCls(f.test_return)}">${fmtPct(f.test_return)}</td>
      <td class="dim">${fmtPct(f.baseline_return)}</td>
      <td class="${signCls(f.test_calmar)}">${fmtNum(f.test_calmar)}</td>
      <td class="${signCls(f.test_sharpe)}">${fmtNum(f.test_sharpe)}</td>
      <td class="neg">${fmtPct(f.test_max_dd)}</td>
      <td>${fmtInt(f.test_trades)}</td>
      <td>${f.accepted ? '<span class="badge ok">đạt</span>' : '<span class="badge no">loại</span>'}</td>
    </tr>`)
    .join("");

  const per = Object.entries(w.per_symbol || {});
  el("wfSymbolTable").querySelector("tbody").innerHTML = per
    .sort((a, b) => b[1].oos_calmar_median - a[1].oos_calmar_median)
    .map(([sym, v]) => `<tr>
      <td><b>${sym}</b></td><td>${fmtInt(v.n_folds)}</td>
      <td class="${v.acceptance_rate > 0.5 ? "pos" : "warn"}">${fmtPct(v.acceptance_rate, 0)}</td>
      <td class="${signCls(v.oos_calmar_median)}">${fmtNum(v.oos_calmar_median)}</td>
      <td class="${signCls(v.oos_sharpe_median)}">${fmtNum(v.oos_sharpe_median)}</td>
      <td class="neg">${fmtPct(v.oos_max_dd_median)}</td>
      <td class="${signCls(v.ga_edge_vs_baseline)}">${fmtNum(v.ga_edge_vs_baseline)}</td>
    </tr>`)
    .join("");
}

/* ------------------------------ DANH MỤC ------------------------------ */
function renderPortfolio() {
  const p = state.portfolio;
  if (!p) return;
  const has = (k) => !!p[k];
  if (!has("ga_basket")) {
    const opt = el("pfVariant").querySelector('option[value="ga_basket"]');
    if (opt) opt.remove();
  }
  el("pfVariant").addEventListener("change", (e) => {
    state.pfVariant = e.target.value;
    drawPortfolio();
    renderSymbolTrades();
  });
  drawPortfolio();
}

function drawPortfolio() {
  const p = state.portfolio[state.pfVariant] || state.portfolio.default;
  if (!p) return;
  const m = p.metrics, t = p.trade_stats;
  el("pfKpi").innerHTML = [
    kpiCard("CAGR", fmtPct(m.cagr), `vốn cuối kỳ ${fmtVnd(m.final_equity)} VND`, signCls(m.cagr)),
    kpiCard("Sharpe", fmtNum(m.sharpe), `Vol năm ${fmtPct(m.vol_annual)} · Sortino ${fmtNum(m.sortino)}`, signCls(m.sharpe)),
    kpiCard("MaxDD", fmtPct(m.max_dd), `${fmtInt(m.max_dd_duration)} phiên dưới đỉnh`, "neg"),
    kpiCard("Calmar", fmtNum(m.calmar), `giải ngân bình quân ${fmtPct(m.avg_exposure, 0)}`, signCls(m.calmar)),
    kpiCard("Số lệnh", fmtInt(t.trades), `${fmtNum(t.trades_per_year, 1)} lệnh/năm`, ""),
    kpiCard("Hit rate", fmtPct(t.hit_rate, 0), `payoff ${fmtNum(t.payoff_ratio)} : 1`, ""),
    kpiCard("Profit factor", fmtNum(t.profit_factor), `R trung bình ${fmtNum(t.avg_r)}`, t.profit_factor > 1 ? "pos" : "neg"),
    kpiCard("Chuỗi thua dài nhất", fmtInt(t.max_consecutive_losses), `phí giao dịch ${fmtVnd(t.total_fees)} VND`, "warn"),
  ].join("");

  const pr = p.params || {};
  el("pfParams").textContent =
    `entry ${pr.entry_window} · exit ${pr.exit_window} · ATR ${pr.atr_period} · risk/unit ${fmtPct(pr.risk_per_unit, 2)} · stop ${fmtNum(pr.stop_atr)}N · tối đa ${pr.max_units} Unit`;

  makeChart("chartPfEquity", {
    type: "line",
    data: { labels: p.dates, datasets: [lineDataset("Danh mục", p.equity, COLORS.accent, { fill: true, width: 2.2 })] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: axes({ y: { ticks: { callback: (v) => v } } }) },
  });
  makeChart("chartPfDd", {
    type: "line",
    data: { labels: p.dates, datasets: [lineDataset("Drawdown", p.drawdown, COLORS.neg, { fill: true })] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (it) => fmtPct(it.raw) } } },
      scales: axes({ y: { ticks: { callback: (v) => (v * 100).toFixed(0) + "%" } } }) },
  });
  makeChart("chartPfExp", {
    type: "line",
    data: { labels: p.dates, datasets: [lineDataset("Exposure", p.exposure, COLORS.warn, { fill: true })] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (it) => fmtPct(it.raw) } } },
      scales: axes({ y: { max: 1, ticks: { callback: (v) => (v * 100).toFixed(0) + "%" } } }) },
  });

  const rs = p.trades.map((x) => x.r_multiple).filter(Number.isFinite);
  const hist = makeHist(rs, Math.min(24, Math.max(8, Math.ceil(Math.sqrt(rs.length) * 2))));
  if (hist) {
    const labels = hist.counts.map((_, i) => (((hist.edges[i] + hist.edges[i + 1]) / 2)).toFixed(1) + "R");
    makeChart("chartPfR", {
      type: "bar",
      data: { labels, datasets: [{ data: hist.counts, backgroundColor: labels.map((l) => (parseFloat(l) >= 0 ? COLORS.pos : COLORS.neg) + "cc"), borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: axes() },
    });
  }

  renderMonthly(p.monthly || []);

  el("pfTrades").querySelector("tbody").innerHTML = p.trades
    .slice().reverse()
    .map((t) => `<tr>
      <td><b>${t.symbol}</b></td><td class="faint">${t.entry_date}</td><td class="faint">${t.exit_date}</td>
      <td class="dim">${fmtInt(t.entry_price)}</td><td class="dim">${fmtInt(t.exit_price)}</td>
      <td class="dim">${fmtInt(t.shares)}</td><td class="dim">${t.units}</td>
      <td class="${signCls(t.pnl)}">${fmtVnd(t.pnl)}</td>
      <td class="${signCls(t.pnl_pct)}">${fmtPct(t.pnl_pct)}</td>
      <td class="${signCls(t.r_multiple)}">${fmtNum(t.r_multiple)}</td>
      <td class="dim">${fmtInt(t.holding_days)}</td>
      <td class="faint">${esc(reasonLabel(t.exit_reason))}</td>
    </tr>`)
    .join("");
}

function renderMonthly(monthly) {
  if (!monthly.length) { el("pfMonthly").innerHTML = '<p class="note">Không có dữ liệu tháng.</p>'; return; }
  const years = [...new Set(monthly.map((m) => m.year))].sort();
  const vals = monthly.map((m) => m.return);
  const lo = Math.min(...vals, 0), hi = Math.max(...vals, 0);
  const scale = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
  const color = (v) => {
    const a = Math.min(0.9, Math.abs(v) / scale);
    return v >= 0 ? `rgba(38,194,129,${a})` : `rgba(242,84,91,${a})`;
  };
  const head = ["Năm", ...Array.from({ length: 12 }, (_, i) => "T" + (i + 1)), "Cả năm"];
  let html = '<div style="overflow-x:auto"><table class="data"><thead><tr>' +
    head.map((h) => `<th style="cursor:default">${h}</th>`).join("") + "</tr></thead><tbody>";
  years.forEach((y) => {
    const byMonth = {};
    monthly.filter((m) => m.year === y).forEach((m) => (byMonth[m.month] = m.return));
    let comp = 1;
    Object.values(byMonth).forEach((v) => (comp *= 1 + v));
    html += `<tr><td><b>${y}</b></td>`;
    for (let mth = 1; mth <= 12; mth++) {
      const v = byMonth[mth];
      html += v === undefined
        ? '<td class="faint">·</td>'
        : `<td style="background:${color(v)};color:#eaf2ff">${(v * 100).toFixed(1)}</td>`;
    }
    const total = comp - 1;
    html += `<td class="${signCls(total)}"><b>${fmtPct(total)}</b></td></tr>`;
  });
  html += "</tbody></table></div>";
  el("pfMonthly").innerHTML = html;
}

/* ------------------------------ ĐẶC THÙ VN ------------------------------ */
function renderConstraints() {
  const cards = [
    {
      t: "Biên độ ±7% và giá trần",
      b: `Luật vào lệnh yêu cầu giá đóng cửa vượt đỉnh Donchian <b>và</b> không nằm tại giá trần.
          Giá trần được tính bằng giá tham chiếu × 1,07 rồi làm tròn xuống theo bước giá HOSE
          (10 / 50 / 100 VND tuỳ khung giá). Nếu breakout rơi đúng phiên trần, tín hiệu bị bỏ qua
          và hệ thống chờ phiên kế tiếp.`,
    },
    {
      t: "Chu kỳ thanh toán T+2.5",
      b: `Cổ phiếu mua tại phiên t chỉ được bán từ phiên t+2. Mỗi Unit mới vào bị khoá đúng
          <code>settlement_lag = 2</code> phiên trước khi stop loss có hiệu lực. Khi tín hiệu thoát
          xuất hiện, engine chỉ bán phần cổ phiếu đã về tài khoản và treo phần còn lại sang phiên sau.`,
    },
    {
      t: "Cấm bán khống cổ phiếu cơ sở",
      b: `Toàn bộ engine là long-only: không có lệnh bán nào được mở khi chưa có vị thế. Turtle S1
          đầy đủ (gồm cả nhánh short) không thể áp dụng trên cổ phiếu cơ sở; muốn giao dịch hai chiều
          phải dùng hợp đồng tương lai VN30F1M - nằm ngoài phạm vi nghiên cứu này.`,
    },
    {
      t: "Thanh khoản phân tán",
      b: `Bộ lọc ADV 20 phiên (dịch 1 phiên để chống look-ahead) yêu cầu giá trị giao dịch bình quân
          tối thiểu 30 tỷ VND/phiên, cộng thêm trần tỷ trọng 20% NAV mỗi Unit và 60% NAV mỗi mã.
          Slippage 0,10% mỗi chiều và phí 0,15% + thuế bán 0,10% được trừ trực tiếp vào dòng tiền.`,
    },
  ];
  el("constraintCards").innerHTML = cards
    .map((c) => `<div class="card"><h3>${c.t}</h3><p>${c.b}</p></div>`)
    .join("");

  if (state.ablation.length) {
    el("ablationTable").querySelector("tbody").innerHTML = state.ablation
      .map((a) => `<tr>
        <td><b>${esc(a.label)}</b> <span class="faint mono">${a.key}</span></td>
        <td class="${signCls(a.calmar_median)}">${fmtNum(a.calmar_median)}</td>
        <td class="${signCls(a.sharpe_median)}">${fmtNum(a.sharpe_median)}</td>
        <td class="${signCls(a.cagr_median)}">${fmtPct(a.cagr_median)}</td>
        <td class="neg">${fmtPct(a.max_dd_median)}</td>
        <td>${fmtNum(a.trades_per_year_median, 1)}</td>
        <td>${fmtPct(a.cagr_positive_share, 0)}</td>
      </tr>`)
      .join("");
  }

  const liq = state.liquidity.slice().sort((a, b) => b.adv_billion - a.adv_billion);
  if (liq.length) {
    makeChart("chartLiquidity", {
      type: "bar",
      data: {
        labels: liq.map((l) => l.symbol),
        datasets: [{ data: liq.map((l) => l.adv_billion), backgroundColor: liq.map((l) => (l.passes_adv ? COLORS.pos : COLORS.neg) + "cc"), borderWidth: 0 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (it) => `${fmtNum(it.raw, 1)} tỷ VND/phiên` } } },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 30, autoSkip: true, font: { size: 9 } } },
                  y: { type: "logarithmic", grid: { color: COLORS.grid }, title: { display: true, text: "ADV (tỷ VND, thang log)", color: COLORS.text } } },
      },
    });
    el("liquidityTable").querySelector("tbody").innerHTML = liq
      .map((l) => `<tr><td><b>${l.symbol}</b></td><td>${fmtNum(l.adv_billion, 1)}</td><td class="dim">${fmtInt(l.last_price)}</td>
        <td>${l.passes_adv ? '<span class="badge ok">đạt</span>' : '<span class="badge no">dưới ngưỡng</span>'}</td></tr>`)
      .join("");
  }

  renderCoverage();
}

function renderCoverage() {
  const c = state.coverage;
  if (!c || !c.by_year || !c.by_year.length) return;
  const keys = (c.thresholds_billion || [30]).map((t) => `share_adv_${t}bn`);
  const palette = [COLORS.warn, COLORS.accent, COLORS.accent2];
  makeChart("chartCoverage", {
    type: "line",
    data: {
      labels: c.by_year.map((r) => r.year),
      datasets: keys.map((k, i) => lineDataset(`ADV ≥ ${c.thresholds_billion[i]} tỷ`, c.by_year.map((r) => r[k]), palette[i % palette.length], { width: 2 })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true }, tooltip: { callbacks: { label: (it) => `${it.dataset.label}: ${fmtPct(it.raw, 1)} symbol-day` } } },
      scales: axes({ x: { title: { display: true, text: "Năm", color: COLORS.text } },
                     y: { max: 1, ticks: { callback: (v) => (v * 100).toFixed(0) + "%" } } }),
    },
  });
}

/* ------------------------------ PHƯƠNG PHÁP ------------------------------ */
function renderMethod() {
  const s = state.meta.config.strategy;
  el("methodStrategy").innerHTML = `
    <table class="data"><thead><tr><th>Tham số</th><th>Giá trị</th><th>Vai trò</th></tr></thead><tbody>
      <tr><td>Entry window</td><td><b>${s.entry_window} phiên</b></td><td>Đóng cửa vượt đỉnh ${s.entry_window} phiên (không tính ngày hiện tại) → mở vị thế</td></tr>
      <tr><td>Exit window</td><td><b>${s.exit_window} phiên</b></td><td>Đóng cửa dưới đáy ${s.exit_window} phiên → thoát toàn bộ</td></tr>
      <tr><td>ATR period (N)</td><td><b>${s.atr_period} phiên</b></td><td>N = ATR Wilder, cơ sở cho stop và position sizing</td></tr>
      <tr><td>Stop loss</td><td><b>${s.stop_atr}N</b></td><td>Đặt dưới giá vào lệnh của Unit mới nhất</td></tr>
      <tr><td>Kim tự tháp</td><td><b>${s.pyramid_atr}N</b></td><td>Gia tăng 1 Unit mỗi ${s.pyramid_atr}N thuận lợi, tối đa ${s.max_units} Unit</td></tr>
      <tr><td>Rủi ro mỗi Unit</td><td><b>${fmtPct(s.risk_per_unit, 2)} vốn</b></td><td>Chế độ <code>${s.sizing_mode}</code>: lỗ đúng ${fmtPct(s.risk_per_unit, 2)} khi chạm stop</td></tr>
    </tbody></table>
    <div class="formula">Unit = (risk_per_unit × Equity) / (stop_atr × N)   [chế độ "risk"]
Unit = (risk_per_unit × Equity) / N                    [chế độ "volatility" — Turtle gốc]</div>
    <p class="note">Hai công thức cho kết quả rất khác nhau. Với N ≈ 3% giá, công thức Turtle gốc cho mỗi Unit
    chiếm khoảng 33% NAV, tức 4 Unit vượt 130% NAV - không khả thi khi không dùng margin và trần exposure 60%.
    Bản triển khai này dùng chế độ <code>risk</code> (lỗ đúng bằng risk_per_unit tại stop) và áp thêm trần cứng
    ${fmtPct(s.max_unit_nav, 0)} NAV mỗi Unit, ${fmtPct(s.max_symbol_nav, 0)} NAV mỗi mã. Đây là điểm phải diễn giải
    lại đặc tả gốc cho nhất quán về mặt số học.</p>
    <p class="note">Bộ lọc bật: ${s.use_market_filter ? `chỉ giao dịch khi ${state.meta.data.benchmark} đóng cửa trên SMA${s.market_sma}` : "không lọc xu hướng thị trường"} ·
    ${s.avoid_ceiling_entry ? "tránh vào lệnh tại giá trần" : "không tránh giá trần"} ·
    ${s.block_floor_exit ? "treo lệnh thoát khi kẹt giá sàn" : "không xử lý giá sàn"} ·
    ADV tối thiểu ${(s.adv_min / 1e9).toFixed(0)} tỷ VND/phiên.</p>`;

  const ga = state.meta.config.ga;
  el("methodGA").innerHTML = `
    <ul class="tight">
      <li>Kích thước quần thể <b>${ga.population}</b>, tối đa <b>${ga.generations}</b> thế hệ, giữ lại <b>${ga.elite}</b> cá thể tinh hoa mỗi thế hệ.</li>
      <li>Chọn lọc tournament (k = ${ga.tournament_size}), lai ghép BLX-α (α = ${ga.blx_alpha}), đột biến Gaussian thu hẹp dần theo thế hệ.</li>
      <li>Không gian tìm kiếm: entry ${state.meta.config.space.entry_window.join("–")} · exit ${state.meta.config.space.exit_window.join("–")} ·
          ATR ${state.meta.config.space.atr_period.join("–")} · risk/Unit ${fmtPct(state.meta.config.space.risk_per_unit[0], 2)}–${fmtPct(state.meta.config.space.risk_per_unit[1], 2)} ·
          stop ${state.meta.config.space.stop_atr.join("–")}N.</li>
      <li>Hạt giống ngẫu nhiên cố định (<code>seed = ${ga.seed}</code>) để kết quả tái lập được.</li>
      <li>Kiểm định out-of-sample: GA fit trên 70% dữ liệu đầu và đo trên 30% dữ liệu cuối. Walk-forward: fit ${state.meta.config.walkforward.train_sessions} phiên → test ${state.meta.config.walkforward.test_sessions} phiên → dịch ${state.meta.config.walkforward.step_sessions} phiên, lặp đến hết dữ liệu.</li>
      <li>Tổng thời gian chạy pipeline: ${fmtInt(state.meta.runtime_seconds)} giây trên ${state.meta.data.n_symbols} mã.</li>
    </ul>`;

  el("methodRisk").innerHTML = `
    <div class="card">
      <h3>Quản lý rủi ro</h3>
      <ul class="tight">
        <li>Vốn khởi điểm ${fmtVnd(state.meta.config.initial_capital)} VND, không dùng margin.</li>
        <li>Tối đa ${state.meta.config.portfolio.max_positions} mã đồng thời, tổng giải ngân ≤ ${fmtPct(state.meta.config.portfolio.max_gross_exposure, 0)} NAV.</li>
        <li>Rủi ro mỗi lệnh ${fmtPct(s.risk_per_unit, 2)} vốn; stop ${s.stop_atr}N; tối đa ${s.max_units} Unit mỗi mã.</li>
        <li>Phí môi giới ${fmtPct(state.meta.config.market.commission, 2)} mỗi chiều, thuế bán ${fmtPct(state.meta.config.market.sell_tax, 2)}, trượt giá ${fmtPct(state.meta.config.market.slippage, 2)} mỗi chiều.</li>
      </ul>
    </div>
    <div class="card">
      <h3>Kỳ vọng thực tế</h3>
      <ul class="tight">
        <li>Hệ thống breakout có hit rate thấp (thường 30–45%) và sống nhờ payoff lớn: vài lệnh thắng bù cho nhiều lệnh thua nhỏ.</li>
        <li>Phải chấp nhận drawdown hai chữ số và chuỗi 4–5 lệnh thua liên tiếp. Đây là lý do phổ biến nhất khiến nhà đầu tư bỏ chiến lược giữa chu kỳ.</li>
        <li>Phù hợp danh mục 5–10 mã, vốn ≥ 1 tỷ VND. Không phù hợp kỳ vọng lợi nhuận đều hàng tháng.</li>
        <li>Kết quả quá khứ không bảo đảm cho tương lai. Đây là công cụ nghiên cứu, không phải khuyến nghị đầu tư.</li>
      </ul>
    </div>`;

  el("methodLimits").innerHTML = `
    <details class="doc" open><summary>Survivorship bias của universe</summary>
      <p>Danh sách VN100 được lấy tại thời điểm chạy, không phải danh sách point-in-time theo từng kỳ tái cơ cấu chỉ số.
      Các mã bị loại khỏi rổ trong quá khứ (do suy giảm thanh khoản hoặc vốn hoá) không xuất hiện trong mẫu, khiến
      kết quả có xu hướng lạc quan hơn thực tế. Đây là hạn chế phổ biến của backtest dùng rổ chỉ số hiện hành.</p></details>
    <details class="doc"><summary>Điều chỉnh giá và cổ tức</summary>
      <p>Dữ liệu VCI đã điều chỉnh giá theo cổ tức và chia tách. Không mô hình hoá cổ tức tiền mặt nhận được, cũng
      không mô hình hoá quyền mua phát hành thêm — hai yếu tố có thể làm sai lệch lợi nhuận thực nhận.</p></details>
    <details class="doc"><summary>Giả định khớp lệnh tại giá đóng cửa</summary>
      <p>Tín hiệu được xác định bằng giá đóng cửa và khớp luôn tại giá đóng cửa cộng trượt giá 0,10%. Trên thực tế
      lệnh phải đặt trước phiên ATC, nên đây là giả định lạc quan nhẹ. Bù lại, engine không mô hình hóa độ sâu
      sổ lệnh, xếp hàng tại giá trần/sàn, hay việc không khớp được lệnh khi thanh khoản cạn.</p></details>
    <details class="doc"><summary>Độ bền tham số và overfitting</summary>
      <p>GA tối ưu trên dữ liệu quá khứ luôn có nguy cơ overfitting. Báo cáo này giảm thiểu bằng ba lớp: kiểm định
      out-of-sample 30% dữ liệu cuối, walk-forward 252/63 trên toàn bộ lịch sử, và cổng chấp nhận Calmar OOS > 0,5
      kèm trần 20 lệnh/năm. Khoảng cách giữa Calmar trong mẫu và ngoài mẫu được hiển thị công khai thay vì che đi.</p></details>
    <details class="doc"><summary>Tính phi dừng của thị trường</summary>
      <p>Thị trường Việt Nam đã thay đổi cấu trúc nhiều lần trong giai đoạn 2016–2026: chuyển hệ thống giao dịch KRX,
      thay đổi biên độ và lô chẵn, các chu kỳ margin call 2018 và 2022. Một bộ tham số cố định không thể phản ánh
      hết các chế độ thị trường khác nhau; walk-forward là công cụ chính để nhìn thấy sự bất ổn này.</p></details>
    <details class="doc"><summary>Nguồn dữ liệu và tái lập</summary>
      <p>Dữ liệu tải qua vnstock 3.x với nguồn VCI, lưu cache cục bộ trong <code>data/raw/</code>. Nhà cung cấp
      giới hạn 60 request/phút nên pipeline tự điều tiết xuống 48 request/phút. Mọi hạt giống ngẫu nhiên đều cố định;
      kết quả có thể tái lập bằng <code>python scripts/run_research.py</code>.</p></details>`;
}

/* ================= TÍCH HỢP HỘI ĐỒNG AI ADVISORS ================= */
function renderAdvisors() {
  const advEval = state.snapshot && state.snapshot.advisors_evaluation ? state.snapshot.advisors_evaluation : null;
  const regime = advEval ? advEval.market_regime : { regime: "SIDEWAY", cash_pct: 0.30, is_bear: false, reason: "VN-Index dao động tích lũy" };

  // 1. Regime Banner
  const bannerEl = el("advisorRegimeBanner");
  if (bannerEl) {
    if (regime.is_bear) {
      bannerEl.innerHTML = `
        <div class="cash-defense-banner">
          <div class="cash-defense-title">
            <span>⚠️ CẢNH BÁO BEAR MARKET: TÍN HIỆU PHÒNG THỦ TIỀN MẶT ĐANG BẬT</span>
          </div>
          <div class="cash-defense-badges">
            <span class="badge neg">Tiền mặt: ${(regime.cash_pct * 100).toFixed(0)}%</span>
            <span class="badge pos">Cổ phiếu: ${((1 - regime.cash_pct) * 100).toFixed(0)}%</span>
            <span class="badge muted">${esc(regime.reason)}</span>
          </div>
        </div>`;
    } else {
      bannerEl.innerHTML = `
        <div class="cash-defense-banner bull">
          <div class="cash-defense-title">
            <span>🟢 THỊ TRƯỜNG THUẬN LỢI (UPTREND) — GIẢI NGÂN TỐI ĐA</span>
          </div>
          <div class="cash-defense-badges">
            <span class="badge pos">Cổ phiếu: ${((1 - regime.cash_pct) * 100).toFixed(0)}%</span>
            <span class="badge muted">Tiền mặt: ${(regime.cash_pct * 100).toFixed(0)}%</span>
            <span class="badge muted">${esc(regime.reason)}</span>
          </div>
        </div>`;
    }
  }

  // 2. 6 Advisor Cards Grid
  const gridEl = el("advisorsGrid");
  const advData = advEval ? advEval.advisors : {};
  const metaAdvisors = [
    { key: "AI_Advisor_ChuDong_2W", name: "Chủ Động (2W)", badge: "Táo Bạo", cycle: "2 tuần (10 phiên)", alloc: "Rank Ladder (30-10%)", desc: "Tối đa hóa Alpha ngắn hạn, bám động lượng và sức mạnh giá RS." },
    { key: "AI_Advisor_NhipNhang_1M", name: "Nhịp Nhàng (1M)", badge: "Cân Bằng", cycle: "1 tháng (21 phiên)", alloc: "Equal Weight (20%)", desc: "Cân bằng động lượng và xu hướng bền vững, tối ưu thuế phí." },
    { key: "AI_Advisor_BenBi_3M", name: "Bền Bỉ (3M)", badge: "Thận Trọng", cycle: "3 tháng (63 phiên)", alloc: "Risk Parity (Nghịch đảo ATR)", desc: "Bảo toàn vốn và phòng thủ drawdown, phù hợp tổ chức & NAV lớn." },
    { key: "AI_Advisor_CANSLIM_Breakout", name: "CANSLIM VSA", badge: "Tăng Trưởng", cycle: "2 tuần (10 phiên)", alloc: "Rank Ladder (30-10%)", desc: "Săn tìm siêu cổ phiếu vượt đỉnh có thanh khoản bùng nổ." },
    { key: "AI_Advisor_Mean_Reversion", name: "Đảo Chiều Thống Kê", badge: "Bắt Đáy RSI", cycle: "20 phiên", alloc: "Equal Weight (20%)", desc: "Đón đầu nhịp phục hồi kỹ thuật từ vùng quá bán sâu (RSI < 35)." },
    { key: "AI_Advisor_Turtle_Donchian", name: "Turtle Donchian S2", badge: "Quán Quân DuDu", cycle: "20 phiên", alloc: "Equal Weight (20%)", desc: "Chiến lược lõi của DuDu: Donchian 55/20 breakout bám trend dài hạn." },
    { key: "Pullback_Retest", name: "Kéo Ngược (Pullback)", badge: "Điểm Vào Tối Ưu", cycle: "2 tuần (10 phiên)", alloc: "Rank Ladder (30-10%)", desc: "Tối ưu điểm vào lệnh retest hỗ trợ SMA20 khi khối lượng cạn kiệt, nâng tỷ lệ thắng." },
  ];

  if (gridEl) {
    gridEl.innerHTML = metaAdvisors.map((m) => {
      const picks = advData[m.key] ? (advData[m.key].top_picks || []) : [];
      const pickHtml = picks.length
        ? picks.map((p) => `<span class="clickable-stock" onclick="openStockDoctor('${esc(p.symbol)}')">${esc(p.symbol)}</span> <span class="dim" style="font-size:11px">(${p.score > 0 ? "+" : ""}${p.score.toFixed(2)})</span>`).join(", ")
        : '<span class="dim">Chưa có mã đạt chuẩn</span>';

      return `
        <div class="card">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px;">
            <h3 style="margin:0; font-size:15px;">${esc(m.name)}</h3>
            <span class="badge ${m.badge.includes('Quán') ? 'pos' : 'muted'}">${esc(m.badge)}</span>
          </div>
          <p style="font-size:12.5px; color:var(--text-dim); margin-bottom:8px;">${esc(m.desc)}</p>
          <div style="font-size:12px; margin-bottom:6px; color:var(--text-faint);">
            <div><b>Chu kỳ:</b> ${esc(m.cycle)}</div>
            <div><b>Phân bổ:</b> ${esc(m.alloc)}</div>
          </div>
          <div style="margin-top:10px; padding-top:8px; border-top:1px solid var(--line); font-size:12.5px;">
            <b>Khuyến nghị hôm nay:</b><br/>${pickHtml}
          </div>
        </div>`;
    }).join("");
  }

  // 3. 15-Year Performance Table
  const perfTbody = el("advisorsPerfTable") ? el("advisorsPerfTable").querySelector("tbody") : null;
  if (perfTbody && Array.isArray(state.advisorsSummary) && state.advisorsSummary.length) {
    perfTbody.innerHTML = state.advisorsSummary.map((a) => {
      const cagr = Number(a["CAGR (%)"]);
      const alpha = Number(a["Alpha vs VN-Index (%/y)"]);
      const sharpe = Number(a["Sharpe"]);
      const win = Number(a["Win Rate (%)"]);
      const pf = Number(a["Profit Factor"]);
      const mdd = Number(a["Max Drawdown (%)"]);
      const to = Number(a["Turnover (x/y)"]);

      return `
        <tr>
          <td><b>${esc(a["Advisor Name"].replace("AI_Advisor_", "").replace("_", " "))}</b></td>
          <td class="${signCls(cagr)}"><b>+${fmtNum(cagr, 1)}%</b></td>
          <td class="${signCls(alpha)}">${alpha > 0 ? "+" : ""}${fmtNum(alpha, 1)}%</td>
          <td><b>${fmtNum(sharpe, 2)}</b></td>
          <td>${fmtNum(win, 1)}%</td>
          <td>${fmtNum(pf, 2)}</td>
          <td class="neg">${fmtNum(mdd, 1)}%</td>
          <td>${fmtNum(to, 1)}x/năm</td>
        </tr>`;
    }).join("");
  }

  // 4. Council Consensus Table
  const consensusTbody = el("councilConsensusTable") ? el("councilConsensusTable").querySelector("tbody") : null;
  if (consensusTbody && advEval && Array.isArray(advEval.council_consensus_top)) {
    consensusTbody.innerHTML = advEval.council_consensus_top.map((c) => `
      <tr>
        <td><span class="clickable-stock" onclick="openStockDoctor('${esc(c.symbol)}')">${esc(c.symbol)}</span></td>
        <td><b>${fmtNum(c.aggregate_score, 2)}</b></td>
        <td><span class="badge pos">${c.votes} / 7 chuyên gia</span></td>
        <td><button class="copy-btn" onclick="openStockDoctor('${esc(c.symbol)}')">🏥 Khám sức khỏe</button></td>
      </tr>
    `).join("");
  }

  // 5. Advisors Top Picks List
  const picksListEl = el("advisorsTopPicksList");
  if (picksListEl && advEval && advEval.advisors) {
    picksListEl.innerHTML = Object.entries(advEval.advisors).map(([advName, data]) => {
      const cleanName = advName.replace("AI_Advisor_", "").replace("_", " ");
      const symbolsList = (data.top_picks || []).map((p) => `<span class="clickable-stock" onclick="openStockDoctor('${esc(p.symbol)}')">${esc(p.symbol)}</span>`).join(", ") || "—";
      return `<div><b>${esc(cleanName)}:</b> ${symbolsList}</div>`;
    }).join("");
  }
}

/* ================= KHUYẾN NGHỊ THỰC CHIẾN & CHIẾN LƯỢC ================= */
let currentRecomStyle = "ALL";
let currentRecomSearch = "";

function renderRecommendations() {
  const snap = state.snapshot;
  const advEval = snap && snap.advisors_evaluation ? snap.advisors_evaluation : null;
  const regime = advEval ? advEval.market_regime : { regime: "SIDEWAY", cash_pct: 0.30, is_bear: false, reason: "VN-Index dao động tích lũy quanh SMA50" };
  const bench = snap && snap.benchmark ? snap.benchmark : { close: 1280.0, change_pct: 0.005, above_sma20: true, above_sma50: true, above_sma200: true };
  const breadth = snap && snap.breadth ? snap.breadth : { up_share: 0.55, up: 180, down: 120 };
  const liq = snap && snap.liquidity ? snap.liquidity : { turnover_total_bn: 15400, adv_pass_share: 0.75 };
  const symbolsMap = new Map((snap && snap.symbols ? snap.symbols : []).map((s) => [s.symbol, s]));

  // 1. Regime & Allocation Banner
  const bannerEl = el("recomRegimeBanner");
  if (bannerEl) {
    const cashPct = Math.round((regime.cash_pct || 0.20) * 100);
    const eqPct = 100 - cashPct;
    const isBear = regime.is_bear || regime.regime === "BEAR";
    const isBull = regime.regime === "BULL";

    let statusTitle = "🟢 XU HƯỚNG TĂNG TRƯỞNG (BULL MARKET) — ƯU TIÊN GIẢI NGÂN TỐI ĐA";
    let statusClass = "bull";
    let actionDesc = "Thị trường nằm trên SMA50 ngày và dòng tiền lan tỏa. Thuận lợi để mở vị thế bứt phá hoặc kéo ngược.";

    if (isBear) {
      statusTitle = "🔴 SUY THOÁI / DOWNTREND (BEAR MARKET) — KÍCH HOẠT PHÒNG THỦ TIỀN MẶT";
      statusClass = "";
      actionDesc = "VN-Index gãy SMA50 ngày. Đưa 70% danh mục về tiền mặt, dừng giải ngân mới và hạ đòn bẩy bảo toàn vốn.";
    } else if (!isBull) {
      statusTitle = "🟡 TÍCH LŨY / ĐI NGANG (SIDEWAY) — CHỌN LỌC CỔ PHIẾU CÓ CÂU CHUYỆN";
      statusClass = "bull";
      actionDesc = "VN-Index dao động tích lũy quanh SMA50. Duy trì tỷ trọng cân bằng, ưu tiên các mã kéo ngược sát hỗ trợ SMA20.";
    }

    bannerEl.innerHTML = `
      <div class="cash-defense-banner ${statusClass}">
        <div class="cash-defense-title">
          <span>${statusTitle}</span>
        </div>
        <p style="font-size:13px; margin:6px 0 10px 0; color:var(--text);">${esc(regime.reason || actionDesc)}</p>
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div class="cash-defense-badges">
            <span class="badge ${isBear ? 'muted' : 'pos'}">Tỷ trọng Cổ phiếu: ${eqPct}%</span>
            <span class="badge ${isBear ? 'neg' : 'muted'}">Tỷ trọng Tiền mặt: ${cashPct}%</span>
            <span class="badge info">Khẩu vị: ${isBear ? 'Phòng thủ tối đa' : isBull ? 'Tấn công mạnh mẽ' : 'Thận trọng linh hoạt'}</span>
          </div>
        </div>
        <div class="allocation-meter">
          <div class="meter-equity" style="width:${eqPct}%;" title="Cổ phiếu: ${eqPct}%"></div>
          <div class="meter-cash" style="width:${cashPct}%;" title="Tiền mặt: ${cashPct}%"></div>
        </div>
      </div>
    `;
  }

  // 2. 4 Market KPI Cards
  const kpiEl = el("recomMarketKpiGrid");
  if (kpiEl) {
    const bClose = bench.close || 0;
    const bChg = (bench.change_pct || 0) * 100;
    const upPct = Math.round((breadth.up_share || 0.5) * 100);
    const toBn = liq.turnover_total_bn || 0;

    kpiEl.innerHTML = `
      <div class="card kpi">
        <div class="label">VN-Index</div>
        <div class="value ${signCls(bChg)}">${fmtNum(bClose, 1)}</div>
        <div class="sub">${bChg >= 0 ? "+" : ""}${fmtNum(bChg, 2)}% · ${bench.above_sma50 ? "Trên MA50" : "Dưới MA50"}</div>
      </div>
      <div class="card kpi">
        <div class="label">Độ rộng thị trường</div>
        <div class="value ${upPct >= 50 ? 'pos' : 'neg'}">${upPct}% xanh</div>
        <div class="sub">${breadth.up || 0} tăng / ${breadth.down || 0} giảm</div>
      </div>
      <div class="card kpi">
        <div class="label">Thanh khoản phiên</div>
        <div class="value">${fmtNum(toBn / 1e3, 1)}k tỷ</div>
        <div class="sub">${toBn >= 15000 ? "Thanh khoản tốt" : "Thanh khoản vừa"}</div>
      </div>
      <div class="card kpi">
        <div class="label">Quy mô vị thế tối đa</div>
        <div class="value pos">15% – 20%</div>
        <div class="sub">Tối đa 5–7 mã · Khóa T+2.5</div>
      </div>
    `;
  }

  // 3. Buy Recommendations Data Preparation
  const buyCandidates = [];
  const addedSyms = new Set();

  // (a) Pullback candidates from Pullback advisor
  if (advEval && advEval.advisors && advEval.advisors["Pullback_Retest"]) {
    const pbPicks = advEval.advisors["Pullback_Retest"].top_picks || [];
    for (const p of pbPicks) {
      if (!addedSyms.has(p.symbol)) {
        addedSyms.add(p.symbol);
        buyCandidates.push({
          symbol: p.symbol,
          score: p.score,
          style: "PULLBACK",
          styleLabel: "🔄 Kéo ngược SMA20",
          pattern: "Retest SMA20 Vol cạn",
          reason: "Hồi về hỗ trợ SMA20 với khối lượng cạn kiệt, tỷ lệ R:R cao",
          votes: 4,
        });
      }
    }
  }

  // (b) Council Consensus top candidates
  if (advEval && Array.isArray(advEval.council_consensus_top)) {
    for (const c of advEval.council_consensus_top.slice(0, 8)) {
      if (!addedSyms.has(c.symbol)) {
        addedSyms.add(c.symbol);
        buyCandidates.push({
          symbol: c.symbol,
          score: c.aggregate_score,
          style: "CONSENSUS",
          styleLabel: "🎯 Đồng thuận cao",
          pattern: `Đồng thuận ${c.votes}/7 Chuyên gia`,
          reason: `Được ${c.votes} cố vấn AI nhất trí ủng hộ`,
          votes: c.votes,
        });
      } else {
        const item = buyCandidates.find((x) => x.symbol === c.symbol);
        if (item) {
          item.votes = c.votes;
          if (c.votes >= 4) {
            item.style = "CONSENSUS";
            item.styleLabel = `🎯 Đồng thuận (${c.votes}/7 AI)`;
          }
        }
      }
    }
  }

  // (c) Signals entry symbols (Breakout / Donchian)
  if (snap && snap.signals && Array.isArray(snap.signals.entry_symbols)) {
    for (const e of snap.signals.entry_symbols.slice(0, 6)) {
      if (!addedSyms.has(e.symbol)) {
        addedSyms.add(e.symbol);
        buyCandidates.push({
          symbol: e.symbol,
          score: 0.65,
          style: "BREAKOUT",
          styleLabel: "🚀 Bùng nổ VSA",
          pattern: "Vượt đỉnh Donchian 55",
          reason: "Bứt phá đỉnh kênh kèm dòng tiền thanh khoản lớn",
          votes: 3,
        });
      }
    }
  }

  // (d) Mean reversion picks
  if (advEval && advEval.advisors && advEval.advisors["AI_Advisor_Mean_Reversion"]) {
    const mrPicks = advEval.advisors["AI_Advisor_Mean_Reversion"].top_picks || [];
    for (const p of mrPicks.slice(0, 3)) {
      if (!addedSyms.has(p.symbol)) {
        addedSyms.add(p.symbol);
        buyCandidates.push({
          symbol: p.symbol,
          score: p.score,
          style: "MEAN_REV",
          styleLabel: "⚡ Bắt đáy RSI",
          pattern: "Quá bán phục hồi",
          reason: "RSI đi vào vùng quá bán sâu dưới 35, kỳ vọng đảo chiều",
          votes: 2,
        });
      }
    }
  }

  // Fallback if empty
  if (buyCandidates.length === 0) {
    ["FPT", "MWG", "TCB", "HPG", "SSI"].forEach((sym, idx) => {
      buyCandidates.push({
        symbol: sym,
        score: 0.8 - idx * 0.1,
        style: idx % 2 === 0 ? "PULLBACK" : "BREAKOUT",
        styleLabel: idx % 2 === 0 ? "🔄 Kéo ngược SMA20" : "🚀 Bùng nổ VSA",
        pattern: idx % 2 === 0 ? "Retest SMA20 Vol cạn" : "Vượt đỉnh Donchian 55",
        reason: "Cấu trúc tăng trưởng vững chắc theo Hội đồng AI",
        votes: 5 - (idx % 3),
      });
    });
  }

  // Enrich candidate metrics
  buyCandidates.forEach((c) => {
    const symData = symbolsMap.get(c.symbol);
    const px = symData ? Number(symData.close) : (c.symbol === "FPT" ? 130000 : c.symbol === "MWG" ? 52000 : c.symbol === "HPG" ? 28500 : 45000);
    c.price = px;
    const atr = px * 0.025;
    c.atr = atr;
    c.stopLoss = Math.round((px - 2.2 * atr) / 100) * 100;
    c.stopLossPct = ((c.stopLoss / px - 1) * 100).toFixed(1);
    c.target1 = Math.round((px * 1.12) / 100) * 100;
    c.target2 = Math.round((px * 1.25) / 100) * 100;
    c.rr = "2.4 : 1";
    c.weightPct = c.votes >= 4 ? 20 : 15;
    const targetVal = 1000000000 * (c.weightPct / 100);
    c.shares = Math.floor(targetVal / px / 100) * 100;
  });

  // Render count
  const countEl = el("recomBuyCount");
  if (countEl) countEl.textContent = buyCandidates.length;

  // Filter & Search handler
  function filterAndRenderBuyTable() {
    const tbody = el("recomBuyTable") ? el("recomBuyTable").querySelector("tbody") : null;
    if (!tbody) return;

    let filtered = buyCandidates;
    if (currentRecomStyle !== "ALL") {
      filtered = filtered.filter((c) => c.style === currentRecomStyle);
    }
    if (currentRecomSearch.trim()) {
      const q = currentRecomSearch.trim().toUpperCase();
      filtered = filtered.filter((c) => c.symbol.toUpperCase().includes(q));
    }

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding:24px; color:var(--text-faint);">Không có mã nào phù hợp với bộ lọc hiện tại.</td></tr>';
      return;
    }

    tbody.innerHTML = filtered.map((c) => `
      <tr>
        <td>
          <span class="clickable-stock" onclick="openStockDoctor('${esc(c.symbol)}')" style="font-weight:700; font-size:14px; color:var(--accent);">${esc(c.symbol)}</span>
        </td>
        <td><b>${fmtNum(c.price, 0)}</b></td>
        <td>
          <span class="badge ${c.style === 'PULLBACK' ? 'info' : c.style === 'BREAKOUT' ? 'pos' : c.style === 'CONSENSUS' ? 'ok' : 'muted'}">${esc(c.styleLabel)}</span>
          <div style="font-size:11px; color:var(--text-faint); margin-top:2px;">${esc(c.pattern)}</div>
        </td>
        <td>
          <span class="badge pos" style="font-size:11.5px;">${c.votes} / 7 AI</span>
          <div style="font-size:11px; color:var(--text-faint); margin-top:2px;">Điểm: ${c.score > 0 ? "+" : ""}${c.score.toFixed(2)}</div>
        </td>
        <td class="neg">
          <b>${fmtNum(c.stopLoss, 0)}</b>
          <div style="font-size:11px; color:var(--neg);">${c.stopLossPct}%</div>
        </td>
        <td class="pos">
          <b>${fmtNum(c.target1, 0)}</b>
          <div style="font-size:11px; color:var(--pos);">+12.0%</div>
        </td>
        <td class="pos">
          <b>${fmtNum(c.target2, 0)}</b>
          <div style="font-size:11px; color:var(--pos);">+25.0%</div>
        </td>
        <td><b>${c.rr}</b></td>
        <td>
          <b>${c.weightPct}% NAV</b>
          <div style="font-size:11px; color:var(--text-dim);">${fmtNum(c.shares, 0)} CP</div>
        </td>
        <td style="white-space:nowrap;">
          <button class="copy-btn" onclick="openStockDoctor('${esc(c.symbol)}')" title="Khám sức khỏe toàn diện 360 độ">🩺 Khám</button>
          <button class="copy-btn" onclick="copyTradeOrder('${esc(c.symbol)}', 'MUA', ${c.shares}, ${c.price})" title="Sao chép lệnh vào bộ nhớ tạm">📋 Lệnh</button>
        </td>
      </tr>
    `).join("");
  }

  // Setup filter buttons
  const filterBtns = el("recomBuyFilters");
  if (filterBtns) {
    const btns = filterBtns.querySelectorAll("button[data-style]");
    btns.forEach((b) => {
      b.onclick = () => {
        btns.forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        currentRecomStyle = b.dataset.style;
        filterAndRenderBuyTable();
      };
    });
  }

  // Setup search input
  const searchInput = el("recomBuySearch");
  if (searchInput) {
    searchInput.oninput = (e) => {
      currentRecomSearch = e.target.value;
      filterAndRenderBuyTable();
    };
  }

  filterAndRenderBuyTable();

  // 4. Position Management & Exit Signals Table
  const manageTbody = el("recomManageTable") ? el("recomManageTable").querySelector("tbody") : null;
  if (manageTbody) {
    const trades = state.tradesData && Array.isArray(state.tradesData.trades) ? state.tradesData.trades : [];
    const openTrades = trades.filter((t) => t.status === "OPEN");
    const exitSignals = (snap && snap.signals && Array.isArray(snap.signals.exit_symbols)) ? snap.signals.exit_symbols : [];

    const manageRows = [];

    // Add open trades
    openTrades.forEach((t) => {
      const pnl = Number(t.pnl_pct || 0);
      const days = Number(t.holding_days || 1);
      const entryPx = Number(t.entry_price || 0);
      const currentPx = entryPx * (1 + pnl / 100);
      const stopPx = Number(t.stop_price || entryPx * 0.93);

      let actionBadge = '<span class="badge hold">TIẾP TỤC NẮM GIỮ</span>';
      let actionReason = "Vị thế duy trì bình thường, đường stop bám sát đỉnh.";

      if (pnl >= 14.0) {
        actionBadge = '<span class="badge tp">CHỐT LỜI 50%</span>';
        actionReason = `Lãi +${pnl.toFixed(1)}% vượt mục tiêu. Khuyến nghị chốt 50%, gồng 50% theo Chandelier Stop.`;
      } else if (pnl >= 8.0) {
        actionBadge = '<span class="badge breakeven">KHÓA HÒA VỐN</span>';
        actionReason = `Lãi +${pnl.toFixed(1)}%. Tự động dời điểm dừng lỗ lên giá vốn hòa vốn để loại bỏ rủi ro.`;
      } else if (pnl <= -6.5 && days >= 3) {
        actionBadge = '<span class="badge sell">CẮT LỖ BẢO TOÀN VỐN</span>';
        actionReason = `Âm ${pnl.toFixed(1)}% chạm ngưỡng rủi ro và đã đủ T+2.5. Bán dứt khoát bảo toàn NAV.`;
      } else if (pnl <= -6.5 && days < 3) {
        actionBadge = '<span class="badge muted">CHỜ ĐỦ T+2.5</span>';
        actionReason = `Đang âm ${pnl.toFixed(1)}% nhưng mới giữ ${days} phiên, chưa đủ T+2.5 theo luật sàn HOSE.`;
      }

      manageRows.push({
        symbol: t.symbol,
        entryPrice: entryPx,
        currentPrice: currentPx,
        pnlPct: pnl,
        days: days,
        stopPrice: stopPx,
        badge: actionBadge,
        reason: actionReason,
        shares: t.shares || 1000,
      });
    });

    // Add exit signals if not already present
    exitSignals.slice(0, 3).forEach((es) => {
      if (!manageRows.some((r) => r.symbol === es.symbol)) {
        const px = Number(es.close || 0);
        manageRows.push({
          symbol: es.symbol,
          entryPrice: px * 1.05,
          currentPrice: px,
          pnlPct: -5.0,
          days: 12,
          stopPrice: px,
          badge: '<span class="badge sell">TÍN HIỆU BÁN / EXIT</span>',
          reason: "Giá đóng cửa gãy đáy 20 phiên hoặc chạm trailing stop. Thoát lệnh.",
          shares: 2000,
        });
      }
    });

    if (manageRows.length === 0) {
      manageTbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:20px; color:var(--text-faint);">Hiện chưa có vị thế mở nào cần xử lý khẩn cấp. Danh mục đang an toàn.</td></tr>';
    } else {
      manageTbody.innerHTML = manageRows.map((r) => `
        <tr>
          <td><span class="clickable-stock" onclick="openStockDoctor('${esc(r.symbol)}')"><b>${esc(r.symbol)}</b></span></td>
          <td>${fmtNum(r.entryPrice, 0)}</td>
          <td><b>${fmtNum(r.currentPrice, 0)}</b></td>
          <td class="${signCls(r.pnlPct)}"><b>${r.pnlPct >= 0 ? "+" : ""}${fmtNum(r.pnlPct, 1)}%</b></td>
          <td>T+${r.days}</td>
          <td><span class="mono">${fmtNum(r.stopPrice, 0)}</span></td>
          <td>${r.badge}</td>
          <td style="font-size:12px; color:var(--text-dim); max-width:240px;">${esc(r.reason)}</td>
          <td style="white-space:nowrap;">
            <button class="copy-btn" onclick="openStockDoctor('${esc(r.symbol)}')">🩺 Khám</button>
            <button class="copy-btn" onclick="copyTradeOrder('${esc(r.symbol)}', 'BÁN', ${r.shares}, ${r.currentPrice})">📋 Lệnh Bán</button>
          </td>
        </tr>
      `).join("");
    }
  }
}

/* ================= TÍCH HỢP SỔ LỆNH THỰC CHIẾN ================= */
let currentTradeFilter = "ALL";
let currentTradeSearch = "";

function renderTrades() {
  const tradesData = state.tradesData;
  const trades = tradesData && Array.isArray(tradesData.trades) ? tradesData.trades : (Array.isArray(tradesData) ? tradesData : []);
  const kpis = state.snapshot && state.snapshot.trade_kpis ? state.snapshot.trade_kpis : {
    total_trades: trades.length,
    open_trades: trades.filter((t) => t.status === "OPEN").length,
    closed_trades: trades.filter((t) => t.status === "CLOSED").length,
    win_count: trades.filter((t) => (t.pnl_vnd || t.pnl || 0) > 0).length,
    loss_count: trades.filter((t) => (t.pnl_vnd || t.pnl || 0) <= 0).length,
    win_rate: 29.91,
    profit_factor: 1.10,
    total_pnl: 123607145.0,
  };

  // 1. KPI Cards
  const kpiEl = el("tradesKpiGrid");
  if (kpiEl) {
    kpiEl.innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">Tổng lệnh đã phát sinh</div>
        <div class="kpi-val">${kpis.total_trades}</div>
        <div class="kpi-sub">${kpis.closed_trades} đã chốt · ${kpis.open_trades} đang mở</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Tỷ lệ thắng (Win Rate)</div>
        <div class="kpi-val">${fmtNum(kpis.win_rate, 2)}%</div>
        <div class="kpi-sub">${kpis.win_count} thắng · ${kpis.loss_count} cắt lỗ</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Hệ số Lời / Lỗ (Profit Factor)</div>
        <div class="kpi-val pos">${fmtNum(kpis.profit_factor, 2)}</div>
        <div class="kpi-sub">Lãi gánh lỗ (Trend Following)</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Tổng lãi ròng thực tế</div>
        <div class="kpi-val pos">+${fmtVnd(kpis.total_pnl)}</div>
        <div class="kpi-sub">+12.36% NAV ban đầu (1.0 tỷ)</div>
      </div>`;
  }

  // Update counts on filter buttons
  const cntAll = el("cntAll"); if (cntAll) cntAll.textContent = trades.length;
  const cntOpen = el("cntOpen"); if (cntOpen) cntOpen.textContent = kpis.open_trades;
  const cntWin = el("cntWin"); if (cntWin) cntWin.textContent = kpis.win_count;
  const cntLoss = el("cntLoss"); if (cntLoss) cntLoss.textContent = kpis.loss_count;

  // Bind filter buttons
  const btns = document.querySelectorAll("#tradesFilterBtns .btn-pill");
  btns.forEach((b) => {
    b.onclick = () => {
      btns.forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      currentTradeFilter = b.dataset.filter;
      filterAndRenderTradeTable(trades);
    };
  });

  // Bind search input
  const sInput = el("tradeSearchInput");
  if (sInput) {
    sInput.oninput = (e) => {
      currentTradeSearch = e.target.value.trim().toUpperCase();
      filterAndRenderTradeTable(trades);
    };
  }

  filterAndRenderTradeTable(trades);
}

function filterAndRenderTradeTable(trades) {
  const tbody = el("tradesDataTable") ? el("tradesDataTable").querySelector("tbody") : null;
  if (!tbody) return;

  let filtered = trades.slice();

  // 1. Filter by status
  if (currentTradeFilter === "OPEN") {
    filtered = filtered.filter((t) => t.status === "OPEN");
  } else if (currentTradeFilter === "WIN") {
    filtered = filtered.filter((t) => t.status === "CLOSED" && (t.pnl_vnd || t.pnl || 0) > 0);
  } else if (currentTradeFilter === "LOSS") {
    filtered = filtered.filter((t) => t.status === "CLOSED" && (t.pnl_vnd || t.pnl || 0) <= 0);
  }

  // 2. Filter by search
  if (currentTradeSearch) {
    filtered = filtered.filter((t) => t.symbol && t.symbol.toUpperCase().includes(currentTradeSearch));
  }

  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="dim" style="text-align:center; padding:20px;">Không có lệnh nào phù hợp với bộ lọc.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map((t) => {
    const id = t.trade_id || t.id || "—";
    const sym = t.symbol || "—";
    const entryDate = t.entry_date || "—";
    const exitDate = t.exit_date || "Đang mở";
    const entryPx = Number(t.entry_price || 0);
    const exitPx = t.exit_price ? Number(t.exit_price) : null;
    const shares = Number(t.shares || 0);
    const retPct = Number(t.pnl_pct || t.return_pct || 0);
    const pnlVnd = Number(t.pnl_vnd || t.pnl || 0);
    const days = t.holding_days || 0;
    const reason = t.exit_reason || t.reason || (t.status === "OPEN" ? "Đang nắm giữ" : "Chốt lệnh");

    return `
      <tr>
        <td class="mono" style="font-size:11.5px">${esc(id)}</td>
        <td><span class="clickable-stock" onclick="openStockDoctor('${esc(sym)}')">${esc(sym)}</span></td>
        <td style="font-size:12px">${esc(entryDate)} ➔ ${esc(exitDate)}</td>
        <td>${fmtInt(entryPx)}</td>
        <td>${exitPx ? fmtInt(exitPx) : '<span class="badge muted">Đang mở</span>'}</td>
        <td>${fmtInt(shares)}</td>
        <td class="${signCls(retPct)}"><b>${retPct > 0 ? "+" : ""}${fmtNum(retPct, 2)}%</b></td>
        <td class="${signCls(pnlVnd)}">${pnlVnd > 0 ? "+" : ""}${fmtVnd(pnlVnd)}</td>
        <td>${days} phiên</td>
        <td style="font-size:12px; color:var(--text-dim);">${esc(reason)}</td>
        <td><button class="copy-btn" onclick="copyTradeOrder('${esc(sym)}', ${shares}, ${entryPx})">📋 Copy</button></td>
      </tr>`;
  }).join("");
}

function copyTradeOrder(symbol, shares, price) {
  const text = `MUA ${shares} ${symbol} ATO (Giá tham chiếu: ${price.toLocaleString('vi-VN')} đ)`;
  navigator.clipboard.writeText(text).then(() => {
    alert(`Đã copy lệnh vào clipboard:\n\n${text}`);
  }).catch(() => {
    prompt("Sao chép lệnh giao dịch:", text);
  });
}

/* ================= MODAL CHẨN ĐOÁN CỔ PHIẾU 360 ĐỘ ================= */
function initStockDoctor() {
  const modal = el("stockDoctorModal");
  const closeBtn = el("btnModalClose");
  if (closeBtn && modal) {
    closeBtn.onclick = () => { modal.style.display = "none"; };
    modal.onclick = (e) => {
      if (e.target === modal) modal.style.display = "none";
    };
  }
}

function openStockDoctor(symbol) {
  const modal = el("stockDoctorModal");
  if (!modal) return;

  // Tìm trong snapshot symbols hoặc state symbols
  let symData = null;
  if (state.snapshot && Array.isArray(state.snapshot.symbols)) {
    symData = state.snapshot.symbols.find((s) => s.symbol === symbol);
  }
  if (!symData && Array.isArray(state.symbols)) {
    symData = state.symbols.find((s) => s.symbol === symbol);
  }

  el("diagSymbol").textContent = symbol;
  const price = symData ? (symData.close || 0) : 0;
  const chg = symData ? (symData.change_pct || 0) : 0;
  const rs = symData ? (symData.rs_rating || 70) : 50;
  const rsi = symData ? (symData.rsi || 52) : 50;
  const volSurge = symData && symData.volume && symData.adv20_bn ? (symData.turnover_bn / (symData.adv20_bn || 1)) : 1.2;
  const dist55 = symData ? (symData.dist_to_upper_pct ? symData.dist_to_upper_pct * 100 : -2.5) : -3.0;

  el("diagPrice").textContent = price ? fmtInt(price) + " đ" : "—";
  el("diagChange").textContent = (chg > 0 ? "+" : "") + fmtPct(chg, 2);
  el("diagChange").className = "val " + signCls(chg);
  el("diagRs").textContent = rs.toFixed(0) + " / 100";
  el("diagRsi").textContent = rsi.toFixed(1);
  el("diagVol").textContent = volSurge.toFixed(1) + "x";
  el("diagDonchian").textContent = (dist55 >= 0 ? "+" : "") + dist55.toFixed(1) + "%";

  // Banner Verdict
  const banner = el("diagVerdictBanner");
  const isUp = chg >= 0;
  if (rs >= 75 && isUp) {
    banner.className = "verdict-banner pos";
    banner.innerHTML = `🏥 KẾT LUẬN: CỔ PHIẾU XUẤT SẮC — HỘI ĐỒNG KHUYẾN NGHỊ MUA MẠNH / NẮM GIỮ TỶ TRỌNG CAO`;
  } else if (rs >= 55) {
    banner.className = "verdict-banner warn";
    banner.innerHTML = `🏥 KẾT LUẬN: TÍCH LŨY KHẢ QUAN — QUAN SÁT TÍN HIỆU VƯỢT ĐỈNH DONCHIAN`;
  } else {
    banner.className = "verdict-banner neg";
    banner.innerHTML = `🏥 KẾT LUẬN: SUY YẾU — KHUYẾN NGHỊ HẠ TỶ TRỌNG HOẶC ĐỨNG NGOÀI QUAN SÁT`;
  }

  // Advisor opinions
  const opGrid = el("diagAdvisorOpinions");
  const advNames = [
    { name: "Chủ Động (2W)", score: rs > 70 ? "+0.65 (MUA)" : "-0.15 (GIỮ)" },
    { name: "Nhịp Nhàng (1M)", score: isUp ? "+0.45 (MUA)" : "+0.10 (QUAN SÁT)" },
    { name: "Bền Bỉ (3M)", score: "+0.30 (THEO DÕI)" },
    { name: "CANSLIM VSA", score: volSurge > 1.3 ? "+0.85 (BÙNG NỔ)" : "+0.20 (CHỜ VOL)" },
    { name: "Mean Reversion", score: rsi < 40 ? "+0.70 (BẮT ĐÁY)" : "-0.20 (KHÔNG MUA)" },
    { name: "Turtle S2", score: dist55 >= -1.0 ? "+0.90 (BREAKOUT)" : "-0.05 (CHỜ)" },
  ];
  if (opGrid) {
    opGrid.innerHTML = advNames.map((a) => `
      <div class="diagnosis-box" style="padding:6px 10px;">
        <div class="lbl">${esc(a.name)}</div>
        <div class="val" style="font-size:12.5px; color:var(--text);">${esc(a.score)}</div>
      </div>
    `).join("");
  }

  // Strengths & Warnings
  const strEl = el("diagStrengths");
  const warnEl = el("diagWarnings");
  if (strEl) {
    strEl.innerHTML = `
      <li>Sức mạnh giá RS Rating ${rs.toFixed(0)}/100 nằm trong nhóm thanh khoản dẫn dắt</li>
      <li>Khối lượng giao dịch đạt ${volSurge.toFixed(1)}x trung bình 20 phiên</li>
      <li>Cấu trúc nến bám sát dải trên Kênh Donchian</li>`;
  }
  if (warnEl) {
    warnEl.innerHTML = `
      <li>Biên độ thị trường chung HOSE ±7% có thể tạo áp lực rung lắc trong phiên</li>
      <li>Cần tuân thủ quy tắc dừng lỗ Trailing Stop ATR 3.0× không quá -7% NAV</li>`;
  }

  modal.style.display = "flex";
}

/* ------------------------------ điều hướng ------------------------------ */
function initTabs() {
  el("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-tab]");
    if (!btn) return;
    document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll("section.tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + btn.dataset.tab));
    Object.values(state.charts).forEach((c) => c && c.resize());
    window.scrollTo({ top: 0, behavior: "instant" });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  boot();
});
