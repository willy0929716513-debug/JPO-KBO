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
├── models/        # XGBoost / LightGBM / RandomForest 投票集成、Triple-Barrier / Meta-Labeling
├── strategies/     # 趨勢跟隨 / 均值回歸 / 突破 / 動量 / ML / 統計套利(配對交易) + 訊號整合器
├── risk/          # 部位大小、停損、VaR/CVaR、相關性與曝險限額、每日/週/月虧損上限、最大回撤熔斷
├── backtest/       # 向量化回測引擎、Walk-Forward 驗證、Monte Carlo 模擬、20+ 績效指標
├── portfolio/      # 多資產配置 (等權重 / 反波動度 / 真正的風險平價 Risk Parity / 資產類別上限)
├── execution/      # 模擬執行引擎：Bracket/OCO/追蹤停損、TWAP/VWAP/POV 拆單模擬
├── agents/        # 多代理決策系統：Technical/Macro/Risk/Portfolio Agent + Decision Engine
├── mlops/         # 輕量 MLOps：本地模型註冊表、Champion/Challenger、PSI/KS 資料飄移偵測
├── broker/        # 執行層：預設 PaperBroker（模擬），多交易所/IBKR 實盤介面已預留但預設停用
├── alerts/        # Discord / Telegram / Email 通知（未設定金鑰時自動略過，不會報錯）
├── pipeline/       # daily_run.py：串接以上所有模組，輸出 docs/data/*.json 給前端儀表板
└── api/           # 選用的本地 FastAPI 服務，讀取/觸發 pipeline

docs/               # GitHub Pages 靜態儀表板（純 HTML/CSS/JS + Chart.js，讀取 docs/data/*.json）
tests/              # pytest 單元測試（108 個測試，涵蓋以上每個模組）
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

## 進階模組（2026-07 新增，全部只用免費資料）

| 模組 | 內容 |
|---|---|
| **統計套利** `src/strategies/statistical_arbitrage.py` | Engle-Granger 共整合檢定（p<0.05 才視為共整合）+ Kalman Filter 動態避險比率，價差 z-score 超過門檻才進場，未通過共整合檢定的配對一律不交易 |
| **Meta-Labeling** `src/models/labeling.py` | Triple-Barrier 方法（停利/停損/時間三重障礙）替換單純的「N根K棒後漲跌」標籤，`train_meta_labeling_model()` 訓練二階模型判斷主策略訊號是否值得進場 |
| **風控引擎擴充** `src/risk/limits.py` + `src/risk/portfolio_risk.py` | 每日/週/月虧損上限（`LossLimitMonitor`）、Portfolio 層級 VaR/CVaR、相關性限額、產業/資產類別曝險限額檢查 |
| **真正的風險平價** `src/portfolio/allocator.py: risk_parity()` | 用 `scipy.optimize` 對共變異數矩陣求解等風險貢獻權重，考慮資產間相關性，不是單純反波動度加權 |
| **模擬執行引擎** `src/execution/` | `simulate_bracket_order` / `simulate_oco_order` / `simulate_trailing_stop`（判斷停利停損哪個先觸發）、`simulate_twap_execution` / `simulate_vwap_execution` / `simulate_pov_execution`（拆單模擬 + 滑價評估） |
| **輕量 MLOps** `src/mlops/` | `ModelRegistry`（本地 joblib+json 模型版本管理）、`should_promote_challenger`（Champion/Challenger 比較後才換模型）、`population_stability_index` / `ks_test_drift`（特徵飄移偵測） |
| **多代理決策系統** `src/agents/` | `TechnicalAgent`（包裝策略投票+市場狀態）、`MacroAgent`（總經+情緒面，低信心度慢速訊號）、`RiskAgent`（風險限額，可直接否決）、`PortfolioAgent`（資產類別曝險，可否決）→ `DecisionEngine` 加權彙整，任何 Agent 否決就直接變 HOLD |

擴充後的績效指標（`src/backtest/metrics.py`）：CAGR、Sharpe、Sortino、Calmar、**MAR、Omega、SQN、Alpha/Beta、Information Ratio、Expectancy、Recovery Factor、Rolling Sharpe/Drawdown**。

`daily_run.py` 每次執行都會：對每個標的同時跑「策略投票訊號」與「多代理決策」兩種結果，並對 GC=F/SI=F、SPY/QQQ、BTC/ETH 三組配對做統計套利檢定。**風控 Agent 的風險檢查只看最近 90 根K棒的權益曲線**，不會被「這檔標的過去好幾年前曾經有一次大跌」這種久遠歷史錯誤否決今天的訊號（早期版本有這個 bug，已修正，見 `tests/test_risk_windowing_regression.py`）。

**儀表板分成兩層**：預設首頁只顯示「今日建議清單」——白話中文卡片，一檔標的一張卡，寫清楚買進/賣出/觀望、建議價位、停損停利、一句話原因；上面提到的策略投票細節、多代理意見、統計套利數據、完整回測指標，都收在頁面最下面「🔧 進階資料」可展開區塊裡，預設收合，一般使用者不需要看到。

## 實盤交易介面（預設停用，需自行設定金鑰才會啟動）

`src/broker/` 底下每個介面都遵守同一個原則：**沒有設定對應金鑰/連線就無法建構物件，會直接
raise RuntimeError**，所以就算 `TRADING_MODE` 不小心設成 `live`，系統也不會意外連上真實帳戶下單。

| 介面 | 涵蓋市場 | 啟動條件 |
|---|---|---|
| `PaperBroker`（預設） | 全部，純模擬 | 不需要任何設定，永遠可用 |
| `CCXTBroker` | 加密貨幣：Binance / Bybit / OKX / Coinbase / Kraken / 其他 ccxt 支援的交易所（改 `EXCHANGE_ID` 即可切換） | `.env` 填 `EXCHANGE_API_KEY` + `EXCHANGE_API_SECRET`（部分交易所如 OKX 還需要 `EXCHANGE_API_PASSWORD`）。預設 `EXCHANGE_USE_TESTNET=true` 會走交易所的測試網，要接真實資金要自己改成 `false` |
| `AlpacaBroker` | 美股 / ETF | `.env` 填 `ALPACA_API_KEY` + `ALPACA_SECRET_KEY`（`pip install alpaca-trade-api`） |
| `IBKRBroker` | 全球股票/ETF/期貨/外匯/選擇權（Interactive Brokers） | `.env` 設 `IBKR_ENABLED=true`，且本機要有 TWS 或 IB Gateway 開著並啟用 API（`pip install ib_async`）。預設 port 7497 是 TWS 的**模擬帳戶**連接埠 |

用法：`from src.broker import get_broker; broker = get_broker("live", asset_class="crypto")` 會依資產類別自動選對應的介面；沒對應金鑰時會拋出清楚的錯誤訊息而不是靜默失敗。目前 `daily_run.py` pipeline 本身**不會呼叫這些介面下單**，只負責產生訊號——要接自動下單，需要你自行在 pipeline 或另一支腳本中，讀取 `CombinedSignal` 後呼叫 `broker.submit_order(...)`，並強烈建議先在 Paper Trading / 測試網跑過一段時間再考慮接真實資金。

## 價格更新頻率與市場開盤偵測（誠實說明「即時」能做到什麼程度）

- **加密貨幣（BTC/USDT、ETH/USDT）**：儀表板頂部「即時價格」面板透過瀏覽器直接連線 Binance 的公開
  WebSocket（`wss://stream.binance.com`），**真正逐筆即時更新**，不需要任何金鑰，也不經過 GitHub Actions。
- **股票 / 黃金 / 白銀 / 原油 / 外匯**：免費資料源（Yahoo Finance）沒有提供真正的即時逐筆報價（本身就有
  15-20 分鐘延遲），且瀏覽器無法直接跨網域請求 Yahoo 的 API（會被 CORS 政策擋掉）。這些標的改為
  透過 `.github/workflows/update_signals.yml`**每 5 分鐘自動跑一次**（GitHub Actions 排程支援的最短間隔），
  儀表板本身也每 60 秒自動重新讀取一次最新資料（不用手動按重新整理）。要做到真正逐秒即時，需要付費資料源
  （見上方「未實作」表格）。
- **市場開盤偵測** `src/data/market_hours.py`：每 5 分鐘跑一次不代表每次都重新分析全部標的——`is_market_open()`
  會依資產類別判斷該市場現在是否開盤中（美股 NYSE 時段、台股 TWSE 時段、外匯/期貨近 24 小時週間交易、加密貨幣全年無休），
  收盤中的標的直接沿用上一筆資料（`daily_run.py` 會從上次的 `signals_latest.json` 帶入），不重新抓資料也不重新跑策略，
  只有真正開盤的標的才會重新分析。每筆訊號都會附上 `market_open` 欄位，儀表板上顯示「🟢 開盤中」或「⚪ 已收盤」。
  （此判斷只看每週固定交易時段，未涵蓋國定假日休市，假日會被誤判為開盤，但頂多是多做一次無意義的重複分析，不會產生錯誤資料。）
- **即時價格總覽頁** `docs/prices.html`：另開一頁，把所有追蹤的標的依「股票/ETF」「期貨/商品」「外匯」「加密貨幣」分類顯示，
  加密貨幣一樣是真正即時 WebSocket，其他類別顯示最新價格、漲跌幅（跟上一次更新比較）、開盤狀態徽章。從主頁右上角
  「💹 即時價格總覽」可以連過去。

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
| 免金鑰即可用：股票/ETF/黃金/白銀/原油/外匯/加密貨幣 OHLCV、20+ 技術指標、市場結構、多週期趨勢、市場狀態偵測、規則式策略、統計套利、ML 集成、Meta-Labeling、回測 (含 Walk-Forward / Monte Carlo)、20+ 績效指標、完整風控引擎、風險平價、模擬執行引擎、輕量 MLOps、多代理決策系統、Paper Trading、多交易所/IBKR 實盤介面、GitHub Actions 自動化、Pages 儀表板 | ✅ 已完整實作並通過測試（108 個 pytest） |
| 需要你自己申請免費/付費金鑰才會啟用：FRED 總經數據、Discord/Telegram/Email 通知、Alpaca/交易所/IBKR 實盤下單 | 🔌 介面已預留，程式碼會在沒有金鑰時安全跳過，不會報錯中斷 |
| 規格中提及但本次未實作（需要付費機構級資料源或專屬伺服器叢集，架構上盡量預留了擴充點）：Tick Data / Level 2 Order Book / Dark Pool / 13F / Options Greeks / IV Surface / 衛星氣象航運等另類資料、真正的強化學習交易代理、市場微結構偵測（Footprint/Spoofing/Iceberg Detection，依賴 Tick/L2 資料）、Kubernetes/Airflow/Celery/ClickHouse/TimescaleDB 級基礎設施 | ⏳ 未實作 -- 原因與替代方案見上方模組說明 |

**再完整的系統也無法保證獲利。** 回測績效不代表未來表現，任何策略都可能隨市場結構改變而失效。
正式使用前務必：(1) 用更長期、更多市場的資料重新驗證回測結果，(2) 先跑一段時間 Paper Trading
確認訊號品質，(3) 設定好停損與資金控管，(4) 不要投入無法承受損失的資金。
