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

**儀表板分成兩層**：預設首頁只顯示「今日建議清單」——白話中文卡片，一檔標的一張卡，寫清楚做多/做空/觀望、建議價位、停損停利、一句話原因；上面提到的策略投票細節、多代理意見、統計套利數據、完整回測指標，都收在頁面最下面「🔧 進階資料」可展開區塊裡，預設收合，一般使用者不需要看到。「今日建議清單」內再分成「🇹🇼 台股焦點（主要）」與「🌐 其他市場（輔助參考）」兩區，`WATCHLIST["taiwan"]`（`src/pipeline/daily_run.py`）目前涵蓋 48 檔台股大型權值股（半導體、金融、電子代工、塑化鋼鐵、航運、電信等各產業龍頭），是追蹤標的最多、也是唯一大幅擴充的單一市場；美股/ETF/黃金/原油/外匯/加密貨幣維持原本的小規模輔助清單。每張卡片除了買賣建議，也會顯示一行技術指標細節（RSI(14)、MACD 柱狀圖、SMA20/SMA50、量比、ATR%），資料來自 `_extract_indicators()`（`src/pipeline/daily_run.py`），從既有的 300+ 特徵矩陣中挑出這幾個最常用的指標，不需要另外重算。

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
  透過 `.github/workflows/update_signals.yml` 每 5 分鐘自動跑一次，儀表板本身也每 60 秒自動重新讀取一次最新資料
  （不用手動按重新整理）。要做到真正逐秒即時，需要付費資料源（見上方「未實作」表格）。
  **關於「每 5 分鐘」的真正做法（誠實說明一段排查過程）**：一開始單純用 GitHub 的 `schedule: */5 * * * *`，但實測
  發現真實執行間隔是 **60-250 分鐘一次，根本不是 5 分鐘**。原因是 GitHub 官方文件承認的平台限制：排程事件在系統
  負載高時會延遲，尤其整點附近；而 `*/5 * * * *` 剛好是全 GitHub 上最多人用的排程寫法，等於跟全世界的 repo 一起
  排隊。**解法是不要依賴 `schedule:` 本身的準時性**：現在的 `update_signals.yml` 改成「自我串聯」設計——每次執行
  一開始就用內建的 `GITHUB_TOKEN`（不需要另外申請任何金鑰）呼叫 `gh workflow run` 把「下一次」排進佇列，然後在同一次
  執行裡用 shell 迴圈每 5 分鐘重算一次、連續跑上限約 5 小時 40 分（GitHub 單一 job 的硬上限是 6 小時），時間到了
  之後，已經排隊等待的下一棒會立刻接手，完全不會中斷。原本的 `schedule:` 只留著當保險（每 6 小時觸發一次），
  萬一整串串聯真的斷掉（例如有人手動取消某次執行、或執行環境罕見地整個當機），最多幾小時內會自動重新啟動一串新的。
  如果你還是想要更保守的雙重保險，也可以另外設定外部排程服務（例如免費的 cron-job.org）每 5 分鐘呼叫一次
  GitHub REST API 的 `workflow_dispatch` endpoint，但這需要你自己申請一組 Personal Access Token 並設定在該外部
  服務裡——這是選用的額外保險，不是必要步驟，因為上面的自我串聯設計已經能穩定達到每 5 分鐘的效果。
- **台股（嘗試提供真即時報價）** `common.js` 的 `startTaiwanLiveQuotes()`：會嘗試直接連線 TWSE 自己的公開報價
  API（`mis.twse.com.tw`，無需金鑰），每 15 秒輪詢一次，成功的話會直接更新台股卡片上的價格數字（閃綠/閃紅提示漲跌），
  不用等 5 分鐘的排程。**這個 API 是否對外開放 CORS 是不保證的行為，本機開發環境的網路政策擋住了對它的連線測試，
  所以無法在部署前實際驗證**——設計上刻意做成失敗才會安靜關閉（連續 2 次失敗就停止輪詢、隱藏綠點指示燈），
  絕不會因為它連不上而讓其他功能出錯，最差情況就是退回原本每 5 分鐘更新一次的價格。實際能不能用，需要你在瀏覽器
  打開網站後觀察「🇹🇼 台股焦點」標題旁邊有沒有出現綠色小圓點。
- **市場開盤偵測** `src/data/market_hours.py`：每 5 分鐘跑一次不代表每次都重新分析全部標的——`is_market_open()`
  會依資產類別判斷該市場現在是否開盤中（美股 NYSE 時段、台股 TWSE 時段、外匯/期貨近 24 小時週間交易、加密貨幣全年無休），
  收盤中的標的直接沿用上一筆資料（`daily_run.py` 會從上次的 `signals_latest.json` 帶入），不重新抓資料也不重新跑策略，
  只有真正開盤的標的才會重新分析。每筆訊號都會附上 `market_open` 欄位，儀表板上顯示「🟢 開盤中」或「⚪ 已收盤」，
  這個欄位**永遠反映 `is_market_open()` 當下判斷的真實結果**，跟這檔標的這次到底是「沿用舊資料」還是「剛好重新分析」無關——
  早期版本曾經把「這是第一次追蹤、沒有舊資料可沿用，所以重新分析一次」誤寫成順便把 `market_open` 寫死成 `True`，
  導致剛加入清單的新標的即使市場明明已收盤，也會被誤標成「🟢 開盤中」，已修正（見
  `tests/test_daily_run_market_hours.py::test_first_run_analyzes_closed_market_symbol_anyway`）。
  （此判斷只看每週固定交易時段，未涵蓋國定假日休市，假日會被誤判為開盤，但頂多是多做一次無意義的重複分析，不會產生錯誤資料。）
- **即時價格總覽頁** `docs/prices.html`：另開一頁，把所有追蹤的標的依「台股」「美股/ETF」「期貨/商品」「外匯」分類顯示，
  加密貨幣一樣是真正即時 WebSocket，其他類別顯示最新價格、漲跌幅（跟前一個交易日收盤價比較，和一般股票 App 的
  「漲跌幅」定義一致——**不是**跟上一次資料更新比較；早期版本曾經誤用「跟上一次輪詢比較」，在免費資料源本身
  15-20 分鐘才更新一次的情況下，大部分時間都會顯示沒意義的 0%，已修正）、開盤狀態徽章。從主頁右上角
  「💹 即時價格總覽」可以連過去。
- **「重新整理」按鈕的實際行為**：按下去只會重新抓取 `docs/data/signals_latest.json`（GitHub Actions 產生的最新結果，實際更新間隔請見上方的誠實說明），
  **不會**在瀏覽器裡當場重新跑一次策略運算。這是因為 GitHub Pages 是純靜態網站，沒有後端伺服器可以即時執行 Python；
  唯一能觸發真正重算的方式是 GitHub Actions 排程或手動 `workflow_dispatch`，而在瀏覽器端安全地觸發這件事需要一組有寫入
  權限的 GitHub 憑證——把它放進前端 JavaScript 等於公開給任何訪客，是不能接受的安全風險，所以沒有這樣做。實務上兩者
  差距最多 5 分鐘，重新整理的價值是「看最新一次結果」而不是「逼系統馬上重算」。

## 模擬交易頁面 `docs/paper.html`（純瀏覽器端，不是真的自動交易）

一個獨立頁面，讓你可以用一筆虛擬台幣（預設 100 萬）練習跟著系統訊號做多/做空：

- **手動模擬**：在「今日建議」首頁的每張台股/其他市場卡片下方，都有「模擬做多」「模擬做空」按鈕，點下去輸入想要的股數，
  依目前價格模擬成交；已有模擬持倉的卡片會改成顯示未實現損益和「模擬平倉」按鈕。
- **自動跟單**：在 `paper.html` 頁面上有一個開關，打開後系統每次更新建議清單時，會自動幫你模擬開倉（固定約 10 萬台幣
  一筆）/ 平倉，完全依照卡片上顯示的做多/做空/觀望訊號，不需要手動操作；自動跟單開的倉位跟手動開的倉位互不干擾。
- **資料儲存與限制（誠實說明）**：整個模擬交易功能都是純前端 JavaScript + `localStorage`，**沒有任何後端資料庫**：
  虛擬資產只存在你目前這個瀏覽器裡，換裝置、換瀏覽器、清除網站資料都會重置回初始的 100 萬；「自動跟單」也只有在你
  **開著這個網頁分頁時**才會被評估執行一次，瀏覽器關掉或分頁沒開，就不會有任何模擬交易發生——這跟真正 24 小時在背景
  幫你下單的系統是完全不同的，之所以做成這樣，是因為 GitHub Pages 是純靜態網站，沒有伺服器可以在你沒開網頁時執行任何程式碼。
- **虛擬資產走勢圖**：`paper.html` 上會畫出虛擬總資產隨時間變化的折線圖（`paperRecordEquitySnapshot()`，`docs/assets/paper.js`），
  每次任何頁面抓到最新價格時都會記錄一筆快照，累積到至少兩筆之後開始畫線；跟其他模擬交易資料一樣，只存在這個瀏覽器裡。

## 個股相關新聞（讓訊號跟時事掛勾）

每張股票卡片（台股/美股/ETF/黃金/原油/外匯）下方，如果 Yahoo 有收錄相關新聞，會額外顯示 1-3 則最新新聞標題＋
連結＋來源媒體，讓你在看到「建議做多/做空」的同時，也能一眼看到背後可能是什麼時事在推動（例如財報、法說會、
產業消息）。**只顯示新聞，不會拿新聞內容去影響做多/做空的信心度計算**——這個判斷交給你自己，系統只負責把相關
新聞攤在你面前。

實作在 `YFinanceProvider.get_news()`（`src/data/providers/yfinance_provider.py`），用 yfinance 內建、完全免費、
不需要金鑰的新聞功能，加密貨幣目前沒有接（yfinance 的新聞功能只涵蓋它本身有報價的股票類標的，不包含 `BTC/USDT`
這種格式的加密貨幣代號）。**誠實說明一個無法在部署前驗證的風險**：Yahoo 這個新聞 API 的 JSON 格式在不同 yfinance
版本之間换过至少一次（舊版是平鋪的欄位，新版把大部分欄位包在一層 `content` 裡），而這個 repo 的沙盒環境沒有對外
網路可以連線測試新聞 API 的即時回傳格式長什麼樣子，所以無法百分之百保證正式環境的回應格式跟程式碼假設的一致。
`_extract_news_items()` 對兩種已知格式都做了容錯處理，遇到解析不出來的文章就直接跳過，最差情況就是某些標的暫時沒有
新聞可顯示，**不會**讓整個訊號產生流程壞掉。如果你發現網站上某些股票明明有新聞、卻完全沒顯示，麻煩跟我說一聲，
我再依實際的 API 回應格式調整解析邏輯。

## 易用性功能（2026-07 新增）

- **搜尋 / 篩選**：首頁「今日建議」新增搜尋框（比對代號或中文名稱）和「只看做多/做空」開關，即時套用在已抓到的資料上，
  不用重新打一次 API；台股清單擴充到 48 檔之後，這讓你不用整批卡片捲過一遍找想看的標的。
- **🌟 今日焦點**：獨立於搜尋/篩選之外，永遠顯示全市場信心程度最高的前 5 檔可操作（非觀望）標的，一打開網頁就有結論。
- **🆕 剛轉變徽章**：每次資料更新都會比對這個瀏覽器上次看到的訊號（`localStorage`），如果某檔標的的做多/做空/觀望
  狀態跟上次不一樣，卡片上會多一個「🆕 剛轉變」徽章；第一次看到的標的不會被誤判成「剛轉變」。
- **瀏覽器通知**：首頁右上角「🔔 開啟強訊號通知」按鈕（需要使用者主動點擊才能跳出瀏覽器的權限請求，這是瀏覽器規定，
  網站無法自動跳出）。開啟後，只要有標的的訊號轉為信心程度較高（≥60%）的做多/做空，就會跳出瀏覽器通知；同樣是純
  前端功能，只在你開著分頁時才會運作。
- **加到主畫面（PWA）**：三個頁面都加了 `manifest.json`、`apple-touch-icon`、offline 用的 `sw.js` (Service Worker)。
  在手機瀏覽器（例如 iPhone Safari）用「加入主畫面」，就會出現一個獨立的品牌圖示，點開後接近全螢幕的原生 App 體驗；
  Service Worker 會快取頁面本身的 HTML/CSS/JS，離線時仍能打開 App 並看到最後一次抓到的資料（外部連線如即時股價、
  Chart.js CDN 沒有網路時當然還是不能用）。

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
