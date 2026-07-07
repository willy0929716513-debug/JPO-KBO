// Page-specific loader for paper.html. The actual trading engine and
// rendering (paperRenderDashboardPage etc.) live in paper.js, shared with
// index.html's inline trade buttons; this file just fetches the latest
// signals and drives that shared renderer on its own refresh cadence.
const DATA_URL = "data/signals_latest.json";
const PAPER_PAGE_REFRESH_MS = 60_000;

async function loadPaperPage() {
  try {
    const resp = await fetch(`${DATA_URL}?t=${Date.now()}`);
    const payload = await resp.json();

    document.getElementById("generated-at").textContent =
      "資料最後更新: " + new Date(payload.generated_at).toLocaleString();

    paperCacheLatestPrices(payload);
    paperAutoTradeTick(payload);
    paperRenderDashboardPage();
  } catch (err) {
    document.getElementById("generated-at").textContent = "尚未有資料，等待第一次自動更新";
    console.error(err);
  }
  loadServerAutoTrader();
}

document.getElementById("refresh-btn").addEventListener("click", loadPaperPage);
loadPaperPage();
setInterval(loadPaperPage, PAPER_PAGE_REFRESH_MS);

// -----------------------------------------------------------------------
// Always-on server-side auto-trade account (src/pipeline/auto_trader.py):
// unlike the browser-only auto-trade toggle above (which only ever runs
// while this tab is open), this account is advanced once per pipeline run
// -- already happening ~24/7 via the self-chaining GitHub Actions workflow
// -- so it keeps trading whether or not anyone has the dashboard open.
// Purely a read-only display here: the frontend never writes to this
// account, it can only show whatever the last pipeline run computed.
// -----------------------------------------------------------------------
const AUTO_TRADE_STATE_URL = "data/auto_trade_state.json";
let serverAutoEquityChart;

function serverAutoWinRate(stats) {
  const total = stats.wins + stats.losses;
  return total > 0 ? (stats.wins / total) * 100 : null;
}

function serverAutoProfitFactor(stats) {
  if (stats.gross_loss === 0) return stats.gross_profit > 0 ? Infinity : null;
  return stats.gross_profit / stats.gross_loss;
}

async function loadServerAutoTrader() {
  const el = document.getElementById("server-auto-summary");
  if (!el) return;
  try {
    const resp = await fetch(`${AUTO_TRADE_STATE_URL}?t=${Date.now()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const state = await resp.json();
    renderServerAutoTrader(state);
  } catch (err) {
    el.innerHTML = `<p class="footnote">伺服器端自動跟單資料尚未產生，下一次系統自動執行後就會出現。</p>`;
    console.warn("Server auto-trader data unavailable:", err);
  }
}

function renderServerAutoTrader(state) {
  const unrealized = Object.entries(state.positions).reduce((sum, [symbol, pos]) => {
    const cur = PAPER_LATEST_PRICES[symbol];
    if (!cur) return sum;
    const diff = pos.side === "long" ? (cur - pos.avg_price) : (pos.avg_price - cur);
    return sum + diff * pos.qty;
  }, 0);
  const positionsValue = Object.values(state.positions).reduce((sum, p) => sum + p.avg_price * p.qty, 0);
  const equity = state.cash + positionsValue + unrealized;
  const totalPnl = equity - state.starting_cash;
  const totalReturnPct = (totalPnl / state.starting_cash) * 100;
  const pnlCls = (v) => (v >= 0 ? "live-up" : "live-down");

  const summaryEl = document.getElementById("server-auto-summary");
  if (summaryEl) {
    const cards = [
      {
        label: "累積損益", primary: true, cls: pnlCls(totalPnl),
        value: `${totalPnl >= 0 ? "+" : ""}${Math.round(totalPnl).toLocaleString()}（${totalReturnPct >= 0 ? "+" : ""}${fmtNum(totalReturnPct, 2)}%）`,
      },
      { label: "虛擬總資產", value: Math.round(equity).toLocaleString() },
      { label: "現金餘額", value: Math.round(state.cash).toLocaleString() },
      { label: "已實現損益", cls: pnlCls(state.realized_pnl), value: `${state.realized_pnl >= 0 ? "+" : ""}${Math.round(state.realized_pnl).toLocaleString()}` },
    ];
    summaryEl.innerHTML = cards.map((c) =>
      `<div class="card${c.primary ? " card-primary" : ""}"><div class="label">${c.label}</div><div class="value ${c.cls || ""}">${c.value}</div></div>`
    ).join("");
  }

  const canvas = document.getElementById("server-auto-equity-chart");
  const history = state.equity_history || [];
  if (canvas && typeof Chart !== "undefined" && history.length >= 2) {
    if (serverAutoEquityChart) serverAutoEquityChart.destroy();
    const isUp = history[history.length - 1].equity >= state.starting_cash;
    const lineColor = isUp ? "#22c55e" : "#f43f5e";
    serverAutoEquityChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: history.map((h) => new Date(h.time).toLocaleString()),
        datasets: [{
          label: "虛擬總資產", data: history.map((h) => h.equity),
          borderColor: lineColor, backgroundColor: `${lineColor}22`, tension: 0.3, pointRadius: 0, fill: true,
        }],
      },
      options: {
        responsive: true, plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#8b93a7", maxTicksLimit: 6 }, grid: { color: "#232c42" } },
          y: { ticks: { color: "#8b93a7" }, grid: { color: "#232c42" } },
        },
      },
    });
  }

  const positionsEl = document.getElementById("server-auto-positions");
  if (positionsEl) {
    const entries = Object.entries(state.positions);
    if (entries.length === 0) {
      positionsEl.className = "";
      positionsEl.innerHTML = `<p class="footnote">目前沒有伺服器端自動跟單持倉。</p>`;
    } else {
      const cardsHtml = entries.map(([symbol, pos], i) => {
        const cur = PAPER_LATEST_PRICES[symbol];
        const diff = cur ? (pos.side === "long" ? cur - pos.avg_price : pos.avg_price - cur) : 0;
        const pnl = diff * pos.qty;
        const pnlClass = pnl >= 0 ? "live-up" : "live-down";
        const isExtra = i >= PICK_GRID_COLLAPSE_THRESHOLD;
        const heldDays = Math.floor((Date.now() - new Date(pos.opened_at).getTime()) / 86_400_000);
        return `<div class="price-card${isExtra ? " pick-card-extra" : ""}" ${isExtra ? "hidden" : ""}>
          <div class="price-card-head">
            <div class="pick-name">${SYMBOL_NAMES[symbol] || symbol} <span class="pick-symbol">${symbol}</span></div>
            <span class="badge ${pos.side === "long" ? "badge-buy" : "badge-sell"}">${pos.side === "long" ? "做多" : "做空"}</span>
          </div>
          <div class="num">數量 ${pos.qty}｜成本 ${fmtNum(pos.avg_price, 2)}｜現價 ${cur ? fmtNum(cur, 2) : "-"}</div>
          <div class="num ${pnlClass}">未實現損益：${pnl >= 0 ? "+" : ""}${fmtNum(pnl, 0)}</div>
          ${(pos.stop_loss != null || pos.take_profit != null) ? `<div class="num footnote">停損 ${pos.stop_loss != null ? fmtNum(pos.stop_loss, 2) : "-"}｜停利 ${pos.take_profit != null ? fmtNum(pos.take_profit, 2) : "-"}</div>` : ""}
          <div class="footnote">持有 ${heldDays} 天 · 開倉時間 ${new Date(pos.opened_at).toLocaleString()}</div>
        </div>`;
      }).join("");
      const toggleHtml = entries.length > PICK_GRID_COLLAPSE_THRESHOLD
        ? `<button type="button" class="pick-grid-toggle">展開查看全部 ${entries.length} 檔 ▾</button>`
        : "";
      positionsEl.className = "paper-positions-grid";
      positionsEl.innerHTML = cardsHtml + toggleHtml;
      if (typeof wirePickGridToggle === "function") wirePickGridToggle(positionsEl);
    }
  }

  const statsEl = document.getElementById("server-auto-history-stats");
  if (statsEl) {
    const s = state.trade_stats;
    const total = s.wins + s.losses;
    const pf = serverAutoProfitFactor(s);
    const pfLabel = pf === null ? "-" : (pf === Infinity ? "∞" : fmtNum(pf, 2));
    statsEl.textContent = total === 0
      ? "尚無已平倉交易，還沒有統計資料。"
      : `總交易 ${total} 次｜獲利 ${s.wins} 次｜虧損 ${s.losses} 次｜勝率 ${fmtNum(serverAutoWinRate(s), 0)}%｜獲利因子 ${pfLabel}`;
  }

  const historyEl = document.getElementById("server-auto-history-body");
  if (historyEl) {
    const rows = (state.history || []).map((h) => {
      const pnlCls = (h.pnl === undefined || h.pnl === null) ? "" : (h.pnl >= 0 ? "paper-row-win" : "paper-row-loss");
      const actionLabel = h.action === "open" ? "開倉"
        : h.close_reason === "stop_loss" ? "停損出場"
        : h.close_reason === "take_profit" ? "停利出場" : "平倉";
      return `<tr class="${pnlCls}">
        <td data-label="時間">${new Date(h.time).toLocaleString()}</td>
        <td data-label="標的">${SYMBOL_NAMES[h.symbol] || h.symbol}</td>
        <td data-label="方向">${h.side === "long" ? "做多" : "做空"}</td>
        <td data-label="動作">${actionLabel}</td>
        <td data-label="數量">${h.qty}</td>
        <td data-label="價格">${fmtNum(h.price, 2)}</td>
        <td data-label="損益">${(h.pnl === undefined || h.pnl === null) ? "-" : `${h.pnl >= 0 ? "+" : ""}${fmtNum(h.pnl, 0)}`}</td>
      </tr>`;
    }).join("");
    historyEl.innerHTML = rows || `<tr><td colspan="7">尚無交易紀錄</td></tr>`;
  }
}
