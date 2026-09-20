"""Cross-sectional equity mean reversion with optional PIT membership mask."""

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
    membership: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Rank names by past `lookback` return.
    Long the worst performers, short the best (classic short-horizon reversal).
    If `membership` is provided, only index members that day are eligible.
    """
    rets = prices.pct_change(lookback)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    if membership is not None:
        membership = membership.reindex(index=prices.index, columns=prices.columns).fillna(False)

    rebalance_days = prices.index[::holding]
    for dt in rebalance_days:
        row = rets.loc[dt]
        if membership is not None:
            eligible = membership.loc[dt]
            row = row.where(eligible)
        valid = row.dropna()
        n = len(valid)
        if n < 10:
            continue
        n_long = max(1, int(np.floor(n * long_pct)))
        n_short = max(1, int(np.floor(n * short_pct)))
        ranked = valid.sort_values()
        longs = ranked.index[:n_long]
        shorts = ranked.index[-n_short:]

        w = pd.Series(0.0, index=prices.columns)
        w.loc[longs] = 1.0 / n_long
        w.loc[shorts] = -1.0 / n_short
        weights.loc[dt] = w

    weights = weights.replace(0.0, np.nan)
    signal_rows = weights.dropna(how="all")
    held = signal_rows.reindex(prices.index).ffill().fillna(0.0)

    if membership is not None:
        # Drop names that leave the index between rebalances
        held = held.where(membership, 0.0)

    return neutralize_weights(held)
