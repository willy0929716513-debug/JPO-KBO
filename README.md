# Professional Quant Trading System

一套模組化、可擴充的量化交易研究框架，涵蓋美股 / 台股 / ETF / 黃金 / 白銀 / 原油 / 外匯 / 加密貨幣，
自動產生技術分析、多策略投票訊號（BUY / SELL / HOLD）、回測績效與風險指標，並透過 GitHub Actions
每日自動更新、發布到 GitHub Pages 儀表板。

**Dashboard**: `docs/index.html`（GitHub Pages 啟用後即為 `https://<user>.github.io/<repo>/`）

> ⚠️ **重要聲明**：本系統預設僅連接 **Paper Trading（模擬撮合）**，不會下真實訂單、不會動用真實資金。
> 所有訊號皆由規則式策略與機率模型自動產生，僅供研究與教育用途，**不構成投資建議，也不保證獲利**。
> 任何量化策略都可能隨市場結構改變而失效，請務必自行判斷並做好資金與風險管理。

---

## 系統架構總覽

```
src/
├── config/        # 全域設定、資產池 (Universe)，全部可用環境變數覆寫，無需任何金鑰即可執行
├── data/          # 資料層：yfinance / ccxt / FRED / Fear&Greed provider + 本地 Parquet 快取
├── features/      # 技術指標、市場結構 (SMC/ICT 簡化版)、多週期趨勢、特徵管線 (registry pattern)
├── regime/        # 市場狀態偵測：牛市/熊市/盤整/高波動/低波動
├── models/        # XGBoost / LightGBM / RandomForest 投票集成，含機率校準
├── strategies/     # 趨勢跟隨 / 均值回歸 / 突破 / 動量 / ML 策略 + 依市場狀態動態加權的訊號整合器
├── risk/          # Kelly / 固定比例 / ATR 部位、追蹤停損、VaR / CVaR、最大回撤熔斷、破產風險
├── backtest/       # 向量化回測引擎、Walk-Forward 驗證、Monte Carlo 模擬、績效指標
├── portfolio/      # 多資產配置 (等權重 / 反波動度風險平價 / 資產類別上限)
├── broker/        # 執行層：預設 PaperBroker（模擬），Alpaca / 交易所實盤介面已預留但預設停用
├── alerts/        # Discord / Telegram / Email 通知（未設定金鑰時自動略過，不會報錯）
├── pipeline/       # daily_run.py：串接以上所有模組，輸出 docs/data/*.json 給前端儀表板
└── api/           # 選用的本地 FastAPI 服務，讀取/觸發 pipeline

docs/               # GitHub Pages 靜態儀表板（純 HTML/CSS/JS + Chart.js，讀取 docs/data/*.json）
tests/              # pytest 單元測試（技術指標、特徵管線、策略、回測、風險、broker、portfolio）
scripts/run_pipeline.py   # 本地手動執行整套 pipeline 的 CLI 入口
.github/workflows/  # 每日排程更新訊號 (update_signals.yml) + CI 測試 (ci.yml)
```

## 資料流程

1. **抓資料**：`YFinanceProvider`（股票/ETF/台股/黃金/白銀/原油/外匯，來自 Yahoo Finance，免金鑰）
   與 `CCXTProvider`（加密貨幣 OHLCV / 委託簿 / Funding Rate / 未平倉量，來自 Binance 公開 API，免金鑰）。
   總經數據（CPI/PPI/Fed利率/公債殖利率/失業率/GDP/非農）透過 FRED API（需免費金鑰，未設定時自動跳過不報錯）。
2. **特徵工程**：`FeaturePipeline` 用 `@register_feature` 裝飾器將指標拆成獨立區塊（趨勢/動量/波動率/量能/
   市場結構/時間特徵），並自動加上滯後與滾動統計特徵，方便持續擴充到數百個欄位而不需改動主流程。
3. **市場狀態偵測**：`RegimeDetector` 依 ADX 與已實現波動率百分位，將市場分類為 `bull_trend` /
   `bear_trend` / `range_bound` / `high_volatility` / `low_volatility`。
4. **策略投票**：四個規則式策略（趨勢跟隨、均值回歸、突破、動量）各自產生訊號與信心度，
   `StrategyCombiner` 依偵測到的市場狀態動態調整每個策略的權重（例如盤整時均值回歸權重提高、
   趨勢盤時趨勢跟隨與動量權重提高），加權投票得出最終 BUY / SELL / HOLD 訊號、停損與停利價位。
5. **（選用）機器學習策略**：`src/models/train.py` 可用 XGBoost + LightGBM + RandomForest 投票集成，
   以 TimeSeriesSplit 做出樣本外驗證，訓練完成後可包成 `MLStrategy` 一起加入投票。
6. **回測驗證**：`BacktestEngine` 將訊號序列轉換成停損反手部位、計入手續費與滑價成本，輸出
   權益曲線與交易紀錄；`walk_forward_backtest` 做滾動樣本外回測；`monte_carlo_simulate` 對交易報酬
   重抽樣估計破產機率與報酬分佈，避免對單一歷史路徑過度自信。
7. **風險管理**：部位大小可選 Kelly / 固定風險比例 / ATR 動態部位；`DrawdownCircuitBreaker` 在權益
   回撤超過門檻時停止進場；`historical_var` / `conditional_var` 估計尾端風險。
8. **輸出與自動化**：`src/pipeline/daily_run.py` 串接以上全部流程，將結果寫入
   `docs/data/signals_latest.json`（含每檔標的訊號、市場狀態、策略回測快照）與
   `docs/data/history.json`（近 90 次執行的訊號歷史，供前端畫趨勢圖）。GitHub Actions
   (`update_signals.yml`) 每個交易日自動執行一次並提交更新，儀表板隨之自動更新。

## 快速開始

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # 選用：填入 FRED / Discord / Telegram 等金鑰，完全不填也能跑核心功能

python scripts/run_pipeline.py     # 執行一次完整 pipeline，結果寫入 docs/data/
pytest tests/ -v                   # 執行單元測試

# 本地預覽儀表板
cd docs && python -m http.server 8000   # 開瀏覽器打開 http://localhost:8000
```

## 部署到 GitHub Pages

1. Repo 設定 → Pages → Source 選擇 `main` 分支、`/docs` 資料夾。
2. 確認 `.github/workflows/update_signals.yml` 有權限寫回 repo（Settings → Actions → General →
   Workflow permissions → 設為 *Read and write permissions*）。
3. 之後每個交易日 GitHub Actions 會自動抓最新資料、重新計算訊號並更新 `docs/data/*.json`，
   Pages 網站會自動反映最新內容；也可以在 Actions 頁面手動觸發 `workflow_dispatch`。

首次部署前 `docs/data/signals_latest.json` 內含**合成示範資料**（`"demo_data": true`），方便先看到
畫面長什麼樣子；第一次自動排程執行後就會被真實資料取代。

## 目前涵蓋範圍與已知限制（誠實揭露）

這份系統把使用者原始需求中的規格拆成三類：

| 類別 | 狀態 |
|---|---|
| 免金鑰即可用：股票/ETF/黃金/白銀/原油/外匯/加密貨幣 OHLCV、20+ 技術指標、市場結構、多週期趨勢、市場狀態偵測、規則式策略、ML 集成、回測 (含 Walk-Forward / Monte Carlo)、風險管理、Paper Trading、GitHub Actions 自動化、Pages 儀表板 | ✅ 已完整實作並通過測試 |
| 需要你自己申請免費/付費金鑰才會啟用：FRED 總經數據、Discord/Telegram/Email 通知、Alpaca 或交易所實盤下單 | 🔌 介面已預留，程式碼會在沒有金鑰時安全跳過，不會報錯中斷 |
| 規格中提及但本次未實作（範疇過大或需要付費資料源，架構上都預留了擴充點）：Order Book 完整歷史 / Options Gamma Exposure / Whale Alert / 鏈上資料 / Twitter/Reddit 即時情緒 (`SentimentProvider` 有 pluggable 介面可自行接入) / 強化學習 / 多代理 AI 投票 / 異常偵測 / PostgreSQL+Redis+Kubernetes 級基礎設施 | ⏳ 未實作 |

**再完整的系統也無法保證獲利。** 回測績效不代表未來表現，任何策略都可能隨市場結構改變而失效。
正式使用前務必：(1) 用更長期、更多市場的資料重新驗證回測結果，(2) 先跑一段時間 Paper Trading
確認訊號品質，(3) 設定好停損與資金控管，(4) 不要投入無法承受損失的資金。
