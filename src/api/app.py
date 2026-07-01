"""Optional local FastAPI server exposing the latest signals/backtests as
JSON (useful if you want to hit this from your own tools instead of reading
docs/data/*.json directly). Run with: `uvicorn src.api.app:app --reload`
"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException

from src.config import DOCS_DATA_DIR
from src.pipeline.daily_run import run_daily_pipeline

app = FastAPI(title="Quant Trading System API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/signals/latest")
def latest_signals():
    path = DOCS_DATA_DIR / "signals_latest.json"
    if not path.exists():
        raise HTTPException(404, "No signals generated yet. Run scripts/run_pipeline.py first.")
    return json.loads(path.read_text())


@app.post("/signals/refresh")
def refresh_signals():
    return run_daily_pipeline()
