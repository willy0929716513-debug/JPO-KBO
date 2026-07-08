// Page-specific logic for top-picks.html ("🚀 最強推薦") -- per user
// request, a dedicated page ranking every actionable (BUY/SELL) signal
// across the whole watchlist by confidence, with a 🚀 rocket badge on the
// single highest-confidence pick and a ⭐ star tier for the rest. Relies
// on SYMBOL_NAMES / ACTION_ZH / fmtNum / effectiveAction / effectiveConfidence /
// confidenceLabel / confidenceDots / pickStrengthBadge / badgeClass /
// PICK_GRID_COLLAPSE_THRESHOLD / wirePickGridToggle / renderNewsList from
// common.js, and renderTradeButtons from paper.js (both loaded before this
// file) for the inline 模擬做多/做空 buttons.
const DATA_URL = "data/signals_latest.json";
const TOP_PICKS_REFRESH_MS = 60_000;

function topPicksPlainReason(s) {
  const action = effectiveAction(s);
  const regimeText = REGIME_ZH[s.regime.state] || "資料不足";
  if (action === "BUY") return `目前${regimeText}，多項技術指標偏多，可考慮找機會分批做多`;
  if (action === "SELL") return `目前${regimeText}，多項技術指標偏空，可考慮找機會分批做空`;
  return `目前${regimeText}，訊號不夠明確，建議先觀望，不用急著進場`;
}

function topPickCardHtml(s, rank, isHero, isExtra) {
  const sig = s.signal;
  const action = effectiveAction(s);
  const name = SYMBOL_NAMES[s.symbol] || s.symbol;
  const conf = effectiveConfidence(s);
  return `<div class="pick-card ${badgeClass(action)}-card${isHero ? " pick-card-hero" : ""}${isExtra ? " pick-card-extra" : ""}" data-symbol="${s.symbol}" ${isExtra ? "hidden" : ""} style="animation-delay:${Math.min(rank * 35, 350)}ms">
    <div class="pick-head">
      <div class="pick-name">${name} <span class="pick-symbol">${s.symbol}</span></div>
      <div class="pick-head-badges">
        ${pickStrengthBadge(rank, conf)}
        <div class="pick-action badge ${badgeClass(action)}">${ACTION_ZH[action]}</div>
      </div>
    </div>
    <div class="pick-price">目前價格：<b class="num">${fmtNum(s.last_price, 4)}</b>${
      (s.change_pct === null || s.change_pct === undefined) ? "" :
      ` <span class="live-change ${s.change_pct >= 0 ? "live-up" : "live-down"}">${s.change_pct >= 0 ? "▲" : "▼"} ${fmtNum(Math.abs(s.change_pct), 2)}%</span>`
    } ${marketStatusBadge(s.market_open)}</div>
    <div class="pick-levels num">
      <span>建議停損：${fmtNum(sig.stop_loss, 4)}</span>
      <span>建議停利：${fmtNum(sig.take_profit, 4)}</span>
    </div>
    <div class="confidence-row">
      信心程度：${confidenceLabel(conf)}（${(conf * 100).toFixed(0)}%）
      <span class="confidence-dots">${confidenceDots(conf)}</span>
    </div>
    <div class="pick-reason">${topPicksPlainReason(s)}</div>
    ${s.news && s.news.length > 0 ? `<div class="pick-news-wrap">
      <div class="footnote">📰 相關新聞</div>
      ${renderNewsList(s.news)}
    </div>` : ""}
    <div class="pick-trade-actions" data-symbol="${s.symbol}" data-price="${s.last_price}"></div>
  </div>`;
}

async function loadTopPicksPage() {
  try {
    const resp = await fetch(`${DATA_URL}?t=${Date.now()}`);
    const payload = await resp.json();
    document.getElementById("generated-at").textContent =
      "資料最後更新: " + new Date(payload.generated_at).toLocaleString();

    if (typeof paperCacheLatestPrices === "function") paperCacheLatestPrices(payload);

    const ranked = (payload.signals || [])
      .filter((s) => effectiveAction(s) !== "HOLD")
      .slice()
      .sort((a, b) => effectiveConfidence(b) - effectiveConfidence(a));

    const heroPanel = document.getElementById("hero-panel");
    const heroEl = document.getElementById("hero-pick");
    const gridEl = document.getElementById("hot-picks-grid");

    if (ranked.length === 0) {
      heroPanel.style.display = "none";
      gridEl.className = "";
      gridEl.innerHTML = `<p class="footnote">目前沒有信心度足夠的做多/做空建議，全部標的都是觀望。</p>`;
      return;
    }

    heroPanel.style.display = "";
    heroEl.innerHTML = topPickCardHtml(ranked[0], 0, true, false);

    const rest = ranked.slice(1);
    gridEl.className = "pick-grid";
    if (rest.length === 0) {
      gridEl.innerHTML = `<p class="footnote">目前只有這一檔符合做多/做空建議。</p>`;
    } else {
      const cardsHtml = rest.map((s, i) => {
        const rank = i + 1;
        return topPickCardHtml(s, rank, false, rank >= PICK_GRID_COLLAPSE_THRESHOLD);
      }).join("");
      const toggleHtml = rest.length > PICK_GRID_COLLAPSE_THRESHOLD
        ? `<button type="button" class="pick-grid-toggle">展開查看全部 ${rest.length} 檔 ▾</button>`
        : "";
      gridEl.innerHTML = cardsHtml + toggleHtml;
      if (typeof wirePickGridToggle === "function") wirePickGridToggle(gridEl);
    }

    if (typeof renderTradeButtons === "function") {
      renderTradeButtons(heroEl);
      renderTradeButtons(gridEl);
    }
  } catch (err) {
    document.getElementById("generated-at").textContent = "尚未有資料，等待第一次自動更新";
    console.error(err);
  }
}

document.getElementById("refresh-btn").addEventListener("click", loadTopPicksPage);
loadTopPicksPage();
setInterval(loadTopPicksPage, TOP_PICKS_REFRESH_MS);
