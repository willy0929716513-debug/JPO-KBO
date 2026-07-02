const DATA_URL = "data/signals_latest.json";
const HISTORY_URL = "data/history.json";
const DASHBOARD_REFRESH_MS = 60_000; // pipeline data only changes when Actions runs, but this keeps the page current without a manual click
const LIVE_CRYPTO_SYMBOLS = ["btcusdt", "ethusdt"];

function badgeClass(action) {
  if (action === "BUY") return "badge-buy";
  if (action === "SELL") return "badge-sell";
  return "badge-hold";
}

function fmtNum(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function renderSummary(payload) {
  const counts = { BUY: 0, SELL: 0, HOLD: 0 };
  payload.signals.forEach((s) => counts[s.signal.final_action]++);

  const cards = [
    { label: "分析標的數", value: `${payload.successful} / ${payload.watchlist_size}` },
    { label: "BUY 訊號", value: counts.BUY },
    { label: "SELL 訊號", value: counts.SELL },
    { label: "HOLD 訊號", value: counts.HOLD },
  ];

  document.getElementById("summary-cards").innerHTML = cards
    .map((c) => `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`)
    .join("");
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
        { label: "BUY", data: buyCounts, borderColor: "#22c55e", backgroundColor: "#22c55e33", tension: 0.3 },
        { label: "SELL", data: sellCounts, borderColor: "#ef4444", backgroundColor: "#ef444433", tension: 0.3 },
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

async function loadDashboard() {
  try {
    const resp = await fetch(`${DATA_URL}?t=${Date.now()}`);
    const payload = await resp.json();

    document.getElementById("generated-at").textContent =
      "最後更新: " + new Date(payload.generated_at).toLocaleString();
    const fg = payload.market_sentiment?.crypto_fear_greed;
    document.getElementById("fear-greed").textContent =
      fg && fg.value !== null ? `Fear & Greed: ${fg.value} (${fg.classification})` : "Fear & Greed: N/A";

    renderSummary(payload);
    renderSignals(payload);
    renderPairs(payload);
    renderBacktest(payload);
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

// Genuinely real-time crypto prices via Binance's public WebSocket ticker
// stream -- free, no API key, and works directly from a static page since
// WebSocket isn't subject to the CORS restrictions that a plain fetch to
// most market-data REST APIs would hit. Stocks/gold/forex have no free
// real-time equivalent (see README), so those stay on the periodic
// pipeline refresh below instead of pretending to be live.
function startLiveCryptoTicker() {
  const container = document.getElementById("live-crypto");
  if (!container) return;

  const streams = LIVE_CRYPTO_SYMBOLS.map((s) => `${s}@ticker`).join("/");
  const ws = new WebSocket(`wss://stream.binance.com:9443/stream?streams=${streams}`);
  const lastPrices = {};

  const render = () => {
    container.innerHTML = LIVE_CRYPTO_SYMBOLS.map((s) => {
      const data = lastPrices[s];
      if (!data) return `<div class="live-price-item"><span class="live-symbol">${s.toUpperCase()}</span><span class="live-value">連線中...</span></div>`;
      const changeClass = data.changePct >= 0 ? "live-up" : "live-down";
      const arrow = data.changePct >= 0 ? "▲" : "▼";
      return `<div class="live-price-item">
        <span class="live-symbol">${s.replace("usdt", "").toUpperCase()}/USDT</span>
        <span class="live-value">${fmtNum(data.price, 2)}</span>
        <span class="live-change ${changeClass}">${arrow} ${fmtNum(Math.abs(data.changePct), 2)}%</span>
      </div>`;
    }).join("");
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      const ticker = msg.data;
      if (!ticker || !ticker.s) return;
      const symbol = ticker.s.toLowerCase();
      lastPrices[symbol] = { price: parseFloat(ticker.c), changePct: parseFloat(ticker.P) };
      render();
    } catch (err) {
      console.warn("live ticker parse error", err);
    }
  };

  ws.onerror = () => {
    container.innerHTML = `<div class="live-price-item">即時報價連線失敗（可能是網路封鎖了 WebSocket），股票/黃金等其他標的價格不受影響</div>`;
  };

  render();
}

document.getElementById("refresh-btn").addEventListener("click", loadDashboard);
loadDashboard();
startLiveCryptoTicker();
setInterval(loadDashboard, DASHBOARD_REFRESH_MS);
