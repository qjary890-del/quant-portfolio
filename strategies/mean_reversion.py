"""Cross-sectional equity mean reversion."""

from __future__ import annotations

import numpy as np
import pandas as pd

from utils import neutralize_weights


def build_cross_sectional_weights(
    prices: pd.DataFrame,
    *,
    lookback: int = 5,
    holding: int = 5,
    long_pct: float = 0.2,
    short_pct: float = 0.2,
) -> pd.DataFrame:
    """
    Rank names by past `lookback` return.
    Long the worst performers, short the best (classic short-horizon reversal).
    Rebalance every `holding` days; hold constant between rebalances.
    """
    rets = prices.pct_change(lookback)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    rebalance_days = prices.index[::holding]
    for dt in rebalance_days:
        row = rets.loc[dt]
        valid = row.dropna()
        n = len(valid)
        if n < 10:
            continue
        n_long = max(1, int(np.floor(n * long_pct)))
        n_short = max(1, int(np.floor(n * short_pct)))
        ranked = valid.sort_values()  # ascending: losers first
        longs = ranked.index[:n_long]
        shorts = ranked.index[-n_short:]

        w = pd.Series(0.0, index=prices.columns)
        w.loc[longs] = 1.0 / n_long
        w.loc[shorts] = -1.0 / n_short
        weights.loc[dt] = w

    # forward-fill holdings between rebalance dates
    weights = weights.replace(0.0, np.nan)
    # keep true zeros on non-rebalance as missing, then ffill signal rows
    signal_rows = weights.dropna(how="all")
    held = signal_rows.reindex(prices.index).ffill().fillna(0.0)
    return neutralize_weights(held)
