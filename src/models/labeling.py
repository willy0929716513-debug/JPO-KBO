"""Triple-barrier labeling and meta-labeling (Lopez de Prado, 'Advances in
Financial Machine Learning', ch. 3). Turns a primary directional signal into
a proper supervised-learning target that accounts for *when* a trade would
have closed (profit-take, stop-loss, or time-out), instead of the naive
"did price go up N bars later" label used by `train.make_labels()`.

Meta-labeling then trains a *second* classifier to predict whether the
primary signal's bet is worth taking at all -- used to filter out
low-quality primary signals. This typically trades some recall for higher
precision, which is usually the right trade-off for live trading (fewer,
higher-conviction trades beat many noisy ones).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_volatility(close: pd.Series, span: int = 100) -> pd.Series:
    """Exponentially-weighted rolling volatility of returns, used to scale
    the profit-take/stop-loss barriers to current market conditions."""
    returns = close.pct_change()
    return returns.ewm(span=span, min_periods=max(span // 2, 2)).std()


def triple_barrier_labels(
    close: pd.Series, primary_side: pd.Series, pt_mult: float = 2.0, sl_mult: float = 2.0,
    max_holding: int = 10, volatility: pd.Series | None = None,
) -> pd.DataFrame:
    """For each bar where `primary_side` is non-zero (1=long, -1=short),
    look forward up to `max_holding` bars and find whichever barrier is
    touched first: profit-take (+pt_mult*vol), stop-loss (-sl_mult*vol), or
    the vertical/time barrier. Returns one row per signalled bar with the
    realized return, the resulting outcome_label (1=win/-1=loss/0=flat),
    and a binary meta_label (1 iff the primary bet would have won) that is
    the actual target used to train a meta-labeling model.
    """
    vol = volatility if volatility is not None else daily_volatility(close)
    n = len(close)
    idx = close.index
    close_vals = close.to_numpy()
    side_vals = primary_side.reindex(close.index).fillna(0).to_numpy()
    vol_vals = vol.to_numpy()

    records = []
    for i in range(n):
        side = side_vals[i]
        if side == 0 or np.isnan(vol_vals[i]) or vol_vals[i] <= 0:
            continue

        entry_price = close_vals[i]
        pt_barrier = entry_price * (1 + side * pt_mult * vol_vals[i])
        sl_barrier = entry_price * (1 - side * sl_mult * vol_vals[i])

        end = min(i + max_holding, n - 1)
        exit_price, holding_bars, outcome_label = close_vals[end], end - i, None

        for j in range(i + 1, end + 1):
            price = close_vals[j]
            hit_pt = price >= pt_barrier if side == 1 else price <= pt_barrier
            hit_sl = price <= sl_barrier if side == 1 else price >= sl_barrier
            if hit_pt:
                exit_price, holding_bars, outcome_label = price, j - i, 1
                break
            if hit_sl:
                exit_price, holding_bars, outcome_label = price, j - i, -1
                break

        if outcome_label is None:
            # time barrier reached without hitting pt/sl: label by realized return sign
            realized = side * (exit_price / entry_price - 1)
            outcome_label = 1 if realized > 0 else (-1 if realized < 0 else 0)

        realized_return = side * (exit_price / entry_price - 1)
        records.append({
            "timestamp": idx[i], "side": side, "entry_price": entry_price, "exit_price": exit_price,
            "holding_bars": holding_bars, "realized_return": realized_return, "outcome_label": outcome_label,
            "meta_label": 1 if outcome_label == 1 else 0,
        })

    if not records:
        return pd.DataFrame(columns=["side", "entry_price", "exit_price", "holding_bars",
                                      "realized_return", "outcome_label", "meta_label"])
    return pd.DataFrame(records).set_index("timestamp")


def momentum_primary_side(close: pd.Series, lookback: int = 10) -> pd.Series:
    """A simple, deterministic primary model (sign of trailing momentum)
    good enough to generate the primary side needed for meta-labeling when
    you don't already have another strategy's directional call to reuse.
    In practice you'd usually pass in an existing Strategy's BUY/SELL calls
    instead -- this is just a reasonable default."""
    momentum = close.pct_change(lookback)
    return np.sign(momentum).fillna(0)
