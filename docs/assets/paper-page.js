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
}

document.getElementById("refresh-btn").addEventListener("click", loadPaperPage);
loadPaperPage();
setInterval(loadPaperPage, PAPER_PAGE_REFRESH_MS);
