// Page-specific logic for news-picks.html ("📰 新聞熱門股") -- per user
// request, a dedicated page that scans each symbol's recent news headlines
// (already flowing through signals_latest.json via src/data/news_scoring.py)
// and surfaces which ones read net-bullish, with the actual article links
// attached so the user can judge for themselves. Deliberately does NOT
// invent a "why it will surge" narrative beyond what the matched keywords
// and existing technical regime already say -- see the on-page disclaimer.
// Relies on SYMBOL_NAMES / ACTION_ZH / REGIME_ZH / ASSET_CLASS_ZH / fmtNum /
// effectiveAction / effectiveConfidence / badgeClass / marketStatusBadge /
// renderNewsListTagged from common.js, and autoTradeGroupOf from paper.js
// (both loaded before this file) for the cross-symbol group-heat panel.
const NEWS_DATA_URL = "data/signals_latest.json";
const NEWS_PICKS_REFRESH_MS = 60_000;
const NEWS_HEAT_MIN_GROUP_SIZE = 2; // an "industry heat" needs >=2 co-moving symbols, not a single stock

function newsGroupLabel(group) {
  if (group === "tw_financial_holding") return "台股金控股";
  if (group.startsWith("tw_")) return `台股（代碼 ${group.slice(3)}xx 開頭）`;
  return ASSET_CLASS_ZH[group] || group;
}

// Renders one "🔮 AI 前瞻潛力股" card from src/data/providers/llm_provider.py's
// GeminiProvider output (see daily_run.py's _get_forward_looking_picks --
// gated to at most once/hour, so this section may not change every refresh).
function forwardLookingCardHtml(pick) {
  const name = SYMBOL_NAMES[pick.symbol] || pick.symbol;
  const basedOnName = pick.based_on_symbol ? (SYMBOL_NAMES[pick.based_on_symbol] || pick.based_on_symbol) : null;
  const citation = basedOnName
    ? `<div class="footnote">依據：${escapeHtml(basedOnName)} ${escapeHtml(pick.based_on_symbol)}${
        pick.based_on_headline ? ` -「${escapeHtml(pick.based_on_headline)}」` : ""
      }</div>`
    : "";
  return `<div class="news-heat-card" data-symbol="${escapeHtml(pick.symbol)}">
    <div class="news-heat-card-title">${escapeHtml(name)} <span class="pick-symbol">${escapeHtml(pick.symbol)}</span></div>
    <div class="news-heat-card-members">${escapeHtml(pick.reasoning)}</div>
    ${citation}
  </div>`;
}

function newsPicksReason(s) {
  const bullishNews = (s.news || []).filter((n) => n.tone === "bullish");
  const keywords = [...new Set(bullishNews.flatMap((n) => n.matched_keywords || []))].slice(0, 5);
  const kwText = keywords.length ? `（觸發關鍵字：${keywords.join("、")}）` : "";
  const action = effectiveAction(s);
  const regimeText = REGIME_ZH[s.regime.state] || "資料不足";
  const techText = action === "HOLD"
    ? `目前技術面訊號還不明確（${regimeText}），建議先當觀察名單`
    : `技術面目前也偏${action === "BUY" ? "多" : "空"}（${regimeText}，信心度 ${(effectiveConfidence(s) * 100).toFixed(0)}%）`;
  return `近期 ${bullishNews.length} 則相關新聞內容偏正面${kwText}，${techText}。`;
}

function newsScoreBadge(sentiment) {
  const pct = Math.round(sentiment.score * 100);
  return `<span class="badge badge-buy" title="新聞偏多則數佔比">📈 新聞偏多 ${pct}%</span>`;
}

function newsPickCardHtml(s, rank) {
  const name = SYMBOL_NAMES[s.symbol] || s.symbol;
  const action = effectiveAction(s);
  return `<div class="pick-card ${badgeClass(action)}-card" data-symbol="${s.symbol}" style="animation-delay:${Math.min(rank * 35, 350)}ms">
    <div class="pick-head">
      <div class="pick-name">${name} <span class="pick-symbol">${s.symbol}</span></div>
      <div class="pick-head-badges">
        ${newsScoreBadge(s.news_sentiment)}
        <div class="pick-action badge ${badgeClass(action)}">${ACTION_ZH[action]}</div>
      </div>
    </div>
    <div class="pick-price">目前價格：<b class="num">${fmtNum(s.last_price, 4)}</b>${
      (s.change_pct === null || s.change_pct === undefined) ? "" :
      ` <span class="live-change ${s.change_pct >= 0 ? "live-up" : "live-down"}">${s.change_pct >= 0 ? "▲" : "▼"} ${fmtNum(Math.abs(s.change_pct), 2)}%</span>`
    } ${marketStatusBadge(s.market_open)}</div>
    <div class="pick-reason">${newsPicksReason(s)}</div>
    <div class="pick-news-wrap">
      <div class="footnote">📰 相關新聞（點連結看原文）</div>
      ${renderNewsListTagged(s.news)}
    </div>
    <div class="pick-trade-actions" data-symbol="${s.symbol}" data-price="${s.last_price}"></div>
  </div>`;
}

function newsHeatCardHtml(heat) {
  const members = heat.members
    .slice()
    .sort((a, b) => b.news_sentiment.score - a.news_sentiment.score)
    .map((s) => `${SYMBOL_NAMES[s.symbol] || s.symbol} ${s.symbol}`)
    .join("、");
  return `<div class="news-heat-card">
    <div class="news-heat-card-title">${newsGroupLabel(heat.group)}</div>
    <div class="footnote">平均新聞偏多比例 ${Math.round(heat.avgScore * 100)}%（${heat.members.length} 檔）</div>
    <div class="news-heat-card-members">${members}</div>
  </div>`;
}

async function loadNewsPicksPage() {
  try {
    const resp = await fetch(`${NEWS_DATA_URL}?t=${Date.now()}`);
    const payload = await resp.json();
    document.getElementById("generated-at").textContent =
      "資料最後更新: " + new Date(payload.generated_at).toLocaleString();

    if (typeof paperCacheLatestPrices === "function") paperCacheLatestPrices(payload);

    const forwardPanel = document.getElementById("forward-looking-panel");
    const forwardGrid = document.getElementById("forward-looking-grid");
    const forwardPicks = (payload.forward_looking_picks && payload.forward_looking_picks.picks) || [];
    if (forwardPicks.length === 0) {
      forwardPanel.style.display = "none";
    } else {
      forwardPanel.style.display = "";
      forwardGrid.innerHTML = forwardPicks.map(forwardLookingCardHtml).join("");
    }

    const withNews = (payload.signals || []).filter((s) => s.news_sentiment && s.news && s.news.length > 0);

    // Group-level "industry heat": average news_sentiment.score across
    // every symbol sharing a group (reusing paper.js's autoTradeGroupOf --
    // same TWSE-prefix/asset-class grouping already used for the auto-trade
    // concentration cap), shown only when >=2 members share a net-positive
    // average so this reflects a genuine cross-symbol pattern, not one
    // stock's own news dressed up as "industry" news.
    const groups = {};
    withNews.forEach((s) => {
      const group = typeof autoTradeGroupOf === "function" ? autoTradeGroupOf(s.symbol, s.asset_class) : (s.asset_class || "other");
      (groups[group] = groups[group] || []).push(s);
    });
    const heat = Object.entries(groups)
      .map(([group, members]) => ({
        group, members,
        avgScore: members.reduce((sum, s) => sum + s.news_sentiment.score, 0) / members.length,
      }))
      .filter((h) => h.members.length >= NEWS_HEAT_MIN_GROUP_SIZE && h.avgScore > 0)
      .sort((a, b) => b.avgScore - a.avgScore)
      .slice(0, 6);

    const heatPanel = document.getElementById("heat-panel");
    const heatGrid = document.getElementById("news-heat-grid");
    if (heat.length === 0) {
      heatPanel.style.display = "none";
    } else {
      heatPanel.style.display = "";
      heatGrid.innerHTML = heat.map(newsHeatCardHtml).join("");
    }

    const bullishSort = (a, b) =>
      b.news_sentiment.score - a.news_sentiment.score ||
      b.news_sentiment.bullish_count - a.news_sentiment.bullish_count ||
      effectiveConfidence(b) - effectiveConfidence(a);

    const bullish = withNews.filter((s) => s.news_sentiment.score > 0);
    // 台股為主力焦點 -- 分開兩區塊呈現，台股永遠排在最前面，不會被新聞措辭
    // 比較聳動的美股標題稀釋掉。
    const rankedTw = bullish.filter((s) => s.asset_class === "taiwan").sort(bullishSort);
    const rankedOther = bullish.filter((s) => s.asset_class !== "taiwan").sort(bullishSort);

    const renderGrid = (elId, ranked, emptyMsg) => {
      const gridEl = document.getElementById(elId);
      if (ranked.length === 0) {
        gridEl.className = "";
        gridEl.innerHTML = `<p class="footnote">${emptyMsg}</p>`;
        return;
      }
      gridEl.className = "pick-grid";
      gridEl.innerHTML = ranked.map((s, i) => newsPickCardHtml(s, i)).join("");
      if (typeof renderTradeButtons === "function") renderTradeButtons(gridEl);
    };

    renderGrid("news-picks-grid-tw", rankedTw, "目前掃描到的台股新聞裡，沒有標的內容淨偏多，等下一次資料更新再看看。");
    renderGrid("news-picks-grid-other", rankedOther, "目前掃描到的其他市場新聞裡，沒有標的內容淨偏多。");
  } catch (err) {
    document.getElementById("generated-at").textContent = "尚未有資料，等待第一次自動更新";
    console.error(err);
  }
}

document.getElementById("refresh-btn").addEventListener("click", loadNewsPicksPage);
loadNewsPicksPage();
setInterval(loadNewsPicksPage, NEWS_PICKS_REFRESH_MS);
