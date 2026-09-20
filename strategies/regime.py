"""Regime risk overlay: cut gross exposure when market vol is elevated."""

from __future__ import annotations

import numpy as np
import pandas as pd


def realized_vol(
    prices: pd.DataFrame,
    *,
    lookback: int = 21,
    ann: int = 252,
) -> pd.Series:
    """
    Annualized realized vol of an equal-weight basket (simple macro/risk proxy).
    No external VIX dependency — uses the trading universe itself.
    """
    rets = prices.pct_change()
    basket = rets.mean(axis=1)
    vol = basket.rolling(lookback, min_periods=max(lookback // 2, 5)).std(ddof=0) * np.sqrt(ann)
    return vol


def regime_gross_scaler(
    vol: pd.Series,
    *,
    target_vol: float = 0.15,
    floor: float = 0.30,
    ceil: float = 1.00,
) -> pd.Series:
    """
    Scale = clip(target_vol / realized_vol, floor, ceil).
    High-vol regimes -> smaller gross; calm regimes -> up to full exposure.
    Shifted by 1 so today's scale uses info through yesterday.
    """
    raw = target_vol / vol.replace(0, np.nan)
    scale = raw.clip(lower=floor, upper=ceil).fillna(floor)
    return scale.shift(1).fillna(floor)


def apply_gross_scaler(weights: pd.DataFrame, scale: pd.Series) -> pd.DataFrame:
    s = scale.reindex(weights.index).fillna(1.0)
    return weights.mul(s, axis=0)


def macro_shock_scaler(
    prices: pd.DataFrame,
    *,
    short_vol_lb: int = 5,
    long_vol_lb: int = 63,
    vol_spike_ratio: float = 2.0,
    crash_days: int = 5,
    crash_ret: float = -0.08,
    day1_crash: float = -0.035,
    cooldown_days: int = 10,
    shock_floor: float = 0.0,
    ann: int = 252,
) -> pd.Series:
    """
    Hard cut on macro shock, then stay flat for a cooldown.

    Triggers (any):
      - short realized vol / long realized vol >= vol_spike_ratio
      - equal-weight basket return over crash_days <= crash_ret
      - 1-day basket return <= day1_crash

    Scale is lagged by 1 day (no same-day look-ahead). During cooldown, scale
    stays at shock_floor (default 0 = full flatten).
    """
    rets = prices.pct_change()
    basket = rets.mean(axis=1)
    short_vol = basket.rolling(short_vol_lb, min_periods=max(short_vol_lb // 2, 2)).std(ddof=0) * np.sqrt(ann)
    long_vol = basket.rolling(long_vol_lb, min_periods=max(long_vol_lb // 2, 10)).std(ddof=0) * np.sqrt(ann)
    ratio = short_vol / long_vol.replace(0, np.nan)
    n_day = basket.rolling(crash_days, min_periods=crash_days).sum()

    shock_raw = (
        (ratio >= vol_spike_ratio)
        | (n_day <= crash_ret)
        | (basket <= day1_crash)
    )
    shock_raw = shock_raw.fillna(False)

    active = pd.Series(False, index=prices.index)
    remaining = 0
    for i, is_shock in enumerate(shock_raw.astype(bool).tolist()):
        if is_shock:
            remaining = max(remaining, int(cooldown_days))
        if remaining > 0:
            active.iloc[i] = True
            remaining -= 1

    scale = pd.Series(1.0, index=prices.index)
    scale = scale.where(~active, float(shock_floor))
    return scale.shift(1).fillna(1.0)


def book_drawdown_scaler(
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    max_dd: float = -0.12,
    cooldown_days: int = 15,
    floor: float = 0.0,
) -> pd.Series:
    """
    Flatten when the *book's* lagged equity drawdown breaches max_dd.

    Uses previous-day weights * today's returns to build a proxy curve, then
    lags the kill signal by 1 day so the trigger day is not looked ahead.
    Catches pair-breakdown bleed that market-vol shocks miss.
    """
    rets = prices.pct_change().reindex(index=weights.index, columns=weights.columns).fillna(0.0)
    w = weights.reindex_like(rets).fillna(0.0)
    pnl = (w.shift(1).fillna(0.0) * rets).sum(axis=1)
    eq = (1.0 + pnl).cumprod()
    dd = eq / eq.cummax() - 1.0
    breach = (dd <= float(max_dd)).fillna(False)

    active = pd.Series(False, index=weights.index)
    remaining = 0
    for i, hit in enumerate(breach.astype(bool).tolist()):
        if hit:
            remaining = max(remaining, int(cooldown_days))
        if remaining > 0:
            active.iloc[i] = True
            remaining -= 1

    scale = pd.Series(1.0, index=weights.index)
    scale = scale.where(~active, float(floor))
    return scale.shift(1).fillna(1.0)


def rebalance_breakeven_pct(
    *,
    commission_bps: float,
    slippage_bps: float,
    turnover: float,
    holding_days: int,
    borrow_fee_annual: float = 0.015,
    avg_short_gross: float = 0.5,
    ann: int = 252,
) -> dict[str, float]:
    """
    Minimum expected gross return over the holding period to cover costs.

    turnover: sum(|Δw|) at the rebalance (1.0 ≈ recycle half the L1 book;
              2.0 ≈ full exit+rebuild for dollar-neutral L1=1 book).
    """
    trade_cost = turnover * (commission_bps + slippage_bps) / 10_000.0
    borrow_cost = avg_short_gross * borrow_fee_annual * (holding_days / ann)
    total = trade_cost + borrow_cost
    # annualize as if every holding period pays this cost
    periods_per_year = ann / max(holding_days, 1)
    return {
        "turnover": float(turnover),
        "holding_days": float(holding_days),
        "trade_cost_pct": trade_cost * 100.0,
        "borrow_cost_pct": borrow_cost * 100.0,
        "breakeven_hold_pct": total * 100.0,
        "breakeven_annualized_pct": total * periods_per_year * 100.0,
    }
