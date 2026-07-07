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
const PAPER_STARTING_CASH = 10_000_000; // virtual TWD
const PAPER_MANUAL_DEFAULT_NOTIONAL = 100_000; // suggested size for a manual trade
const PAPER_AUTO_TRADE_NOTIONAL = PAPER_STARTING_CASH * 0.1; // per-symbol cap per auto-followed signal
// Per user request: "不要盲目下單，要經過分析考慮" -- calibrated against real
// production decision_engine.confidence values (see src/pipeline/auto_trader.py
// for the same constant and full reasoning) rather than picked round; the
// combined multi-agent confidence rarely exceeds ~0.3 for actionable signals.
const PAPER_AUTO_TRADE_MIN_CONFIDENCE = 0.20;

let PAPER_LATEST_PRICES = {};
let PAPER_LATEST_STOPS = {}; // { [symbol]: { stopLoss, takeProfit } } from the dashboard's own recommended levels
let PAPER_LATEST_ASSET_CLASS = {}; // { [symbol]: "taiwan"|"equity"|"etf"|"crypto"|... } for quantityUnitLabel()

function paperEmptyTradeStats() {
  return { wins: 0, losses: 0, grossProfit: 0, grossLoss: 0 };
}

// Fills in fields added by later versions of this feature so every
// downstream function can assume they're present, instead of scattering
// `|| 0` / `|| {}` fallbacks everywhere. Safe to call on a state that
// already has them (no-op).
function paperNormalizeState(state) {
  state.realizedPnl = state.realizedPnl || 0;
  state.realizedPnlBySource = state.realizedPnlBySource || { auto: 0, manual: 0 };
  state.realizedPnlBySymbol = state.realizedPnlBySymbol || {};
  state.tradeStats = state.tradeStats || { overall: paperEmptyTradeStats(), auto: paperEmptyTradeStats(), manual: paperEmptyTradeStats() };
  return state;
}

function paperLoadState() {
  try {
    const raw = localStorage.getItem(PAPER_STORAGE_KEY);
    if (raw) {
      const state = JSON.parse(raw);
      if (state && typeof state === "object" && state.positions) return paperNormalizeState(state);
    }
  } catch (err) {
    console.warn("Paper trading state was corrupted, resetting.", err);
  }
  return paperNormalizeState({ cash: PAPER_STARTING_CASH, positions: {}, history: [], autoTradeEnabled: false, equityHistory: [] });
}

function paperSaveState(state) {
  localStorage.setItem(PAPER_STORAGE_KEY, JSON.stringify(state));
}

// Small in-page modal used instead of the browser's native prompt()/confirm(),
// which pop up as a jarring light-themed system dialog on this otherwise
// dark-themed site. Injects one reusable overlay into <body> the first time
// it's called; safe to call from both index.html and paper.html.
function paperShowModal({ title, bodyHtml, onConfirm, confirmLabel = "確認", cancelLabel = "取消" }) {
  let overlay = document.getElementById("paper-modal-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "paper-modal-overlay";
    overlay.className = "paper-modal-overlay";
    document.body.appendChild(overlay);
  }
  overlay.innerHTML = `
    <div class="paper-modal">
      <div class="paper-modal-title">${title}</div>
      <div class="paper-modal-body">${bodyHtml}</div>
      <div class="paper-modal-actions">
        <button type="button" class="pill pill-btn" data-modal-cancel>${cancelLabel}</button>
        <button type="button" class="pill pill-btn" data-modal-confirm>${confirmLabel}</button>
      </div>
    </div>`;
  overlay.style.display = "flex";
  const close = () => { overlay.style.display = "none"; overlay.innerHTML = ""; };
  overlay.querySelector("[data-modal-cancel]").addEventListener("click", close);
  overlay.querySelector("[data-modal-confirm]").addEventListener("click", () => {
    if (onConfirm(overlay) !== false) close();
  });
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); }, { once: true });
  return overlay;
}

function paperResetState() {
  paperShowModal({
    title: "重置模擬帳戶",
    bodyHtml: `<div class="footnote">確定要重置模擬帳戶嗎？所有虛擬持倉與紀錄都會清空，恢復成 ${PAPER_STARTING_CASH.toLocaleString()} 虛擬台幣，且無法復原。</div>`,
    confirmLabel: "確定重置",
    onConfirm: () => {
      localStorage.removeItem(PAPER_STORAGE_KEY);
      location.reload();
    },
  });
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
    PAPER_LATEST_STOPS[s.symbol] = {
      stopLoss: s.signal ? s.signal.stop_loss : null,
      takeProfit: s.signal ? s.signal.take_profit : null,
    };
    PAPER_LATEST_ASSET_CLASS[s.symbol] = s.asset_class;
  });
  let state = paperLoadState();
  state = paperCheckStopsAndTargets(state);
  paperRecordEquitySnapshot(state);
  paperSaveState(state);
}

// Force-closes any open position (manual or auto) whose current price has
// breached its own stored stop-loss/take-profit -- previously nothing in
// the paper-trading simulator ever checked this, so a position could keep
// losing well past the "建議停損" shown on its own card with no automatic
// exit, even though the site prominently displays that level as if it
// mattered. Runs on every price refresh regardless of the auto-trade
// toggle, since a manually-opened position deserves the same protection.
function paperCheckStopsAndTargets(state) {
  Object.entries(state.positions).forEach(([symbol, pos]) => {
    if (pos.stopLoss == null && pos.takeProfit == null) return;
    const price = PAPER_LATEST_PRICES[symbol];
    if (!price) return;
    const hitStop = pos.stopLoss != null && (pos.side === "long" ? price <= pos.stopLoss : price >= pos.stopLoss);
    const hitTarget = pos.takeProfit != null && (pos.side === "long" ? price >= pos.takeProfit : price <= pos.takeProfit);
    if (hitStop || hitTarget) {
      state = paperClosePositionAtPrice(symbol, hitStop ? pos.stopLoss : pos.takeProfit, state, hitStop ? "stop_loss" : "take_profit");
    }
  });
  return state;
}

function paperPushHistory(state, entry) {
  state.history.unshift({ time: new Date().toISOString(), ...entry });
  state.history = state.history.slice(0, 200);
}

function paperOpenPosition(symbol, side, price, qty, source, stopLoss, takeProfit, assetClass) {
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
  state.positions[symbol] = {
    side, qty, avgPrice: price, openedAt: new Date().toISOString(), source,
    stopLoss: stopLoss ?? null, takeProfit: takeProfit ?? null, assetClass: assetClass ?? null,
  };
  paperPushHistory(state, { symbol, side, action: "open", qty, price, source, assetClass });
  paperSaveState(state);
  paperRenderAll();
}

// closeReason: undefined for a normal signal-flip/manual close, or
// "stop_loss"/"take_profit" when paperCheckStopsAndTargets forced the exit --
// shown distinctly in the trade history table so it's clear *why* a position
// closed, not just that it did.
function paperClosePositionAtPrice(symbol, price, state, closeReason) {
  const pos = state.positions[symbol];
  if (!pos || !price) return state;
  const pnl = pos.side === "long" ? (price - pos.avgPrice) * pos.qty : (pos.avgPrice - price) * pos.qty;
  state.cash += pos.avgPrice * pos.qty + pnl;

  state.realizedPnl += pnl;
  state.realizedPnlBySource[pos.source] = (state.realizedPnlBySource[pos.source] || 0) + pnl;
  state.realizedPnlBySymbol[symbol] = (state.realizedPnlBySymbol[symbol] || 0) + pnl;
  const bucket = pnl >= 0 ? "wins" : "losses";
  const magnitudeKey = pnl >= 0 ? "grossProfit" : "grossLoss";
  [state.tradeStats.overall, state.tradeStats[pos.source]].forEach((stats) => {
    stats[bucket] += 1;
    stats[magnitudeKey] += Math.abs(pnl);
  });

  paperPushHistory(state, { symbol, side: pos.side, action: "close", qty: pos.qty, price, pnl, source: pos.source, closeReason, assetClass: pos.assetClass });
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
  const name = SYMBOL_NAMES[symbol] || symbol;
  const suggested = Math.max(1, Math.floor(PAPER_MANUAL_DEFAULT_NOTIONAL / price));
  const stops = PAPER_LATEST_STOPS[symbol] || {};
  const unit = quantityUnitLabel(PAPER_LATEST_ASSET_CLASS[symbol]);

  const overlay = paperShowModal({
    title: `模擬${sideZh}：${name}`,
    confirmLabel: `確認${sideZh}`,
    bodyHtml: `
      <div class="footnote">目前價格 ${fmtNum(price, 2)}</div>
      <div class="paper-modal-qty-row">
        <button type="button" class="pill pill-btn small" data-qty-step="-1">－</button>
        <input type="number" id="paper-modal-qty-input" min="1" step="1" value="${suggested}" />
        <span class="footnote">${unit}${unit === "股" ? "（非「張」，1張＝1000股）" : ""}</span>
        <button type="button" class="pill pill-btn small" data-qty-step="1">＋</button>
      </div>
      <div class="footnote" id="paper-modal-qty-cost"></div>
      <div class="footnote" style="margin-top:10px">停損／停利（碰到會自動平倉，留空表示不設定；預設帶入系統建議值，可自行修改）</div>
      <div class="paper-modal-stops-row">
        <label>停損<input type="number" id="paper-modal-stop-input" step="any" value="${stops.stopLoss != null ? stops.stopLoss : ""}" placeholder="不設定" /></label>
        <label>停利<input type="number" id="paper-modal-target-input" step="any" value="${stops.takeProfit != null ? stops.takeProfit : ""}" placeholder="不設定" /></label>
      </div>
    `,
    onConfirm: (el) => {
      const qty = parseInt(el.querySelector("#paper-modal-qty-input").value, 10);
      if (!qty || qty <= 0) return false;
      const stopRaw = el.querySelector("#paper-modal-stop-input").value;
      const targetRaw = el.querySelector("#paper-modal-target-input").value;
      const stopLoss = stopRaw === "" ? null : parseFloat(stopRaw);
      const takeProfit = targetRaw === "" ? null : parseFloat(targetRaw);
      if (stopLoss != null && isNaN(stopLoss)) { alert("停損價格不合法。"); return false; }
      if (takeProfit != null && isNaN(takeProfit)) { alert("停利價格不合法。"); return false; }
      const stopOk = stopLoss == null || (side === "long" ? stopLoss < price : stopLoss > price);
      const targetOk = takeProfit == null || (side === "long" ? takeProfit > price : takeProfit < price);
      if (!stopOk) { alert(side === "long" ? "做多的停損價必須低於目前價格。" : "做空的停損價必須高於目前價格。"); return false; }
      if (!targetOk) { alert(side === "long" ? "做多的停利價必須高於目前價格。" : "做空的停利價必須低於目前價格。"); return false; }
      paperOpenPosition(symbol, side, price, qty, "manual", stopLoss, takeProfit, PAPER_LATEST_ASSET_CLASS[symbol]);
    },
  });

  const input = overlay.querySelector("#paper-modal-qty-input");
  const costEl = overlay.querySelector("#paper-modal-qty-cost");
  const updateCost = () => {
    const qty = Math.max(1, parseInt(input.value, 10) || 1);
    costEl.textContent = `${qty} ${unit} ・ 約需 ${Math.round(qty * price).toLocaleString()} 虛擬台幣`;
  };
  overlay.querySelectorAll("[data-qty-step]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const step = parseInt(btn.dataset.qtyStep, 10);
      input.value = Math.max(1, (parseInt(input.value, 10) || 1) + step);
      updateCost();
    });
  });
  input.addEventListener("input", updateCost);
  updateCost();
}

function paperSetAutoTrade(enabled) {
  const state = paperLoadState();
  state.autoTradeEnabled = enabled;
  paperSaveState(state);
}

// Among a symbol's individual strategy votes that agree with the direction
// of `action`, finds whichever strategy is actually driving the recommendation
// (largest weight*confidence) and returns that strategy's own historical
// profit_factor for this exact symbol -- so a live BUY/SELL crossing the
// combined threshold can still be skipped if the strategy behind it has a
// known-bad track record here (e.g. mean-reversion on a symbol that's mostly
// trended for years). Returns null when there's not enough information to
// judge (never blocks a trade just because backtest data is missing).
function dominantStrategyProfitFactor(s, action) {
  const direction = action === "BUY" ? 1 : action === "SELL" ? -1 : null;
  if (direction === null) return null;
  const votes = (s.signal && s.signal.votes) || [];
  const dirOf = (a) => (a === "BUY" ? 1 : a === "SELL" ? -1 : 0);
  const agreeing = votes.filter((v) => dirOf(v.action) === direction);
  if (agreeing.length === 0) return null;
  const dominant = agreeing.reduce((best, v) =>
    (v.weight ?? 1) * (v.confidence ?? 0) > (best.weight ?? 1) * (best.confidence ?? 0) ? v : best
  );
  const metrics = s.backtest && s.backtest[dominant.strategy];
  return metrics ? metrics.profit_factor : null;
}

// Follows the dashboard's own recommendations: opens a virtual long/short
// when a symbol newly signals BUY/SELL, and closes it once that symbol's
// signal flips or drops back to HOLD. Only touches positions this
// auto-trader itself opened (source === "auto") so it never interferes
// with a manually-opened position on the same symbol.
function paperAutoTradeTick(payload) {
  let state = paperLoadState();
  if (!state.autoTradeEnabled) return;

  const signals = payload.signals || [];

  signals.forEach((s) => {
    const price = s.last_price;
    if (!price) return;
    const existing = state.positions[s.symbol];
    if (!existing || existing.source !== "auto") return;
    const action = effectiveAction(s);
    const wantSide = action === "BUY" ? "long" : action === "SELL" ? "short" : null;
    if (wantSide !== existing.side) {
      state = paperClosePositionAtPrice(s.symbol, price, state);
    }
  });

  // Candidate filtering -- "分析考慮，不要盲目下單": a raw BUY/SELL crossing
  // the combined threshold isn't enough on its own. Require (1) confidence
  // above PAPER_AUTO_TRADE_MIN_CONFIDENCE (skip the weakest borderline calls)
  // and (2) the strategy actually driving the recommendation to have a
  // historically profitable (>=1.0) track record for this exact symbol.
  const candidates = signals.filter((s) => {
    if (!s.last_price || state.positions[s.symbol]) return false;
    const action = effectiveAction(s);
    if (action !== "BUY" && action !== "SELL") return false;
    if (effectiveConfidence(s) < PAPER_AUTO_TRADE_MIN_CONFIDENCE) return false;
    const pf = dominantStrategyProfitFactor(s, action);
    if (pf !== null && pf < 1.0) return false;
    return true;
  });

  if (candidates.length > 0) {
    // Position size scales with confidence instead of splitting cash flat
    // across every candidate -- a stronger signal earns a bigger bet, a
    // barely-qualifying one gets a smaller bet, both still capped at
    // PAPER_AUTO_TRADE_NOTIONAL so one very-confident symbol can't swallow
    // the whole account. Shares are computed against a snapshot of cash
    // taken before this loop, not the live balance (which shrinks as
    // earlier candidates spend it) -- otherwise later candidates in the
    // same batch would get a shrinking budget regardless of their own
    // confidence.
    const totalConfidence = candidates.reduce((sum, s) => sum + effectiveConfidence(s), 0);
    const availableCash = state.cash;
    candidates.forEach((s) => {
      const price = s.last_price;
      const action = effectiveAction(s);
      const confidence = effectiveConfidence(s);
      const share = totalConfidence > 0 ? confidence / totalConfidence : 1 / candidates.length;
      const budget = Math.min(availableCash * share, PAPER_AUTO_TRADE_NOTIONAL);
      const qty = Math.floor(budget / price);
      const notional = qty * price;
      if (qty > 0 && notional <= state.cash) {
        state.cash -= notional;
        state.positions[s.symbol] = {
          side: action === "BUY" ? "long" : "short", qty, avgPrice: price, openedAt: new Date().toISOString(), source: "auto",
          stopLoss: s.signal.stop_loss ?? null, takeProfit: s.signal.take_profit ?? null, assetClass: s.asset_class ?? null,
        };
        paperPushHistory(state, { symbol: s.symbol, side: action === "BUY" ? "long" : "short", action: "open", qty, price, source: "auto", assetClass: s.asset_class });
      }
    });
  }

  paperSaveState(state);
}

function paperUnrealizedPnl(pos, currentPrice) {
  if (!currentPrice) return 0;
  return pos.side === "long" ? (currentPrice - pos.avgPrice) * pos.qty : (pos.avgPrice - currentPrice) * pos.qty;
}

function paperWinRate(stats) {
  const total = stats.wins + stats.losses;
  return total > 0 ? (stats.wins / total) * 100 : null;
}

function paperProfitFactor(stats) {
  if (stats.grossLoss === 0) return stats.grossProfit > 0 ? Infinity : null;
  return stats.grossProfit / stats.grossLoss;
}

function paperFmtRatio(value) {
  if (value === null) return "-";
  if (value === Infinity) return "∞";
  return fmtNum(value, 2);
}

// Diffs current equity against the last equity snapshot recorded before
// today (i.e. roughly "since this morning"), so paper.html can show a
// separate "today's P&L" alongside all-time cumulative P&L. Returns null
// when there's no earlier snapshot to diff against yet (e.g. the very
// first day this browser has ever used the feature).
function paperTodayPnl(state, currentEquity) {
  const history = state.equityHistory || [];
  if (history.length === 0) return null;
  const todayStr = new Date().toDateString();
  for (let i = history.length - 1; i >= 0; i--) {
    if (new Date(history[i].time).toDateString() !== todayStr) {
      return currentEquity - history[i].equity;
    }
  }
  return null; // every snapshot we have is from today -- no baseline yet
}

// Combines realized (tracked cumulatively so it survives history trimming)
// and live unrealized P&L for the 自動跟單/手動操作 performance comparison.
function paperSourceBreakdown(state) {
  const unrealizedBySource = { auto: 0, manual: 0 };
  Object.entries(state.positions).forEach(([symbol, pos]) => {
    unrealizedBySource[pos.source] += paperUnrealizedPnl(pos, PAPER_LATEST_PRICES[symbol]);
  });
  return ["auto", "manual"].map((source) => {
    const realized = state.realizedPnlBySource[source] || 0;
    const unrealized = unrealizedBySource[source];
    const stats = state.tradeStats[source];
    return {
      source, realized, unrealized, total: realized + unrealized,
      trades: stats.wins + stats.losses,
      winRate: paperWinRate(stats),
      profitFactor: paperProfitFactor(stats),
    };
  });
}

// Per-symbol total P&L (realized-to-date + any currently-open unrealized),
// for the gainers/losers leaderboard.
function paperSymbolPnlLeaderboard(state) {
  const totals = { ...state.realizedPnlBySymbol };
  Object.entries(state.positions).forEach(([symbol, pos]) => {
    totals[symbol] = (totals[symbol] || 0) + paperUnrealizedPnl(pos, PAPER_LATEST_PRICES[symbol]);
  });
  return Object.entries(totals)
    .filter(([, pnl]) => pnl !== 0)
    .map(([symbol, pnl]) => ({ symbol, pnl }));
}

// In-memory only (not persisted) -- resets to showing everything on reload,
// which matches how the search/filter bar on index.html behaves too.
let paperHistoryFilter = { query: "", type: "all", sort: "time_desc" };

function paperSetHistoryFilter(patch) {
  Object.assign(paperHistoryFilter, patch);
  paperRenderDashboardPage();
}

function paperFilterHistory(history) {
  let rows = history;
  const q = paperHistoryFilter.query.trim().toLowerCase();
  if (q) {
    rows = rows.filter((h) => h.symbol.toLowerCase().includes(q) || (SYMBOL_NAMES[h.symbol] || "").toLowerCase().includes(q));
  }
  if (paperHistoryFilter.type !== "all") {
    rows = rows.filter((h) => h.action === paperHistoryFilter.type);
  }
  if (paperHistoryFilter.sort === "pnl_desc") {
    rows = rows.slice().sort((a, b) => (b.pnl ?? -Infinity) - (a.pnl ?? -Infinity));
  } else if (paperHistoryFilter.sort === "pnl_asc") {
    rows = rows.slice().sort((a, b) => (a.pnl ?? Infinity) - (b.pnl ?? Infinity));
  }
  return rows;
}

function paperHistoryRowToCsvFields(h) {
  return [
    new Date(h.time).toLocaleString(),
    SYMBOL_NAMES[h.symbol] || h.symbol,
    h.side === "long" ? "做多" : "做空",
    h.action === "open" ? "開倉" : (h.closeReason === "stop_loss" ? "停損出場" : h.closeReason === "take_profit" ? "停利出場" : "平倉"),
    `${h.qty} ${quantityUnitLabel(h.assetClass)}`,
    h.price,
    Math.round(h.qty * h.price),
    h.pnl === undefined ? "" : Math.round(h.pnl),
    h.source === "auto" ? "自動跟單" : "手動",
  ];
}

function paperExportHistoryCsv() {
  const state = paperLoadState();
  const header = ["時間", "標的", "方向", "動作", "數量", "價格", "金額", "損益", "來源"];
  const rows = paperFilterHistory(state.history).map(paperHistoryRowToCsvFields);
  const csv = [header, ...rows]
    .map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
    .join("\r\n");
  // Leading BOM so Excel opens the UTF-8 Chinese text correctly instead of mojibake.
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `paper_trading_history_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
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
        <span>模擬持倉：${pos.side === "long" ? "做多" : "做空"} ${pos.qty} ${quantityUnitLabel(pos.assetClass)} @ ${fmtNum(pos.avgPrice, 2)}（金額 ${Math.round(pos.avgPrice * pos.qty).toLocaleString()}）</span>
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
  const isUp = history[history.length - 1].equity >= PAPER_STARTING_CASH;
  const lineColor = isUp ? "#22c55e" : "#f43f5e";
  paperEquityChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: history.map((h) => new Date(h.time).toLocaleString()),
      datasets: [{
        label: "虛擬總資產", data: history.map((h) => h.equity),
        borderColor: lineColor, backgroundColor: `${lineColor}22`, tension: 0.3, pointRadius: 0, fill: true,
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
    const totalReturnPct = (totalPnl / PAPER_STARTING_CASH) * 100;
    const todayPnl = paperTodayPnl(state, equity);
    const pnlCls = (v) => (v >= 0 ? "live-up" : "live-down");
    const cards = [
      {
        label: "累積損益", primary: true, cls: pnlCls(totalPnl),
        value: `${totalPnl >= 0 ? "+" : ""}${Math.round(totalPnl).toLocaleString()}（${totalReturnPct >= 0 ? "+" : ""}${fmtNum(totalReturnPct, 2)}%）`,
      },
      { label: "虛擬總資產", value: Math.round(equity).toLocaleString() },
      { label: "現金餘額", value: Math.round(state.cash).toLocaleString() },
      {
        label: "今日損益", cls: todayPnl === null ? "" : pnlCls(todayPnl),
        value: todayPnl === null ? "-（今天第一次記錄）" : `${todayPnl >= 0 ? "+" : ""}${Math.round(todayPnl).toLocaleString()}`,
      },
      { label: "已實現損益", cls: pnlCls(state.realizedPnl), value: `${state.realizedPnl >= 0 ? "+" : ""}${Math.round(state.realizedPnl).toLocaleString()}` },
      { label: "未實現損益", cls: pnlCls(unrealized), value: `${unrealized >= 0 ? "+" : ""}${Math.round(unrealized).toLocaleString()}` },
    ];
    summaryEl.innerHTML = cards.map((c) =>
      `<div class="card${c.primary ? " card-primary" : ""}"><div class="label">${c.label}</div><div class="value ${c.cls || ""}">${c.value}</div></div>`
    ).join("");
  }

  paperRenderEquityChart(state);
  paperRenderSourceBreakdown(state);
  paperRenderSymbolLeaderboard(state);

  const positionsEl = document.getElementById("paper-positions");
  if (positionsEl) {
    const entries = Object.entries(state.positions);
    if (entries.length === 0) {
      positionsEl.className = "";
      positionsEl.innerHTML = `<p class="footnote">目前沒有模擬持倉。可以到「今日建議」頁面針對個股點「模擬做多/做空」，或開啟下面的自動跟單。</p>`;
    } else {
      const cardsHtml = entries.map(([symbol, pos], i) => {
        const cur = PAPER_LATEST_PRICES[symbol];
        const pnl = paperUnrealizedPnl(pos, cur);
        const pnlClass = pnl >= 0 ? "live-up" : "live-down";
        const isExtra = i >= PICK_GRID_COLLAPSE_THRESHOLD;
        const heldDays = Math.floor((Date.now() - new Date(pos.openedAt).getTime()) / 86_400_000);
        return `<div class="price-card${isExtra ? " pick-card-extra" : ""}" ${isExtra ? "hidden" : ""}>
          <div class="price-card-head">
            <div class="pick-name">${SYMBOL_NAMES[symbol] || symbol} <span class="pick-symbol">${symbol}</span></div>
            <span class="badge ${pos.side === "long" ? "badge-buy" : "badge-sell"}">${pos.side === "long" ? "做多" : "做空"}</span>
          </div>
          <div class="num">數量 ${pos.qty} ${quantityUnitLabel(pos.assetClass)}｜成本 ${fmtNum(pos.avgPrice, 2)}｜現價 ${fmtNum(cur, 2)}</div>
          <div class="num footnote">開倉金額：${Math.round(pos.avgPrice * pos.qty).toLocaleString()}</div>
          <div class="num ${pnlClass}">未實現損益：${pnl >= 0 ? "+" : ""}${fmtNum(pnl, 0)}</div>
          ${(pos.stopLoss != null || pos.takeProfit != null) ? `<div class="num footnote">停損 ${pos.stopLoss != null ? fmtNum(pos.stopLoss, 2) : "-"}｜停利 ${pos.takeProfit != null ? fmtNum(pos.takeProfit, 2) : "-"}（碰到會自動平倉）</div>` : ""}
          <div class="footnote">來源：${pos.source === "auto" ? "自動跟單" : "手動模擬"} · 持有 ${heldDays} 天 · 開倉時間 ${new Date(pos.openedAt).toLocaleString()}</div>
          <button class="pill pill-btn small" onclick="paperClosePosition('${symbol}')">模擬平倉</button>
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

  const statsEl = document.getElementById("paper-history-stats");
  if (statsEl) {
    const s = state.tradeStats.overall;
    const total = s.wins + s.losses;
    statsEl.innerHTML = total === 0
      ? "尚無已平倉交易，還沒有統計資料。"
      : `總交易 ${total} 次｜獲利 ${s.wins} 次｜虧損 ${s.losses} 次｜勝率 ${fmtNum(paperWinRate(s), 0)}%｜獲利因子 ${paperFmtRatio(paperProfitFactor(s))}`;
  }

  const historyEl = document.getElementById("paper-history-body");
  if (historyEl) {
    const filtered = paperFilterHistory(state.history);
    const rows = filtered.map((h) => {
      const pnlCls = h.pnl === undefined ? "" : (h.pnl >= 0 ? "paper-row-win" : "paper-row-loss");
      return `<tr class="${pnlCls}">
        <td data-label="時間">${new Date(h.time).toLocaleString()}</td>
        <td data-label="標的">${SYMBOL_NAMES[h.symbol] || h.symbol}</td>
        <td data-label="方向">${h.side === "long" ? "做多" : "做空"}</td>
        <td data-label="動作">${h.action === "open" ? "開倉" : (h.closeReason === "stop_loss" ? "停損出場" : h.closeReason === "take_profit" ? "停利出場" : "平倉")}</td>
        <td data-label="數量">${h.qty} ${quantityUnitLabel(h.assetClass)}</td>
        <td data-label="價格">${fmtNum(h.price, 2)}</td>
        <td data-label="金額">${Math.round(h.qty * h.price).toLocaleString()}</td>
        <td data-label="損益">${h.pnl === undefined ? "-" : `${h.pnl >= 0 ? "+" : ""}${fmtNum(h.pnl, 0)}`}</td>
        <td data-label="來源">${h.source === "auto" ? "自動跟單" : "手動"}</td>
      </tr>`;
    }).join("");
    if (rows) {
      historyEl.innerHTML = rows;
    } else if (state.history.length === 0) {
      historyEl.innerHTML = `<tr><td colspan="9">尚無交易紀錄。可以到「今日建議」頁面針對個股點「模擬做多/做空」，或開啟自動跟單。</td></tr>`;
    } else {
      historyEl.innerHTML = `<tr><td colspan="9">沒有符合篩選條件的紀錄。</td></tr>`;
    }
  }
}

function paperRenderSourceBreakdown(state) {
  const el = document.getElementById("paper-source-breakdown");
  if (!el) return;
  const breakdown = paperSourceBreakdown(state);
  el.innerHTML = breakdown.map((b) => {
    const label = b.source === "auto" ? "自動跟單" : "手動操作";
    const cls = b.total >= 0 ? "live-up" : "live-down";
    return `<div class="card">
      <div class="label">${label}</div>
      <div class="value ${cls}">${b.total >= 0 ? "+" : ""}${Math.round(b.total).toLocaleString()}</div>
      <div class="footnote">已實現 ${b.realized >= 0 ? "+" : ""}${Math.round(b.realized).toLocaleString()}｜未實現 ${b.unrealized >= 0 ? "+" : ""}${Math.round(b.unrealized).toLocaleString()}</div>
      <div class="footnote">交易 ${b.trades} 次｜勝率 ${b.winRate === null ? "-" : `${fmtNum(b.winRate, 0)}%`}｜獲利因子 ${paperFmtRatio(b.profitFactor)}</div>
    </div>`;
  }).join("");
}

function paperRenderSymbolLeaderboard(state) {
  const el = document.getElementById("paper-symbol-leaderboard");
  if (!el) return;
  const rows = paperSymbolPnlLeaderboard(state);
  const gainers = rows.filter((r) => r.pnl > 0).sort((a, b) => b.pnl - a.pnl).slice(0, 5);
  const losers = rows.filter((r) => r.pnl < 0).sort((a, b) => a.pnl - b.pnl).slice(0, 5);

  const renderList = (list, emptyMsg) => list.length === 0
    ? `<p class="footnote">${emptyMsg}</p>`
    : `<ol class="paper-leaderboard-list">${list.map((r) =>
        `<li><span>${SYMBOL_NAMES[r.symbol] || r.symbol}</span><span class="${r.pnl >= 0 ? "live-up" : "live-down"}">${r.pnl >= 0 ? "+" : ""}${Math.round(r.pnl).toLocaleString()}</span></li>`
      ).join("")}</ol>`;

  el.innerHTML = `
    <div class="paper-leaderboard-col">
      <div class="footnote">賺最多</div>
      ${renderList(gainers, "目前沒有獲利標的")}
    </div>
    <div class="paper-leaderboard-col">
      <div class="footnote">賠最多</div>
      ${renderList(losers, "目前沒有虧損標的")}
    </div>`;
}

function paperRenderAll() {
  renderTradeButtons(document);
  paperRenderDashboardPage();
}
