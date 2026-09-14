"""Vectorized daily backtest with simple cost model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    stats: dict[str, float]


def _performance_stats(returns: pd.Series, equity: pd.Series, ann: int = 252) -> dict[str, float]:
    r = returns.dropna()
    if r.empty:
        return {}
    total = float(equity.iloc[-1] / equity.iloc[0] - 1)
    years = len(r) / ann
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / max(years, 1e-9)) - 1)
    vol = float(r.std(ddof=0) * np.sqrt(ann))
    sharpe = float(r.mean() / r.std(ddof=0) * np.sqrt(ann)) if r.std(ddof=0) > 0 else 0.0
    dd = equity / equity.cummax() - 1
    max_dd = float(dd.min())
    hit = float((r > 0).mean())
    return {
        "total_return": total,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "hit_rate": hit,
        "avg_daily_turnover": float("nan"),  # filled by caller
    }


def run_backtest(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    *,
    initial_capital: float = 100_000.0,
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
    ann: int = 252,
) -> BacktestResult:
    """
    Weights are target portfolio weights at close of day t, applied to next-day returns.
    Cost = (commission + slippage) * turnover, charged on the rebalance day.
    """
    prices = prices.sort_index()
    weights = weights.reindex(prices.index).fillna(0.0)
    asset_rets = prices.pct_change().fillna(0.0)

    # Use yesterday's weights for today's returns (no look-ahead)
    lagged_w = weights.shift(1).fillna(0.0)
    gross = (lagged_w * asset_rets).sum(axis=1)

    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    cost_rate = (commission_bps + slippage_bps) / 10_000.0
    net = gross - turnover * cost_rate

    equity = (1 + net).cumprod() * initial_capital
    equity.iloc[0] = initial_capital
    stats = _performance_stats(net, equity, ann=ann)
    stats["avg_daily_turnover"] = float(turnover.mean())
    return BacktestResult(
        equity=equity,
        returns=net,
        weights=weights,
        turnover=turnover,
        stats=stats,
    )


def combine_weights(
    sleeves: dict[str, pd.DataFrame],
    sleeve_weights: dict[str, float],
) -> pd.DataFrame:
    """Blend strategy weight matrices by sleeve capital allocation."""
    total = sum(sleeve_weights.values())
    if total <= 0:
        raise ValueError("sleeve weights must sum to positive value")
    norm = {k: v / total for k, v in sleeve_weights.items()}

    cols = sorted({c for w in sleeves.values() for c in w.columns})
    idx = None
    for w in sleeves.values():
        idx = w.index if idx is None else idx.union(w.index)
    combined = pd.DataFrame(0.0, index=idx.sort_values(), columns=cols)
    for name, w in sleeves.items():
        combined = combined.add(w.reindex(combined.index).fillna(0.0) * norm[name], fill_value=0.0)
    # renormalize gross to 1 when book is active
    l1 = combined.abs().sum(axis=1).replace(0, np.nan)
    return combined.div(l1, axis=0).fillna(0.0)
