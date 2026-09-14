"""Shared helpers for signals and portfolio construction."""

from __future__ import annotations

import numpy as np
import pandas as pd


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def neutralize_weights(weights: pd.DataFrame) -> pd.DataFrame:
    """Dollar-neutralize each row and L1-normalize gross exposure to 1."""
    w = weights.copy().astype(float)
    active = w != 0
    n = active.sum(axis=1).clip(lower=1)
    row_sum = w.sum(axis=1)
    w = w.sub(row_sum / n, axis=0).where(active, 0.0)
    l1 = w.abs().sum(axis=1).replace(0, np.nan)
    return w.div(l1, axis=0).fillna(0.0)
