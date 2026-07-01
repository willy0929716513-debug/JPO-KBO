"""Statistical arbitrage: pairs trading via cointegration + a dynamic
(Kalman-filtered) hedge ratio. This operates on *two* symbols at once, so it
deliberately does not implement the single-symbol `Strategy` interface --
use `PairsTradingStrategy.analyze()` directly instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class KalmanHedgeRatio:
    """1D Kalman filter estimating a time-varying hedge ratio beta (and
    intercept alpha) for y_t = beta_t * x_t + alpha_t + noise -- standard in
    pairs trading so the hedge ratio adapts as the relationship between the
    two assets drifts, instead of locking in one fixed OLS beta.
    """
    delta: float = 1e-4            # state transition covariance scale (how fast beta/alpha can drift)
    observation_var: float = 1e-3  # measurement noise variance

    def run(self, y: pd.Series, x: pd.Series) -> pd.DataFrame:
        n = len(y)
        theta = np.zeros(2)   # state = [beta, alpha]
        P = np.eye(2)
        Q = np.eye(2) * self.delta

        betas = np.zeros(n)
        alphas = np.zeros(n)
        spreads = np.zeros(n)  # innovation = observed y - predicted y, i.e. the trading spread

        y_vals, x_vals = y.to_numpy(), x.to_numpy()
        for t in range(n):
            F = np.array([x_vals[t], 1.0])

            P = P + Q  # predict (random-walk state model)

            y_pred = F @ theta
            innovation = y_vals[t] - y_pred
            S = F @ P @ F.T + self.observation_var
            K = (P @ F) / S
            theta = theta + K * innovation
            P = P - np.outer(K, F) @ P

            betas[t], alphas[t], spreads[t] = theta[0], theta[1], innovation

        return pd.DataFrame({"beta": betas, "alpha": alphas, "spread": spreads}, index=y.index)


def cointegration_test(y: pd.Series, x: pd.Series) -> dict:
    """Engle-Granger two-step cointegration test between two price series.
    A pair should only be traded as stat-arb if this passes (p < 0.05) --
    otherwise the 'spread' isn't statistically mean-reverting and trading it
    is directional risk dressed up as arbitrage.
    """
    from statsmodels.tsa.stattools import coint

    aligned = pd.concat([y, x], axis=1, join="inner").dropna()
    if len(aligned) < 30:
        return {"cointegrated": False, "p_value": 1.0, "t_stat": 0.0, "n_obs": len(aligned)}

    t_stat, p_value, _ = coint(aligned.iloc[:, 0], aligned.iloc[:, 1])
    return {"cointegrated": bool(p_value < 0.05), "p_value": float(p_value), "t_stat": float(t_stat),
            "n_obs": len(aligned)}


@dataclass
class PairSignal:
    symbol_a: str
    symbol_b: str
    action_a: str  # BUY/SELL/HOLD on symbol_a
    action_b: str  # BUY/SELL/HOLD on symbol_b -- opposite of action_a when trading the spread
    zscore: float
    hedge_ratio: float
    cointegrated: bool
    p_value: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol_a": self.symbol_a, "symbol_b": self.symbol_b,
            "action_a": self.action_a, "action_b": self.action_b,
            "zscore": round(self.zscore, 3), "hedge_ratio": round(self.hedge_ratio, 4),
            "cointegrated": self.cointegrated, "p_value": round(self.p_value, 4),
            "reasons": self.reasons,
        }


class PairsTradingStrategy:
    """Cointegration + Kalman-filtered hedge ratio pairs trading.

    Entry: when the pair is cointegrated and the spread z-score exceeds
    `entry_z`, bet on mean reversion (long the relative underperformer,
    short the relative outperformer). Exit when the spread reverts inside
    `exit_z`.
    """

    name = "statistical_arbitrage"

    def __init__(self, entry_z: float = 2.0, exit_z: float = 0.5, lookback: int = 60,
                 kalman: KalmanHedgeRatio | None = None):
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.lookback = lookback
        self.kalman = kalman or KalmanHedgeRatio()

    def analyze(self, symbol_a: str, close_a: pd.Series, symbol_b: str, close_b: pd.Series) -> PairSignal:
        coint_result = cointegration_test(close_a, close_b)

        aligned = pd.concat([close_a, close_b], axis=1, join="inner").dropna()
        aligned.columns = ["a", "b"]
        if len(aligned) < self.lookback:
            return PairSignal(symbol_a, symbol_b, "HOLD", "HOLD", 0.0, 0.0,
                               coint_result["cointegrated"], coint_result["p_value"],
                               ["Not enough overlapping history for this pair"])

        if not coint_result["cointegrated"]:
            return PairSignal(symbol_a, symbol_b, "HOLD", "HOLD", 0.0, 0.0, False, coint_result["p_value"],
                               [f"Pair failed cointegration test (p={coint_result['p_value']:.3f} >= 0.05); "
                                "spread is not statistically mean-reverting, skipping"])

        kf = self.kalman.run(np.log(aligned["a"]), np.log(aligned["b"]))
        spread = kf["spread"]
        recent_spread = spread.tail(self.lookback)
        spread_std = recent_spread.std() or 1.0
        zscore = float((spread.iloc[-1] - recent_spread.mean()) / spread_std)
        hedge_ratio = float(kf["beta"].iloc[-1])

        reasons = [f"Engle-Granger cointegration p={coint_result['p_value']:.4f} (cointegrated)",
                   f"Kalman-filtered hedge ratio={hedge_ratio:.4f}", f"Spread z-score={zscore:.2f}"]

        if zscore >= self.entry_z:
            action_a, action_b = "SELL", "BUY"
            reasons.append(f"Spread stretched high (z>={self.entry_z}): short {symbol_a}, long {symbol_b}")
        elif zscore <= -self.entry_z:
            action_a, action_b = "BUY", "SELL"
            reasons.append(f"Spread stretched low (z<=-{self.entry_z}): long {symbol_a}, short {symbol_b}")
        elif abs(zscore) <= self.exit_z:
            action_a, action_b = "HOLD", "HOLD"
            reasons.append(f"Spread reverted inside exit band (|z|<={self.exit_z}): flat/close")
        else:
            action_a, action_b = "HOLD", "HOLD"
            reasons.append("Spread in no-trade zone between exit and entry bands")

        return PairSignal(symbol_a, symbol_b, action_a, action_b, zscore, hedge_ratio, True,
                           coint_result["p_value"], reasons)
