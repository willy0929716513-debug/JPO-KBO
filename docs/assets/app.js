const DATA_URL = "data/signals_latest.json";
const HISTORY_URL = "data/history.json";
const DASHBOARD_REFRESH_MS = 60_000; // pipeline data only changes when Actions runs, but this keeps the page current without a manual click
const LIVE_CRYPTO_SYMBOLS = ["btcusdt", "ethusdt"];

// Plain-language translations so the page reads naturally in Chinese
// instead of exposing raw English strategy/regime jargon.
const SYMBOL_NAMES = {
  AAPL: "蘋果", MSFT: "微軟", NVDA: "輝達", TSLA: "特斯拉",
  SPY: "標普500 ETF", QQQ: "那斯達克100 ETF", "2330.TW": "台積電",
  "GC=F": "黃金", "SI=F": "白銀", "CL=F": "原油", "EURUSD=X": "歐元/美元",
  "BTC/USDT": "比特幣", "ETH/USDT": "以太幣",
};
const ACTION_ZH = { BUY: "買進", SELL: "賣出", HOLD: "觀望" };
const REGIME_ZH = {
  bull_trend: "上漲趨勢", bear_trend: "下跌趨勢", range_bound: "區間盤整",
  high_volatility: "波動較大", low_volatility: "走勢平穩", unknown: "資料不足",
};
const FEAR_GREED_ZH = {
  "Extreme Fear": "極度恐慌", "Fear": "恐慌", "Neutral": "中性",
  "Greed": "貪婪", "Extreme Greed": "極度貪婪",
};

function badgeClass(action) {
  if (action === "BUY") return "badge-buy";
  if (action === "SELL") return "badge-sell";
  return "badge-hold";
}

function fmtNum(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function confidenceLabel(c) {
  if (c >= 0.6) return "高";
  if (c >= 0.3) return "中";
  return "低";
}

function confidenceDots(c) {
  const filled = c >= 0.6 ? 3 : c >= 0.3 ? 2 : 1;
  return Array.from({ length: 3 }, (_, i) =>
    `<span class="${i < filled ? "filled" : ""}"></span>`
  ).join("");
}

// The multi-agent risk check can veto a technically-strong signal (e.g. a
// symbol that just hit its drawdown limit) -- this is the single "what
// should I actually do" answer shown on the simple card, folding that veto
// in so the page never shows two contradicting recommendations for one symbol.
function effectiveAction(s) {
  const vetoed = s.decision_engine && s.decision_engine.vetoed;
  return vetoed ? "HOLD" : s.signal.final_action;
}

function buildPlainReason(s) {
  const vetoed = s.decision_engine && s.decision_engine.vetoed;
  if (vetoed) {
    return "⚠️ 風控機制建議暫緩進場（近期虧損或風險超出安全範圍），先觀望比較保險";
  }
  const action = s.signal.final_action;
  const regimeText = REGIME_ZH[s.regime.state] || "資料不足";
  if (action === "BUY") return `目前${regimeText}，多項技術指標偏多，可考慮找機會分批買進`;
  if (action === "SELL") return `目前${regimeText}，多項技術指標偏空，可考慮減碼或先賣出`;
  return `目前${regimeText}，訊號不夠明確，建議先觀望，不用急著進場`;
}

function renderFearGreed(fg) {
  const el = document.getElementById("fear-greed");
  if (!fg || fg.value === null || fg.value === undefined) {
    el.innerHTML = "市場情緒：無資料";
    return;
  }
  const fgZh = FEAR_GREED_ZH[fg.classification] || fg.classification;
  const pct = Math.max(0, Math.min(100, fg.value));
  el.innerHTML = `市場情緒：${fgZh}（${fg.value}）
    <span class="fg-gauge"><span class="fg-gauge-track"><span class="fg-gauge-thumb" style="left:${pct}%"></span></span></span>`;
}

function renderSummary(payload) {
  const counts = { BUY: 0, SELL: 0, HOLD: 0 };
  payload.signals.forEach((s) => counts[effectiveAction(s)]++);

  const cards = [
    { label: "分析標的數", value: `${payload.successful} / ${payload.watchlist_size}` },
    { label: "建議買進", value: counts.BUY },
    { label: "建議賣出", value: counts.SELL },
    { label: "建議觀望", value: counts.HOLD },
  ];

  document.getElementById("summary-cards").innerHTML = cards
    .map((c) => `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`)
    .join("");
}

function renderSimpleSignals(payload) {
  const container = document.getElementById("simple-signals");
  container.className = "pick-grid";
  const signals = payload.signals || [];
  if (signals.length === 0) {
    container.innerHTML = `<p class="footnote">尚無資料</p>`;
    return;
  }

  const sorted = signals.slice().sort((a, b) => {
    const rank = (s) => (effectiveAction(s) === "HOLD" ? 1 : 0);
    const diff = rank(a) - rank(b);
    return diff !== 0 ? diff : b.signal.confidence - a.signal.confidence;
  });

  container.innerHTML = sorted.map((s, i) => {
    const sig = s.signal;
    const action = effectiveAction(s);
    const name = SYMBOL_NAMES[s.symbol] || s.symbol;
    const conf = (s.decision_engine && s.decision_engine.vetoed) ? 0 : sig.confidence;

    return `<div class="pick-card ${badgeClass(action)}-card" style="animation-delay:${Math.min(i * 35, 350)}ms">
      <div class="pick-head">
        <div class="pick-name">${name} <span class="pick-symbol">${s.symbol}</span></div>
        <div class="pick-action badge ${badgeClass(action)}">${ACTION_ZH[action]}</div>
      </div>
      <div class="pick-price">目前價格：<b class="num">${fmtNum(s.last_price, 4)}</b></div>
      <div class="pick-levels num">
        <span>建議停損：${fmtNum(sig.stop_loss, 4)}</span>
        <span>建議停利：${fmtNum(sig.take_profit, 4)}</span>
      </div>
      <div class="confidence-row">
        信心程度：${confidenceLabel(conf)}
        <span class="confidence-dots">${confidenceDots(conf)}</span>
      </div>
      <div class="pick-reason">${buildPlainReason(s)}</div>
    </div>`;
  }).join("");
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
    renderFearGreed(payload.market_sentiment?.crypto_fear_greed);

    renderSummary(payload);
    renderSimpleSignals(payload);
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
  const statusDot = document.getElementById("live-status");
  if (!container) return;

  const streams = LIVE_CRYPTO_SYMBOLS.map((s) => `${s}@ticker`).join("/");
  const ws = new WebSocket(`wss://stream.binance.com:9443/stream?streams=${streams}`);
  const lastPrices = {};
  let itemsBuilt = false;

  const buildItems = () => {
    container.innerHTML = LIVE_CRYPTO_SYMBOLS.map((s) =>
      `<div class="live-price-item" id="live-${s}">
        <span class="live-symbol">${s.replace("usdt", "").toUpperCase()}/USDT</span>
        <span class="live-value num">連線中...</span>
      </div>`
    ).join("");
    itemsBuilt = true;
  };

  const updateItem = (s, data, prevPrice) => {
    const el = document.getElementById(`live-${s}`);
    if (!el) return;
    const changeClass = data.changePct >= 0 ? "live-up" : "live-down";
    const arrow = data.changePct >= 0 ? "▲" : "▼";
    el.innerHTML = `
      <span class="live-symbol">${s.replace("usdt", "").toUpperCase()}/USDT</span>
      <span class="live-value num">${fmtNum(data.price, 2)}</span>
      <span class="live-change ${changeClass}">${arrow} ${fmtNum(Math.abs(data.changePct), 2)}%</span>`;

    if (prevPrice !== undefined && prevPrice !== data.price) {
      el.classList.remove("live-flash-up", "live-flash-down");
      // reflow so the animation can be re-triggered on rapid consecutive ticks
      void el.offsetWidth;
      el.classList.add(data.price > prevPrice ? "live-flash-up" : "live-flash-down");
    }
  };

  ws.onopen = () => {
    if (statusDot) statusDot.style.display = "inline-block";
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      const ticker = msg.data;
      if (!ticker || !ticker.s) return;
      if (!itemsBuilt) buildItems();
      const symbol = ticker.s.toLowerCase();
      const prevPrice = lastPrices[symbol]?.price;
      const data = { price: parseFloat(ticker.c), changePct: parseFloat(ticker.P) };
      lastPrices[symbol] = data;
      updateItem(symbol, data, prevPrice);
    } catch (err) {
      console.warn("live ticker parse error", err);
    }
  };

  ws.onerror = () => {
    if (statusDot) statusDot.style.display = "none";
    container.innerHTML = `<div class="live-price-item">即時報價連線失敗（可能是網路封鎖了 WebSocket），股票/黃金等其他標的價格不受影響</div>`;
  };

  buildItems();
}

document.getElementById("refresh-btn").addEventListener("click", loadDashboard);
loadDashboard();
startLiveCryptoTicker();
setInterval(loadDashboard, DASHBOARD_REFRESH_MS);
