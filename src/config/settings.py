"""Central configuration for the quant trading system.

All values can be overridden via environment variables or a local .env file.
Nothing here requires a paid API key to run the core pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
DOCS_DATA_DIR = ROOT_DIR / "docs" / "data"

for _dir in (DATA_DIR, CACHE_DIR, DOCS_DATA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Trading mode safety switch ---
    trading_mode: Literal["paper", "live"] = Field(default="paper")

    # --- Macro data ---
    fred_api_key: str | None = None

    # --- Alerts ---
    discord_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    alert_email_to: str | None = None

    # --- Broker credentials (unused unless trading_mode == "live") ---
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    binance_api_key: str | None = None
    binance_secret: str | None = None

    # --- Database ---
    database_url: str = f"sqlite:///{DATA_DIR / 'quant.db'}"

    # --- Backtest defaults ---
    default_commission_bps: float = 5.0   # 0.05% per trade
    default_slippage_bps: float = 5.0     # 0.05% per trade
    risk_free_rate: float = 0.04

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"


settings = Settings()


class Universe:
    """Default tradable universe across asset classes.

    Symbols use the ticker convention understood by each data provider
    (yfinance tickers for equities/ETF/futures/FX, ccxt unified symbols for crypto).
    Edit freely -- this is just a sane starting default.
    """

    US_EQUITIES = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V"]
    TAIWAN_EQUITIES = ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2603.TW"]
    ETF = ["SPY", "QQQ", "IWM", "DIA", "VTI", "ARKK"]
    METALS = {"gold": "GC=F", "silver": "SI=F", "gold_etf": "GLD", "silver_etf": "SLV"}
    ENERGY = {"crude_oil": "CL=F", "brent": "BZ=F", "natgas": "NG=F"}
    FOREX = ["EURUSD=X", "USDJPY=X", "GBPUSD=X", "USDTWD=X", "DX-Y.NYB"]
    CRYPTO = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]

    MACRO_FRED_SERIES = {
        "cpi": "CPIAUCSL",
        "ppi": "PPIACO",
        "fed_funds_rate": "FEDFUNDS",
        "us_10y_yield": "DGS10",
        "us_2y_yield": "DGS2",
        "unemployment": "UNRATE",
        "gdp": "GDP",
        "nonfarm_payroll": "PAYEMS",
    }

    TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1wk"]

    @classmethod
    def all_yfinance_symbols(cls) -> list[str]:
        syms = set(cls.US_EQUITIES + cls.TAIWAN_EQUITIES + cls.ETF + cls.FOREX)
        syms.update(cls.METALS.values())
        syms.update(cls.ENERGY.values())
        return sorted(syms)
