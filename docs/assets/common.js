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
  "2002.TW": "中鋼", "1216.TW": "統一", "2886.TW": "兆豐金",
  "2891.TW": "中信金", "2892.TW": "第一金", "2884.TW": "玉山金",
  "2885.TW": "元大金", "2880.TW": "華南金", "5880.TW": "合庫金",
  "2887.TW": "台新金", "2890.TW": "永豐金", "1101.TW": "台泥",
  "1303.TW": "南亞", "1326.TW": "台化", "2379.TW": "瑞昱",
  "2357.TW": "華碩", "2353.TW": "宏碁", "2408.TW": "南亞科",
  "2609.TW": "陽明", "2615.TW": "萬海", "3034.TW": "聯詠",
  "3037.TW": "欣興", "3045.TW": "台灣大", "4904.TW": "遠傳",
  "2207.TW": "和泰車", "9910.TW": "豐泰", "6505.TW": "台塑化",
  "2395.TW": "研華", "3008.TW": "大立光", "2409.TW": "友達",
  "3231.TW": "緯創", "2324.TW": "仁寶", "2327.TW": "國巨",
  "5871.TW": "中租-KY", "2377.TW": "微星",
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

// News titles/publishers come from an external API (Yahoo Finance), unlike
// our own static translation tables -- escape before inserting into
// innerHTML so a stray "<"/"&" in a headline can't be interpreted as markup.
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// published_at is either an ISO string (current yfinance news schema's
// "pubDate") or a Unix timestamp *in seconds* (legacy "providerPublishTime")
// -- `new Date()` expects milliseconds, so a raw seconds value must be
// scaled up first or it parses as a date in 1970.
function formatNewsDate(publishedAt) {
  if (!publishedAt) return "";
  const ms = typeof publishedAt === "number" && publishedAt < 1e12 ? publishedAt * 1000 : publishedAt;
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

function renderNewsList(news) {
  if (!news || news.length === 0) return "";
  const items = news.map((n) => {
    const publisher = n.publisher ? `${escapeHtml(n.publisher)} · ` : "";
    return `<li><a href="${escapeHtml(n.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(n.title)}</a>
      <span class="footnote">${publisher}${formatNewsDate(n.published_at)}</span></li>`;
  }).join("");
  return `<ul class="pick-news">${items}</ul>`;
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

// Best-effort near-real-time quotes for Taiwan stocks via TWSE's public
// (undocumented, no API key) MIS quote endpoint. Unlike Binance's
// WebSocket this is a plain polled REST endpoint behind an ordinary CORS
// policy that can vary or change without notice -- if the browser blocks
// it (CORS, corporate network, TWSE-side change, etc.) this silently gives
// up after a couple of failed attempts, and the page just keeps showing
// the regular 5-minute-refreshed price from signals_latest.json. A block
// here can never break the rest of the dashboard.
function startTaiwanLiveQuotes(symbols, statusDotId) {
  if (!symbols || symbols.length === 0) return;
  const statusDot = statusDotId ? document.getElementById(statusDotId) : null;
  const exCh = symbols.map((s) => `tse_${s.replace(".TW", "")}.tw`).join("|");
  const url = `https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=${exCh}`;
  const lastPrices = {};
  let failCount = 0;
  let timer = null;

  const tick = async () => {
    try {
      const resp = await fetch(`${url}&_=${Date.now()}`, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const rows = data.msgArray || [];
      if (rows.length === 0) throw new Error("empty msgArray");

      failCount = 0;
      if (statusDot) statusDot.style.display = "inline-block";

      rows.forEach((row) => {
        const symbol = `${row.c}.TW`;
        const price = parseFloat(row.z);
        if (!price || Number.isNaN(price)) return;
        const prevPrice = lastPrices[symbol];
        lastPrices[symbol] = price;

        document.querySelectorAll(`[data-symbol="${symbol}"] .js-live-price`).forEach((el) => {
          el.textContent = fmtNum(price, 2);
          if (prevPrice !== undefined && prevPrice !== price) {
            el.classList.remove("live-flash-up", "live-flash-down");
            void el.offsetWidth; // reflow so the flash can retrigger on rapid consecutive ticks
            el.classList.add(price > prevPrice ? "live-flash-up" : "live-flash-down");
          }
        });
      });
    } catch (err) {
      failCount += 1;
      if (failCount >= 2) {
        if (statusDot) statusDot.style.display = "none";
        if (timer) clearInterval(timer);
        console.warn("TWSE live quotes unavailable -- keeping the 5-minute-refreshed price instead.", err);
      }
    }
  };

  timer = setInterval(tick, 15000);
  tick();
}

// The splash screen (#app-splash, present on every page) fades itself out
// via a CSS animation; this just removes the now-invisible element from
// the DOM afterwards so it can't linger in the accessibility tree or catch
// a stray click. No-op if a page doesn't have a splash element.
(function cleanupSplashScreen() {
  const splash = document.getElementById("app-splash");
  if (!splash) return;
  splash.addEventListener("animationend", (event) => {
    if (event.animationName === "splashFadeOut") splash.remove();
  });
})();

// Opt-in browser notifications for "a symbol's signal just flipped to a
// strong BUY/SELL" -- opt-in because browsers refuse to even show the
// permission prompt unless it's triggered by a real user click, and
// because auto-prompting on page load is a bad, spammy pattern users
// (rightly) distrust.
const NOTIFY_PREF_KEY = "quantDashboardNotifyEnabled_v1";

function notificationsSupported() {
  return typeof Notification !== "undefined";
}

function notificationsEnabled() {
  return notificationsSupported() && Notification.permission === "granted" && localStorage.getItem(NOTIFY_PREF_KEY) === "true";
}

function requestNotificationPermission() {
  if (!notificationsSupported()) {
    alert("這個瀏覽器不支援通知功能。");
    return;
  }
  if (Notification.permission === "denied") {
    alert("瀏覽器先前已封鎖這個網站的通知權限，需要到瀏覽器的網站設定裡手動重新允許。");
    return;
  }
  Notification.requestPermission().then((perm) => {
    localStorage.setItem(NOTIFY_PREF_KEY, perm === "granted" ? "true" : "false");
    if (typeof refreshNotifyButton === "function") refreshNotifyButton();
    if (perm === "granted") {
      new Notification("量化訊號小幫手", { body: "通知已開啟，之後有標的轉為強烈做多/做空訊號時會提醒你。", icon: "icons/icon-192.png" });
    }
  });
}

function disableNotifications() {
  localStorage.setItem(NOTIFY_PREF_KEY, "false");
  if (typeof refreshNotifyButton === "function") refreshNotifyButton();
}

// items: [{ symbol, name, action }]
function notifyStrongSignals(items) {
  if (!notificationsEnabled() || !items || items.length === 0) return;
  const preview = items.slice(0, 3).map((i) => `${i.name}(${ACTION_ZH[i.action]})`).join("、");
  const more = items.length > 3 ? ` 等 ${items.length} 檔` : "";
  new Notification("量化訊號更新", {
    body: `${preview}${more} 剛轉為新訊號`,
    icon: "icons/icon-192.png",
  });
}

// Registers the offline/app-shell service worker so the site can be added
// to a phone's home screen and still open (with the last cached data) when
// there's no connection. Safe to call on every page load -- the browser
// no-ops if it's already registered and unchanged.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((err) => {
      console.warn("Service worker registration failed (site still works normally online):", err);
    });
  });
}
