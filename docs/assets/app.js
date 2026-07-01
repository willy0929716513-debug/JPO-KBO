const DATA_URL = "data/signals_latest.json";
const HISTORY_URL = "data/history.json";

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
        <td><b>${s.symbol}</b></td>
        <td>${s.asset_class}</td>
        <td>${fmtNum(s.last_price, 4)}</td>
        <td><span class="badge ${badgeClass(sig.final_action)}">${sig.final_action}</span></td>
        <td>${(sig.confidence * 100).toFixed(1)}%</td>
        <td>${s.regime.state}</td>
        <td>${fmtNum(sig.stop_loss, 4)}</td>
        <td>${fmtNum(sig.take_profit, 4)}</td>
        <td class="reasons">${reasons}</td>
      </tr>`;
    })
    .join("");
  document.getElementById("signals-body").innerHTML = rows || `<tr><td colspan="9">尚無資料</td></tr>`;
}

function renderBacktest(payload) {
  const rows = [];
  payload.signals.forEach((s) => {
    Object.entries(s.backtest || {}).forEach(([strategy, m]) => {
      rows.push(`<tr>
        <td>${s.symbol}</td><td>${strategy}</td>
        <td>${fmtNum(m.total_return_pct)}%</td>
        <td>${fmtNum(m.cagr_pct)}%</td>
        <td>${fmtNum(m.sharpe_ratio, 2)}</td>
        <td>${fmtNum(m.sortino_ratio, 2)}</td>
        <td>${fmtNum(m.max_drawdown_pct)}%</td>
        <td>${fmtNum(m.win_rate_pct)}%</td>
        <td>${m.num_trades}</td>
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

document.getElementById("refresh-btn").addEventListener("click", loadDashboard);
loadDashboard();
