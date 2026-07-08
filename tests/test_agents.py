import pandas as pd

from src.agents import AgentContext, DecisionEngine, MacroAgent, PortfolioAgent, RiskAgent, TechnicalAgent
from src.features.feature_pipeline import FeaturePipeline
from src.strategies.base import Action


def test_technical_agent_produces_opinion(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    context = AgentContext(symbol="TEST", features=features)
    opinion = TechnicalAgent().analyze(context)
    assert -1.0 <= opinion.lean <= 1.0
    assert 0.0 <= opinion.confidence <= 1.0
    assert opinion.veto is False


def test_macro_agent_neutral_without_data(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    context = AgentContext(symbol="TEST", features=features)
    opinion = MacroAgent().analyze(context)
    assert opinion.lean == 0.0
    assert opinion.confidence == 0.0


def test_macro_agent_contrarian_lean_on_extreme_fear(synthetic_ohlcv):
    """Crypto Fear & Greed only applies its contrarian lean to crypto
    symbols -- confirmed via asset_class_of, not just "any symbol"."""
    features = FeaturePipeline().build(synthetic_ohlcv)
    context = AgentContext(symbol="BTC/USDT", features=features,
                            sentiment_snapshot={"crypto_fear_greed": {"value": 10}},
                            asset_class_of={"BTC/USDT": "crypto"})
    opinion = MacroAgent().analyze(context)
    assert opinion.lean > 0


def test_macro_agent_ignores_crypto_sentiment_for_non_crypto_symbols(synthetic_ohlcv):
    """Regression test for a real production bug: crypto Fear & Greed was
    being applied as a contrarian lean to every symbol regardless of asset
    class -- e.g. gold futures, Taiwan equities, forex -- which had nothing
    to do with crypto crowd sentiment, and its ~0.25 confidence was large
    enough to significantly distort or cancel out those symbols' actual
    technical signal in the combined decision score."""
    features = FeaturePipeline().build(synthetic_ohlcv)
    context = AgentContext(symbol="GC=F", features=features,
                            sentiment_snapshot={"crypto_fear_greed": {"value": 10}},
                            asset_class_of={"GC=F": "metal"})
    opinion = MacroAgent().analyze(context)
    assert opinion.lean == 0.0
    assert opinion.confidence == 0.0


def test_risk_agent_vetoes_on_drawdown_breach(synthetic_ohlcv):
    from src.risk import DrawdownCircuitBreaker

    features = FeaturePipeline().build(synthetic_ohlcv)
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    equity = pd.Series([100_000] * 5 + [70_000] * 5, index=dates, dtype=float)  # 30% drawdown
    context = AgentContext(symbol="TEST", features=features, equity_curve=equity)

    agent = RiskAgent(drawdown_breaker=DrawdownCircuitBreaker(max_drawdown_pct=0.20))
    opinion = agent.analyze(context)
    assert opinion.veto is True


def test_risk_agent_flags_high_correlation_when_data_is_provided(synthetic_ohlcv):
    """The correlation-limit check inside RiskAgent was dead code in
    production: daily_run.py never populated `returns_by_symbol` on the
    AgentContext, so this branch could never execute. This confirms the
    check itself works correctly once given real data (the actual wiring
    is covered separately in test_daily_run_market_hours-style pipeline
    tests)."""
    features = FeaturePipeline().build(synthetic_ohlcv)
    dates = pd.date_range("2024-01-01", periods=50, freq="D")
    base_returns = pd.Series([0.01, -0.01] * 25, index=dates)
    # Two symbols with near-identical returns -- avg pairwise correlation
    # should be very high, well above the 0.85 default limit.
    returns_by_symbol = {"A": base_returns, "B": base_returns * 1.001}
    context = AgentContext(symbol="TEST", features=features, returns_by_symbol=returns_by_symbol)

    opinion = RiskAgent().analyze(context)
    assert opinion.veto is False  # flagged, not a hard veto
    assert any("correlation" in r.lower() for r in opinion.reasons)


def test_risk_agent_no_veto_when_healthy(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    equity = pd.Series([100_000 + i * 100 for i in range(10)], index=dates, dtype=float)
    context = AgentContext(symbol="TEST", features=features, equity_curve=equity)
    opinion = RiskAgent().analyze(context)
    assert opinion.veto is False


def test_portfolio_agent_vetoes_over_exposed_class(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    context = AgentContext(
        symbol="BTC/USDT", features=features,
        portfolio_weights={"BTC/USDT": 0.4, "ETH/USDT": 0.3, "AAPL": 0.3},
        asset_class_of={"BTC/USDT": "crypto", "ETH/USDT": "crypto", "AAPL": "equity"},
    )
    agent = PortfolioAgent(max_asset_class_weight=0.5)
    opinion = agent.analyze(context)
    assert opinion.veto is True


def test_decision_engine_veto_overrides_bullish_technical(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    equity = pd.Series([100_000] * 5 + [70_000] * 5, index=dates, dtype=float)

    from src.risk import DrawdownCircuitBreaker
    engine = DecisionEngine([TechnicalAgent(), RiskAgent(drawdown_breaker=DrawdownCircuitBreaker(max_drawdown_pct=0.2))])
    context = AgentContext(symbol="TEST", features=features, equity_curve=equity)
    decision = engine.decide(context)

    assert decision.vetoed is True
    assert decision.action == Action.HOLD


def test_decision_engine_aggregates_without_veto(synthetic_ohlcv):
    features = FeaturePipeline().build(synthetic_ohlcv)
    engine = DecisionEngine([TechnicalAgent(), MacroAgent()])
    context = AgentContext(symbol="TEST", features=features)
    decision = engine.decide(context)

    assert decision.vetoed is False
    assert decision.action in (Action.BUY, Action.SELL, Action.HOLD)
    d = decision.to_dict()
    assert len(d["opinions"]) == 2
