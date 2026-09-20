"""Cross-sectional equity mean reversion with optional sector neutrality."""

from __future__ import annotations

import numpy as np
import pandas as pd

from utils import neutralize_weights


def _sector_map_from_groups(sector_groups: dict[str, list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sector, names in sector_groups.items():
        for t in names:
            out[str(t).upper().replace(".", "-")] = str(sector)
    return out


def build_cross_sectional_weights(
    prices: pd.DataFrame,
    *,
    lookback: int = 5,
    holding: int = 5,
    long_pct: float = 0.2,
    short_pct: float = 0.2,
    membership: pd.DataFrame | None = None,
    sector_groups: dict[str, list[str]] | None = None,
    sector_neutral: bool = False,
    min_sector_names: int = 4,
) -> pd.DataFrame:
    """
    Rank names by past `lookback` return.
    Long losers / short winners.

    If sector_neutral=True and sector_groups given, rank **within each sector**,
    equal-weight sector books, then L1-normalize (sector-neutral CS).
    """
    rets = prices.pct_change(lookback)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    if membership is not None:
        membership = membership.reindex(index=prices.index, columns=prices.columns).fillna(False)

    sector_of = _sector_map_from_groups(sector_groups) if sector_groups else {}

    rebalance_days = prices.index[::holding]
    for dt in rebalance_days:
        row = rets.loc[dt]
        if membership is not None:
            row = row.where(membership.loc[dt])
        valid = row.dropna()
        if len(valid) < 10:
            continue

        w = pd.Series(0.0, index=prices.columns)

        if sector_neutral and sector_of:
            sector_weights: list[pd.Series] = []
            for sector, names in (sector_groups or {}).items():
                names = [n for n in names if n in valid.index]
                if len(names) < min_sector_names:
                    continue
                sub = valid.loc[names].sort_values()
                n = len(sub)
                n_long = max(1, int(np.floor(n * long_pct)))
                n_short = max(1, int(np.floor(n * short_pct)))
                sw = pd.Series(0.0, index=prices.columns)
                sw.loc[sub.index[:n_long]] = 1.0 / n_long
                sw.loc[sub.index[-n_short:]] = -1.0 / n_short
                # dollar-neutral within sector
                sw = sw - sw.mean()
                l1 = sw.abs().sum()
                if l1 > 0:
                    sector_weights.append(sw / l1)
            if not sector_weights:
                continue
            w = sum(sector_weights) / len(sector_weights)
        else:
            n = len(valid)
            n_long = max(1, int(np.floor(n * long_pct)))
            n_short = max(1, int(np.floor(n * short_pct)))
            ranked = valid.sort_values()
            w.loc[ranked.index[:n_long]] = 1.0 / n_long
            w.loc[ranked.index[-n_short:]] = -1.0 / n_short

        weights.loc[dt] = w

    weights = weights.replace(0.0, np.nan)
    signal_rows = weights.dropna(how="all")
    held = signal_rows.reindex(prices.index).ffill().fillna(0.0)

    if membership is not None:
        held = held.where(membership, 0.0)

    return neutralize_weights(held)
