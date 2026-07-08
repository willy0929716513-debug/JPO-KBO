// Page-specific logic for index.html (the main "今日建議" dashboard).
// Shared constants/helpers (translations, fmtNum, live ticker, etc.) live
// in common.js, loaded before this file.
const DATA_URL = "data/signals_latest.json";
const HISTORY_URL = "data/history.json";
const DASHBOARD_REFRESH_MS = 60_000; // pipeline data only changes when Actions runs, but this keeps the page current without a manual click

function buildPlainReason(s) {
  const vetoed = s.decision_engine && s.decision_engine.vetoed;
  if (vetoed) {
    return "⚠️ 風控機制建議暫緩進場（近期虧損或風險超出安全範圍），先觀望比較保險";
  }
  const action = effectiveAction(s);
  const regimeText = REGIME_ZH[s.regime.state] || "資料不足";
  if (action === "BUY") return `目前${regimeText}，多項技術指標偏多，可考慮找機會分批做多`;
  if (action === "SELL") return `目前${regimeText}，多項技術指標偏空，可考慮找機會分批做空`;
  return `目前${regimeText}，訊號不夠明確，建議先觀望，不用急著進場`;
}

// Search text + "hide HOLD" toggle applied to both the Taiwan and
// auxiliary grids (not to 今日焦點, which always shows the global best
// regardless of the active filter -- it's meant to be glanceable even
// while you're mid-search for something else).
const filterState = { query: "", hideHold: false };

function passesFilter(s) {
  if (filterState.hideHold && effectiveAction(s) === "HOLD") return false;
  if (filterState.query) {
    const q = filterState.query;
    const name = (SYMBOL_NAMES[s.symbol] || "").toLowerCase();
    if (!s.symbol.toLowerCase().includes(q) && !name.includes(q)) return false;
  }
  return true;
}

// Tracks each symbol's action across polls (localStorage, so it survives
// a reload) purely to detect "this just flipped since last time" -- both
// for the 🆕 badge on cards and for triggering a browser notification.
// A symbol seen for the first time is never flagged as "changed": with
// no prior action to compare against, everything would otherwise light
// up as new on the very first load.
const LAST_SEEN_ACTIONS_KEY = "quantDashboardLastSeenActions_v1";
let changedSymbols = new Set();

function updateChangeTrackingAndNotify(payload) {
  let previous = {};
  try { previous = JSON.parse(localStorage.getItem(LAST_SEEN_ACTIONS_KEY) || "{}"); } catch (err) { previous = {}; }

  const current = {};
  const changed = new Set();
  const strongNew = [];

  (payload.signals || []).forEach((s) => {
    const action = effectiveAction(s);
    current[s.symbol] = action;
    const prevAction = previous[s.symbol];
    if (prevAction !== undefined && prevAction !== action) {
      changed.add(s.symbol);
      if (action !== "HOLD" && effectiveConfidence(s) >= 0.6) {
        strongNew.push({ symbol: s.symbol, name: SYMBOL_NAMES[s.symbol] || s.symbol, action });
      }
    }
  });

  changedSymbols = changed;
  localStorage.setItem(LAST_SEEN_ACTIONS_KEY, JSON.stringify(current));
  if (strongNew.length > 0) notifyStrongSignals(strongNew);
}

function refreshNotifyButton() {
  const btn = document.getElementById("notify-btn");
  if (!btn) return;
  btn.textContent = notificationsEnabled() ? "🔔 強訊號通知：已開啟" : "🔔 開啟強訊號通知";
}

// The overall Taiwan market's daily change (加權股價指數/大盤) -- per user
// request ("我是指大盤總共"), a single "is the whole market up or down
// today" figure distinct from any individual stock pick.
function renderTaiex(taiex) {
  const el = document.getElementById("taiex-pill");
  if (!el) return;
  if (!taiex || taiex.change_pct == null) {
    el.textContent = "大盤：--";
    el.className = "pill";
    return;
  }
  const isUp = taiex.change_pct >= 0;
  const sign = isUp ? "+" : "";
  const closedNote = taiex.market_open === false ? "（收盤）" : "";
  el.textContent = `大盤 加權指數 ${fmtNum(taiex.price, 0)} ${sign}${fmtNum(taiex.change_pts, 0)}（${sign}${fmtNum(taiex.change_pct, 2)}%）${closedNote}`;
  el.className = `pill ${isUp ? "live-up" : "live-down"}`;
}

function renderSummary(payload) {
  const counts = { BUY: 0, SELL: 0, HOLD: 0 };
  payload.signals.forEach((s) => counts[effectiveAction(s)]++);

  const cards = [
    { label: "分析標的數", value: `${payload.successful} / ${payload.watchlist_size}` },
    { label: "建議做多", value: counts.BUY },
    { label: "建議做空", value: counts.SELL },
    { label: "建議觀望", value: counts.HOLD },
  ];

  document.getElementById("summary-cards").innerHTML = cards
    .map((c) => `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`)
    .join("");
}

// Renders one group of pick-cards into containerId. Shared by the primary
// Taiwan-focus section and the smaller auxiliary section for every other
// market, so both look and sort identically.
function renderPickCards(containerId, signals, emptyMessage) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.className = "pick-grid";
  if (signals.length === 0) {
    container.innerHTML = `<p class="footnote">${emptyMessage || "尚無資料"}</p>`;
    return;
  }

  const sorted = signals.slice().sort((a, b) => {
    const rank = (s) => (effectiveAction(s) === "HOLD" ? 1 : 0);
    const diff = rank(a) - rank(b);
    return diff !== 0 ? diff : effectiveConfidence(b) - effectiveConfidence(a);
  });

  const cardsHtml = sorted.map((s, i) => {
    const sig = s.signal;
    const action = effectiveAction(s);
    const name = SYMBOL_NAMES[s.symbol] || s.symbol;
    const conf = effectiveConfidence(s);
    const ind = s.indicators;

    const isExtra = i >= PICK_GRID_COLLAPSE_THRESHOLD;
    return `<div class="pick-card ${badgeClass(action)}-card${isExtra ? " pick-card-extra" : ""}" data-symbol="${s.symbol}" ${isExtra ? "hidden" : ""} style="animation-delay:${Math.min(i * 35, 350)}ms">
      <div class="pick-head">
        <div class="pick-name">${name} <span class="pick-symbol">${s.symbol}</span></div>
        <div class="pick-head-badges">
          ${changedSymbols.has(s.symbol) ? `<span class="badge badge-new">🆕 剛轉變</span>` : ""}
          <div class="pick-action badge ${badgeClass(action)}">${ACTION_ZH[action]}</div>
        </div>
      </div>
      <div class="pick-price">目前價格：<b class="num js-live-price">${fmtNum(s.last_price, 4)}</b>${
        (s.change_pct === null || s.change_pct === undefined) ? "" :
        ` <span class="live-change ${s.change_pct >= 0 ? "live-up" : "live-down"}">${s.change_pct >= 0 ? "▲" : "▼"} ${fmtNum(Math.abs(s.change_pct), 2)}%</span>`
      } ${marketStatusBadge(s.market_open)}</div>
      <div class="pick-levels num">
        <span>建議停損：${fmtNum(sig.stop_loss, 4)}</span>
        <span>建議停利：${fmtNum(sig.take_profit, 4)}</span>
      </div>
      <div class="confidence-row">
        信心程度：${confidenceLabel(conf)}
        <span class="confidence-dots">${confidenceDots(conf)}</span>
      </div>
      <div class="pick-reason">${buildPlainReason(s)}</div>
      ${ind ? `<div class="pick-indicators footnote num">
        RSI(14) ${fmtNum(ind.rsi_14, 1)}｜MACD柱 ${fmtNum(ind.macd_hist, 3)}｜
        SMA20 ${fmtNum(ind.sma_20, 2)} / SMA50 ${fmtNum(ind.sma_50, 2)}｜
        量比 ${fmtNum(ind.volume_ratio, 2)}｜ATR% ${fmtNum(ind.atr_pct, 2)}%
      </div>` : ""}
      ${s.news && s.news.length > 0 ? `<div class="pick-news-wrap">
        <div class="footnote">📰 相關新聞</div>
        ${renderNewsList(s.news)}
      </div>` : ""}
      <div class="pick-trade-actions" data-symbol="${s.symbol}" data-price="${s.last_price}"></div>
    </div>`;
  }).join("");

  const toggleHtml = sorted.length > PICK_GRID_COLLAPSE_THRESHOLD
    ? `<button type="button" class="pick-grid-toggle">展開查看全部 ${sorted.length} 檔 ▾</button>`
    : "";
  container.innerHTML = cardsHtml + toggleHtml;

  if (typeof renderTradeButtons === "function") renderTradeButtons(container);
  wirePickGridToggle(container);
}

// Taiwan is the user's primary focus and is the default tab; the other
// markets each get their own tab too (rather than one lumped-together
// "其他市場" list) so a specific market (e.g. gold under 期貨/商品) is a
// click away instead of something to scroll past dozens of Taiwan cards
// to find.
const MARKET_TABS = [
  { key: "taiwan", classes: ["taiwan"] },
  { key: "us", classes: ["equity", "etf"] },
  { key: "futures", classes: ["metal", "energy"] },
  { key: "forex", classes: ["forex"] },
  { key: "crypto", classes: ["crypto"] },
];

function renderSimpleSignals(payload) {
  const signals = (payload.signals || []).filter(passesFilter);
  const filterActive = filterState.query || filterState.hideHold;
  const emptyMessage = filterActive ? "沒有符合搜尋/篩選條件的標的" : "尚無資料";
  MARKET_TABS.forEach((tab) => {
    const tabSignals = signals.filter((s) => tab.classes.includes(s.asset_class));
    renderPickCards(`simple-signals-${tab.key}`, tabSignals, emptyMessage);
  });
}

// Independent of the search/filter above -- always surfaces the handful of
// highest-confidence actionable (non-HOLD) picks across every market, so
// there's an at-a-glance answer before scrolling through 48+ Taiwan cards.
function renderTopPicks(payload) {
  const panel = document.getElementById("top-picks-panel");
  if (!panel) return;
  const actionable = (payload.signals || [])
    .filter((s) => effectiveAction(s) !== "HOLD")
    .slice()
    .sort((a, b) => effectiveConfidence(b) - effectiveConfidence(a))
    .slice(0, 5);

  panel.style.display = actionable.length > 0 ? "" : "none";
  renderPickCards("top-picks", actionable);
}

function renderDecisionBadge(decision) {
  if (!decision) return "-";
  if (decision.vetoed) {
    const vetoReason = (decision.opinions || []).find((o) => o.veto);
    const title = vetoReason ? vetoReason.reasons.join("; ") : "risk veto";
    return `<span class="badge badge-hold" title="${title.replace(/"/g, "&quot;")}">VETO -&gt; HOLD</span>`;
  }
  return `<span class="badge ${badgeClass(decision.action)}">${decision.action} (${(decision.confidence * 100).toFixed(0)}%)</span>`;
}

function renderSignals(payload) {
  const rows = payload.signals
    .slice()
    .sort((a, b) => b.signal.confidence - a.signal.confidence)
    .map((s) => {
      const sig = s.signal;
      const reasons = sig.votes
        .map((v) => `${v.strategy}: ${v.action} (${(v.confidence * 100).toFixed(0)}%)`)
        .join(" · ");
      return `<tr>
        <td data-label="Symbol"><b>${s.symbol}</b></td>
        <td data-label="資產類別">${s.asset_class}</td>
        <td data-label="價格">${fmtNum(s.last_price, 4)}</td>
        <td data-label="訊號"><span class="badge ${badgeClass(sig.final_action)}">${sig.final_action}</span></td>
        <td data-label="信心度">${(sig.confidence * 100).toFixed(1)}%</td>
        <td data-label="市場狀態">${s.regime.state}</td>
        <td data-label="停損">${fmtNum(sig.stop_loss, 4)}</td>
        <td data-label="停利">${fmtNum(sig.take_profit, 4)}</td>
        <td data-label="多代理決策">${renderDecisionBadge(s.decision_engine)}</td>
        <td data-label="細節" class="reasons">${reasons}</td>
      </tr>`;
    })
    .join("");
  document.getElementById("signals-body").innerHTML = rows || `<tr><td colspan="10">尚無資料</td></tr>`;
}

function renderPairs(payload) {
  const pairs = payload.pairs_signals || [];
  const rows = pairs.map((p) => `<tr>
    <td data-label="標的 A"><b>${p.symbol_a}</b></td>
    <td data-label="標的 B"><b>${p.symbol_b}</b></td>
    <td data-label="共整合檢定">${p.cointegrated ? "✅ 通過" : "❌ 未通過"}</td>
    <td data-label="p-value">${fmtNum(p.p_value, 4)}</td>
    <td data-label="價差 Z-score">${fmtNum(p.zscore, 2)}</td>
    <td data-label="避險比率">${fmtNum(p.hedge_ratio, 4)}</td>
    <td data-label="A 動作"><span class="badge ${badgeClass(p.action_a)}">${p.action_a}</span></td>
    <td data-label="B 動作"><span class="badge ${badgeClass(p.action_b)}">${p.action_b}</span></td>
    <td data-label="說明" class="reasons">${(p.reasons || []).join(" · ")}</td>
  </tr>`).join("");
  document.getElementById("pairs-body").innerHTML = rows || `<tr><td colspan="9">尚無資料</td></tr>`;
}

function renderBacktest(payload) {
  const rows = [];
  payload.signals.forEach((s) => {
    Object.entries(s.backtest || {}).forEach(([strategy, m]) => {
      rows.push(`<tr>
        <td data-label="Symbol">${s.symbol}</td><td data-label="策略">${strategy}</td>
        <td data-label="總報酬">${fmtNum(m.total_return_pct)}%</td>
        <td data-label="年化報酬 CAGR">${fmtNum(m.cagr_pct)}%</td>
        <td data-label="Sharpe">${fmtNum(m.sharpe_ratio, 2)}</td>
        <td data-label="Sortino">${fmtNum(m.sortino_ratio, 2)}</td>
        <td data-label="最大回撤 MDD">${fmtNum(m.max_drawdown_pct)}%</td>
        <td data-label="勝率">${fmtNum(m.win_rate_pct)}%</td>
        <td data-label="交易次數">${m.num_trades}</td>
      </tr>`);
    });
  });
  document.getElementById("backtest-body").innerHTML = rows.join("") || `<tr><td colspan="9">尚無資料</td></tr>`;
}

let taiwanLiveStarted = false;

let historyChart;
function renderHistory(history) {
  const canvas = document.getElementById("history-chart");
  if (!history || history.length === 0) return;

  const labels = history.map((h) => new Date(h.generated_at).toLocaleDateString());
  const buyCounts = history.map((h) => h.signals.filter((s) => s.action === "BUY").length);
  const sellCounts = history.map((h) => h.signals.filter((s) => s.action === "SELL").length);

  if (historyChart) historyChart.destroy();
  historyChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "做多", data: buyCounts, borderColor: "#22c55e", backgroundColor: "#22c55e33", tension: 0.3 },
        { label: "做空", data: sellCounts, borderColor: "#ef4444", backgroundColor: "#ef444433", tension: 0.3 },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: "#e6e9f2" } } },
      scales: {
        x: { ticks: { color: "#8b93a7" }, grid: { color: "#232c42" } },
        y: { ticks: { color: "#8b93a7" }, grid: { color: "#232c42" }, beginAtZero: true },
      },
    },
  });
}

let lastPayload = null;

async function loadDashboard() {
  try {
    const resp = await fetch(`${DATA_URL}?t=${Date.now()}`);
    const payload = await resp.json();
    lastPayload = payload;

    document.getElementById("generated-at").textContent =
      "最後更新: " + new Date(payload.generated_at).toLocaleString();
    renderTaiex(payload.taiex);
    renderFearGreed("fear-greed", payload.market_sentiment?.crypto_fear_greed);

    if (typeof paperCacheLatestPrices === "function") paperCacheLatestPrices(payload);
    if (typeof paperAutoTradeTick === "function") paperAutoTradeTick(payload);
    updateChangeTrackingAndNotify(payload);

    renderSummary(payload);
    renderTopPicks(payload);
    renderSimpleSignals(payload);
    renderSignals(payload);
    renderPairs(payload);
    renderBacktest(payload);

    if (!taiwanLiveStarted) {
      const taiwanSymbols = (payload.signals || []).filter((s) => s.asset_class === "taiwan").map((s) => s.symbol);
      startTaiwanLiveQuotes(taiwanSymbols, "live-status-tw");
      taiwanLiveStarted = true;
    }
  } catch (err) {
    document.getElementById("generated-at").textContent = "尚未有資料，等待第一次自動更新";
    console.error(err);
  }

  try {
    const histResp = await fetch(`${HISTORY_URL}?t=${Date.now()}`);
    if (histResp.ok) renderHistory(await histResp.json());
  } catch (err) {
    console.warn("No history yet", err);
  }
}

document.getElementById("refresh-btn").addEventListener("click", loadDashboard);

// Filtering re-renders instantly from the already-fetched payload -- no
// need to hit the network again just to change what's shown.
const searchInput = document.getElementById("signal-search");
if (searchInput) {
  searchInput.addEventListener("input", () => {
    filterState.query = searchInput.value.trim().toLowerCase();
    if (lastPayload) renderSimpleSignals(lastPayload);
  });
}
const hideHoldToggle = document.getElementById("hide-hold-toggle");
if (hideHoldToggle) {
  hideHoldToggle.addEventListener("change", () => {
    filterState.hideHold = hideHoldToggle.checked;
    if (lastPayload) renderSimpleSignals(lastPayload);
  });
}

// Tab panels stay permanently in the DOM (just hidden/shown) rather than
// being torn down and rebuilt on switch -- so #live-status-tw keeps the
// same element identity the whole time, and startTaiwanLiveQuotes' one-time
// captured reference to it never goes stale.
document.querySelectorAll(".market-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".market-tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".market-tab-panel").forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== btn.dataset.tab;
    });
  });
});

refreshNotifyButton();
loadDashboard();
createLiveCryptoTicker("live-crypto", "live-status");
setInterval(loadDashboard, DASHBOARD_REFRESH_MS);
