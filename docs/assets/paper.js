// Client-side "paper trading" simulator shared by index.html (inline
// 模擬做多/做空 buttons on each pick-card) and paper.html (the dedicated
// virtual portfolio page). There is no backend on this static site, so the
// whole thing lives in this browser's localStorage:
//   - a virtual wallet only exists on this device/browser (clearing site
//     data or switching browsers resets it, no cross-device sync)
//   - "自動跟單" only evaluates while a page that loads this script is
//     actually open in a tab -- it cannot trade in the background when the
//     browser is closed, since that would require a server.
// Relies on SYMBOL_NAMES / ACTION_ZH / fmtNum / effectiveAction from
// common.js, loaded before this file.
const PAPER_STORAGE_KEY = "quantDashboardPaperTrading_v1";
const PAPER_STARTING_CASH = 1_000_000; // virtual TWD
const PAPER_MANUAL_DEFAULT_NOTIONAL = 100_000; // suggested size for a manual trade
const PAPER_AUTO_TRADE_NOTIONAL = PAPER_STARTING_CASH * 0.1; // fixed virtual lot per auto-followed signal

let PAPER_LATEST_PRICES = {};

function paperLoadState() {
  try {
    const raw = localStorage.getItem(PAPER_STORAGE_KEY);
    if (raw) {
      const state = JSON.parse(raw);
      if (state && typeof state === "object" && state.positions) return state;
    }
  } catch (err) {
    console.warn("Paper trading state was corrupted, resetting.", err);
  }
  return { cash: PAPER_STARTING_CASH, positions: {}, history: [], autoTradeEnabled: false, equityHistory: [] };
}

function paperSaveState(state) {
  localStorage.setItem(PAPER_STORAGE_KEY, JSON.stringify(state));
}

function paperResetState() {
  if (!confirm("確定要重置模擬帳戶嗎？所有虛擬持倉與紀錄都會清空，恢復成 100 萬虛擬台幣。")) return;
  localStorage.removeItem(PAPER_STORAGE_KEY);
  location.reload();
}

function paperComputeEquity(state) {
  const unrealized = Object.entries(state.positions).reduce(
    (sum, [symbol, pos]) => sum + paperUnrealizedPnl(pos, PAPER_LATEST_PRICES[symbol]), 0);
  const positionsValue = Object.entries(state.positions).reduce(
    (sum, [, pos]) => sum + pos.avgPrice * pos.qty, 0);
  return state.cash + positionsValue + unrealized;
}

// Appends one {time, equity} point every time fresh prices come in (from
// either page that loads this script), so paper.html can plot an equity
// curve. Capped to the last 300 points -- plenty for a 5-minute-cadence
// dashboard without letting localStorage grow unbounded.
function paperRecordEquitySnapshot(state) {
  state.equityHistory = state.equityHistory || [];
  state.equityHistory.push({ time: new Date().toISOString(), equity: paperComputeEquity(state) });
  state.equityHistory = state.equityHistory.slice(-300);
}

function paperCacheLatestPrices(payload) {
  (payload.signals || []).forEach((s) => {
    if (typeof s.last_price === "number") PAPER_LATEST_PRICES[s.symbol] = s.last_price;
  });
  const state = paperLoadState();
  paperRecordEquitySnapshot(state);
  paperSaveState(state);
}

function paperPushHistory(state, entry) {
  state.history.unshift({ time: new Date().toISOString(), ...entry });
  state.history = state.history.slice(0, 200);
}

function paperOpenPosition(symbol, side, price, qty, source) {
  if (!price || !qty || qty <= 0) return;
  const state = paperLoadState();
  if (state.positions[symbol]) {
    alert("這檔已經有模擬持倉了，請先平倉再開新倉。");
    return;
  }
  const notional = price * qty;
  if (notional > state.cash) {
    alert(`虛擬資金不足：這筆需要 ${Math.round(notional).toLocaleString()}，目前剩餘 ${Math.round(state.cash).toLocaleString()}。`);
    return;
  }
  state.cash -= notional;
  state.positions[symbol] = { side, qty, avgPrice: price, openedAt: new Date().toISOString(), source };
  paperPushHistory(state, { symbol, side, action: "open", qty, price, source });
  paperSaveState(state);
  paperRenderAll();
}

function paperClosePositionAtPrice(symbol, price, state) {
  const pos = state.positions[symbol];
  if (!pos || !price) return state;
  const pnl = pos.side === "long" ? (price - pos.avgPrice) * pos.qty : (pos.avgPrice - price) * pos.qty;
  state.cash += pos.avgPrice * pos.qty + pnl;
  paperPushHistory(state, { symbol, side: pos.side, action: "close", qty: pos.qty, price, pnl, source: pos.source });
  delete state.positions[symbol];
  return state;
}

function paperClosePosition(symbol) {
  const price = PAPER_LATEST_PRICES[symbol];
  if (!price) {
    alert("目前沒有這檔的最新價格，稍後再試一次。");
    return;
  }
  const state = paperClosePositionAtPrice(symbol, price, paperLoadState());
  paperSaveState(state);
  paperRenderAll();
}

function paperPromptOpen(symbol, side) {
  const price = PAPER_LATEST_PRICES[symbol];
  if (!price) {
    alert("目前沒有這檔的最新價格，稍後再試一次。");
    return;
  }
  const sideZh = side === "long" ? "做多" : "做空";
  const suggested = Math.max(1, Math.floor(PAPER_MANUAL_DEFAULT_NOTIONAL / price));
  const input = window.prompt(`要模擬${sideZh} ${SYMBOL_NAMES[symbol] || symbol} 幾單位？（目前價格 ${fmtNum(price, 2)}，預設約 10 萬虛擬台幣）`, suggested);
  if (input === null) return;
  const qty = parseInt(input, 10);
  if (!qty || qty <= 0) return;
  paperOpenPosition(symbol, side, price, qty, "manual");
}

function paperSetAutoTrade(enabled) {
  const state = paperLoadState();
  state.autoTradeEnabled = enabled;
  paperSaveState(state);
}

// Follows the dashboard's own recommendations: opens a fixed-size virtual
// long/short when a symbol newly signals BUY/SELL, and closes it once that
// symbol's signal flips or drops back to HOLD. Only touches positions this
// auto-trader itself opened (source === "auto") so it never interferes
// with a manually-opened position on the same symbol.
function paperAutoTradeTick(payload) {
  let state = paperLoadState();
  if (!state.autoTradeEnabled) return;

  (payload.signals || []).forEach((s) => {
    const price = s.last_price;
    if (!price) return;
    const action = effectiveAction(s);
    const existing = state.positions[s.symbol];

    if (existing && existing.source === "auto") {
      const wantSide = action === "BUY" ? "long" : action === "SELL" ? "short" : null;
      if (wantSide !== existing.side) {
        state = paperClosePositionAtPrice(s.symbol, price, state);
      }
    } else if (!existing && (action === "BUY" || action === "SELL")) {
      const qty = Math.floor(PAPER_AUTO_TRADE_NOTIONAL / price);
      const notional = qty * price;
      if (qty > 0 && notional <= state.cash) {
        state.cash -= notional;
        state.positions[s.symbol] = { side: action === "BUY" ? "long" : "short", qty, avgPrice: price, openedAt: new Date().toISOString(), source: "auto" };
        paperPushHistory(state, { symbol: s.symbol, side: action === "BUY" ? "long" : "short", action: "open", qty, price, source: "auto" });
      }
    }
  });

  paperSaveState(state);
}

function paperUnrealizedPnl(pos, currentPrice) {
  if (!currentPrice) return 0;
  return pos.side === "long" ? (currentPrice - pos.avgPrice) * pos.qty : (pos.avgPrice - currentPrice) * pos.qty;
}

// Renders the 模擬做多/做空/平倉 controls embedded in each pick-card's
// `.pick-trade-actions` placeholder (index.html only -- a no-op elsewhere
// since querySelectorAll just finds nothing).
function renderTradeButtons(scopeEl) {
  const state = paperLoadState();
  const els = (scopeEl || document).querySelectorAll(".pick-trade-actions");
  els.forEach((el) => {
    const symbol = el.dataset.symbol;
    const pos = state.positions[symbol];
    if (pos) {
      const cur = PAPER_LATEST_PRICES[symbol] ?? parseFloat(el.dataset.price);
      const pnl = paperUnrealizedPnl(pos, cur);
      const pnlClass = pnl >= 0 ? "live-up" : "live-down";
      el.innerHTML = `<div class="paper-position-badge">
        <span>模擬持倉：${pos.side === "long" ? "做多" : "做空"} ${pos.qty} 單位 @ ${fmtNum(pos.avgPrice, 2)}（金額 ${Math.round(pos.avgPrice * pos.qty).toLocaleString()}）</span>
        <span class="${pnlClass}">未實現損益 ${pnl >= 0 ? "+" : ""}${fmtNum(pnl, 0)}</span>
        <button class="pill pill-btn small" onclick="paperClosePosition('${symbol}')">模擬平倉</button>
      </div>`;
    } else {
      el.innerHTML = `
        <button class="pill pill-btn small" onclick="paperPromptOpen('${symbol}', 'long')">模擬做多</button>
        <button class="pill pill-btn small" onclick="paperPromptOpen('${symbol}', 'short')">模擬做空</button>`;
    }
  });
}

let paperEquityChart;

// No-ops on index.html (no #paper-equity-chart canvas there, and Chart.js
// isn't even loaded on that page). Needs at least 2 points to draw a line.
function paperRenderEquityChart(state) {
  const canvas = document.getElementById("paper-equity-chart");
  if (!canvas || typeof Chart === "undefined") return;
  const history = state.equityHistory || [];
  if (history.length < 2) return;

  if (paperEquityChart) paperEquityChart.destroy();
  paperEquityChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: history.map((h) => new Date(h.time).toLocaleString()),
      datasets: [{
        label: "虛擬總資產", data: history.map((h) => h.equity),
        borderColor: "#5b8cff", backgroundColor: "#5b8cff22", tension: 0.3, pointRadius: 0, fill: true,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8b93a7", maxTicksLimit: 6 }, grid: { color: "#232c42" } },
        y: { ticks: { color: "#8b93a7" }, grid: { color: "#232c42" } },
      },
    },
  });
}

// Full portfolio view for paper.html: summary cards, open positions
// (with live-ish unrealized P&L and a close button), and recent history.
// No-ops if the page doesn't have these elements (e.g. when paper.js is
// loaded on index.html just for the inline trade buttons).
function paperRenderDashboardPage() {
  const state = paperLoadState();

  const toggle = document.getElementById("paper-auto-toggle");
  if (toggle) toggle.checked = !!state.autoTradeEnabled;

  const unrealized = Object.entries(state.positions).reduce(
    (sum, [symbol, pos]) => sum + paperUnrealizedPnl(pos, PAPER_LATEST_PRICES[symbol]), 0);
  const equity = paperComputeEquity(state);

  const summaryEl = document.getElementById("paper-summary");
  if (summaryEl) {
    const totalPnl = equity - PAPER_STARTING_CASH;
    const cards = [
      { label: "虛擬總資產", value: Math.round(equity).toLocaleString() },
      { label: "現金餘額", value: Math.round(state.cash).toLocaleString() },
      { label: "未實現損益", value: `${unrealized >= 0 ? "+" : ""}${Math.round(unrealized).toLocaleString()}` },
      { label: "累積損益", value: `${totalPnl >= 0 ? "+" : ""}${Math.round(totalPnl).toLocaleString()}` },
    ];
    summaryEl.innerHTML = cards.map((c) => `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`).join("");
  }

  paperRenderEquityChart(state);

  const positionsEl = document.getElementById("paper-positions");
  if (positionsEl) {
    const entries = Object.entries(state.positions);
    if (entries.length === 0) {
      positionsEl.innerHTML = `<p class="footnote">目前沒有模擬持倉。可以到「今日建議」頁面針對個股點「模擬做多/做空」，或開啟下面的自動跟單。</p>`;
    } else {
      positionsEl.innerHTML = entries.map(([symbol, pos]) => {
        const cur = PAPER_LATEST_PRICES[symbol];
        const pnl = paperUnrealizedPnl(pos, cur);
        const pnlClass = pnl >= 0 ? "live-up" : "live-down";
        return `<div class="price-card">
          <div class="price-card-head">
            <div class="pick-name">${SYMBOL_NAMES[symbol] || symbol} <span class="pick-symbol">${symbol}</span></div>
            <span class="badge ${pos.side === "long" ? "badge-buy" : "badge-sell"}">${pos.side === "long" ? "做多" : "做空"}</span>
          </div>
          <div class="num">數量 ${pos.qty}｜成本 ${fmtNum(pos.avgPrice, 2)}｜現價 ${fmtNum(cur, 2)}</div>
          <div class="num footnote">開倉金額：${Math.round(pos.avgPrice * pos.qty).toLocaleString()}</div>
          <div class="num ${pnlClass}">未實現損益：${pnl >= 0 ? "+" : ""}${fmtNum(pnl, 0)}</div>
          <div class="footnote">來源：${pos.source === "auto" ? "自動跟單" : "手動模擬"} · 開倉時間 ${new Date(pos.openedAt).toLocaleString()}</div>
          <button class="pill pill-btn small" onclick="paperClosePosition('${symbol}')">模擬平倉</button>
        </div>`;
      }).join("");
      positionsEl.className = "paper-positions-grid";
    }
  }

  const historyEl = document.getElementById("paper-history-body");
  if (historyEl) {
    const rows = state.history.map((h) => `<tr>
      <td data-label="時間">${new Date(h.time).toLocaleString()}</td>
      <td data-label="標的">${SYMBOL_NAMES[h.symbol] || h.symbol}</td>
      <td data-label="方向">${h.side === "long" ? "做多" : "做空"}</td>
      <td data-label="動作">${h.action === "open" ? "開倉" : "平倉"}</td>
      <td data-label="數量">${h.qty}</td>
      <td data-label="價格">${fmtNum(h.price, 2)}</td>
      <td data-label="金額">${Math.round(h.qty * h.price).toLocaleString()}</td>
      <td data-label="損益">${h.pnl === undefined ? "-" : `${h.pnl >= 0 ? "+" : ""}${fmtNum(h.pnl, 0)}`}</td>
      <td data-label="來源">${h.source === "auto" ? "自動跟單" : "手動"}</td>
    </tr>`).join("");
    historyEl.innerHTML = rows || `<tr><td colspan="9">尚無交易紀錄</td></tr>`;
  }
}

function paperRenderAll() {
  renderTradeButtons(document);
  paperRenderDashboardPage();
}
