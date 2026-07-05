// Shared constants/helpers used by both index.html (app.js) and
// prices.html (prices.js). Loaded first via a plain <script> tag on both
// pages -- no build step/bundler on this static site, so this is the
// simplest way to avoid duplicating the same translation tables and
// live-ticker logic in two places.

const SYMBOL_NAMES = {
  AAPL: "蘋果", MSFT: "微軟", NVDA: "輝達", TSLA: "特斯拉",
  SPY: "標普500 ETF", QQQ: "那斯達克100 ETF",
  "2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科",
  "2308.TW": "台達電", "2382.TW": "廣達", "2303.TW": "聯電",
  "2881.TW": "富邦金", "2882.TW": "國泰金", "2412.TW": "中華電",
  "1301.TW": "台塑", "2603.TW": "長榮", "3711.TW": "日月光投控",
  "0050.TW": "元大台灣50",
  "GC=F": "黃金", "SI=F": "白銀", "CL=F": "原油", "EURUSD=X": "歐元/美元",
  "BTC/USDT": "比特幣", "ETH/USDT": "以太幣",
};
// 做多 = go long (buy to profit from a rise), 做空 = go short (sell/borrow
// to profit from a fall) -- matches how the user actually trades, rather
// than a plain spot buy/sell framing.
const ACTION_ZH = { BUY: "做多", SELL: "做空", HOLD: "觀望" };
const REGIME_ZH = {
  bull_trend: "上漲趨勢", bear_trend: "下跌趨勢", range_bound: "區間盤整",
  high_volatility: "波動較大", low_volatility: "走勢平穩", unknown: "資料不足",
};
const FEAR_GREED_ZH = {
  "Extreme Fear": "極度恐慌", "Fear": "恐慌", "Neutral": "中性",
  "Greed": "貪婪", "Extreme Greed": "極度貪婪",
};
const ASSET_CLASS_ZH = {
  equity: "股票", etf: "ETF", taiwan: "台股", metal: "貴金屬期貨",
  energy: "能源期貨", forex: "外匯", crypto: "加密貨幣",
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
// should I actually do" answer, folding that veto in so the page never
// shows two contradicting recommendations for one symbol.
function effectiveAction(s) {
  const vetoed = s.decision_engine && s.decision_engine.vetoed;
  return vetoed ? "HOLD" : s.signal.final_action;
}

function renderFearGreed(elementId, fg) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (!fg || fg.value === null || fg.value === undefined) {
    el.innerHTML = "市場情緒：無資料";
    return;
  }
  const fgZh = FEAR_GREED_ZH[fg.classification] || fg.classification;
  const pct = Math.max(0, Math.min(100, fg.value));
  el.innerHTML = `市場情緒：${fgZh}（${fg.value}）
    <span class="fg-gauge"><span class="fg-gauge-track"><span class="fg-gauge-thumb" style="left:${pct}%"></span></span></span>`;
}

function marketStatusBadge(marketOpen) {
  if (marketOpen === false) return `<span class="market-status market-closed">⚪ 已收盤</span>`;
  return `<span class="market-status market-open">🟢 開盤中</span>`;
}

// Genuinely real-time prices via Binance's public WebSocket ticker stream --
// free, no API key, and works directly from a static page since WebSocket
// isn't subject to the CORS restrictions a plain fetch to most market-data
// REST APIs would hit. `containerId` holds the price items; `statusDotId`
// (optional) is toggled visible while the socket is connected.
function createLiveCryptoTicker(containerId, statusDotId, symbols = ["btcusdt", "ethusdt"]) {
  const container = document.getElementById(containerId);
  const statusDot = statusDotId ? document.getElementById(statusDotId) : null;
  if (!container) return;

  const streams = symbols.map((s) => `${s}@ticker`).join("/");
  const ws = new WebSocket(`wss://stream.binance.com:9443/stream?streams=${streams}`);
  const lastPrices = {};
  let itemsBuilt = false;

  const buildItems = () => {
    container.innerHTML = symbols.map((s) =>
      `<div class="live-price-item" id="${containerId}-${s}">
        <span class="live-symbol">${s.replace("usdt", "").toUpperCase()}/USDT</span>
        <span class="live-value num">連線中...</span>
      </div>`
    ).join("");
    itemsBuilt = true;
  };

  const updateItem = (s, data, prevPrice) => {
    const el = document.getElementById(`${containerId}-${s}`);
    if (!el) return;
    const changeClass = data.changePct >= 0 ? "live-up" : "live-down";
    const arrow = data.changePct >= 0 ? "▲" : "▼";
    el.innerHTML = `
      <span class="live-symbol">${s.replace("usdt", "").toUpperCase()}/USDT</span>
      <span class="live-value num">${fmtNum(data.price, 2)}</span>
      <span class="live-change ${changeClass}">${arrow} ${fmtNum(Math.abs(data.changePct), 2)}%</span>`;

    if (prevPrice !== undefined && prevPrice !== data.price) {
      el.classList.remove("live-flash-up", "live-flash-down");
      void el.offsetWidth; // reflow so the animation can retrigger on rapid consecutive ticks
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
    container.innerHTML = `<div class="live-price-item">即時報價連線失敗（可能是網路封鎖了 WebSocket），其他標的價格不受影響</div>`;
  };

  buildItems();
}
