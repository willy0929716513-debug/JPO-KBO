// Page-specific logic for prices.html (grouped price overview). Shared
// constants/helpers live in common.js, loaded before this file.
const DATA_URL = "data/signals_latest.json";
const HISTORY_URL = "data/history.json";
const PRICES_REFRESH_MS = 60_000;
let taiwanLiveStarted = false;

const GROUPS = [
  { key: "taiwan", classes: ["taiwan"] },
  { key: "stocks", classes: ["equity", "etf"] },
  { key: "futures", classes: ["metal", "energy"] },
  { key: "forex", classes: ["forex"] },
];

function groupSignals(signals) {
  const groups = { taiwan: [], stocks: [], futures: [], forex: [] };
  signals.forEach((s) => {
    const group = GROUPS.find((g) => g.classes.includes(s.asset_class));
    if (group) groups[group.key].push(s);
  });
  return groups;
}

// Approximates a "since last update" % change using the two most recent
// history.json entries that included this symbol -- the same signal.price
// series already recorded for the "近期訊號走勢" chart on the main page,
// reused here rather than tracked separately.
function priceChangeFromHistory(symbol, history) {
  if (!history || history.length < 2) return null;
  const entries = history
    .map((h) => h.signals.find((s) => s.symbol === symbol))
    .filter((e) => e && typeof e.price === "number");
  if (entries.length < 2) return null;
  const prev = entries[entries.length - 2];
  const curr = entries[entries.length - 1];
  if (!prev.price) return null;
  return ((curr.price - prev.price) / prev.price) * 100;
}

function renderGroup(containerId, signals, history) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.className = "price-grid";
  if (signals.length === 0) {
    container.innerHTML = `<p class="footnote">尚無資料</p>`;
    return;
  }

  container.innerHTML = signals.map((s) => {
    const name = SYMBOL_NAMES[s.symbol] || s.symbol;
    const change = priceChangeFromHistory(s.symbol, history);
    const changeHtml = change === null ? "" : `
      <span class="live-change ${change >= 0 ? "live-up" : "live-down"}">
        ${change >= 0 ? "▲" : "▼"} ${fmtNum(Math.abs(change), 2)}%
      </span>`;
    const action = effectiveAction(s);
    const asOf = s.as_of ? new Date(s.as_of).toLocaleString() : "-";

    return `<div class="price-card" data-symbol="${s.symbol}">
      <div class="price-card-head">
        <div class="pick-name">${name} <span class="pick-symbol">${s.symbol}</span></div>
        ${marketStatusBadge(s.market_open)}
      </div>
      <div class="price-card-value num"><span class="js-live-price">${fmtNum(s.last_price, 4)}</span>${changeHtml}</div>
      <div class="price-card-meta">
        <span class="badge ${badgeClass(action)}">${ACTION_ZH[action]}</span>
        <span class="footnote">資料時間：${asOf}</span>
      </div>
    </div>`;
  }).join("");
}

async function loadPrices() {
  let history = [];
  try {
    const histResp = await fetch(`${HISTORY_URL}?t=${Date.now()}`);
    if (histResp.ok) history = await histResp.json();
  } catch (err) {
    console.warn("No history yet", err);
  }

  try {
    const resp = await fetch(`${DATA_URL}?t=${Date.now()}`);
    const payload = await resp.json();

    document.getElementById("generated-at").textContent =
      "最後更新: " + new Date(payload.generated_at).toLocaleString();
    renderFearGreed("fear-greed", payload.market_sentiment?.crypto_fear_greed);

    const groups = groupSignals(payload.signals || []);
    renderGroup("group-taiwan", groups.taiwan, history);
    renderGroup("group-stocks", groups.stocks, history);
    renderGroup("group-futures", groups.futures, history);
    renderGroup("group-forex", groups.forex, history);

    if (!taiwanLiveStarted) {
      startTaiwanLiveQuotes(groups.taiwan.map((s) => s.symbol), "live-status-tw");
      taiwanLiveStarted = true;
    }
  } catch (err) {
    document.getElementById("generated-at").textContent = "尚未有資料，等待第一次自動更新";
    console.error(err);
  }
}

document.getElementById("refresh-btn").addEventListener("click", loadPrices);
loadPrices();
createLiveCryptoTicker("live-crypto", "live-status");
setInterval(loadPrices, PRICES_REFRESH_MS);
