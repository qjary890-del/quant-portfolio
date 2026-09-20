"""Macro-resilience diagnostics for portfolio comparison."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import BacktestResult
from strategies.regime import realized_vol


def resilience_row(
    name: str,
    result: BacktestResult,
    prices: pd.DataFrame,
    *,
    vol_lookback: int = 21,
    ann: int = 252,
) -> dict[str, float | str]:
    """
    Metrics tilted toward surviving macro stress, not just point Sharpe.
    """
    stats = result.stats
    r = result.returns.dropna()
    vol = realized_vol(prices, lookback=vol_lookback, ann=ann).reindex(r.index)
    # High-vol days = top quartile of realized vol (lagged already in scaler path;
    # here use contemporaneous vol level as regime label — diagnostic only)
    thr = float(vol.quantile(0.75))
    high = vol >= thr
    low = vol <= float(vol.quantile(0.25))

    def _ann_ret(mask: pd.Series) -> float:
        sub = r.loc[mask.reindex(r.index).fillna(False)]
        if len(sub) < 20 or sub.std(ddof=0) == 0:
            return float("nan")
        return float(sub.mean() * ann)

    def _sharpe(mask: pd.Series) -> float:
        sub = r.loc[mask.reindex(r.index).fillna(False)]
        if len(sub) < 20 or sub.std(ddof=0) == 0:
            return float("nan")
        return float(sub.mean() / sub.std(ddof=0) * np.sqrt(ann))

    cagr = float(stats.get("cagr", float("nan")))
    mdd = float(stats.get("max_drawdown", float("nan")))
    calmar = float(cagr / abs(mdd)) if np.isfinite(cagr) and np.isfinite(mdd) and mdd < 0 else float("nan")

    # Yearly returns robustness
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    worst_year = float(yearly.min()) if len(yearly) else float("nan")

    return {
        "name": name,
        "cagr": cagr,
        "sharpe": float(stats.get("sharpe", float("nan"))),
        "max_dd": mdd,
        "calmar": calmar,
        "vol": float(stats.get("vol", float("nan"))),
        "ann_turnover": float(stats.get("ann_turnover", float("nan"))),
        "high_vol_ann_ret": _ann_ret(high),
        "high_vol_sharpe": _sharpe(high),
        "low_vol_ann_ret": _ann_ret(low),
        "worst_year": worst_year,
        "resilience_score": _resilience_score(
            calmar,
            _sharpe(high),
            float(stats.get("ann_turnover", float("nan"))),
            mdd,
            worst_year,
        ),
    }


def _resilience_score(
    calmar: float,
    high_vol_sharpe: float,
    ann_turnover: float,
    mdd: float,
    worst_year: float,
) -> float:
    """
    Favor strategies that limit left-tail damage in stress.
    Calmar/high-vol sharpe help, but large MDD / bad years dominate.
    """
    score = 0.0
    if np.isfinite(calmar):
        score += 0.40 * calmar
    if np.isfinite(high_vol_sharpe):
        score += 0.25 * high_vol_sharpe
    if np.isfinite(mdd):
        score += 1.00 * mdd  # e.g. -0.40 => -0.40
    if np.isfinite(worst_year):
        score += 0.80 * worst_year
    if np.isfinite(ann_turnover):
        score -= 0.015 * max(ann_turnover - 8.0, 0.0)
    return float(score)
