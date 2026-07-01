#!/usr/bin/env python3
"""CLI entry point: `python scripts/run_pipeline.py`
Runs the full data -> features -> regime -> strategies -> signals pipeline
once, and writes results to docs/data/ for the dashboard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.daily_run import run_daily_pipeline  # noqa: E402

if __name__ == "__main__":
    payload = run_daily_pipeline()
    print(f"Analyzed {payload['successful']}/{payload['watchlist_size']} symbols.")
    for sig in payload["signals"]:
        s = sig["signal"]
        print(f"  {sig['symbol']:>10} [{sig['asset_class']:<8}] "
              f"{s['final_action']:<4} conf={s['confidence']:.2f} regime={sig['regime']['state']}")
