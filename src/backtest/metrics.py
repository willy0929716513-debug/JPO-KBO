"""Performance metrics computed from an equity curve / trade log."""
from __future__ import annotations

import numpy as np
import pandas as pd


def cagr(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    if len(equity_curve) < 2 or equity_curve.iloc[0] <= 0:
        return 0.0
    n_years = len(equity_curve) / periods_per_year
    if n_years <= 0:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    if total_return <= 0:
        return -1.0
    return float(total_return ** (1 / n_years) - 1)


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.04, periods_per_year: int = 252) -> float:
    excess = returns - risk_free_rate / periods_per_year
    std = excess.std()
    # A near-zero std (e.g. a flat, all-cash equity curve with no trades) makes
    # this ratio blow up to a meaningless huge number from floating-point noise
    # rather than a true division by exactly zero -- guard with an epsilon.
    if np.isnan(std) or std < 1e-8:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.04, periods_per_year: int = 252) -> float:
    excess = returns - risk_free_rate / periods_per_year
    downside = excess[excess < 0]
    downside_std = downside.std()
    if np.isnan(downside_std) or downside_std < 1e-8:
        return 0.0
    return float(excess.mean() / downside_std * np.sqrt(periods_per_year))


def calmar_ratio(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    from src.risk.portfolio_risk import max_drawdown
    mdd = abs(max_drawdown(equity_curve))
    if mdd < 1e-8:
        return 0.0
    return float(cagr(equity_curve, periods_per_year) / mdd)


def win_rate(trade_pnls: pd.Series) -> float:
    if trade_pnls.empty:
        return 0.0
    return float((trade_pnls > 0).mean())


def profit_factor(trade_pnls: pd.Series) -> float:
    gains = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def expectancy(trade_pnls: pd.Series) -> float:
    """Average $ P&L per trade -- the single number that answers 'is this
    strategy worth trading at all, on average, per trade'."""
    if trade_pnls.empty:
        return 0.0
    return float(trade_pnls.mean())


def recovery_factor(equity_curve: pd.Series) -> float:
    """Net profit / max drawdown magnitude -- how much return you got per
    unit of the worst pain you had to sit through."""
    from src.risk.portfolio_risk import max_drawdown
    if len(equity_curve) < 2:
        return 0.0
    net_profit = equity_curve.iloc[-1] - equity_curve.iloc[0]
    mdd_abs = abs(max_drawdown(equity_curve)) * equity_curve.iloc[0]
    if mdd_abs < 1e-8:
        return 0.0
    return float(net_profit / mdd_abs)


def omega_ratio(returns: pd.Series, threshold: float = 0.0) -> float:
    """Ratio of the sum of gains above `threshold` to the sum of losses
    below it -- unlike Sharpe/Sortino it uses the whole return distribution,
    not just mean/std, so it captures skew and fat tails."""
    excess = returns - threshold
    gains = excess[excess > 0].sum()
    losses = -excess[excess < 0].sum()
    if losses < 1e-12:
        return float("inf") if gains > 0 else 1.0
    return float(gains / losses)


def mar_ratio(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    """CAGR / |Max Drawdown|. Same formula as Calmar; MAR conventionally
    uses since-inception CAGR while Calmar traditionally uses a trailing
    3-year window -- both are exposed since either name gets asked for."""
    return calmar_ratio(equity_curve, periods_per_year)


def sqn(trade_pnls: pd.Series) -> float:
    """System Quality Number (Van Tharp): sqrt(N) * mean(R) / std(R) over
    trade P&L. Rule of thumb: <1.6 poor, 1.6-2.5 average, 2.5-4 good, >4 excellent."""
    if len(trade_pnls) < 2:
        return 0.0
    std = trade_pnls.std()
    if std < 1e-8 or np.isnan(std):
        return 0.0
    return float(np.sqrt(len(trade_pnls)) * trade_pnls.mean() / std)


def alpha_beta(strategy_returns: pd.Series, benchmark_returns: pd.Series,
               risk_free_rate: float = 0.04, periods_per_year: int = 252) -> tuple[float, float]:
    """CAPM-style alpha/beta of the strategy against a benchmark (e.g. SPY).
    Beta = cov(strategy, benchmark) / var(benchmark); Alpha is annualized
    excess return not explained by beta exposure to the benchmark."""
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 10:
        return 0.0, 0.0
    strat, bench = aligned.iloc[:, 0], aligned.iloc[:, 1]
    bench_var = bench.var()
    if bench_var < 1e-12:
        return 0.0, 0.0
    beta = float(strat.cov(bench) / bench_var)
    rf_period = risk_free_rate / periods_per_year
    alpha_period = (strat.mean() - rf_period) - beta * (bench.mean() - rf_period)
    alpha_annualized = float(alpha_period * periods_per_year)
    return alpha_annualized, beta


def information_ratio(strategy_returns: pd.Series, benchmark_returns: pd.Series,
                       periods_per_year: int = 252) -> float:
    """Active return over a benchmark, scaled by tracking error -- measures
    consistency of out/under-performance rather than raw return."""
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 10:
        return 0.0
    active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    tracking_error = active.std()
    if tracking_error < 1e-8 or np.isnan(tracking_error):
        return 0.0
    return float(active.mean() / tracking_error * np.sqrt(periods_per_year))


def rolling_sharpe(returns: pd.Series, window: int = 60, risk_free_rate: float = 0.04,
                    periods_per_year: int = 252) -> pd.Series:
    """Rolling Sharpe over a trailing window -- reveals whether an
    apparently-good overall Sharpe is stable or driven by one lucky stretch."""
    rf_period = risk_free_rate / periods_per_year
    excess = returns - rf_period
    roll_mean = excess.rolling(window).mean()
    roll_std = excess.rolling(window).std()
    return (roll_mean / roll_std.replace(0, np.nan) * np.sqrt(periods_per_year)).fillna(0.0)


def rolling_drawdown(equity_curve: pd.Series, window: int | None = None) -> pd.Series:
    """Drawdown at each point in time (window=None -> since-inception running
    max; pass a window for a trailing max instead)."""
    running_max = equity_curve.cummax() if window is None else equity_curve.rolling(window, min_periods=1).max()
    return equity_curve / running_max - 1


def summarize_performance(equity_curve: pd.Series, trade_pnls: pd.Series, risk_free_rate: float = 0.04,
                           periods_per_year: int = 252, benchmark_returns: pd.Series | None = None) -> dict:
    from src.risk.portfolio_risk import max_drawdown

    returns = equity_curve.pct_change().dropna()
    pf = profit_factor(trade_pnls)

    result = {
        "total_return_pct": round((equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100, 2) if len(equity_curve) > 1 else 0.0,
        "cagr_pct": round(cagr(equity_curve, periods_per_year) * 100, 2),
        "sharpe_ratio": round(sharpe_ratio(returns, risk_free_rate, periods_per_year), 3),
        "sortino_ratio": round(sortino_ratio(returns, risk_free_rate, periods_per_year), 3),
        "calmar_ratio": round(calmar_ratio(equity_curve, periods_per_year), 3),
        "mar_ratio": round(mar_ratio(equity_curve, periods_per_year), 3),
        "omega_ratio": round(omega_ratio(returns), 3) if np.isfinite(omega_ratio(returns)) else None,
        "sqn": round(sqn(trade_pnls), 3),
        "max_drawdown_pct": round(max_drawdown(equity_curve) * 100, 2),
        "win_rate_pct": round(win_rate(trade_pnls) * 100, 2),
        "profit_factor": round(pf, 3) if np.isfinite(pf) else None,
        "expectancy": round(expectancy(trade_pnls), 2),
        "recovery_factor": round(recovery_factor(equity_curve), 3),
        "num_trades": int(len(trade_pnls)),
    }

    if benchmark_returns is not None and not benchmark_returns.empty:
        alpha, beta = alpha_beta(returns, benchmark_returns, risk_free_rate, periods_per_year)
        result["alpha_annualized_pct"] = round(alpha * 100, 3)
        result["beta"] = round(beta, 3)
        result["information_ratio"] = round(information_ratio(returns, benchmark_returns, periods_per_year), 3)

    return result
