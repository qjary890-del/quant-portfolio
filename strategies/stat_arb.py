"""Statistical arbitrage via cointegrated pairs / residual z-score."""

from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

from utils import zscore


def hedge_ratio(y: pd.Series, x: pd.Series) -> float:
    """OLS hedge ratio: y ~ a + b*x."""
    aligned = pd.concat([y, x], axis=1).dropna()
    if len(aligned) < 20:
        return np.nan
    model = OLS(aligned.iloc[:, 0], add_constant(aligned.iloc[:, 1])).fit()
    return float(model.params.iloc[1])


def pair_spread(
    prices: pd.DataFrame,
    y_ticker: str,
    x_ticker: str,
    lookback: int,
) -> pd.DataFrame:
    """Rolling hedge ratio and mean-reverting spread for one pair."""
    betas: list[float] = []
    idx: list[pd.Timestamp] = []
    for i in range(lookback, len(prices) + 1):
        window = prices.iloc[i - lookback : i][[y_ticker, x_ticker]].dropna()
        if len(window) < max(20, lookback // 2):
            continue
        betas.append(hedge_ratio(window[y_ticker], window[x_ticker]))
        idx.append(prices.index[i - 1])

    beta_s = pd.Series(betas, index=idx, name="beta")
    spread = prices[y_ticker].loc[beta_s.index] - beta_s * prices[x_ticker].loc[beta_s.index]
    z = zscore(spread, lookback)
    return pd.DataFrame({"beta": beta_s, "spread": spread, "z": z})


def pair_positions(
    z: pd.Series,
    entry_z: float,
    exit_z: float,
    stop_z: float,
) -> pd.Series:
    """
    Position in the spread:
      +1 = long spread (long y, short x) when z is very negative
      -1 = short spread when z is very positive
       0 = flat
    """
    pos = 0.0
    out: list[float] = []
    for val in z:
        if np.isnan(val):
            out.append(0.0)
            continue
        if abs(val) >= stop_z:
            pos = 0.0
        elif pos == 0.0:
            if val >= entry_z:
                pos = -1.0
            elif val <= -entry_z:
                pos = 1.0
        elif abs(val) <= exit_z:
            pos = 0.0
        out.append(pos)
    return pd.Series(out, index=z.index, dtype=float)


def build_stat_arb_weights(
    prices: pd.DataFrame,
    pairs: list[tuple[str, str]],
    *,
    lookback: int = 60,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
) -> pd.DataFrame:
    """Equal-risk across active pairs; L1-normalize the book each day."""
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    for y_t, x_t in pairs:
        if y_t not in prices.columns or x_t not in prices.columns:
            continue
        diagnostics = pair_spread(prices, y_t, x_t, lookback)
        pos = pair_positions(diagnostics["z"], entry_z, exit_z, stop_z)
        beta = diagnostics["beta"].reindex(prices.index).ffill()
        pos = pos.reindex(prices.index).fillna(0.0)

        weights.loc[:, y_t] = weights[y_t] + pos
        weights.loc[:, x_t] = weights[x_t] - pos * beta.fillna(1.0)

    l1 = weights.abs().sum(axis=1).replace(0, np.nan)
    return weights.div(l1, axis=0).fillna(0.0)
